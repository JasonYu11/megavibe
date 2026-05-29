import requests
import os
from typing import Optional, Dict, Any
import time

def get_debank_token_info( token_address: str,chain_id: str="base", access_key: str=os.getenv("DEBANK_ACCESS_KEY", ""), max_retries: int = 5) -> Optional[Dict[str, Any]]:
    """
    从DeBank API获取代币信息
    
    Args:
        chain_id: 链ID (如 'eth', 'bsc' 等)
        token_address: 代币合约地址
        access_key: DeBank API访问密钥
        max_retries: 最大重试次数，默认3次
    
    Returns:
        返回代币信息字典，如果请求失败则返回None
    """
    base_url = f"https://pro-openapi.debank.com/v1/token"
    params = {
        "chain_id": chain_id,
        "id": token_address
    }
    headers = {
        "accept": "application/json",
        "AccessKey": access_key
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(base_url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            #print(f"获取到代币信息: {data}")
            return data
                
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                print(f"第{attempt + 1}次请求失败: {e}，准备重试...")
                time.sleep(1)  # 添加延迟，避免请求过于频繁
                continue
            else:
                print(f"所有重试都失败了: {e}")
                return None
def get_token_price(token_address: str):
    token_info=get_debank_token_info(token_address)
    if not token_info:
        print("未获取到代币信息")
        return None
    return token_info.get("symbol"),token_info.get("name")
a=2
if a==1:
    # 获取USDT代币信息
    token_symple,token_name=get_token_price(
        token_address="0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b",
    )
    if token_price:
        print(f"代币名称: {token_name}")
        print(f"代币价格: {token_price}")
        print(f"代币地址: {token_symple}")
