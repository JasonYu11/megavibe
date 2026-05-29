#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试通用代币处理
"""

from okxswap_buybot_v1 import (
    get_token_balance, NATIVE_ETH, WALLET_ADDRESS, w3,
    okx_swap_mev, ERC20_ABI
)

def test_token_info():
    """测试代币信息获取"""
    print("=" * 60)
    print("测试代币信息获取")
    print("=" * 60)
    
    # 测试 ETH
    print("1. 测试 ETH:")
    eth_balance = get_token_balance(NATIVE_ETH, WALLET_ADDRESS)
    eth_balance_eth = w3.from_wei(eth_balance, "ether")
    print(f"   ETH 余额: {eth_balance_eth} ETH")
    
    # 测试 USDC
    print("\n2. 测试 USDC:")
    usdc_address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    try:
        usdc_balance = get_token_balance(usdc_address, WALLET_ADDRESS)
        usdc_contract = w3.eth.contract(address=usdc_address, abi=ERC20_ABI)
        usdc_decimals = usdc_contract.functions.decimals().call()
        usdc_symbol = usdc_contract.functions.symbol().call()
        usdc_balance_display = usdc_balance / (10 ** usdc_decimals)
        print(f"   USDC 余额: {usdc_balance_display} {usdc_symbol}")
        print(f"   USDC 精度: {usdc_decimals}")
        print(f"   USDC 符号: {usdc_symbol}")
    except Exception as e:
        print(f"   获取 USDC 信息失败: {e}")
    
    # 测试其他代币
    print("\n3. 测试其他代币:")
    other_token = "0x0bc945e3Ea693ad1527683d9cfE999407EBAAbB0"
    try:
        other_balance = get_token_balance(other_token, WALLET_ADDRESS)
        other_contract = w3.eth.contract(address=other_token, abi=ERC20_ABI)
        other_decimals = other_contract.functions.decimals().call()
        other_symbol = other_contract.functions.symbol().call()
        other_balance_display = other_balance / (10 ** other_decimals)
        print(f"   代币余额: {other_balance_display} {other_symbol}")
        print(f"   代币精度: {other_decimals}")
        print(f"   代币符号: {other_symbol}")
    except Exception as e:
        print(f"   获取代币信息失败: {e}")

def test_swap_with_different_tokens():
    """测试不同代币的交换"""
    print("\n" + "=" * 60)
    print("测试不同代币的交换")
    print("=" * 60)
    
    # 测试用例
    test_cases = [
        {
            "name": "ETH -> USDC",
            "token_in": "ETH",
            "token_out": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "amount": 0.000001
        },
        {
            "name": "USDC -> ETH",
            "token_in": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "token_out": "ETH",
            "amount": 0.000001
        },
        {
            "name": "USDC -> 其他代币",
            "token_in": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "token_out": "0x0bc945e3Ea693ad1527683d9cfE999407EBAAbB0",
            "amount": 0.000001
        }
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n{i}. {case['name']}:")
        print(f"   输入代币: {case['token_in']}")
        print(f"   输出代币: {case['token_out']}")
        print(f"   数量: {case['amount']}")
        
        try:
            # 只测试余额检查，不实际执行交易
            if case['token_in'].upper() == 'ETH':
                token_in = NATIVE_ETH
            else:
                token_in = case['token_in']
            
            if case['token_out'].upper() == 'ETH':
                token_out = NATIVE_ETH
            else:
                token_out = case['token_out']
            
            # 检查输入代币余额
            balance = get_token_balance(token_in, WALLET_ADDRESS)
            if token_in.lower() == NATIVE_ETH.lower():
                balance_display = w3.from_wei(balance, "ether")
                symbol = "ETH"
            else:
                try:
                    contract = w3.eth.contract(address=token_in, abi=ERC20_ABI)
                    decimals = contract.functions.decimals().call()
                    symbol = contract.functions.symbol().call()
                    balance_display = balance / (10 ** decimals)
                except:
                    balance_display = balance / (10 ** 18)
                    symbol = "TOKEN"
            
            print(f"   当前余额: {balance_display} {symbol}")
            
            # 检查是否有足够余额
            amount_wei = w3.to_wei(case['amount'], "ether")
            if balance >= amount_wei:
                print(f"   ✅ 余额充足")
            else:
                print(f"   ❌ 余额不足")
                
        except Exception as e:
            print(f"   ❌ 检查失败: {e}")

def test_balance_check():
    """测试余额检查功能"""
    print("\n" + "=" * 60)
    print("测试余额检查功能")
    print("=" * 60)
    
    try:
        # 测试一个很小的数量
        amount_eth = 0.0000001  # 0.0000001 ETH
        print(f"测试数量: {amount_eth} ETH")
        
        # 只运行到余额检查部分，不实际执行交易
        print("开始余额检查...")
        
        # 这里我们只测试余额检查逻辑，不执行完整交易
        token_balance = get_token_balance(NATIVE_ETH, WALLET_ADDRESS)
        balance_eth = w3.from_wei(token_balance, "ether")
        print(f"ETH 余额: {balance_eth} ETH")
        
        amount_in_wei = w3.to_wei(amount_eth, "ether")
        print(f"请求数量: {amount_eth} ETH ({amount_in_wei} wei)")
        
        if token_balance >= amount_in_wei:
            print("✅ 余额充足")
        else:
            print("❌ 余额不足")
            
    except Exception as e:
        print(f"❌ 余额检查失败: {e}")

if __name__ == "__main__":
    print("通用代币处理测试")
    
    # 选择测试模式
    print("\n选择测试模式:")
    print("1. 测试代币信息获取")
    print("2. 测试不同代币的交换")
    print("3. 测试余额检查功能")
    print("4. 运行所有测试")
    
    choice = input("请输入选择 (1-4): ").strip()
    
    if choice == "1":
        test_token_info()
    elif choice == "2":
        test_swap_with_different_tokens()
    elif choice == "3":
        test_balance_check()
    elif choice == "4":
        test_token_info()
        test_swap_with_different_tokens()
        test_balance_check()
    else:
        print("无效选择，运行默认测试")
        test_token_info()


