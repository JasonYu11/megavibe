import requests
from telegram import Bot
import asyncio
from datetime import datetime
from telegram.error import TimedOut, RetryAfter
import json
import signal
import sys
from typing import Optional, Set
import telegram
from telegram.utils.request import Request
import os
from followbot_v3_okxswap1 import virtual_follow_bot_V2
from time import sleep
import time

def load_config(config_file: str) -> list:
    """加载配置文件"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, config_file)
    
    with open(config_path, 'r', encoding='utf-8') as file:
        configs = json.load(file)

    # 确保返回的是监控器配置列表
    if isinstance(configs, dict):
        configs = configs.get('monitors', [])
    
    print(f"✅ 已成功加载 {len(configs)} 个监控器配置")
    return configs

async def run_monitors(configs: list):
    """使用循环方式运行多个监控器"""
    monitors = []
    MONITOR_CLASSES = {
        "virtual_follow_bot_V2": virtual_follow_bot_V2,
    }

    # 初始化所有监控器
    for config in configs:
        monitor_class = MONITOR_CLASSES.get(config.get("monitor_class"))
        print(f"正在初始化: {config.get('name')}")
        
        if monitor_class is None:
            print(f"\n=== 初始化错误 ===")
            print(f"跳过监控器: {config.get('name', 'unknown')}")

            print(f"错误信息: 监控器类未找到")
            continue
            

        # 添加重试逻辑
        for attempt in range(3):  # 最多重试3次

            try:
                monitor = monitor_class(**config)
                monitors.append(monitor)
                print(f"[{config.get('name')}] 监控器初始化成功")
                break  # 成功则跳出重试循环
                
            except Exception as e:
                print(f"[{config.get('name')}] 第{attempt + 1}次初始化失败: {str(e)}")
                if attempt < 2:  # 如果不是最后一次尝试
                    print("等待15秒后重试...")
                    await asyncio.sleep(6)
                else:
                    print(f"[{config.get('name')}] 初始化失败，已达到最大重试次数")
         
    while True:
        # 循环运行每个监控器
        for monitor in monitors:
            try:
                monitor.run()
                #print(f"[{monitor.name}] 监控器运行成功"
                time.sleep(1.2)
            except Exception as e:
                print(f"[{monitor.name}] 监控器运行失败: {str(e)}")
                time.sleep(1.2)
 
if __name__ == "__main__":
    # 确保在脚本所在目录运行
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(current_dir)
    
    # 加载配置文件
    configs = load_config('config1.json')

    if not configs:
        print("❌ 未找到有效的监控器配置")
        sys.exit(1)
        
    # 运行监控器
    asyncio.run(run_monitors(configs))

    print("\n程序已退出")
