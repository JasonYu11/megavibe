
import requests
from typing import Optional, Dict, Any
import json  # 添加json导入
import time
import os

API_KEY = os.getenv("BASESCAN_API_KEY", "")
MY_ADDRESS="0x8EF454c23822C5373df37e8c5E8987aC64dB96F1"

def get_logs_from_base(contract_address: str, tx_hash: str="0xe6d157a0f383b05e8e88adf9ca16e89c20b1378844bb6047ee4155846f4afceb", max_retries: int = 3) -> Optional[Dict[str, Any]]:
    """
    从Base区块链获取指定合约地址和交易哈希的日志数据，并解码topic1
    
    Args:
        contract_address: 合约地址
        tx_hash: 交易哈希
        max_retries: 最大重试次数，默认3次
        
    Returns:
        返回过滤后的日志数据，如果请求失败则返回None
    """
    encoded_address = "0x" + MY_ADDRESS[2:].lower().zfill(64)
    base_url = "https://api.basescan.org/api"
    params = {
        "module": "logs",
        "action": "getLogs",
        "fromBlock": 0,
        "toBlock": 9999999999999,
        "address": contract_address,
        "topic2": encoded_address,
        "page": "1",
        "offset": "200",
        "sort": "desc",
        "apikey": API_KEY,
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # 筛选特定交易哈希的日志并解码topic1
            if data and data.get("result"):
                filtered_result = []
                for log in data["result"]:
                    #print(f"hash:{log.get('transactionHash', '').lower()}")
                    #print(f"tx_hash:{tx_hash.lower()}")
                    if log.get("transactionHash", "").lower() == tx_hash.lower():
                        # 提取并解码topic1
                        topics = log.get("topics", [])
                        if len(topics) > 1:
                            topic1 = topics[1]
                            decoded_address = "0x" + topic1[-40:]
                            log["decoded_topic1"] = decoded_address
                        filtered_result.append(log)
                data["result"] = filtered_result
                #print(data)
                return data
                
            return data
        except requests.RequestException as e:
            if attempt < max_retries - 1:  # 如果不是最后一次尝试
                print(f"第{attempt + 1}次请求失败: {e}，准备重试...")
                continue
            else:
                print(f"所有重试都失败了: {e}")
                return None
def get_logs_from_base_no_filter(contract_address: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
   """
   从Base区块链获取指定合约地址的日志数据，并解码topic1
   
   Args:
       contract_address: 合约地址
       max_retries: 最大重试次数，默认3次
       
   Returns:
       返回日志数据，如果请求失败则返回None
   """
   encoded_address = "0x" + MY_ADDRESS[2:].lower().zfill(64)
   base_url = "https://api.basescan.org/api"
   params = {
       "module": "logs",
       "action": "getLogs",
       "fromBlock": 0,
       "toBlock": 9999999999999,
       "address": contract_address,
       "topic2": encoded_address,
       "page": "1",
       "offset": "20",
       "sort": "asc",
       "apikey": API_KEY,
   }
   
   for attempt in range(max_retries):
       try:
           response = requests.get(base_url, params=params)
           response.raise_for_status()
           data = response.json()
           
           # 直接解码所有日志的topic1
           if data and data.get("result"):
               for log in data["result"]:
                   topics = log.get("topics", [])
                   if len(topics) > 1:
                       topic1 = topics[1]
                       decoded_address = "0x" + topic1[-40:]
                       log["decoded_topic1"] = decoded_address
               print(data)
               return data
               
           return data
       except requests.RequestException as e:
           if attempt < max_retries - 1:
               print(f"第{attempt + 1}次请求失败: {e}，准备重试...")
               continue
           else:
               print(f"所有重试都失败了: {e}")
               return None
           
def get_trans_from_base(contract_address: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
   """
   从Base区块链获取指定合约地址的交易记录
   
   Args:
       contract_address: 合约地址
       max_retries: 最大重试次数，默认3次
       
   Returns:
       返回交易记录数据，如果请求失败则返回None
   """
   base_url = "https://api.basescan.org/api"
   params = {
       "module": "account",
       "action": "tokentx",
       "contractaddress": contract_address,
       "page": "1",
       "offset": "3",
       "startblock": "0",
       "endblock": "999999999",
       "sort": "asc",
       "apikey": API_KEY
   }
   
   for attempt in range(max_retries):
       try:
           response = requests.get(base_url, params=params)
           response.raise_for_status()
           data = response.json()
           
           if data and data.get("status") == "1":
               print(f"获取到 {len(data.get('result', []))} 条交易记录")
               return data
           else:
               print(f"API返回错误: {data.get('message', '未知错误')}")
               
       except requests.RequestException as e:
           if attempt < max_retries - 1:
               print(f"第{attempt + 1}次请求失败: {e}，准备重试...")
               time.sleep(1)
               continue
           else:
               print(f"所有重试都失败了: {e}")
               
   return None

def get_virtual_pool_address_waipan(token_address):
    try:
        for i in range(3):  
            trans = get_trans_from_base(token_address)
            if trans and trans.get("result") and len(trans["result"]) >= 3:
                virtual_pool_address = trans["result"][2]["to"]
                print(f"获取到虚拟池地址: {virtual_pool_address}")
                return virtual_pool_address
            else:
                time.sleep(1)
        return None
    except Exception as e:
        print(f"获取虚拟池地址失败: {str(e)}")
        return None
def get_virtual_pool_address_neipan(token_address):
    try:
        for i in range(3):  
            trans = get_trans_from_base(token_address)
            if trans and trans.get("result") and len(trans["result"]) >= 3:
                virtual_pool_address = trans["result"][1]["to"]
                print(f"获取到虚拟池地址: {virtual_pool_address}")
                return virtual_pool_address
            else:
                time.sleep(1)
        return None
    except Exception as e:
        print(f"获取虚拟池地址失败: {str(e)}")
        return None
a=3
if a==1:
    virtual_pool_address=get_virtual_pool_address("0xd1447D4c2E4F56a9Cab886a4528DD1006BEd249F")
    print(virtual_pool_address)
if a==2:
    #trans=get_trans_from_base("0xf5f2a79eECcF6e7F4C570c803F529930e29cc96B")
    virtual_pool_address=get_virtual_pool_address_neipan("0x0a89132a12d8553C64AEc9D6230E719Ec8AEf69F")
    print(virtual_pool_address)
#logs=get_logs_from_base("0xD400cd7e9CAeAf473C9051AfA9Bf4FbB8Ab5D660")
#json_logs=json.dumps(logs, indent=2, ensure_ascii=False)
#print(json_logs)





