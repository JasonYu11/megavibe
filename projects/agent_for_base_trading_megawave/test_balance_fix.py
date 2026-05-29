#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试余额检查修复
"""

from okxswap_buybot_v1 import (
    get_token_balance, NATIVE_ETH, WALLET_ADDRESS, w3,
    okx_swap_mev, suggest_eip1559_fees
)

def test_balance_analysis():
    """分析余额情况"""
    print("=" * 60)
    print("余额分析")
    print("=" * 60)
    
    # 检查 ETH 余额
    eth_balance = get_token_balance(NATIVE_ETH, WALLET_ADDRESS)
    eth_balance_eth = w3.from_wei(eth_balance, "ether")
    print(f"ETH 余额: {eth_balance_eth} ETH ({eth_balance} wei)")
    
    # 估算 gas 费用
    estimated_gas = 200000
    max_fee, priority_fee = suggest_eip1559_fees()
    estimated_gas_cost = estimated_gas * max_fee
    estimated_gas_cost_eth = w3.from_wei(estimated_gas_cost, "ether")
    print(f"估算 gas 费用: {estimated_gas_cost_eth} ETH")
    
    # 计算可用余额
    available_for_trade = eth_balance - estimated_gas_cost
    available_for_trade_eth = w3.from_wei(available_for_trade, "ether")
    print(f"可用于交易的余额: {available_for_trade_eth} ETH")
    
    if available_for_trade <= 0:
        print("❌ ETH 余额不足，无法进行任何交易")
        return False
    else:
        print("✅ 有足够余额进行交易")
        return True

def test_insufficient_balance():
    """测试余额不足的情况"""
    print("\n" + "=" * 60)
    print("测试余额不足")
    print("=" * 60)
    
    try:
        # 尝试一个明显超过余额的数量
        amount_eth = 1.0  # 1 ETH，明显超过余额
        print(f"尝试交易: {amount_eth} ETH")
        
        tx_hash, total_time = okx_swap_mev(
            "ETH",
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            amount_eth,
            0.5,
            True
        )
        
        if tx_hash and total_time is not None:
            print("❌ 应该失败但成功了")
        else:
            print("✅ 正确处理余额不足")
            
    except Exception as e:
        print(f"✅ 正确捕获余额不足错误: {e}")

def test_small_amount():
    """测试小额交易"""
    print("\n" + "=" * 60)
    print("测试小额交易")
    print("=" * 60)
    
    # 先分析余额
    if not test_balance_analysis():
        print("余额不足，跳过小额交易测试")
        return
    
    try:
        # 使用一个很小的数量
        amount_eth = 0.0000001  # 0.0000001 ETH
        print(f"尝试交易: {amount_eth} ETH")
        
        tx_hash, total_time = okx_swap_mev(
            "ETH",
            "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            amount_eth,
            0.5,
            True
        )
        
        if tx_hash and total_time is not None:
            print("\n" + "=" * 60)
            print("✅ 交易成功!")
            print("=" * 60)
            print(f"交易哈希: {tx_hash}")
            print(f"总用时: {total_time:.2f} 秒")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ 交易失败!")
            print("=" * 60)
            print("交易返回空值")
            print("=" * 60)
            
    except Exception as e:
        print(f"❌ 交易失败: {e}")

if __name__ == "__main__":
    print("余额检查修复测试")
    
    # 选择测试模式
    print("\n选择测试模式:")
    print("1. 分析余额情况")
    print("2. 测试余额不足")
    print("3. 测试小额交易")
    print("4. 运行所有测试")
    
    choice = input("请输入选择 (1-4): ").strip()
    
    if choice == "1":
        test_balance_analysis()
    elif choice == "2":
        test_insufficient_balance()
    elif choice == "3":
        test_small_amount()
    elif choice == "4":
        test_balance_analysis()
        test_insufficient_balance()
        test_small_amount()
    else:
        print("无效选择，运行默认测试")
        test_balance_analysis()


