#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速交易脚本 - 直接修改变量值
"""

from okxswap_buybot_v1 import okx_swap_mev, NATIVE_ETH, w3
from web3 import Web3

def quick_trade():
    """快速交易函数"""
    
    # =========================
    # 在这里直接修改交易参数
    # =========================
    
    # 输入代币 (ETH 或具体地址)
    token_in = "ETH"
    
    # 输出代币地址
    token_out = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # USDC
    
    # 交易数量 (ETH)
    amount_eth = 0.0001
    
    # 滑点百分比
    slippage = 0.5
    
    # MEV 保护
    enable_mev = True
    
    # =========================
    # 执行交易
    # =========================
    
    print("=" * 60)
    print("快速交易")
    print("=" * 60)
    
    # 参数处理
    if token_in.upper() == 'ETH':
        token_in = NATIVE_ETH
    
    # 显示参数
    print(f"输入代币: {token_in}")
    print(f"输出代币: {token_out}")
    print(f"数量: {amount_eth} ETH")
    print(f"滑点: {slippage}%")
    print(f"MEV 保护: {'启用' if enable_mev else '禁用'}")
    print("=" * 60)
    
    print("开始执行交易...")
    
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
        
        return tx_hash, total_time
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 交易失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        print("=" * 60)
        raise e

if __name__ == "__main__":
    quick_trade()
