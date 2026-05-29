#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试脚本
"""

from okxswap_buybot_v1 import (
    get_token_balance, NATIVE_ETH, WALLET_ADDRESS, w3,
    okx_swap_mev
)

def test_balance():
    """测试余额检查"""
    print("=" * 60)
    print("测试余额检查")
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

def test_small_swap():
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

if __name__ == "__main__":
    print("简单测试脚本")
    
    # 先测试余额
    test_balance()
    
    # 询问是否继续测试交易
    choice = input("\n是否继续测试小额交易? (y/n): ").strip().lower()
    if choice == 'y':
        test_small_swap()
    else:
        print("测试结束")


