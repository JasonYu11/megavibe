import requests
from typing import Optional, Dict
import time

def get_virtual_futures_price(symbol: str = "VIRTUALUSDT") -> Optional[float]:
    """
    获取币安合约价格（无需API认证）
    
    Args:
        symbol: 交易对符号，例如 'VIRTUALUSDT'
        
    Returns:
        float: 返回最新价格
        None: 如果请求失败则返回 None
    """
    try:
        # 币安合约API endpoint
        url = "https://fapi.binance.com/fapi/v1/ticker/price"
        
        # 添加交易对参数
        params = {"symbol": symbol.upper()}
        
        # 发送GET请求
        response = requests.get(url, params=params)
        
        # 检查响应状态
        if response.status_code == 200:
            data = response.json()
            return float(data["price"])
        else:
            print(f"请求失败，状态码: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"发生错误: {str(e)}")
        return None

def get_virtual_futures_info(symbol: str = "VIRTUALUSDT") -> Optional[Dict]:
    """
    获取合约详细信息（无需API认证）
    
    Args:
        symbol: 交易对符号，例如 'VIRTUALUSDT'
        
    Returns:
        Dict: 包含价格和24小时统计数据的字典
        None: 如果请求失败则返回 None
    """
    try:
        # 24小时统计数据的endpoint
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        params = {"symbol": symbol.upper()}
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return {
                'symbol': data['symbol'],
                'price': float(data['lastPrice']),
                'price_change': float(data['priceChange']),
                'price_change_percent': float(data['priceChangePercent']),
                'volume': float(data['volume']),
                'high_24h': float(data['highPrice']),
                'low_24h': float(data['lowPrice'])
            }
        else:
            print(f"请求失败，状态码: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"发生错误: {str(e)}")
        return None
def get_token_price_and_info_from_binance(token_address: str):
    try:
        for i in range(3):
            price=get_virtual_futures_price(token_address)
            info=get_virtual_futures_info(token_address)
            if price and info:
                break
            time.sleep(0.5)
    except Exception as e:
        print(f"发生错误: {str(e)}")
        return None
    if not price:
        print("未获取到代币价格")
        return None
    if not info:
        print("未获取到代币信息")
        return None
    return price,info
# 使用示例
a=2
if a==1:
    # 获取VIRTUAL合约价格
    price = get_virtual_futures_price("ETHUSDT")
    if price:
        print(f"VIRTUAL合约当前价格: ${price:,.2f}")
    
    # 获取详细信息
    info = get_virtual_futures_info("VIRTUALUSDT")
    if info:
        print("\nVIRTUAL合约24小时统计数据:")
        for key, value in info.items():
            print(f"{key}: {value}")
    