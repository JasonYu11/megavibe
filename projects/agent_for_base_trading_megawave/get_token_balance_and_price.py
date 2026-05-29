from typing import Optional
import requests
import time
from datetime import datetime, timedelta
from get_token_price_from_binance import get_token_price_and_info_from_binance
from get_virtual_pool_address import get_virtual_pool_address_neipan,get_virtual_pool_address_waipan
API_KEY1 = os.getenv("BASESCAN_API_KEY", "")
K_POOL=6000000000000
VIRTUAL_FUTURES_SYMBOL="VIRTUALUSDT"
VIRTUAL_ADDRESS="0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
API_KEY2 = os.getenv("BASESCAN_API_KEY_2", "")
API_KEY3 = os.getenv("BASESCAN_API_KEY_3", "")
# 添加缓存变量
_virtual_price_cache = {
    'price': None,
    'last_update': None
}

def get_cached_virtual_price(cache_duration: int = 15) -> Optional[float]:
    """
    获取虚拟代币价格，带有缓存机制
    
    Args:
        cache_duration: 缓存时间（秒），默认60秒
    
    Returns:
        返回代币价格，如果获取失败则返回None
    """
    global _virtual_price_cache
    current_time = datetime.now()
    
    # 如果缓存存在且未过期，直接返回缓存的价格
    if (_virtual_price_cache['price'] is not None and 
        _virtual_price_cache['last_update'] is not None and 
        current_time - _virtual_price_cache['last_update'] < timedelta(seconds=cache_duration)):
        return _virtual_price_cache['price'],_virtual_price_cache['price_change_percent']
    
    # 缓存不存在或已过期，重新获取价格
    price , info= get_token_price_and_info_from_binance(VIRTUAL_FUTURES_SYMBOL)
    #print(price,info)
    #input()
    if price is not None:
        _virtual_price_cache['price'] = price
        _virtual_price_cache['price_change_percent'] = info['price_change_percent']
        _virtual_price_cache['last_update'] = current_time

    return _virtual_price_cache['price'],_virtual_price_cache['price_change_percent']

def get_token_balance(address: str, contract_address: str, api_key: str, max_retries: int = 3) -> Optional[float]:
    """
    获取指定地址在特定代币合约中的余额
    
    Args:
        address: 要查询的钱包地址
        contract_address: 代币合约地址
        max_retries: 最大重试次数，默认3次
    
    Returns:
        返回代币余额，如果请求失败则返回None
    """
    base_url = "https://api.basescan.org/api"
    params = {
        "module": "account",
        "action": "tokenbalance",
        "contractaddress": contract_address,
        "address": address,
        "tag": "latest",
        "apikey": api_key
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data["status"] == "1" and data["message"] == "OK":
                # 将余额转换为浮点数，考虑代币精度（假设是18位小数）
                balance = int(data["result"]) / (10 ** 18)
                #print(f"地址 {address} 的代币余额: {balance}")
                return balance
            else:
                print(f"API返回错误: {data['message']}")
                return None
                
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                print(f"第{attempt + 1}次请求失败: {e}，准备重试...")
                time.sleep(1)  # 添加延迟，避免请求过于频繁
                continue
            else:
                print(f"所有重试都失败了: {e}")
                return None
def get_neipan_pool_token_balance( virtual_pool_address: str):
    if not virtual_pool_address:
        print("未获取到虚拟池地址")
        return None
    balance=get_token_balance(virtual_pool_address, VIRTUAL_ADDRESS,API_KEY1)
    return balance

def get_waipan_pool_token_balance(virtual_pool_address: str,token_address: str):
    if not virtual_pool_address:
        print("未获取到虚拟池地址")
        return None
    balance_virtual=get_token_balance(virtual_pool_address, VIRTUAL_ADDRESS,API_KEY2)
    balance_token=get_token_balance(virtual_pool_address, token_address,API_KEY3)
    return balance_virtual,balance_token
def get_neipan_token_price(virtual_pool_address: str="0xd189d039328ba4d6710ff608523e45d52d679e24"):
    pool_token_balance = get_neipan_pool_token_balance(virtual_pool_address)
    if not pool_token_balance:
        print("未获取到虚拟池代币余额")
        return None
    pool_token_balance = round(pool_token_balance, 3)
    pool_token_price_by_virtual = (pool_token_balance + 6000)**2/K_POOL
    # 使用带缓存的价格获取函数
    virtual_price , price_change_percent= get_cached_virtual_price()
    if virtual_price is None:
        print("未获取到虚拟代币价格")
        return None
    pool_token_price_by_usd = pool_token_price_by_virtual * virtual_price
    #print(f"pool_token_price_by_virtual:{pool_token_price_by_virtual} ")
    return pool_token_price_by_usd, pool_token_price_by_virtual,virtual_price,price_change_percent
def get_waipan_token_price(virtual_pool_address: str,token_address: str):
    balance_virtual,balance_token=get_waipan_pool_token_balance(virtual_pool_address,token_address)
    if not balance_virtual or not balance_token:
        print("未获取到虚拟池代币余额")
        return None
    pool_token_price_by_virtual = balance_virtual/balance_token
    virtual_price , price_change_percent= get_cached_virtual_price()
    if virtual_price is None:
        print("未获取到虚拟代币价格")
        return None
    pool_token_price_by_usd = pool_token_price_by_virtual * virtual_price
    return pool_token_price_by_usd,pool_token_price_by_virtual,virtual_price,price_change_percent
    
    
    
    
    
    
    

a=3
if a==1:
    while True:
        virtual_pool_address=get_virtual_pool_address_neipan("0xf2A35E6597CE81070ccC0E3C98e45B1E294783A4")
        pool_token_price_by_usd, pool_token_price_by_virtual, virtual_price , price_change_percent= get_neipan_token_price(virtual_pool_address)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] 价格信息:")
        print(f"  USD价格: {pool_token_price_by_usd:.6f}")
        print(f"  virtual本位价格: {pool_token_price_by_virtual:.6f}")
        print(f"  virtual价格: {virtual_price:.6f}")
        print(f"  virtual价格变化: {price_change_percent:.6f}")
        print("-" * 50)
        time.sleep(5)  # 暂停1秒
elif a==2:
    while True:
        virtual_pool_address=get_virtual_pool_address_waipan("0xf7b0dd0B642a6ccc2fc4d8FfE2BfFb0caC8C43C8")
        pool_token_price_by_usd, pool_token_price_by_virtual, virtual_price , price_change_percent= get_waipan_token_price(virtual_pool_address,"0xf7b0dd0B642a6ccc2fc4d8FfE2BfFb0caC8C43C8")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] 价格信息:")
        print(f"  USD价格: {pool_token_price_by_usd:.6f}")
        print(f"  virtual本位价格: {pool_token_price_by_virtual:.6f}")
        print(f"  virtual价格: {virtual_price:.6f}")
        print(f"  virtual价格变化: {price_change_percent:.6f}")
        print("-" * 50)
        time.sleep(5)  # 暂停1秒
