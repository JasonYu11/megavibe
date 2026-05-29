#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用配置文件的交易脚本示例
"""

from okxswap_buybot_v1 import okx_swap_mev, NATIVE_ETH, w3
from trade_config import get_trade_config, use_example_config
from web3 import Web3

def run_trade_with_config():
    """使用配置文件运行交易"""
    print("=" * 60)
    print("OKX SWAP BOT - 配置文件版本")
    print("=" * 60)
    
    # 获取配置
    config = get_trade_config()
    token_in = config["token_in"]
    token_out = config["token_out"]
    amount_eth = config["amount_eth"]
    slippage = config["slippage"]
    enable_mev = config["enable_mev"]
    
    # 参数处理
    if token_in.upper() == 'ETH':
        token_in = NATIVE_ETH
    elif not Web3.is_address(token_in):
        raise ValueError("输入代币地址格式错误")
    
    if not Web3.is_address(token_out):
        raise ValueError("输出代币地址格式错误")
    
    # 显示参数
    print("\n" + "=" * 60)
    print("交易参数确认:")
    print(f"输入代币: {token_in}")
    print(f"输出代币: {token_out}")
    print(f"数量: {amount_eth} ETH")
    print(f"滑点: {slippage}%")
    print(f"MEV 保护: {'启用' if enable_mev else '禁用'}")
    print("=" * 60)
    
    print("\n开始执行交易...")
    
    try:
        # 执行交易
        tx_hash, total_time = okx_swap_mev(
            token_in, 
            token_out, 
            amount_eth, 
            slippage, 
            enable_mev
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

def run_example_trades():
    """运行示例交易"""
    print("=" * 60)
    print("运行示例交易")
    print("=" * 60)
    
    examples = ["example1", "example2", "example3"]
    
    for example in examples:
        print(f"\n--- 运行 {example} ---")
        try:
            # 切换到示例配置
            use_example_config(example)
            
            # 运行交易
            run_trade_with_config()
            
            print(f"✅ {example} 完成")
            
        except Exception as e:
            print(f"❌ {example} 失败: {e}")
        
        print("-" * 40)

if __name__ == "__main__":
    # 选择运行模式
    print("选择运行模式:")
    print("1. 使用当前配置运行交易")
    print("2. 运行所有示例交易")
    
    choice = input("请输入选择 (1 或 2): ").strip()
    
    if choice == "1":
        run_trade_with_config()
    elif choice == "2":
        run_example_trades()
    else:
        print("无效选择，使用默认配置运行交易")
        run_trade_with_config()
