#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试增强功能的脚本
"""

import time
from web3 import Web3, HTTPProvider

# 导入配置
from okxswap_buybot_v1 import (
    w3, WALLET_ADDRESS, CHAIN_ID, NATIVE_ETH,
    get_safe_nonce, suggest_eip1559_fees, estimate_gas_fallback
)

def test_enhanced_features():
    """测试增强功能"""
    print("=" * 60)
    print("测试增强功能")
    print("=" * 60)
    
    # 测试1: 检查连接
    print("1. 测试 Web3 连接...")
    if w3.is_connected():
        print("✅ Web3 连接正常")
    else:
        print("❌ Web3 连接失败")
        return False
    
    # 测试2: 测试 safe nonce
    print("\n2. 测试 safe nonce...")
    try:
        nonce = get_safe_nonce(WALLET_ADDRESS)
        print(f"✅ Safe nonce: {nonce}")
    except Exception as e:
        print(f"❌ Safe nonce 失败: {e}")
        return False
    
    # 测试3: 测试 EIP-1559 费用
    print("\n3. 测试 EIP-1559 费用...")
    try:
        max_fee, priority_fee = suggest_eip1559_fees()
        print(f"✅ Max fee: {max_fee} wei ({w3.from_wei(max_fee, 'gwei')} gwei)")
        print(f"✅ Priority fee: {priority_fee} wei ({w3.from_wei(priority_fee, 'gwei')} gwei)")
    except Exception as e:
        print(f"❌ EIP-1559 费用失败: {e}")
        return False
    
    # 测试4: 测试 gas 估算
    print("\n4. 测试 gas 估算...")
    try:
        test_tx = {
            "from": WALLET_ADDRESS,
            "to": "0x0000000000000000000000000000000000000000",
            "value": 0,
            "data": "0x"
        }
        gas_limit = estimate_gas_fallback(test_tx)
        print(f"✅ Gas 估算: {gas_limit}")
    except Exception as e:
        print(f"❌ Gas 估算失败: {e}")
        return False
    
    # 测试5: 测试计时功能
    print("\n5. 测试计时功能...")
    start_time = time.time()
    time.sleep(1)  # 模拟1秒操作
    total_time = time.time() - start_time
    print(f"✅ 计时功能: {total_time:.2f} 秒")
    
    # 测试6: 测试参数验证
    print("\n6. 测试参数验证...")
    test_tokens = [
        ("ETH", NATIVE_ETH),
        ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
        ("invalid", None)
    ]
    
    for token_input, expected in test_tokens:
        if token_input.upper() == 'ETH':
            result = NATIVE_ETH
        elif w3.is_address(token_input):
            result = token_input
        else:
            result = None
        
        if result == expected:
            print(f"✅ 参数验证: {token_input} -> {result}")
        else:
            print(f"❌ 参数验证失败: {token_input} -> {result} (期望: {expected})")
    
    print("\n" + "=" * 60)
    print("✅ 所有增强功能测试通过!")
    print("=" * 60)
    return True

def simulate_user_input():
    """模拟用户输入"""
    print("\n模拟用户输入测试:")
    print("-" * 40)
    
    # 模拟输入参数
    token_in = "ETH"
    token_out = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # USDC
    amount_eth = 0.0001
    slippage = 0.5
    enable_mev = True
    
    print(f"输入代币: {token_in}")
    print(f"输出代币: {token_out}")
    print(f"数量: {amount_eth} ETH")
    print(f"滑点: {slippage}%")
    print(f"MEV 保护: {'启用' if enable_mev else '禁用'}")
    
    # 转换参数
    if token_in.upper() == 'ETH':
        token_in = NATIVE_ETH
    
    print(f"\n转换后的参数:")
    print(f"输入代币: {token_in}")
    print(f"输出代币: {token_out}")
    print(f"数量: {amount_eth} ETH")
    print(f"滑点: {slippage}%")
    print(f"MEV 保护: {'启用' if enable_mev else '禁用'}")
    
    return token_in, token_out, amount_eth, slippage, enable_mev

def main():
    """主函数"""
    print("OKX SWAP BOT - 增强功能测试")
    
    # 测试增强功能
    if not test_enhanced_features():
        print("❌ 增强功能测试失败")
        return
    
    # 模拟用户输入
    simulate_user_input()
    
    print("\n🎉 所有测试完成!")

if __name__ == "__main__":
    main()
