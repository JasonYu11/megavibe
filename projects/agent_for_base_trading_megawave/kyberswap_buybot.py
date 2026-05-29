import requests
import web3
import subprocess
from web3 import Web3
import json
import time
import numpy as np
from de_co1 import decrypt_key as de_key
def de_key_from_word(word):
    cmd = 'reg query "HKEY_CURRENT_USER\\Environment" /v python_file'
    result = subprocess.check_output(cmd, shell=True).decode('utf-8')
    python_file = result.split('REG_SZ')[1].strip()
    cmd_salt = 'reg query "HKEY_CURRENT_USER\\Environment" /v matlab_1'
    result_salt = subprocess.check_output(cmd_salt, shell=True).decode('utf-8')
    matlab_1     = result_salt.split('REG_SZ')[1].strip()
    private_key = de_key(python_file, word,matlab_1)
    return private_key
def get_swap_route(chain, token_in, token_out, amount_in, client_id):
    """
    查询 KyberSwap 的最佳交换路线。

    参数：
    - chain (str): 使用的区块链名称，例如 'ethereum'。
    - token_in (str): 输入代币的地址。
    - token_out (str): 输出代币的地址。
    - amount_in (str): 输入代币的数量，单位为 wei（字符串形式）。

    返回：
    - dict: 包含 route_summary 和 router_address 的字典。
    """
    # 构建 API URL
    url = f'https://aggregator-api.kyberswap.com/{chain}/api/v1/routes'

    # 设置查询参数
    params = {
        'tokenIn': token_in,
        'tokenOut': token_out,
        'amountIn': amount_in
    }

    # 设置请求头
    headers = {
        'Accept': 'application/json'
    }

    last_err = None
    for attempt in range(1, 4):
        try:
            # 发送 GET 请求（增加超时）
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            # 提取 routeSummary 和 routerAddress
            route_summary = data.get('data', {}).get('routeSummary')
            router_address = data.get('data', {}).get('routerAddress')

            if not route_summary or not router_address:
                raise ValueError("未能获取到 routeSummary 或 routerAddress。请检查请求参数。")

            return {
                'route_summary': route_summary,
                'router_address': router_address
            }

        except (requests.exceptions.HTTPError, requests.exceptions.RequestException, ValueError) as e:
            last_err = e
            print(f"请求失败(第{attempt}/3次): {e}")
            if attempt < 3:
                time.sleep(3)
            else:
                print("重试次数已用完。")
        except Exception as e:
            last_err = e
            print(f"其他错误(第{attempt}/3次): {e}")
            if attempt < 3:
                time.sleep(3)
            else:
                print("重试次数已用完。")

    return None
def encode_swap_route(chain, route_summary, sender, recipient, client_id, slippage_tolerance=800):
    """
    编码 KyberSwap 的交换路线以获取调用数据。
    
    参数：
    - chain (str): 使用的区块链名称，例如 'ethereum'。
    - route_summary (dict): 从步骤一获取的 routeSummary。
    - sender (str): 发起交易的地址。
    - recipient (str): 接收输出代币的地址。
    - client_id (str): 您的客户端 ID，用于身份识别和避免速率限制。
    - slippage_tolerance (int): 滑点容忍度，单位为基点（bps）。默认为 10（即 0.1%）。
    
    返回：
    - str: 编码后的交换数据（十六进制字符串）。
    """
    # 构建 API URL
    url = f'https://aggregator-api.kyberswap.com/{chain}/api/v1/route/build'
    
    # 设置请求头
    headers = {
        'Content-Type': 'application/json'
    }
    # 构建请求体
    request_body = {
        'routeSummary': route_summary,
        'sender': sender,
        'recipient': recipient,
        'slippageTolerance': slippage_tolerance
    }
    
    last_err = None
    for attempt in range(1, 5):
        try:
            response = requests.post(url, json=request_body, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            encoded_swap_data = data.get('data', {}).get('data')
            
            if not encoded_swap_data:
                raise ValueError("未能获取到编码后的交换数据。请检查请求参数和 routeSummary。")
            
            return encoded_swap_data
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException, ValueError) as e:
            last_err = e
            print(f"请求失败(第{attempt}/3次): {e}")
            if attempt < 3:
                time.sleep(3)
            else:
                print("重试次数已用完。")
        except Exception as e:
            last_err = e
            print(f"其他错误(第{attempt}/3次): {e}")
            if attempt < 3:
                time.sleep(3)
            else:
                print("重试次数已用完。")
    
    return None
def get_token_balance_for_wallet(w3,account,token_address):
    token_abi = [
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "spender",
                "type": "address"
            },
            {
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256"
            }
        ],
        "name": "approve",
        "outputs": [
            {
                "internalType": "bool",
                "name": "",
                "type": "bool"
            }
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "account",
                "type": "address"
            }
        ],
        "name": "balanceOf",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "",
                "type": "uint256"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [
            {
                "internalType": "uint8",
                "name": "",
                "type": "uint8"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [
            {
                "internalType": "string",
                "name": "",
                "type": "string"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "owner",
                "type": "address"
            },
            {
                "internalType": "address",
                "name": "spender",
                "type": "address"
            }
        ],
        "name": "allowance",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "",
                "type": "uint256"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]
    
    token_contract = w3.eth.contract(address=token_address, abi=token_abi)
    balance = token_contract.functions.balanceOf(account).call()
    symbol = token_contract.functions.symbol().call()
    return balance,symbol
def kyberswap_swap(token_in, token_out, amount_in,word, slippage_tolerance=800,chain='base',rate=1):
    time_start = time.time()  # 添加这行来记录开始时间
    # 添加重连机制
    amount_in=amount_in*rate
    max_retries = 5
    retry_count = 0
    connected = False
    while not connected and retry_count < max_retries:
        try:
            w3 = Web3(Web3.HTTPProvider('https://mainnet.base.org'))
            if w3.is_connected():
                connected = True
            else:
                raise ConnectionError("未能连接到以太坊节点。")
        except Exception as e:
            print(f"连接失败，重试中... ({retry_count + 1}/{max_retries})")
            retry_count += 1
            if retry_count >= max_retries:
                print("无法连接到以太坊节点，请检查网络连接或节点地址。")
                return
            time.sleep(2)  # 等待2秒后重试
    client_id = ''
    token_in = Web3.to_checksum_address(token_in)
    token_out = Web3.to_checksum_address(token_out)
    slippage_tolerance=slippage_tolerance
    #改为自己的钱包地址
    my_wallet_address="0xe5cfACD9460fC97Ca4F6bfB02F2d4673a8acaC8d"    
    sender = Web3.to_checksum_address(my_wallet_address)
    recipient = Web3.to_checksum_address(my_wallet_address)
    virtual_token_address = Web3.to_checksum_address("0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b")
    # 调用函数获取交换路线
    #token_abi = json.load(open('erc20_abi.json', 'r'))
    token_abi = [
        {
            "inputs": [
                {
                    "internalType": "address",
                    "name": "spender",
                    "type": "address"
                },
                {
                    "internalType": "uint256",
                    "name": "amount",
                    "type": "uint256"
                }
            ],
            "name": "approve",
            "outputs": [
                {
                    "internalType": "bool",
                    "name": "",
                    "type": "bool"
                }
            ],
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "inputs": [
                {
                    "internalType": "address",
                    "name": "account",
                    "type": "address"
                }
            ],
            "name": "balanceOf",
            "outputs": [
                {
                    "internalType": "uint256",
                    "name": "",
                    "type": "uint256"
                }
            ],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "decimals",
            "outputs": [
                {
                    "internalType": "uint8",
                    "name": "",
                    "type": "uint8"
                }
            ],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "symbol",
            "outputs": [
                {
                    "internalType": "string",
                    "name": "",
                    "type": "string"
                }
            ],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [
                {
                    "internalType": "address",
                    "name": "owner",
                    "type": "address"
                },
                {
                    "internalType": "address",
                    "name": "spender",
                    "type": "address"
                }
            ],
            "name": "allowance",
            "outputs": [
                {
                    "internalType": "uint256",
                    "name": "",
                    "type": "uint256"
                }
            ],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    token_in_contract = w3.eth.contract(address=token_in, abi=token_abi)
    token_virtual_contract = w3.eth.contract(address=virtual_token_address, abi=token_abi)
    balance_in,symbol = get_token_balance_for_wallet(w3,sender,token_in)
    balance_in=w3.from_wei(balance_in, 'ether')
    if balance_in<0.000000000000000001:
        print(f"代币{symbol}余额不足，请充值。")
        return None, None, None, None, None,None,None
    if amount_in > balance_in:
        print(f"计划输入金额（{amount_in} tokens）大于当前余额（{balance_in} tokens），将使用全部余额。")
        amount_in_real = str(w3.to_wei(balance_in, 'ether'))
    else:
        amount_in_real = str(w3.to_wei(amount_in, 'ether'))
        
    result = get_swap_route(chain, token_in, token_out, amount_in_real, client_id)

    if result:
        route_summary = result['route_summary']
        router_address = result['router_address']

        print("\n编码交换路线...")
        encoded_swap_data = encode_swap_route(
            chain, route_summary, sender, recipient, client_id, 
            slippage_tolerance=slippage_tolerance
        )

        if encoded_swap_data:
            print("编码成功")

            # 配置 Web3
            w3 = Web3(Web3.HTTPProvider('https://mainnet.base.org'))

            # 获取当前 gas 价格并设置合理的倍数
            current_gas_price = w3.eth.gas_price
            # 使用1.2倍而不是3倍，避免Gas费用过高
            gas_price = int(current_gas_price * 1.5)
            # 确保Gas价格在合理范围内

            balance_in = token_in_contract.functions.balanceOf(sender).call()
            print(f"钱包地址: {sender}")
            print(f"代币地址: {token_in}")
            print(f"代币余额: {balance_in}")

            private_key = de_key_from_word(word)

            # === Approve ===
            approve_nonce = w3.eth.get_transaction_count(sender)
            approve_txn = token_in_contract.functions.approve(
                router_address, int(amount_in_real)
            ).build_transaction({
                'from': sender,
                'nonce': approve_nonce,
                'gas': 300000,
                'maxFeePerGas': int(gas_price),
                'maxPriorityFeePerGas': int(gas_price // 2),
                'chainId': 8453
            })

            signed_approve_txn = w3.eth.account.sign_transaction(approve_txn, private_key)
            approve_tx_hash = w3.eth.send_raw_transaction(signed_approve_txn.raw_transaction)
            print(f"批准交易已发送，交易哈希: {approve_tx_hash.hex()}")

            tx_receipt = w3.eth.wait_for_transaction_receipt(approve_tx_hash)
            print(f"批准交易已确认，区块号: {tx_receipt['blockNumber']}")
            do_swap=True
            if do_swap:
                # 将地址转换为 checksum 格式
                sender = Web3.to_checksum_address(sender)
                router_address = Web3.to_checksum_address(router_address)

                # === Swap ===
                swap_nonce = approve_nonce + 1
                
                transaction = {
                    'from': sender,
                    'to': router_address,
                    'data': encoded_swap_data,
                    'gas': 3000000,
                    'maxFeePerGas': int(gas_price),
                    'maxPriorityFeePerGas': int(gas_price // 2),
                    'nonce': swap_nonce,
                    'chainId': 8453
                }

                # 交换重试逻辑
                swap_success = False
                base_gas_price = gas_price  # 保存基础gas价格
                for swap_attempt in range(1, 6):
                    try:
                        print(f"尝试交换交易 (第{swap_attempt}/3次)...")
                        
                        # 每次重试增加10%的gas费
                        if swap_attempt > 1:
                            gas_price = int(base_gas_price * (1 + 0.1 * (swap_attempt - 1)))
                            transaction['maxFeePerGas'] = int(gas_price)
                            transaction['maxPriorityFeePerGas'] = int(gas_price // 2)
                            print(f"第{swap_attempt}次重试，Gas价格调整为: {gas_price}")
                        
                        # 重新获取nonce，避免nonce冲突
                        current_nonce = w3.eth.get_transaction_count(sender)
                        transaction['nonce'] = current_nonce
                        
                        signed_txn = w3.eth.account.sign_transaction(transaction, private_key)
                        tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
                        print(f"交易已发送，交易哈希: {tx_hash.hex()}")

                        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                        if tx_receipt['status'] == 1:
                            print(f"交换交易成功，区块号: {tx_receipt['blockNumber']}")
                            swap_success = True

                            # ===== gas 消耗（ETH）
                            eth_spent = float(w3.from_wei(
                                tx_receipt['gasUsed'] * tx_receipt['effectiveGasPrice'], 'ether'
                            ))

                            # ===== 实际收到的 token 数量
                            transfer_event_signature = w3.keccak(text="Transfer(address,address,uint256)").hex()
                            token_out_lower = Web3.to_checksum_address(token_out).lower()
                            tokenout_amount_real = None

                            for log in tx_receipt['logs']:
                                if (
                                    log['topics'][0].hex() == transfer_event_signature and 
                                    log['address'].lower() == token_out_lower and
                                    log['topics'][2].hex()[-40:].lower() == recipient.lower()[2:]
                                ):
                                    tokenout_amount_real = float(
                                        w3.from_wei(w3.to_int(log['data']), 'ether')
                                    )
                                    break

                            # ===== 耗时
                            time_end = time.time()
                            time_used = time_end - time_start

                            # ===== 计算 price_SP
                            amount_in_real = float(w3.from_wei(int(amount_in_real), 'ether'))
                            virtual_token_address = "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b".lower()
                            if token_in.lower() == virtual_token_address:
                                price_SP = amount_in_real / tokenout_amount_real
                            else:
                                price_SP = tokenout_amount_real / amount_in_real

                            # ===== 获取 VIRTUAL 代币余额
                            balance_virtual = token_virtual_contract.functions.balanceOf(sender).call()
                            balance_virtual = w3.from_wei(balance_virtual, 'ether')

                            return (
                                round(eth_spent, 6),
                                round(tokenout_amount_real, 6),
                                round(amount_in_real, 6),
                                round(time_used, 1),
                                round(price_SP, 6),
                                tx_hash.hex(),
                                round(balance_virtual, 6)
                            )

                        else:
                            print(f"交换交易失败 (第{swap_attempt}/3次)，区块号: {tx_receipt['blockNumber']}")
                            if swap_attempt < 3:
                                print("等待3秒后重试...")
                                time.sleep(3)
                            else:
                                print("交换重试次数已用完")
                                return None, None, None, None, None, None, None

                    except Exception as e:
                        print(f"发送交易时出错 (第{swap_attempt}/3次): {e}")
                        if swap_attempt < 3:
                            print("等待3秒后重试...")
                            time.sleep(3)
                        else:
                            print("交换重试次数已用完")
                            return None, None, None, None, None, None, None
            else:
                print("已跳过 swap 交易，仅执行了 approve。")
                return None, None, None, None, None, None, None

        else:
            print("未能获取到交换路线。")
            return None, None, None, None, None, None, None
condition = 2
# 检查条件是否满足
if condition == 1:
    # 调用kyberswap_swap函数进行交换
    eth_spent, tokenout_amount_real, amount_in_real, time_used, price_SP, tx_hash, balance_virtual = kyberswap_swap(
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 
        "0x0bc945e3Ea693ad1527683d9cfE999407EBAAbB0", 
        0.01*10**-12, 
        "nickfollowbot",
        800
    )
    # 检查是否成功消耗ETH
    if eth_spent is not None:
        # 打印交易信息
        print(f"Gas消耗: {eth_spent} ETH")
        print(f"收到代币数量: {tokenout_amount_real}")
        print(f"交易耗时: {time_used} 秒")
        print(f"价格比率: {price_SP}")
        print(f"交易哈希: {tx_hash}")
        print(f"VIRTUAL代币余额: {balance_virtual}")
        print(f"输入代币数量: {amount_in_real}")
