import requests
from telegram import Bot
from datetime import datetime
from telegram.error import TimedOut, RetryAfter
from telegram.utils.request import Request
import time
import os
import traceback
from time import sleep
import telegram
from telegram.error import TimedOut, BadRequest
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
from virtual_fun_buybot_V2_0 import buy_virtualfun_token,sell_virtualfun_token
from kyberswap_buybot import kyberswap_swap
from getpass import getpass
from de_co1 import check_password
from get_price_directly import get_price_directly
from get_token_price_from_binance import get_virtual_futures_price
from debank_token_info import DebankTokenAPI
ACCESS_KEY = os.getenv("DEBANK_ACCESS_KEY", "")
class virtual_follow_bot_V2:
    def __init__(self, 
                 name, 
                 monitor_class, 
                 chain_id, 
                 key_basescan, 
                 key_debank, 
                 url_basescan, 
                 url_base_explorer, 
                 url_debank, 
                 url_base_mainnet, 
                 basic_tokenid, 
                 target_address, 
                 my_address, 
                 bot_token, 
                 chat_id,
                 follow_limit):
        """初始化监控器"""  
        # 首先初始化基本属性
        print(f"请输入密码:")
        self.word = getpass().strip()
        if self.word != 'jason1':
            print("密码错误")
            exit()
        self.name = name
        self.monitor_class = monitor_class
        self.chain_id = chain_id
        self.key_basescan = key_basescan
        self.key_debank = key_debank
        self.url_basescan = url_basescan
        self.url_base_explorer = url_base_explorer
        self.url_debank = url_debank
        self.url_base_mainnet = url_base_mainnet
        self.basic_tokenid = basic_tokenid
        self.target_address = target_address
        self.my_address = my_address
        self.bot_token = bot_token
        self.chat_id = chat_id
        # 获取当前区块号
        #self.current_block = self.get_current_block()
        # 基本配置
        self.max_stored_txs = 500
        self.health_check_interval = 600
        # 存储配置
        self.processed_txs = set()
        self.buyed_txs = set()
        self.buyed_tokenid_virtualfun = set()
        # 添加自检相关的属性
        self.last_health_check = datetime.now() 
        self.time_follow_limit = follow_limit  #交易时间限制
        # 创建bot实例
        self.bot = self.create_bot()
        #用于记录上一次最新virtual交易
        self.last_virtual_transaction = None
        # 外盘跟单参数
        self.waipan_buy_rate = 0.6*10**-12
        self.waipan_sell_rate = 0.5
        self.neipan_buy_rate = 1
        self.neipan_sell_rate = 1
        self.waipan_buy_max = 1500
        self.neipan_buy_max = 1500
        self.TIME_LIMIT =30
        
        if not self.bot:
            print(f"[{self.name}] ❌ Bot创建失败，请检查:")
            print(f"1. 代理是否正常运行 (http://127.0.0.1:7890)")
            print(f"2. Bot Token是否正确: {self.bot_token}")
            print(f"3. 网络连接是否正常")
            raise Exception(f"Bot创建失败")
        # 添加初始化成功的消息
        init_message = (
            f"✅ <b>{self.name} 监控初始化成功</b>\n\n"
            f"⏰ 初始化时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f" 监控地址: <code>{self.target_address}</code>"
        )
        self.send_to_telegram(init_message)

    # 1. 数据获取相关方法 (Data Fetching)
    def get_current_block(self) -> int:
        """获取当前区块号"""
        try:
            timestamp = int(datetime.now().timestamp())
            params = {
                "module": "block",
                "action": "getblocknobytime",
                "timestamp": timestamp,
                "closest": "before",
                "apikey": self.key_basescan
            }
            response = requests.get(self.url_basescan, params=params)
            response.raise_for_status()
            data = response.json()
            if data['status'] == '1' and data['result']:
                return int(data['result'])
            else:
                print(f"[{self.name}] ⚠️ 获取区块号失败，使用默认值 0")
                return 0
        except Exception as e:
            print(f"[{self.name}] ⚠️ 获取区块号错误: {str(e)}，使用默认值 0")
            return 0


    def create_bot(self):
        """创建Telegram Bot实例"""
        try:
            print(f"[{self.name}] 开始创建Bot...")
            print(f"[{self.name}] Bot Token: {self.bot_token}")

            request = Request(
                proxy_url='http://127.0.0.1:7890',
                connect_timeout=30.0,
                read_timeout=30.0
            )
            print(f"[{self.name}] Request对象创建成功")

            bot = Bot(token=self.bot_token, request=request)
            print(f"[{self.name}] Bot对象创建成功")

            try:
                test_result = bot.get_me()
                print(f"[{self.name}] Bot测试成功: {test_result.first_name}")
            except Exception as test_error:
                print(f"[{self.name}] Bot测试失败: {str(test_error)}")
                return None

            return bot

        except Exception as e:
            print(f"[{self.name}] ❌ Bot创建失败")
            print(f"[{self.name}] 错误类型: {type(e)}")
            print(f"[{self.name}] 错误信息: {str(e)}")
            print(f"[{self.name}] 错误追踪:")
            traceback.print_exc()
            return None
    def check_health_status(self):  
        """发送健康检查消息"""
        time_since_last_check = (datetime.now() - self.last_health_check).total_seconds()
        if time_since_last_check >= self.health_check_interval:
            print(f"[{self.name}] 发送健康检查消息...")
            message = (
            f"✅ <b>[{self.name}] 监控状态正常</b>\n\n"
            f"⏰ 检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🔄 监控间隔: {self.health_check_interval}秒\n"
            f"📝 已记录交易数: {len(self.processed_txs)}"
        )
            self.send_to_telegram(message, chat_id=-4695993041)
            self.last_health_check = datetime.now()
    def send_to_telegram(self,message: str, max_retries: int = 3,chat_id=None) -> bool:
        """发送消息到Telegram"""
        for attempt in range(max_retries):
            try:
                if chat_id is None:
                    chat_id = self.chat_id
                print(chat_id)
                self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
                print(f"[{self.name}] ✅ 消息发送成功")
                return True
            except telegram.error.TimedOut:
                if attempt < max_retries - 1:
                    print(f"[{self.name}] 发送超时，5秒后重试...")
                    time.sleep(5)
                continue
            except Exception as e:
                print(f"[{self.name}] ❌ 发送消息失败")
                print(f"[{self.name}] 错误类型: {type(e)}")
                print(f"[{self.name}] 错误信息: {str(e)}")
                print(f"[{self.name}] 详细错误追踪:")
                traceback.print_exc()

                if attempt < max_retries - 1:
                    time.sleep(15)
                    try:
                        self.bot = self.create_bot()
                    except Exception as create_error:
                        print(f"[{self.name}] 重创建 Bot 失败: {str(create_error)}")
                    else:
                        return False
        return False
    def detect_virtual_transaction(self):
        import time
        start_time = time.time()  # 记录开始时间
        
        params = {
            "module": "account",
            "action": "tokentx",
            "address": self.target_address,
            #"contractaddress": self.basic_tokenid,
            "page": 1,
            "offset": 1,
            "startblock": 0,
            "endblock": 999999999,
            "sort": "desc",
            "apikey": self.key_basescan
        }
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(self.url_basescan, params=params)
                response.raise_for_status()  # 检查请求是否成功
                # 获取响应数据
                result = response.json()
                #print(result)
                #input("按回车键继续...")
                if result.get("status") == '1':
                    result = result["result"]
                    first_transaction_hash = result[0]['hash']
                    self.check_health_status()
                    if first_transaction_hash != self.last_virtual_transaction:
                        self.last_virtual_transaction = first_transaction_hash
                        elapsed_time = time.time() - start_time  # 计算用时
                        print(f"[{self.name}] 检测虚拟交易用时: {elapsed_time:.2f}秒")
                        return True
                    else:
                        return False
                else:
                    print(f"[{self.name}] 请求返回非预期状态: {result.get('status')}，重试 {attempt + 1}/{max_retries}")
            except requests.exceptions.RequestException as e:
                print(f"[{self.name}] 请求失败: {str(e)}，重试 {attempt + 1}/{max_retries}")
            
            if attempt < max_retries - 1:
                time.sleep(0.5)  # 等待5秒后重试
            else:
                print(f"[{self.name}] 请求失败，已达到最大重试次数")
                return None
            
    def process_transactions_all_transaction(self, data1, data2):
        """处理和合并交易数据"""
        if not data1 and not data2:
            return {"state": 0, "data": []}
        # 按hash分组交易
        no_follow_contract_list=['0x55fF51DA774b8ce0ed1ABAeD1CB76236bc6b2f16','0x2D90785E30A9df6ccE329c0171CB8Ba0f4a5c17b']
        transactions_by_hash = {}
        for tx in data1:
            hash_key = tx["hash"]
            if tx["hash"] in self.processed_txs:
                continue
            delta_t=time.time()-int(tx["timeStamp"])
            if delta_t/60>self.TIME_LIMIT:
                continue
            #if tx["contractAddress"] in no_follow_contract_list:
              #  continue
            if hash_key not in transactions_by_hash:
                transactions_by_hash[hash_key] = []
                
            # 只保留需要的字段
            simplified_tx = {
                "from": tx["from"],
                "to": tx["to"],
                "contractAddress": tx["contractAddress"],
                "value": float(tx["value"]) / (10 ** int(tx["tokenDecimal"])),  # 转换为实际数值
                "tokenName": tx["tokenName"],
                "tokenSymbol": tx["tokenSymbol"],
                "timeStamp": tx["timeStamp"]
            }
            transactions_by_hash[hash_key].append(simplified_tx)
        for tx in data2:
            hash_key = tx["hash"]
            if tx["hash"] in self.processed_txs:
                continue
            delta_t=time.time()-int(tx["timeStamp"])
            if delta_t/60>self.TIME_LIMIT:
                continue
            if hash_key not in transactions_by_hash:
                transactions_by_hash[hash_key] = []
            simplified_tx1 = {
                "from": tx["from"],
                "to": tx["to"],
                "contractAddress": '0x4200000000000000000000000000000000000006',
                "value": float(tx["value"]) / (10 ** int(18)),  # 转换为实际数值
                "tokenName": 'ETH',
                "tokenSymbol": 'ETH',
                "timeStamp": tx["timeStamp"]
            }
            transactions_by_hash[hash_key].append(simplified_tx1)
            
        
        #print(transactions_by_hash)
        #input("按回车键继续...")
        # 过滤掉交易数为1或大于4的hash
        #for hash_key, txs in transactions_by_hash.items():
        #    if len(txs)==1:
       # print(transactions_by_hash)
       # input()
        filtered_hashes_num1 = {
            hash_key: txs for hash_key, txs in transactions_by_hash.items()
            if len(txs) == 1
        }
        #print(filtered_hashes_num1)
        #input()
        for hash_key, txs in filtered_hashes_num1.items():
            if hash_key  in self.processed_txs:
                continue
            aa=self.get_hash_internal_transaction_basescan(hash_key)
            #print(aa)
            if aa:
                #print(transactions_by_hash[hash_key])
                dex_info=aa
                simplified_tx_dex = {
                "from": self.target_address,
                "to": '0x0000000000000000000000000000000000000006',
                "contractAddress": '0x4200000000000000000000000000000000000006',
                "value": float(dex_info["total_value"]) / (10 ** int(18)),  # 转换为实际数值
                "tokenName": 'ETH',
                "tokenSymbol": 'ETH',
                "timeStamp": dex_info["timeStamp"]
                }
                #print(simplified_tx_dex)
                transactions_by_hash[hash_key].append(simplified_tx_dex)
                #print(json.dumps(transactions_by_hash[hash_key], indent=4))
            else: 
                del transactions_by_hash[hash_key]
            #input("按回车键继续...")
        
        #print(transactions_by_hash)
       # input("按回车键继续...")
        
        
        
        
       #@ filtered_hashes = {
        #    hash_key: txs for hash_key, txs in transactions_by_hash.items()
       #     if len(txs) <= 5
       # }
                # 添加筛选逻辑：删除不符合条件的交易
        no_follow_contract_list=['0x55fF51DA774b8ce0ed1ABAeD1CB76236bc6b2f16','0x2D90785E30A9df6ccE329c0171CB8Ba0f4a5c17b','0xc44141a684f6aa4e36cd9264ab55550b03c88643']
       # no_follow_contract_list=['0x55fF51DA774b8ce0ed1ABAeD1CB76236bc6b2f16','0x2D90785E30A9df6ccE329c0171CB8Ba0f4a5c17b']
        # 将列表中的地址转换为小写
        no_follow_contract_list_lower = [addr.lower() for addr in no_follow_contract_list]
        filtered_hashes = {}
        for hash_key, txs in transactions_by_hash.items():
            bb=0
            # 跳过只有一个交易的hash
            if len(txs) == 1:
                continue
            for tx in txs:
               # print(tx["contractAddress"])
               # print(type(tx["contractAddress"]))
                if tx["contractAddress"].lower() in no_follow_contract_list_lower:
                    #print(11111)
                    bb=1
                    break
            if bb==1:
                print(f"跳过交易hash:{hash_key}")
                continue
            # 检查是否所有交易的tokenName都是ETH
            token_names = [tx.get('tokenName', '') for tx in txs]
            all_eth = all(name == 'ETH' for name in token_names)
            
            # 如果不是所有交易都是ETH，则保留
            if not all_eth:
                filtered_hashes[hash_key] = txs
            else:
                # 所有交易都是ETH，跳过这个hash
                continue
        
        print(f"筛选后的交易数量: {len(filtered_hashes)}")
        print("筛选后的交易:")
        for hash_key, txs in filtered_hashes.items():
            print(f"Hash: {hash_key}")
            for tx in txs:
                print(f"  - {tx.get('tokenName', 'Unknown')}: {tx.get('value', 0)}")
            print()
        
        #input()
        token_adress_USD_ETH_list=['0x4200000000000000000000000000000000000006','0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913','0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b','0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2']
        
        # 处理每个hash中的交易
        processed_data = []
        for hash_key, txs in filtered_hashes.items():
           # 分��发送和接收交易
           #修改了  现在无所谓什么token
           ## 检查是否至少有一个交易涉及 basic token
           # has_basic_token = any(
           #     tx["contractAddress"].lower() == self.basic_tokenid.lower() 
           #     for tx in txs
           # )
            sends = {}  # {token_symbol: {value: total_value, transactions: [tx1, tx2, ...]}}
            receives = {}
            #has_basic_token  =  any()
            #if not has_basic_token:
            #    continue  # 跳过不包含 basic token 的交易

            for tx in txs:
                if tx["from"].lower() == self.target_address.lower():
                    token_key = tx["tokenSymbol"]
                    if token_key not in sends:
                        sends[token_key] = {"value": 0, "transactions": []}
                    sends[token_key]["value"] += tx["value"]
                    sends[token_key]["transactions"].append(tx)
                elif tx["to"].lower() == self.target_address.lower():
                    token_key = tx["tokenSymbol"]
                    if token_key not in receives:
                        receives[token_key] = {"value": 0, "transactions": []}
                    receives[token_key]["value"] += tx["value"]
                    receives[token_key]["transactions"].append(tx)
            # 合并交易
            merged_txs = []
            # 处理发送交易
            for token, data in sends.items():
                max_tx = max(data["transactions"], key=lambda x: x["value"])
                merged_tx = {
                    "type": "send",
                    "from": self.target_address,
                    "to": max_tx["to"],
                    "contractAddress": max_tx["contractAddress"],
                    "value": data["value"],
                    "tokenName": max_tx["tokenName"],
                    "tokenSymbol": token,
                    "timeStamp": max_tx["timeStamp"]
                }
                merged_txs.append(merged_tx)
            
            # 处理接收交易
            for token, data in receives.items():
                max_tx = max(data["transactions"], key=lambda x: x["value"])
                merged_tx = {
                    "type": "receive",
                    "from": max_tx["from"],
                    "to": self.target_address,
                    "contractAddress": max_tx["contractAddress"],
                    "value": data["value"],
                    "tokenName": max_tx["tokenName"],
                    "tokenSymbol": token,
                    "timeStamp": max_tx["timeStamp"]
                }
                merged_txs.append(merged_tx)
            #print(merged_txs)
            #input("按回车键继续...")
            token_adress_USD_ETH_list=['0x4200000000000000000000000000000000000006','0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913','0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b','0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2']
            if merged_txs:
                                # 在合并后进行交易类型和项目类型判断
                trade_type = None
                project_id = None

                # 交易类型判断逻辑
                token_adress_USD_ETH_list = ['0x4200000000000000000000000000000000000006','0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913','0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b','0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2']
                
                # 检查发送和接收的代币地址是否在token_adress_USD_ETH_list中
                send_tokens_in_list = []
                receive_tokens_in_list = []
                
                for tx in merged_txs:
                    if tx["type"] == "send":
                        if tx["contractAddress"].lower() in [addr.lower() for addr in token_adress_USD_ETH_list]:
                            send_tokens_in_list.append(tx["contractAddress"])
                    elif tx["type"] == "receive":
                        if tx["contractAddress"].lower() in [addr.lower() for addr in token_adress_USD_ETH_list]:
                            receive_tokens_in_list.append(tx["contractAddress"])
                
                # 判断交易类型
                if not send_tokens_in_list and not receive_tokens_in_list:
                    # 发送和接收都没有属于token_adress_USD_ETH_list的代币
                    trade_type = "exchange"
                elif len(send_tokens_in_list) > 0 and len(receive_tokens_in_list) > 0:
                    # 发送和接收都有属于token_adress_USD_ETH_list的代币
                    trade_type = "internal"
                elif len(receive_tokens_in_list) > 0:
                    # 只有接收的代币属于token_adress_USD_ETH_list
                    trade_type = "sell"
                elif len(send_tokens_in_list) > 0:
                    # 只有发送的代币属于token_adress_USD_ETH_list
                    trade_type = "buy"

                processed_data.append({
                    "hash": hash_key,
                    "transactions": merged_txs,
                    "trade": trade_type
                })
        #print("processed_data",json.dumps(processed_data, indent=2, ensure_ascii=False))
        #input("按回车键继续...")
        return {
            "state": 1,
            "data": processed_data
        }
           
    def process_transactions_virtual_transaction(self, data):
        """处理和合并交易数据"""
        if not data:
            return {"state": 0, "data": []}
        # 按hash分组交易
        transactions_by_hash = {}
        for tx in data:
            hash_key = tx["hash"]
            if hash_key not in transactions_by_hash:
                transactions_by_hash[hash_key] = []
                
            # 只保留需要的字段
            simplified_tx = {
                "from": tx["from"],
                "to": tx["to"],
                "contractAddress": tx["contractAddress"],
                "value": float(tx["value"]) / (10 ** int(tx["tokenDecimal"])),  # 转换为实际数值
                "tokenName": tx["tokenName"],
                "tokenSymbol": tx["tokenSymbol"],
                "timeStamp": tx["timeStamp"]
            }
            transactions_by_hash[hash_key].append(simplified_tx)
        # 过滤掉交易数为1或大于4的hash
        filtered_hashes = {
            hash_key: txs for hash_key, txs in transactions_by_hash.items()
            if 1 < len(txs) <= 13
        }
        # 处理每个hash中的交易
        processed_data = []
        for hash_key, txs in filtered_hashes.items():
            # 分��发送和接收交易

           # 检查是否至少有一个交易涉及 basic token
            has_basic_token = any(
                tx["contractAddress"].lower() == self.basic_tokenid.lower() 
                for tx in txs
            )
            sends = {}  # {token_symbol: {value: total_value, transactions: [tx1, tx2, ...]}}
            receives = {}
            if not has_basic_token:
                continue  # 跳过不包含 basic token 的交易

            for tx in txs:
                if tx["from"].lower() == self.target_address.lower():
                    token_key = tx["tokenSymbol"]
                    if token_key not in sends:
                        sends[token_key] = {"value": 0, "transactions": []}
                    sends[token_key]["value"] += tx["value"]
                    sends[token_key]["transactions"].append(tx)
                elif tx["to"].lower() == self.target_address.lower():
                    token_key = tx["tokenSymbol"]
                    if token_key not in receives:
                        receives[token_key] = {"value": 0, "transactions": []}
                    receives[token_key]["value"] += tx["value"]
                    receives[token_key]["transactions"].append(tx)
            # 合并交易
            merged_txs = []
            # 处理发送交易
            for token, data in sends.items():
                max_tx = max(data["transactions"], key=lambda x: x["value"])
                merged_tx = {
                    "type": "send",
                    "from": self.target_address,
                    "to": max_tx["to"],
                    "contractAddress": max_tx["contractAddress"],
                    "value": data["value"],
                    "tokenName": max_tx["tokenName"],
                    "tokenSymbol": token,
                    "timeStamp": max_tx["timeStamp"]
                }
                merged_txs.append(merged_tx)
            
            # 处理接收交易
            for token, data in receives.items():
                max_tx = max(data["transactions"], key=lambda x: x["value"])
                merged_tx = {
                    "type": "receive",
                    "from": max_tx["from"],
                    "to": self.target_address,
                    "contractAddress": max_tx["contractAddress"],
                    "value": data["value"],
                    "tokenName": max_tx["tokenName"],
                    "tokenSymbol": token,
                    "timeStamp": max_tx["timeStamp"]
                }
                merged_txs.append(merged_tx)

            if merged_txs:
                # 在合并后进行交易类型和项目类型判断
                trade_type = None
                project_id = None
                
                # 找出非 basic token 的交易
                other_token_tx = next(
                    (tx for tx in merged_txs 
                     if tx["contractAddress"].lower() != self.basic_tokenid.lower()),
                    None
                )
                
                if other_token_tx:
                    # 检查是否有发送 basic token 的交易
                    sent_basic = any(
                        tx["type"] == "send" and 
                        tx["contractAddress"].lower() == self.basic_tokenid.lower()
                        for tx in merged_txs
                    )
                    trade_type = "buy" if sent_basic else "sell"
                    # 判断项目类型
                    if other_token_tx["tokenName"].lower().startswith("fun"):
                        project_id = "virtual_fun"
                    else:
                        project_id = "virtual"

                processed_data.append({
                    "hash": hash_key,
                    "transactions": merged_txs,
                    "project_id": project_id,
                    "trade": trade_type
                })
        #print("processed_data",json.dumps(processed_data, indent=2, ensure_ascii=False))
        #input("按回车键继续...")
        return {
            "state": 1,
            "data": processed_data
        }
    def get_hash_internal_transaction_basescan(self,tx_hash):      
        params1 = {
            "module": "account",
            "action": "txlistinternal",
            "txhash": tx_hash,
            "apikey": self.key_basescan
        }
        #&module=account
   #&action=txlistinternal
   #&txhash=0x40eb908387324f2b575b4879cd9d7188f69c8fc9d87c901b9e2daaea4b442170
  # &apikey=YourApiKeyToken
        # 发送请求
        response1 = requests.get(self.url_basescan, params=params1)
        # 获取响应数据
        result1 = response1.json()
        
        result1 =result1["result"]
        dex_address_list=['0x1111111254EEB25477B68fb85Ed929f73A960582','0x6131B5fae19EA4f9D964eAc0408E4408b66337b5','0x111111125421cA6dc452d289314280a0f8842A65','0x1111111254EEB25477B68fb85Ed929f73A960582','0x0000000000001fF3684f28c67538d4D072C22734','0x5e2F47bD7D4B357fCfd0Bb224Eb665773B1B9801','0x6131B5fae19EA4f9D964eAc0408E4408b66337b5','0x6fF5693b99212Da76ad316178A184AB56D299b43']
        print(1)
        #print(result1)
        
        # 处理内部交易数据，查找DEX地址并计算总价值
        if result1:
            # 将DEX地址列表转换为小写以便比较
            dex_addresses_lower = [addr.lower() for addr in dex_address_list]
            
            # 查找DEX地址
            found_dex_address = None
            total_value = 0
            
            for tx in result1:
                # 检查from地址是否在DEX地址列表中
                if tx.get('from', '').lower() in dex_addresses_lower:
                    found_dex_address = tx['from']
                    # 计算该DEX地址发送的所有value总和
                    for inner_tx in result1:
                        print(inner_tx)
                        if inner_tx.get('from', '').lower() == found_dex_address.lower():
                            # 将value从字符串转换为整数并累加
                            try:
                                value = int(inner_tx.get('value', '0'))
                                total_value += value
                            except ValueError:
                                # 如果value不是有效数字，跳过
                                continue
            
            # 如果找到了DEX地址，返回处理结果
            if found_dex_address:
                # 获取时间戳（假设所有交易都有相同的时间戳）
                timestamp = result1[0].get('timeStamp', '') if result1 else ''
                
                processed_result = {
                    'timeStamp': timestamp,
                    'dex_address': found_dex_address,
                    'total_value': total_value,
                    'total_value_eth': total_value   # 转换为ETH单位
                }
                
                print(f"找到DEX地址: {found_dex_address}")
                print(f"时间戳: {timestamp}")
                print(f"总价值: {total_value} Wei")
                print(f"总价值 (ETH): {total_value / 10**18:.6f} ETH")
                print(processed_result)
                #input()
                return processed_result
            else:
                print("未找到DEX地址")
                return {}
        else:
            print("该交易没有内部交易")
            return {}

    def get_address_virtual_transaction_basescan(self):
        params = {
            "module": "account",
            "action": "tokentx",
            "address": self.target_address,
            "page": 1,
            "offset": 20,
            "startblock": 0,
            "endblock": 999999999,
            "sort": "desc",
            "apikey": self.key_basescan
        }
        # 发送请求
        response = requests.get(self.url_basescan, params=params)
        # 获取响应数据
        result = response.json()
        result =result["result"]
        
        params1 = {
            "module": "account",
            "action": "txlistinternal",
            "address": self.target_address,
            "page": 1,
            "offset": 7,
            "startblock": 0,
            "endblock": 999999999,
            "sort": "desc",
            "apikey": self.key_basescan
        }
        # 发送请求
        response1 = requests.get(self.url_basescan, params=params1)
        # 获取响应数据
        result1 = response1.json()
        result1 =result1["result"]
        #print(result1)
        #print(result)
        #input("按回车键继续...")
        
        # 添加5次重试机制
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                result_processed = self.process_transactions_all_transaction(result, result1)
                break  # 成功则跳出循环
            except Exception as e:
                print(f"处理交易数据失败 (第{attempt}/{max_retries}次): {e}")
                if attempt < max_retries:
                    print("等待3秒后重试...")
                    time.sleep(3)
                else:
                    print("重试次数已用完，返回空结果")
                    result_processed = {"state": 0, "data": []}
        
        # 使用json.dumps美化输出，设置indent=2使输出格式更易读
        #print(result_processed)
        #input("按回车键继续...")
        return result_processed
    def get_address_internel_transaction_basescan(self):
        params = {
            "module": "account",
            "action": "txlistinternal",
            "address": self.target_address,
            "page": 1,
            "offset": 20,
            "startblock": 0,
            "endblock": 999999999,
            "sort": "desc",
            "apikey": self.key_basescan
        }
        # 发送请求
        response = requests.get(self.url_basescan, params=params)
        # 获取响应数据
        result = response.json()
        result =result["result"]
        print(1)
        print(result)
        input("按回车键继续...")
        result_processed=self.process_transactions_virtual_transaction(result)
        # 使用json.dumps美化输出，设置indent=2使输出格式更易读
        return result_processed
    
    def send_transaction_notification_basescan(self: dict,data: dict) -> bool:
        """格式化并发送交易通知"""
        if data["state"]==1:
            data=data["data"]
        else:
            return 0
        for tx in data:
            # 交易基本信息
            tx_hash = tx["hash"]
            trade_type = tx["trade"]
            print("=="*50)
            print("\n=== 交易基本信息 ===")
            print(f"tx_hash: {tx_hash} ({type(tx_hash)})")
            print(f"trade_type: {trade_type} ({type(trade_type)})")
            
            # 发送交易信息 (第一笔交易)
            send_tx = tx["transactions"][0]
            send_type = send_tx["type"]
            send_from = send_tx["from"]
            send_to = send_tx["to"]
            send_contract = send_tx["contractAddress"]
            send_value = send_tx["value"]
            send_token_name = send_tx["tokenName"]
            send_token_symbol = send_tx["tokenSymbol"]
            send_timestamp = send_tx["timeStamp"]
            # 接收交易信息 (第二笔交易)
            receive_tx = tx["transactions"][1]
            receive_type = receive_tx["type"]
            receive_from = receive_tx["from"]
            receive_to = receive_tx["to"]
            receive_contract = receive_tx["contractAddress"]
            receive_value = receive_tx["value"]
            receive_token_name = receive_tx["tokenName"]
            receive_token_symbol = receive_tx["tokenSymbol"]
            receive_timestamp = receive_tx["timeStamp"]
            time_now = int(datetime.now().timestamp())
            print_or_not=True
            if send_type==receive_type:
                continue
            if print_or_not:    
                print("\n=== 发送交易信息 ===")
                #print(f"send_type: {send_type} ({type(send_type)})")
               # print(f"send_from: {send_from} ({type(send_from)})")
                #print(f"send_to: {send_to} ({type(send_to)})")
                #print(f"send_contract: {send_contract} ({type(send_contract)})")
                print(f"send_value: {send_value} ({type(send_value)})")
                print(f"send_token_name: {send_token_name} ({type(send_token_name)})")
                print(f"send_token_symbol: {send_token_symbol} ({type(send_token_symbol)})")
                #print(f"send_timestamp: {send_timestamp} ({type(send_timestamp)})")
                print("\n=== 接收交易信息 ===")
                #print(f"receive_type: {receive_type} ({type(receive_type)})")
                #print(f"receive_from: {receive_from} ({type(receive_from)})")
                #print(f"receive_to: {receive_to} ({type(receive_to)})")
                #print(f"receive_contract: {receive_contract} ({type(receive_contract)})")
                print(f"receive_value: {receive_value} ({type(receive_value)})")
                print(f"receive_token_name: {receive_token_name} ({type(receive_token_name)})")
                print(f"receive_token_symbol: {receive_token_symbol} ({type(receive_token_symbol)})")
                #print(f"receive_timestamp: {receive_timestamp} ({type(receive_timestamp)})")
                #print(f"time_now: {time_now} ({type(time_now)})")
                print("\n" + "="*50 + "\n")
            #input("按回车键继续...")
            # 筛选逻辑
            USDC_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
            if tx_hash not in self.buyed_txs:
                self.buyed_txs.add(tx_hash)
                print(f"检测到[{self.name}] 交易")
                if time_now - int(receive_timestamp) < 60 * self.time_follow_limit:
                    print(f"[{self.name}] 交易时间小于{self.time_follow_limit}分钟，启动跟单")
                    if trade_type == "buy":
                        aa=1
                        
                       
                        price_eth=get_virtual_futures_price("ETHUSDT")
                        price_virtual=get_virtual_futures_price("VIRTUALUSDT")
                        if send_token_symbol=="ETH":
                            price1=price_eth
                        elif send_token_symbol=="VIRTUAL":
                            price1=price_virtual
                        else:
                            price1=1
                        waipan_buy_rate=self.waipan_buy_rate
                        usd_value=send_value*price1
                        if usd_value>self.waipan_buy_max:
                            send_value_real=self.waipan_buy_max
                        else:
                            send_value_real=usd_value
                        #pool_token_price_by_usd, pool_token_price_by_virtual, virtual_price , price_change_percent,mark_cap=get_price_directly(receive_contract)
                        print("price1",price1)
                        print('usd_value',send_value_real)
                        #print(pool_token_price_by_usd)
                        waipan_buy_rate=self.waipan_buy_rate
                
                        if aa==1:
                            word='nickfollowbot'
                        eth_spent, token_received_SP, amount_buy_real, time_used, price_SP, tx_hash_buy,virtual_token_left = kyberswap_swap(
                            USDC_address, 
                            receive_contract, 
                            send_value_real*waipan_buy_rate, 
                            word,
                            1000                       
                        )
                        if print_or_not is None and eth_spent is  None:
                            eth_spent, token_received_SP, amount_buy_real, time_used, price_SP, tx_hash_buy,virtual_token_left = kyberswap_swap(
                            USDC_address, 
                            receive_contract, 
                            send_value_real*waipan_buy_rate, 
                            word,
                            1300                       
                            )
                        time_used_all = time.time() - int(receive_timestamp)
                        price_KOL_buy = float(f'{send_value / receive_value:.3g}') if receive_value != 0 else 0.0
                        print("price_KOL_buy", price_KOL_buy)
                        print("send_value", send_value)
                        print("receive_value", receive_value)
                        print("virtual_token_left", virtual_token_left)
                        if print_or_not and eth_spent is not None:
                            print("\n=== 购买结果信息 ===")
                            print(f"eth_spent: {eth_spent} ({type(eth_spent)})")
                            print(f"token_received_SP: {token_received_SP} ({type(token_received_SP)})")
                            # print(f"time_used: {time_used} ({type(time_used)})")
                            #print(f"price_SP: {price_SP} ({type(price_SP)})")
                            # print(f"tx_hash_buy: {tx_hash_buy} ({type(tx_hash_buy)})")
                            print(f"amount_buy_real: {amount_buy_real} ({type(amount_buy_real)})")
                            print(f"virtual_token_left: {virtual_token_left} ({type(virtual_token_left)})")
                            print("\n" + "=" * 50 + "\n")
                        if eth_spent is not None:
                            price_follow_diff_percent = float(f'{((price_SP - price_KOL_buy) / price_KOL_buy * 100):.3g}') if price_KOL_buy != 0 else 0.0
                            message_buy = (
                                f"🚨 <b>[{self.name}] 跟单(BUY): 用时 {time_used_all:.1f} 秒买入 {amount_buy_real:.1f} USDC 的外盘代币 {receive_token_symbol}</b>\n"
                                f"⏱️ 链上用时: {time_used:.1f} 秒 ⏱️\n"
                                f"🟥 发送: {amount_buy_real*10**12:.2f} USDC\n"  # 红色快 发送
                                f"🟩 接受: {token_received_SP:.1f} {receive_token_symbol} ({receive_token_name})\n"
                            #    f"💰 跟单买入价格: {1/price_SP/10**12}  USD \n"
                                f"    跟单系数: {waipan_buy_rate*10**12:.2f}\n"
                                f"💰 剩余 USDC: {virtual_token_left*10**12:.1f} \n"
                                f"🔍 代币详情: <a href='https://dexscreener.com/base/{receive_contract}'>查看dexscreener</a>\n"
                                f"🔗 跟单地址: <a href='https://debank.com/profile/{self.my_address}'>查看debank详情</a>\n"
                                f"{'-' * 60}\n"  # 下方分界线
                               # f"⚠️ <b>[{self.name}] 买入 {send_value:.1f} USD {receive_token_symbol}</b>\n\n"
                                f"🕒 {self.name} 交易时间: {datetime.fromtimestamp(int(send_timestamp)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"🔍 查看debank: <a href='https://debank.com/profile/{self.target_address}'>查看debank</a>\n"
                                f" Mega_trade_bot V3 Powered by MEGAWAVE investment Lab 2025/08\n"
                            )
                            self.send_to_telegram(message_buy)
                            print(f"[{self.name}] 外盘跟单买入交易发送成功")
                        else:
                            if print_or_not:
                                #print(f"self.name: {self.name} (type: {type(self.name)})")
                                print(f"send_value: {send_value:.1f} (type: {type(send_value)})")
                                #print(f"receive_token_symbol: {receive_token_symbol} (type: {type(receive_token_symbol)})")
                                print(f"send_token_symbol: {send_token_symbol} (type: {type(send_token_symbol)})")
                                #print(f"send_token_name: {send_token_name} (type: {type(send_token_name)})")
                                print(f"receive_value: {receive_value:.1f} (type: {type(receive_value)})")
                                print(f"receive_token_name: {receive_token_name} (type: {type(receive_token_name)})")
                                #print(f"tx_hash: {tx_hash} (type: {type(tx_hash)})")
                                #print(f"send_timestamp: {send_timestamp} (type: {type(send_timestamp)})")
                                #print(f"self.target_address: {self.target_address} (type: {type(self.target_address)})")
                                #input("按回车键继续...")
                            message_buy_error = (
                                f"🚨 <b>[{self.name}]  跟单(BUY)买入失败: {send_token_symbol} 余额为 0</b>\n\n"
                                f"🚨 <b>[{self.name}] 买入 {send_value*price1:.1f} USDC的外盘代币 {receive_token_symbol}</b>\n\n"
                                f"🟥 {self.name} 发送: {send_value:.2f} {send_token_symbol} ({send_token_name})\n"  # 红色快 发送
                                f"🟩 {self.name} 接受: {receive_value:.1f} {receive_token_symbol} ({receive_token_name})\n"
                                f"🔍 {self.name} 交易时间: {datetime.fromtimestamp(int(send_timestamp)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"🔍 代币详情: <a href='https://dexscreener.com/base/{receive_contract}'>查看dexscreener</a>\n"
                                f"🕒 查看交易链接: <a href='https://basescan.org/tx/{tx_hash}'>查看交易详情</a>\n"
                                f"🔍 查看 Debank: <a href='https://debank.com/profile/{self.target_address}'>查看 Debank</a>\n"
                                f" Mega_trade_bot V3 Powered by MEGAWAVE investment Lab 2025/08\n"
                            )
                            self.send_to_telegram(message_buy_error)
                            print(f"[{self.name}] 跟单买入交易失败")    
                    elif trade_type == "sell":
                        eth_spent, received_VIRTUAL, amount_sell_real, time_used, price_SP, tx_hash_sell,virtual_token_left = kyberswap_swap(
                            send_contract, 
                            USDC_address, 
                            send_value*self.waipan_sell_rate, 
                            'nickfollowbot',
                            1000
                        )
                        if print_or_not is None and eth_spent is  None:
                            eth_spent, received_VIRTUAL, amount_sell_real, time_used, price_SP, tx_hash_sell,virtual_token_left = kyberswap_swap(
                            send_contract, 
                            USDC_address, 
                            send_value*self.waipan_sell_rate, 
                            'nickfollowbot',
                            1300
                        )
                        price_KOL_sell = float(f'{receive_value / send_value:.3g}') if send_value != 0 else 0.0
                        if print_or_not and eth_spent is not None:
                            print("\n=== 卖出结果信息 ===")
                            print(f"eth_spent: {eth_spent} ({type(eth_spent)})")
                            print(f"received_USD: {received_VIRTUAL} ({type(received_VIRTUAL)})")
                            print(f"time_used: {time_used} ({type(time_used)})")
                            print(f"price_SP: {price_SP} ({type(price_SP)})")
                            print(f"tx_hash_sell: {tx_hash_sell} ({type(tx_hash_sell)})")
                            print(f"amount_sell_real: {amount_sell_real} ({type(amount_sell_real)})")
                            print(f"virtual_token_left: {virtual_token_left} ({type(virtual_token_left)})")
                            print("\n" + "=" * 50 + "\n")
                        if eth_spent is not None:
                            price_follow_diff_percent = (price_SP - price_KOL_sell) / price_KOL_sell * 100
                            time_used_all = time.time() - int(receive_timestamp)
                            message_sell = (
                                f"🚨 <b>[{self.name}] 卖单(SELL):用时 {time_used_all:.1f} 秒卖出 {amount_sell_real:.1f} 的外盘代币 {send_token_symbol}</b>\n"
                                f"⏱️ 链上用时: {time_used:.1f} 秒 ⏱️\n"
                                f"🟥 发送: {amount_sell_real:.2f} {send_token_symbol} ({send_token_name})\n"
                                f"🟩 接受: {received_VIRTUAL*10**12:.1f} USDC\n"
                            #    f"💰 跟单价格: {price_SP*10**12} USD %\n"
                                f"💰 剩余USDC: {virtual_token_left*10**12:.1f} \n"
                                f"🔍 代币详情: <a href='https://dexscreener.com/base/{send_contract}'>查看dexscreener</a>\n"
                                f"🔗 跟单地址: <a href='https://debank.com/profile/{self.my_address}'>查看debank详情</a>\n"
                                f"{'-' * 60}\n"  # 下方分界线
                               # f"⚠️ <b>[{self.name}] 外盘卖出 {receive_value:.1f} USD 等值 {receive_token_symbol}</b>\n\n"
                                f"🕒 {self.name} 交易时间: {datetime.fromtimestamp(int(receive_timestamp)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"🔍 查看debank: <a href='https://debank.com/profile/{self.target_address}'>查看debank</a>\n"
                                f" Mega_trade_bot V3 Powered by MEGAWAVE investment Lab 2025/08\n"
                            )
                            self.send_to_telegram(message_sell)
                            print(f"[{self.name}] 跟单卖出交易发送成功")
                        else:
                            print("self.name", self.name, type(self.name))
                            print("send_token_symbol", send_token_symbol, type(send_token_symbol))
                            if print_or_not and eth_spent is not None:
                                print(f"self.name: {self.name} ({type(self.name)})")
                                print(f"send_token_symbol: {send_token_symbol} ({type(send_token_symbol)})")
                                print(f"receive_value: {receive_value} ({type(receive_value)})")
                                print(f"receive_token_symbol: {receive_token_symbol} ({type(receive_token_symbol)})")
                                print(f"amount_sell_real: {amount_sell_real} ({type(amount_sell_real)})")
                                print(f"send_token_name: {send_token_name} ({type(send_token_name)})")
                                print(f"vfun_received_VIRTUAL: {vfun_received_VIRTUAL} ({type(vfun_received_VIRTUAL)})")
                                print(f"receive_token_name: {receive_token_name} ({type(receive_token_name)})")
                                print(f"tx_hash: {tx_hash} ({type(tx_hash)})")
                                print(f"receive_timestamp: {receive_timestamp} ({type(receive_timestamp)})")
                                print(f"self.target_address: {self.target_address} ({type(self.target_address)})")

                            message_sell_error = (
                                f"🚨 <b>[{self.name}] 卖单(SELL)卖出失败: {send_token_symbol} 余额为 0</b>\n\n"
                                f"🚨 <b>[{self.name}] 卖出 {receive_value:.1f} USD 等值 {receive_token_symbol}</b>\n\n"
                                f"🚨 {self.name} 发送: {send_value:.2f} {send_token_symbol} ({send_token_name})\n"
                                f"🟩 {self.name} 接受: {receive_value:.1f} {receive_token_symbol} ({receive_token_name})\n"
                                f"🔍 {self.name} 交易时间: {datetime.fromtimestamp(int(receive_timestamp)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"🔍 代币详情: <a href='https://dexscreener.com/base/{send_contract}'>查看dexscreener</a>\n"
                                f"🔍 查看debank: <a href='https://debank.com/profile/{self.target_address}'>查看debank</a>\n"
                                f" Mega_trade_bot V3 Powered by MEGAWAVE investment Lab 2025/08\n"
                            )
                            self.send_to_telegram(message_sell_error)
                            
                            print(f"[{self.name}] 跟单卖出交易失败")
                    elif trade_type == "exchange":  
                            aa=1
                            debank_api = DebankTokenAPI(ACCESS_KEY)
                            price_send_token=debank_api.get_token_price("base",send_contract)
                            price_receive_token=debank_api.get_token_price("base",receive_contract)
                            print(price_send_token)
                            print(price_receive_token)
                            #input("按回车键继续...")
                            if price_send_token>0:
                                usd_value=send_value*price_send_token
                            elif price_receive_token>0:
                                usd_value=receive_value*price_receive_token
                            else:
                                usd_value=300
                            print(usd_value)
                            if usd_value>self.waipan_buy_max:
                                usd_value=self.waipan_buy_max
                            #input("按回车键继续...")
                            send_value_real=send_value
                            #price_eth=get_virtual_futures_price("ETHUSDT")
                            #price_virtual=get_virtual_futures_price("VIRTUALUSDT")

                            price1=1
                            #pool_token_price_by_usd, pool_token_price_by_virtual, virtual_price , price_change_percent,mark_cap=get_price_directly(receive_contract)
                            
                            #print(pool_token_price_by_usd)
                            waipan_buy_rate=self.waipan_buy_rate
                            #input("按回车键继续...")
                            if aa==1:
                                word='nickfollowbot'
                            print(receive_contract)
                            print(send_value_real)
                            print(word)
                            print(waipan_buy_rate)
                            eth_spent, token_received_SP, amount_buy_real, time_used, price_SP, tx_hash_buy,virtual_token_left = kyberswap_swap(
                                USDC_address, 
                                receive_contract, 
                                usd_value*waipan_buy_rate*price1, 
                                word,
                                1000                       
                            )
                            if print_or_not is None and eth_spent is  None:
                                eth_spent, token_received_SP, amount_buy_real, time_used, price_SP, tx_hash_buy,virtual_token_left = kyberswap_swap(
                                USDC_address, 
                                receive_contract, 
                                usd_value*waipan_buy_rate*price1, 
                                word,
                                1300                       
                            )
                            time_used_all = time.time() - int(receive_timestamp)
                            price_KOL_buy = float(f'{send_value / receive_value:.3g}') if receive_value != 0 else 0.0
                            print("price_KOL_buy", price_KOL_buy)
                            print("send_value", send_value)
                            print("receive_value", receive_value)
                            print("virtual_token_left", virtual_token_left)
                            if print_or_not and eth_spent is not None:
                                print("\n=== 购买结果信息 ===")
                                print(f"eth_spent: {eth_spent} ({type(eth_spent)})")
                                print(f"token_received_SP: {token_received_SP} ({type(token_received_SP)})")
                                # print(f"time_used: {time_used} ({type(time_used)})")
                                #print(f"price_SP: {price_SP} ({type(price_SP)})")
                                # print(f"tx_hash_buy: {tx_hash_buy} ({type(tx_hash_buy)})")
                                print(f"amount_buy_real: {amount_buy_real} ({type(amount_buy_real)})")
                                print(f"virtual_token_left: {virtual_token_left} ({type(virtual_token_left)})")
                                print("\n" + "=" * 50 + "\n")
                            if eth_spent is not None:
                                price_follow_diff_percent = float(f'{((price_SP - price_KOL_buy) / price_KOL_buy * 100):.3g}') if price_KOL_buy != 0 else 0.0
                                message_buy = (
                                    f"🚨 <b>[{self.name}] 跟单(BUY/EXCHANGE): 用时 {time_used_all:.1f} 秒买入 {amount_buy_real:.1f} USDC 的外盘代币 {receive_token_symbol}</b>\n"
                                    f"⏱️ 链上用时: {time_used:.1f} 秒 ⏱️\n"
                                    f"🟥 发送: {amount_buy_real*10**12:.2f} USDC\n"  # 红色快 发送
                                    f"🟩 接受: {token_received_SP:.1f} {receive_token_symbol} ({receive_token_name})\n"
                                  #  f"💰 跟单买入价格: {price_SP*10**12}  USD %\n"
                                    f"    跟单系数: {waipan_buy_rate*10**12:.2f}\n"
                                    f"💰 剩余 USDC: {virtual_token_left*10**12:.1f} \n"
                                    f"🔍 代币详情: <a href='https://dexscreener.com/base/{send_contract}'>查看dexscreener</a>\n"
                                    f"🔗 跟单地址: <a href='https://debank.com/profile/{self.my_address}'>查看debank详情</a>\n"
                                    f"{'-' * 60}\n"  # 下方分界线
                                  #  f"⚠️ <b>[{self.name}] 买入 {receive_value:.1f}  {receive_token_symbol}</b>\n\n"
                                    f"🕒 {self.name} 交易时间: {datetime.fromtimestamp(int(send_timestamp)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                    f"🔍 查看debank: <a href='https://debank.com/profile/{self.target_address}'>查看debank</a>\n"
                                    f" Mega_trade_bot V3 Powered by MEGAWAVE investment Lab 2025/08\n"
                                )
                                self.send_to_telegram(message_buy)
                                print(f"[{self.name}] 外盘跟单买入交易发送成功")
                            else:
                                if print_or_not:
                                    #print(f"self.name: {self.name} (type: {type(self.name)})")
                                    print(f"send_value: {send_value:.1f} (type: {type(send_value)})")
                                    #print(f"receive_token_symbol: {receive_token_symbol} (type: {type(receive_token_symbol)})")
                                    print(f"send_token_symbol: {send_token_symbol} (type: {type(send_token_symbol)})")
                                    #print(f"send_token_name: {send_token_name} (type: {type(send_token_name)})")
                                    print(f"receive_value: {receive_value:.1f} (type: {type(receive_value)})")
                                    print(f"receive_token_name: {receive_token_name} (type: {type(receive_token_name)})")
                                    #print(f"tx_hash: {tx_hash} (type: {type(tx_hash)})")
                                    #print(f"send_timestamp: {send_timestamp} (type: {type(send_timestamp)})")
                                    #print(f"self.target_address: {self.target_address} (type: {type(self.target_address)})")
                                    #input("按回车键继续...")
                                message_buy_error = (
                                    f"🚨 <b>[{self.name}] 跟单(BUY/EXCHANGE)买入失败: USDC 余额为 0</b>\n\n"
                                    f"🚨 <b>[{self.name}] 买入 {send_value:.1f} USDC的外盘代币 {receive_token_symbol}</b>\n\n"
                                    f"🟥 {self.name} 发送: {send_value:.2f} {send_token_symbol} ({send_token_name})\n"  # 红色快 发送
                                    f"🟩 {self.name} 接受: {receive_value:.1f} USDC \n"
                                    f"🔍 {self.name} 交易时间: {datetime.fromtimestamp(int(send_timestamp)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                    f"🔍 代币详情: <a href='https://dexscreener.com/base/{send_contract}'>查看dexscreener</a>\n"
                                    f"🔍 查看 Debank: <a href='https://debank.com/profile/{self.target_address}'>查看 Debank</a>\n"
                                    f" Mega_trade_bot V3 Powered by MEGAWAVE investment Lab 2025/08\n"
                                )
                                self.send_to_telegram(message_buy_error)
                                print(f"[{self.name}] 跟单买入交易失败") 
                                
                                
                                
                            #卖出代币  
                            eth_spent, received_VIRTUAL, amount_sell_real, time_used, price_SP, tx_hash_sell,virtual_token_left = kyberswap_swap(
                                send_contract, 
                                USDC_address, 
                                send_value*self.waipan_sell_rate, 
                                'nickfollowbot',
                                1000
                            )
                            if print_or_not is None and eth_spent is  None:
                                eth_spent, received_VIRTUAL, amount_sell_real, time_used, price_SP, tx_hash_sell,virtual_token_left = kyberswap_swap(
                                send_contract, 
                                USDC_address, 
                                send_value*self.waipan_sell_rate, 
                                'nickfollowbot',
                                1300
                            )
                            price_KOL_sell = float(f'{receive_value / send_value:.3g}') if send_value != 0 else 0.0
                            if print_or_not and eth_spent is not None:
                                print("\n=== 卖出结果信息 ===")
                                print(f"eth_spent: {eth_spent} ({type(eth_spent)})")
                                print(f"received_USD: {received_VIRTUAL} ({type(received_VIRTUAL)})")
                                print(f"time_used: {time_used} ({type(time_used)})")
                                print(f"price_SP: {price_SP} ({type(price_SP)})")
                                print(f"tx_hash_sell: {tx_hash_sell} ({type(tx_hash_sell)})")
                                print(f"amount_sell_real: {amount_sell_real} ({type(amount_sell_real)})")
                                print(f"virtual_token_left: {virtual_token_left} ({type(virtual_token_left)})")
                                print("\n" + "=" * 50 + "\n")
                            if eth_spent is not None:
                                price_follow_diff_percent = (price_SP - price_KOL_sell) / price_KOL_sell * 100
                                time_used_all = time.time() - int(receive_timestamp)
                                message_sell = (
                                    f"🚨 <b>[{self.name}] 跟单(SELL/EXCHANGE):用时 {time_used_all:.1f} 秒卖出 {amount_sell_real:.1f} 的外盘代币 {send_token_symbol}</b>\n"
                                    f"⏱️ 链上用时: {time_used:.1f} 秒 ⏱️\n"
                                    f"🟥 发送: {amount_sell_real:.2f} {send_token_symbol} ({send_token_name})\n"
                                    f"🟩 接受: {received_VIRTUAL*10**12:.1f} USDC)\n"
                                    #f"💰 跟单价格: {price_SP*10**12} USD %\n"
                                    f"💰 剩余USDC: {virtual_token_left*10**12:.1f} \n"
                                    f"🔍 代币详情: <a href='https://dexscreener.com/base/{send_contract}'>查看dexscreener</a>\n"
                                    f"🔗 跟单地址: <a href='https://debank.com/profile/{self.my_address}'>查看debank详情</a>\n"
                                    f"{'-' * 60}\n"  # 下方分界线
                                   # f"⚠️ <b>[{self.name}] 外盘卖出 {send_value:.1f} {send_token_symbol}</b>\n\n"
                                    f"🕒 {self.name} 交易时间: {datetime.fromtimestamp(int(receive_timestamp)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                    f"🔍 查看debank: <a href='https://debank.com/profile/{self.target_address}'>查看debank</a>\n"
                                    f" Mega_trade_bot V3 Powered by MEGAWAVE investment Lab 2025/08\n"
                                )
                                self.send_to_telegram(message_sell)
                                print(f"[{self.name}] 跟单卖出交易发送成功")
                            else:
                                print("self.name", self.name, type(self.name))
                                print("send_token_symbol", send_token_symbol, type(send_token_symbol))
                                if print_or_not and eth_spent is not None:
                                    print(f"self.name: {self.name} ({type(self.name)})")
                                    print(f"send_token_symbol: {send_token_symbol} ({type(send_token_symbol)})")
                                    print(f"receive_value: {receive_value} ({type(receive_value)})")
                                    print(f"receive_token_symbol: {receive_token_symbol} ({type(receive_token_symbol)})")
                                    print(f"amount_sell_real: {amount_sell_real} ({type(amount_sell_real)})")
                                    print(f"send_token_name: {send_token_name} ({type(send_token_name)})")
                                    print(f"vfun_received_VIRTUAL: {vfun_received_VIRTUAL} ({type(vfun_received_VIRTUAL)})")
                                    print(f"receive_token_name: {receive_token_name} ({type(receive_token_name)})")
                                    print(f"tx_hash: {tx_hash} ({type(tx_hash)})")
                                    print(f"receive_timestamp: {receive_timestamp} ({type(receive_timestamp)})")
                                    print(f"self.target_address: {self.target_address} ({type(self.target_address)})")

                                message_sell_error = (
                                    f"🚨 <b>[{self.name}] 跟单(SELL/EXCHANGE)卖出失败: {send_token_symbol} 余额为0 </b>\n\n"
                                    f"🚨 <b>[{self.name}] 卖出 {receive_value:.1f} VIRTUAL 等值 {receive_token_symbol}</b>\n\n"
                                    f"🚨 {self.name} 发送: {send_value:.2f} {send_token_symbol} ({send_token_name})\n"
                                    f"🟩 {self.name} 接受: {receive_value:.1f} {receive_token_symbol} ({receive_token_name})\n"
                                    f"🔍 {self.name} 交易时间: {datetime.fromtimestamp(int(receive_timestamp)).strftime('%Y-%m-%d %H:%M:%S')}\n"
                                    f"🔍 代币详情: <a href='https://dexscreener.com/base/{send_contract}'>查看dexscreener</a>\n"
                                    f"🔍 查看debank: <a href='https://debank.com/profile/{self.target_address}'>查看debank</a>\n"
                                    f" Mega_trade_bot V3 Powered by MEGAWAVE investment Lab 2025/08\n"
                                )
                                self.send_to_telegram(message_sell_error)
                                print(f"[{self.name}] 跟单卖出交易失败")
                else:
                    print(f"[{self.name}] 交易时间大于{self.time_follow_limit}分钟，不启动跟单")
                    continue
    # 4. 主要处理流程 (Main Process)
    def run(self):
        """运行监控器"""
        if self.detect_virtual_transaction()==True:
            sleep(3)
            #aa=self.get_hash_internal_transaction_basescan("0xb1d8bac9a780cdb294f742c57b3037707ce697e0986ae5d58266dc2e10956ee0")
            #print(11)
            #print(aa)
            #input("按回车键继续...")
            print(f"[{self.name}] 检测到VIRTUAL新交易")
            print(datetime.now())
            data=self.get_address_virtual_transaction_basescan()
            #data=self.get_address_virtual_transaction_basescan()
            print(data)
            self.send_transaction_notification_basescan(data)
            #data=self.get_address_virtual_transaction_basescan()
            #data=self.get_address_virtual_transaction_basescan()
            #print(data)
            #self.send_transaction_notification_basescan(data)