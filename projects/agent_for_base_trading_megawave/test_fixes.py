#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试所有修复
"""

from okxswap_buybot_v1 import (
    get_token_balance, NATIVE_ETH, WALLET_ADDRESS, w3,
    okx_swap_mev, get_swap_data
)
from web3 import Web3

def test_balance_and_gas_check():
    """测试余额和 gas 检查"""
    print("=" * 60)
    print("测试余额和 gas 检查")
    print("=" * 60)
    
    # 检查 ETH 余额
    eth_balance = get_token_balance(NATIVE_ETH, WALLET_ADDRESS)
    eth_balance_eth = w3.from_wei(eth_balance, "ether")
    print(f"ETH 余额: {eth_balance_eth} ETH ({eth_balance} wei)")
    
    # 检查 USDC 余额
    usdc_address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    try:
        usdc_balance = get_token_balance(usdc_address, WALLET_ADDRESS)
        usdc_balance_decimal = usdc_balance / (10 ** 6)  # USDC 有6位小数
        print(f"USDC 余额: {usdc_balance_decimal} USDC ({usdc_balance} wei)")
    except Exception as e:
        print(f"获取 USDC 余额失败: {e}")
    
    return eth_balance_eth, usdc_balance if 'usdc_balance' in locals() else 0

def test_small_amount_swap():
    """测试小额交易"""
    print("\n" + "=" * 60)
    print("测试小额交易")
    print("=" * 60)
    
    # 使用很小的数量进行测试
    amount_eth = 0.000001  # 0.000001 ETH
    print(f"测试数量: {amount_eth} ETH")
    
    try:
        tx_hash, total_time = okx_swap_mev(
            "ETH",  # 输入代币
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # 输出代币 (USDC)
            amount_eth,  # 交易数量
            0.5,  # 滑点
            True  # MEV 保护
        )
        
        if tx_hash and total_time is not None:
            print("\n" + "=" * 60)
            print("✅ 交易成功!")
            print("=" * 60)
            print(f"交易哈希: {tx_hash}")
            print(f"总用时: {total_time:.2f} 秒")
            print(f"区块浏览器: https://basescan.org/tx/{tx_hash}")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ 交易失败!")
            print("=" * 60)
            print("交易返回空值")
            print("=" * 60)
            
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 交易失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        print("=" * 60)

def test_api_only():
    """仅测试 API 调用，不执行交易"""
    print("\n" + "=" * 60)
    print("测试 API 调用")
    print("=" * 60)
    
    try:
        # 测试获取 swap 数据
        result = get_swap_data(
            NATIVE_ETH,
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            w3.to_wei(0.0001, "ether"),
            0.5
        )
        print("✅ API 调用成功")
        print(f"返回数据: {result}")
    except Exception as e:
        print(f"❌ API 调用失败: {e}")

def test_error_handling():
    """测试错误处理"""
    print("\n" + "=" * 60)
    print("测试错误处理")
    print("=" * 60)
    
    # 测试无效滑点
    try:
        result = get_swap_data(
            NATIVE_ETH,
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            w3.to_wei(0.0001, "ether"),
            -1  # 无效滑点
        )
        print("❌ 应该失败但通过了")
    except Exception as e:
        print(f"✅ 正确捕获错误: {e}")
    
    # 测试余额不足
    try:
        tx_hash, total_time = okx_swap_mev(
            "ETH",
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            999999,  # 超大数量
            0.5,
            True
        )
        if tx_hash and total_time is not None:
            print("❌ 应该失败但成功了")
        else:
            print("✅ 正确处理余额不足")
    except Exception as e:
        print(f"✅ 正确捕获余额不足错误: {e}")

if __name__ == "__main__":
    print("测试所有修复")
    
    # 选择测试模式
    print("\n选择测试模式:")
    print("1. 测试余额检查")
    print("2. 测试小额交易")
    print("3. 测试 API 调用")
    print("4. 测试错误处理")
    print("5. 运行所有测试")
    
    choice = input("请输入选择 (1-5): ").strip()
    
    if choice == "1":
        test_balance_and_gas_check()
    elif choice == "2":
        test_small_amount_swap()
    elif choice == "3":
        test_api_only()
    elif choice == "4":
        test_error_handling()
    elif choice == "5":
        test_balance_and_gas_check()
        test_api_only()
        test_error_handling()
        test_small_amount_swap()
    else:
        print("无效选择，运行默认测试")
        test_balance_and_gas_check()


