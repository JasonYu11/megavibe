#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易参数配置文件
修改这里的参数来配置交易
"""

# =========================
# 交易参数配置
# =========================

# 输入代币地址 (输入 'ETH' 使用原生 ETH，或输入具体的代币地址)
TOKEN_IN = "ETH"  # 修改这里：输入代币地址或 'ETH'

# 输出代币地址
TOKEN_OUT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # 修改这里：输出代币地址 (USDC)

# 交易数量 (ETH)
AMOUNT_ETH = 0.0001  # 修改这里：交易数量

# 滑点百分比
SLIPPAGE = 0.5  # 修改这里：滑点百分比

# 是否启用 MEV 保护
ENABLE_MEV = True  # 修改这里：True=启用，False=禁用

# =========================
# 常用代币地址 (Base 链)
# =========================

# 原生 ETH
NATIVE_ETH = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

# USDC
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# WETH
WETH_BASE = "0x4200000000000000000000000000000000000006"

# USDbC
USDBC_BASE = "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA"

# DAI
DAI_BASE = "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb"

# =========================
# 示例配置
# =========================

# 示例1: ETH -> USDC
EXAMPLE_1 = {
    "token_in": "ETH",
    "token_out": USDC_BASE,
    "amount_eth": 0.001,
    "slippage": 0.5,
    "enable_mev": True
}

# 示例2: ETH -> WETH
EXAMPLE_2 = {
    "token_in": "ETH",
    "token_out": WETH_BASE,
    "amount_eth": 0.0005,
    "slippage": 1.0,
    "enable_mev": False
}

# 示例3: USDC -> ETH
EXAMPLE_3 = {
    "token_in": USDC_BASE,
    "token_out": "ETH",
    "amount_eth": 0.0001,  # 这里 amount_eth 实际上是 USDC 数量
    "slippage": 0.3,
    "enable_mev": True
}

# =========================
# 快速配置函数
# =========================

def get_trade_config():
    """获取当前交易配置"""
    return {
        "token_in": TOKEN_IN,
        "token_out": TOKEN_OUT,
        "amount_eth": AMOUNT_ETH,
        "slippage": SLIPPAGE,
        "enable_mev": ENABLE_MEV
    }

def set_trade_config(token_in, token_out, amount_eth, slippage=0.5, enable_mev=True):
    """设置交易配置"""
    global TOKEN_IN, TOKEN_OUT, AMOUNT_ETH, SLIPPAGE, ENABLE_MEV
    TOKEN_IN = token_in
    TOKEN_OUT = token_out
    AMOUNT_ETH = amount_eth
    SLIPPAGE = slippage
    ENABLE_MEV = enable_mev

def use_example_config(example_name):
    """使用示例配置"""
    examples = {
        "example1": EXAMPLE_1,
        "example2": EXAMPLE_2,
        "example3": EXAMPLE_3
    }
    
    if example_name in examples:
        config = examples[example_name]
        set_trade_config(
            config["token_in"],
            config["token_out"],
            config["amount_eth"],
            config["slippage"],
            config["enable_mev"]
        )
        print(f"已切换到 {example_name} 配置")
    else:
        print(f"未知的示例配置: {example_name}")
        print("可用配置: example1, example2, example3")

