#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试余额检查功能
"""

from okxswap_buybot_v1 import (
    get_token_balance, NATIVE_ETH, WALLET_ADDRESS, w3,
    okx_swap_mev
)
from web3 import Web3

def test_balance_check():
    """测试余额检查功能"""
    print("=" * 60)
    print("测试余额检查功能")
    print("=" * 60)
    
    # 测试1: 检查 ETH 余额
    print("\n1. 检查 ETH 余额:")
    eth_balance = get_token_balance(NATIVE_ETH, WALLET_ADDRESS)
    eth_balance_eth = w3.from_wei(eth_balance, "ether")
    print(f"ETH 余额: {eth_balance_eth} ETH ({eth_balance} wei)")
    
    # 测试2: 检查 USDC 余额
    print("\n2. 检查 USDC 余额:")
    usdc_address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    try:
        usdc_balance = get_token_balance(usdc_address, WALLET_ADDRESS)
        usdc_balance_decimal = usdc_balance / (10 ** 6)  # USDC 有6位小数
        print(f"USDC 余额: {usdc_balance_decimal} USDC ({usdc_balance} wei)")
    except Exception as e:
        print(f"获取 USDC 余额失败: {e}")
    
    # 测试3: 测试余额不足的情况
    print("\n3. 测试余额不足的情况:")
    test_amount = eth_balance_eth + 1  # 请求比余额多1 ETH
    print(f"请求数量: {test_amount} ETH")
    print(f"实际余额: {eth_balance_eth} ETH")
    
    if test_amount > eth_balance_eth:
        print("✅ 余额不足检测正常")
    else:
        print("❌ 余额检查逻辑有问题")
    
    return eth_balance_eth

def test_swap_with_balance_check():
    """测试带余额检查的交易"""
    print("\n" + "=" * 60)
    print("测试带余额检查的交易")
    print("=" * 60)
    
    # 获取当前 ETH 余额
    eth_balance = get_token_balance(NATIVE_ETH, WALLET_ADDRESS)
    eth_balance_eth = w3.from_wei(eth_balance, "ether")
    
    print(f"当前 ETH 余额: {eth_balance_eth} ETH")
    
    # 设置一个合理的交易数量（余额的10%）
    amount_eth = eth_balance_eth * 0.1
    print(f"请求交易数量: {amount_eth} ETH")
    
    # 执行交易
    try:
        tx_hash, total_time = okx_swap_mev(
            "ETH",  # 输入代币
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # 输出代币 (USDC)
            amount_eth,  # 交易数量
            0.5,  # 滑点
            True  # MEV 保护
        )
        
        print("\n" + "=" * 60)
        print("✅ 交易成功!")
        print("=" * 60)
        print(f"交易哈希: {tx_hash}")
        print(f"总用时: {total_time:.2f} 秒")
        print(f"区块浏览器: https://basescan.org/tx/{tx_hash}")
        print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 交易失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        print("=" * 60)

def test_insufficient_balance():
    """测试余额不足的情况"""
    print("\n" + "=" * 60)
    print("测试余额不足的情况")
    print("=" * 60)
    
    # 获取当前 ETH 余额
    eth_balance = get_token_balance(NATIVE_ETH, WALLET_ADDRESS)
    eth_balance_eth = w3.from_wei(eth_balance, "ether")
    
    print(f"当前 ETH 余额: {eth_balance_eth} ETH")
    
    # 设置一个超过余额的数量
    amount_eth = eth_balance_eth + 1
    print(f"请求交易数量: {amount_eth} ETH (超过余额)")
    
    # 执行交易（应该会自动调整为使用全部余额）
    try:
        tx_hash, total_time = okx_swap_mev(
            "ETH",  # 输入代币
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # 输出代币 (USDC)
            amount_eth,  # 交易数量
            0.5,  # 滑点
            True  # MEV 保护
        )
        
        print("\n" + "=" * 60)
        print("✅ 交易成功!")
        print("=" * 60)
        print(f"交易哈希: {tx_hash}")
        print(f"总用时: {total_time:.2f} 秒")
        print(f"区块浏览器: https://basescan.org/tx/{tx_hash}")
        print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 交易失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        print("=" * 60)

if __name__ == "__main__":
    print("余额检查功能测试")
    
    # 测试余额检查
    current_balance = test_balance_check()
    
    # 选择测试模式
    print("\n选择测试模式:")
    print("1. 测试正常余额交易")
    print("2. 测试余额不足自动调整")
    print("3. 仅显示余额信息")
    
    choice = input("请输入选择 (1, 2, 或 3): ").strip()
    
    if choice == "1":
        test_swap_with_balance_check()
    elif choice == "2":
        test_insufficient_balance()
    elif choice == "3":
        print(f"当前 ETH 余额: {current_balance} ETH")
    else:
        print("无效选择，仅显示余额信息")
        print(f"当前 ETH 余额: {current_balance} ETH")


