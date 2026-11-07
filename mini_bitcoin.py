# -*- coding: utf-8 -*-
"""
简化版比特币网络实现
实现：区块、挖矿、交易、UTXO、三节点共识
"""

import hashlib
import json
import time
import threading
from collections import OrderedDict

# ========== 工具函数 ==========

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def double_sha256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).hexdigest()

def hash_block_header(prev_hash, merkle_root, timestamp, nonce):
    """计算区块头哈希"""
    header = json.dumps({
        "prev": prev_hash,
        "merkle": merkle_root,
        "time": timestamp,
        "nonce": nonce
    }, sort_keys=True).encode()
    return double_sha256(header)

def merkle_root(txids):
    """计算Merkle根"""
    if not txids:
        return ""
    if len(txids) == 1:
        return sha256(txids[0].encode())
    while len(txids) > 1:
        if len(txids) % 2 == 1:
            txids.append(txids[-1])
        txids = [sha256((txids[i] + txids[i+1]).encode()) for i in range(0, len(txids), 2)]
    return txids[0]

def txid(tx):
    """计算交易ID"""
    return sha256(json.dumps(tx, sort_keys=True).encode())

# ========== 常量 ==========
BLOCK_REWARD = 50  # 每块奖励50 BTC
DIFFICULTY_TARGET = 0x00FFFFFF000000000000000000000000000000000000000000000000000000  # 难度值（调低便于快速出块）

# ========== 节点类 ==========

class Node:
    def __init__(self, name, address):
        self.name = name
        self.address = address  # 简化版地址
        self.chain = []  # 区块链
        self.mempool = []  # 内存池（待打包交易）
        self.utxo_set = {}  # UTXO集: txid -> [{vout, addr, value}]
        self.peers = []  # 对等节点列表
        
    def add_peer(self, peer):
        self.peers.append(peer)
    
    def create_genesis_block(self):
        """创建创世区块"""
        coinbase = {
            "inputs": [{"coinbase": self.address, "height": 0}],
            "outputs": [{"addr": self.address, "value": BLOCK_REWARD}]
        }
        coinbase_txid = txid(coinbase)
        
        block = {
            "height": 0,
            "prev_hash": "0" * 64,
            "merkle_root": merkle_root([coinbase_txid]),
            "timestamp": int(time.time()),
            "nonce": 0,
            "transactions": [coinbase]
        }
        
        # 挖矿找nonce
        target_hex = f"{DIFFICULTY_TARGET:064x}"
        nonce = 0
        while True:
            block_hash = hash_block_header(
                block["prev_hash"], block["merkle_root"], 
                block["timestamp"], nonce
            )
            if block_hash < target_hex:
                block["nonce"] = nonce
                block["hash"] = block_hash
                break
            nonce += 1
        
        self.chain.append(block)
        self.utxo_set[coinbase_txid] = [{"vout": 0, "addr": self.address, "value": BLOCK_REWARD}]
        print(f"[{self.name}] 创世块生成: {block['hash'][:16]}... nonce={nonce}")
    
    def get_balance(self):
        """查询余额"""
        balance = 0
        for txid, outputs in self.utxo_set.items():
            for out in outputs:
                if out["addr"] == self.address:
                    balance += out["value"]
        return balance
    
    def create_transaction(self, to_addr, amount):
        """创建交易"""
        # 找足够的UTXO
        inputs = []
        total = 0
        for txid, outputs in self.utxo_set.items():
            for i, out in enumerate(outputs):
                if out["addr"] == self.address and total < amount:
                    inputs.append({"txid": txid, "vout": i})
                    total += out["value"]
                    if total >= amount:
                        break
            if total >= amount:
                break
        
        if total < amount:
            print(f"[{self.name}] 余额不足，无法支付 {amount}")
            return None
        
        # 找零
        change = total - amount
        outputs = [{"addr": to_addr, "value": amount}]
        if change > 0:
            outputs.append({"addr": self.address, "value": change})
        
        tx = {"inputs": inputs, "outputs": outputs}
        return tx
    
    def add_transaction_to_mempool(self, tx):
        """交易加入内存池"""
        tx_id = txid(tx)
        self.mempool.append(tx)
        print(f"[{self.name}] 交易进入内存池: {tx_id[:16]}...")
        
        # 广播给其他节点
        for peer in self.peers:
            peer.receive_transaction(tx)
    
    def receive_transaction(self, tx):
        """接收其他节点广播的交易"""
        tx_id = txid(tx)
        if tx not in self.mempool:
            self.mempool.append(tx)
            print(f"[{self.name}] 收到网络广播交易: {tx_id[:16]}...")
    
    def mine_block(self):
        """挖矿生成新区块"""
        if not self.chain:
            return
        
        prev_block = self.chain[-1]
        height = len(self.chain)
        
        # 创建coinbase交易
        coinbase = {
            "inputs": [{"coinbase": self.address, "height": height}],
            "outputs": [{"addr": self.address, "value": BLOCK_REWARD}]
        }
        
        # 从内存池取交易
        txs = [coinbase] + self.mempool[:5]  # 最多打包5笔
        
        # 计算merkle根
        tx_ids = [txid(tx) for tx in txs]
        merkle = merkle_root(tx_ids)
        
        # 挖矿
        target_hex = f"{DIFFICULTY_TARGET:064x}"
        nonce = 0
        timestamp = int(time.time())
        
        while True:
            block_hash = hash_block_header(prev_block["hash"], merkle, timestamp, nonce)
            if block_hash < target_hex:
                break
            nonce += 1
        
        new_block = {
            "height": height,
            "prev_hash": prev_block["hash"],
            "merkle_root": merkle,
            "timestamp": timestamp,
            "nonce": nonce,
            "transactions": txs,
            "hash": block_hash
        }
        
        # 加入链
        self.chain.append(new_block)
        
        # 更新UTXO集
        # 先删除花费掉的UTXO
        for tx in txs[1:]:  # 跳过coinbase
            for inp in tx["inputs"]:
                if inp["txid"] in self.utxo_set:
                    del self.utxo_set[inp["txid"]]
        
        # 添加新的UTXO
        for tx in txs:
            tx_id = txid(tx)
            self.utxo_set[tx_id] = [{"vout": i, "addr": out["addr"], "value": out["value"]} 
                                    for i, out in enumerate(tx["outputs"])]
        
        # 清空已打包的交易
        self.mempool = self.mempool[5:]
        
        print(f"[{self.name}] 挖出区块 #{height}: {block_hash[:16]}... nonce={nonce} 包含{len(txs)}笔交易")
        
        # 广播给其他节点
        for peer in self.peers:
            peer.receive_block(new_block)
        
        return new_block
    
    def receive_block(self, block):
        """接收其他节点广播的区块"""
        # 简化处理：直接接受最长链
        if block["height"] == len(self.chain):
            self.chain.append(block)
            
            # 更新UTXO
            for tx in block["transactions"][1:]:
                for inp in tx["inputs"]:
                    if inp["txid"] in self.utxo_set:
                        del self.utxo_set[inp["txid"]]
            
            for tx in block["transactions"]:
                tx_id = txid(tx)
                self.utxo_set[tx_id] = [{"vout": i, "addr": out["addr"], "value": out["value"]} 
                                        for i, out in enumerate(tx["outputs"])]
            
            print(f"[{self.name}] 收到新区块 #{block['height']}: {block['hash'][:16]}...")


# ========== 主程序 ==========

def main():
    print("=" * 60)
    print("简化版比特币网络实践")
    print("=" * 60)
    
    # 创建三个节点
    node1 = Node("Node1", "addr_node1")
    node2 = Node("Node2", "addr_node2")
    node3 = Node("Node3", "addr_node3")
    
    # 建立P2P连接
    node1.add_peer(node2)
    node1.add_peer(node3)
    node2.add_peer(node1)
    node2.add_peer(node3)
    node3.add_peer(node1)
    node3.add_peer(node2)
    
    print("\n--- 1. 初始化创世区块 ---")
    node1.create_genesis_block()
    node2.chain = [dict(node1.chain[0])]
    node2.utxo_set = dict(node1.utxo_set)
    node3.chain = [dict(node1.chain[0])]
    node3.utxo_set = dict(node1.utxo_set)
    
    print(f"\n初始余额:")
    print(f"  Node1: {node1.get_balance()} BTC")
    print(f"  Node2: {node2.get_balance()} BTC")
    print(f"  Node3: {node3.get_balance()} BTC")
    
    print("\n--- 2. Node1 连续挖矿5个块 ---")
    for i in range(5):
        node1.mine_block()
        # 同步到其他节点
        node2.chain = [dict(b) for b in node1.chain]
        node3.chain = [dict(b) for b in node1.chain]
    
    print(f"\n挖矿后余额:")
    print(f"  Node1: {node1.get_balance()} BTC")
    print(f"  Node2: {node2.get_balance()} BTC")
    print(f"  Node3: {node3.get_balance()} BTC")
    
    print("\n--- 3. Node1 转账 20 BTC 给 Node2 ---")
    tx = node1.create_transaction("addr_node2", 20)
    if tx:
        node1.add_transaction_to_mempool(tx)
    
    print(f"\n交易后内存池状态:")
    print(f"  Node1 内存池: {len(node1.mempool)} 笔交易")
    print(f"  Node2 内存池: {len(node2.mempool)} 笔交易")
    print(f"  Node3 内存池: {len(node3.mempool)} 笔交易")
    
    print("\n--- 4. Node2 挖矿打包交易 ---")
    node2.mine_block()
    
    print(f"\n--- 5. 最终状态 ---")
    print(f"链高度: Node1={len(node1.chain)}, Node2={len(node2.chain)}, Node3={len(node3.chain)}")
    print(f"链顶哈希一致: {node1.chain[-1]['hash'] == node2.chain[-1]['hash'] == node3.chain[-1]['hash']}")
    print(f"\n最终余额:")
    print(f"  Node1: {node1.get_balance():.4f} BTC")
    print(f"  Node2: {node2.get_balance():.4f} BTC")
    print(f"  Node3: {node3.get_balance():.4f} BTC")
    
    total_utxo = sum(out["value"] for utxos in node1.utxo_set.values() for out in utxos)
    print(f"\n全网UTXO总量: {total_utxo:.4f} BTC")
    
    print("\n" + "=" * 60)
    print("实践完成！")
    print("=" * 60)

if __name__ == "__main__":
    main()
