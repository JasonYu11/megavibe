#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试滑点参数修复
"""

from okxswap_buybot_v1 import (
    get_swap_data, NATIVE_ETH, WALLET_ADDRESS, w3,
    okx_swap_mev
)
from web3 import Web3

def test_slippage_validation():
    """测试滑点参数验证"""
    print("=" * 60)
    print("测试滑点参数验证")
    print("=" * 60)
    
    # 测试用例
    test_cases = [
        {"slippage": 0.5, "expected": "valid"},
        {"slippage": 1.0, "expected": "valid"},
        {"slippage": 5.0, "expected": "valid"},
        {"slippage": 0, "expected": "invalid"},
        {"slippage": -1, "expected": "invalid"},
        {"slippage": 101, "expected": "invalid"},
        {"slippage": "0.5", "expected": "valid"},
        {"slippage": "invalid", "expected": "invalid"},
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n测试 {i}: 滑点 = {case['slippage']}")
        try:
            # 尝试调用 get_swap_data
            result = get_swap_data(
                NATIVE_ETH,
                "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                w3.to_wei(0.0001, "ether"),
                case["slippage"]
            )
            if case["expected"] == "valid":
                print("✅ 通过 - 参数有效")
            else:
                print("❌ 失败 - 应该无效但通过了")
        except Exception as e:
            if case["expected"] == "invalid":
                print(f"✅ 通过 - 正确捕获错误: {e}")
            else:
                print(f"❌ 失败 - 应该有效但出错: {e}")

def test_small_amount_swap():
    """测试小额交易"""
    print("\n" + "=" * 60)
    print("测试小额交易")
    print("=" * 60)
    
    try:
        # 使用很小的数量进行测试
        amount_eth = 0.000001  # 0.000001 ETH
        print(f"测试数量: {amount_eth} ETH")
        
        tx_hash, total_time = okx_swap_mev(
            "ETH",  # 输入代币
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # 输出代币 (USDC)
            amount_eth,  # 交易数量
            0.5,  # 滑点
            True  # MEV 保护
        )
        
        if tx_hash:
            print("\n" + "=" * 60)
            print("✅ 交易成功!")
            print("=" * 60)
            print(f"交易哈希: {tx_hash}")
            print(f"总用时: {total_time:.2f} 秒")
            print(f"区块浏览器: https://basescan.org/tx/{tx_hash}")
            print("=" * 60)
        else:
            print("❌ 交易返回空哈希")
            
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 交易失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        print("=" * 60)

def test_different_slippage_values():
    """测试不同的滑点值"""
    print("\n" + "=" * 60)
    print("测试不同的滑点值")
    print("=" * 60)
    
    slippage_values = [0.1, 0.5, 1.0, 2.0, 5.0]
    
    for slippage in slippage_values:
        print(f"\n测试滑点: {slippage}%")
        try:
            # 只测试 API 调用，不实际执行交易
            result = get_swap_data(
                NATIVE_ETH,
                "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                w3.to_wei(0.0001, "ether"),
                slippage
            )
            print(f"✅ 滑点 {slippage}% 有效")
        except Exception as e:
            print(f"❌ 滑点 {slippage}% 失败: {e}")

if __name__ == "__main__":
    print("滑点参数修复测试")
    
    # 选择测试模式
    print("\n选择测试模式:")
    print("1. 测试滑点参数验证")
    print("2. 测试小额交易")
    print("3. 测试不同滑点值")
    print("4. 运行所有测试")
    
    choice = input("请输入选择 (1, 2, 3, 或 4): ").strip()
    
    if choice == "1":
        test_slippage_validation()
    elif choice == "2":
        test_small_amount_swap()
    elif choice == "3":
        test_different_slippage_values()
    elif choice == "4":
        test_slippage_validation()
        test_small_amount_swap()
        test_different_slippage_values()
    else:
        print("无效选择，运行默认测试")
        test_slippage_validation()


