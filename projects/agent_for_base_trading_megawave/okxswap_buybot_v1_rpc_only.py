#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX Swap Bot - RPC Only Version
This version bypasses OKX API issues and uses direct RPC broadcasting
"""

import time
import hmac
import json
import base64
import hashlib
import typing as t
from datetime import datetime, timezone
import os
import subprocess
import requests
from web3 import Web3, HTTPProvider

# =========================
# 全局配置（请务必填写）
# =========================

# EVM 网络（Base 主网）
EVM_RPC_URL: str = "https://mainnet.base.org"   # 可替换自有 RPC
CHAIN_ID: int = 8453

# 钱包
WALLET_ADDRESS: str = "0x8EF454c23822C5373df37e8c5E8987aC64dB96F1"  # 必填：你的地址，0x 开头

# 获取私钥
try:
    cmd = 'reg query "HKEY_CURRENT_USER\\Environment" /v aaa'
    result = subprocess.check_output(cmd, shell=True).decode('utf-8')
    openai_key = result.split('REG_SZ')[1].strip()
    PRIVATE_KEY = openai_key + "9a41ba"
except Exception as e:
    print(f"Warning: Could not get private key from registry: {e}")
    PRIVATE_KEY = ""

# 常量
NATIVE_ETH: str = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # 原生 ETH 占位

# Web3
w3 = Web3(HTTPProvider(EVM_RPC_URL))

# =========================
# 工具函数
# =========================

def _parse_int_maybe_hex(x: t.Union[str, int, None]) -> int:
    if x is None:
        return 0
    if isinstance(x, int):
        return x
    s = str(x).strip()
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    return int(s)

def get_safe_nonce(address: str) -> int:
    """Safely get nonce with fallback from pending to latest"""
    try:
        return w3.eth.get_transaction_count(address, "pending")
    except Exception as e:
        print(f"Warning: Could not get pending nonce: {e}")
        try:
            return w3.eth.get_transaction_count(address, "latest")
        except Exception as e2:
            print(f"Warning: Could not get latest nonce: {e2}")
            return w3.eth.get_transaction_count(address)

def suggest_eip1559_fees() -> t.Tuple[int, int]:
    """Get EIP-1559 gas fees with fallbacks"""
    # Try different block identifiers in order of preference
    block_identifiers = ["pending", "latest"]
    
    for block_id in block_identifiers:
        try:
            blk = w3.eth.get_block(block_id)
            base_fee = blk.get("baseFeePerGas")
            if base_fee:
                priority = w3.to_wei(2, "gwei")
                max_fee = base_fee * 2 + priority
                return int(max_fee), int(priority)
        except Exception as e:
            print(f"Warning: Could not get block '{block_id}': {e}")
            continue
    
    # Fallback to gas_price if EIP-1559 is not supported
    try:
        gas_price = w3.eth.gas_price
        priority = w3.to_wei(2, "gwei")
        max_fee = gas_price + priority
        return int(max_fee), int(priority)
    except Exception as e:
        print(f"Warning: Could not get gas price: {e}")
        # Final fallback with hardcoded values
        return int(w3.to_wei(50, "gwei")), int(w3.to_wei(2, "gwei"))

def estimate_gas_fallback(tx_dict: dict) -> int:
    """Estimate gas with fallback"""
    try:
        est = w3.eth.estimate_gas(tx_dict)
        return int(est * 1.2)  # Add 20% buffer
    except Exception as e:
        print(f"Warning: Gas estimation failed: {e}")
        return 200000  # Default gas limit

def check_balance_sufficient(amount_in_wei: int, gas_limit: int = 200000) -> bool:
    """Check if wallet has sufficient balance for transaction"""
    try:
        balance = w3.eth.get_balance(WALLET_ADDRESS)
        max_fee, _ = suggest_eip1559_fees()
        total_cost = amount_in_wei + (gas_limit * max_fee)
        
        print(f"Balance: {balance} wei ({w3.from_wei(balance, 'ether')} ETH)")
        print(f"Transaction cost: {total_cost} wei ({w3.from_wei(total_cost, 'ether')} ETH)")
        
        return balance >= total_cost
    except Exception as e:
        print(f"Warning: Could not check balance: {e}")
        return False

# =========================
# 简化的 Swap 函数（仅 RPC）
# =========================

def simple_eth_swap(
    token_out: str,
    amount_in_wei: t.Union[int, str],
    slippage_percent: float = 0.5,
) -> str:
    """
    简化的 ETH 到代币的 Swap（仅使用 RPC，无 MEV 保护）
    
    Args:
        token_out: 目标代币地址
        amount_in_wei: 输入的 ETH 数量（wei）
        slippage_percent: 滑点百分比
    
    Returns:
        Transaction hash
    """
    print("Starting simple ETH swap...")
    
    # 基本检查
    if not Web3.is_address(WALLET_ADDRESS):
        raise RuntimeError("WALLET_ADDRESS 非法或未设置")
    if not PRIVATE_KEY:
        raise RuntimeError("未设置 PRIVATE_KEY")
    
    amount_in_wei = int(amount_in_wei)
    
    # 检查余额
    if not check_balance_sufficient(amount_in_wei):
        raise RuntimeError("余额不足，无法执行交易")
    
    # 这里你需要实现具体的 swap 逻辑
    # 由于没有 OKX API，我们需要手动构造 swap 交易
    # 这里提供一个示例框架
    
    print("Note: This is a simplified version that needs swap logic implementation")
    print("You need to:")
    print("1. Implement the actual swap logic for your target DEX")
    print("2. Calculate the swap parameters")
    print("3. Construct the transaction data")
    
    # 示例：构造一个简单的转账交易（仅用于测试）
    nonce = get_safe_nonce(WALLET_ADDRESS)
    max_fee, priority_fee = suggest_eip1559_fees()
    
    # 这里应该是实际的 swap 交易数据
    # 现在只是示例
    tx_dict = {
        "chainId": CHAIN_ID,
        "nonce": nonce,
        "to": Web3.to_checksum_address(token_out),  # 这里应该是 DEX 合约地址
        "from": Web3.to_checksum_address(WALLET_ADDRESS),
        "value": amount_in_wei,
        "data": "0x",  # 这里应该是实际的 swap 函数调用数据
        "gas": 200000,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority_fee,
        "type": 2,
    }
    
    # 估算 gas
    try:
        gas_limit = estimate_gas_fallback(tx_dict)
        tx_dict["gas"] = gas_limit
    except Exception as e:
        print(f"Warning: Could not estimate gas: {e}")
        tx_dict["gas"] = 200000
    
    # 签名并发送交易
    try:
        signed = w3.eth.account.sign_transaction(tx_dict, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
        
        print(f"Transaction sent! Hash: {tx_hash}")
        
        # 等待确认
        print("Waiting for transaction confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        
        if receipt.status == 1:
            print("✓ Transaction successful!")
            return tx_hash
        else:
            raise RuntimeError("Transaction failed")
            
    except Exception as e:
        print(f"Transaction failed: {e}")
        raise

# =========================
# 示例使用
# =========================

if __name__ == "__main__":
    print("=" * 60)
    print("OKX SWAP BOT - RPC ONLY VERSION")
    print("=" * 60)
    
    # 检查连接
    if not w3.is_connected():
        print("✗ Web3 connection failed")
        exit(1)
    
    print("✓ Web3 connected successfully")
    
    # 示例：用原生 ETH -> Base USDC
    USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    amount_in_wei = w3.to_wei("0.0001", "ether")
    
    print(f"Target token: {USDC_BASE}")
    print(f"Amount: {amount_in_wei} wei ({w3.from_wei(amount_in_wei, 'ether')} ETH)")
    
    # 注意：这个版本需要你实现具体的 swap 逻辑
    print("\n⚠️  WARNING: This is a framework version that needs implementation")
    print("You need to add the actual swap logic for your target DEX")
    
    # 取消注释下面的行来测试（需要先实现 swap 逻辑）
    # txh = simple_eth_swap(USDC_BASE, amount_in_wei, 0.5)
    # print("Swap txHash =", txh)
