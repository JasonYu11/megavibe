from web3 import Web3
import os
import subprocess
import json
import time
import numpy as np
from de_co1 import decrypt_key as de_key
MY_wallet_address="0xe5cfACD9460fC97Ca4F6bfB02F2d4673a8acaC8d"
def connect_to_base():
    """连接到Base网络并返回Web3实例，失败时进行重试"""
    infura_url = "https://base-mainnet.infura.io/v3/ea5aba4a02f449b0a9dda3ea43546a16"
    max_retries = 10
    retry_delay = 1  # 秒
    
    for attempt in range(max_retries):
        try:
            w3 = Web3(Web3.HTTPProvider(infura_url))
            if w3.is_connected():
                print(f"连接成功 (尝试次数: {attempt + 1})")
                return w3
            
            print(f"连接失败，正在进行第 {attempt + 1} 次重试...")
            time.sleep(retry_delay)
            
        except Exception as e:
            if attempt == max_retries - 1:
                raise ConnectionError(f"在 {max_retries} 次尝试后仍无法连接到 Infura 节点: {str(e)}")
            print(f"连接出错: {str(e)}，正在进行第 {attempt + 1} 次重试...")
            time.sleep(retry_delay)
    
    raise ConnectionError(f"在 {max_retries} 次尝试后仍无���连接到 Infura 节点")
def de_key_from_word(word):

    cmd = 'reg query "HKEY_CURRENT_USER\\Environment" /v python_file'
    result = subprocess.check_output(cmd, shell=True).decode('utf-8')
    python_file = result.split('REG_SZ')[1].strip()
    cmd_salt = 'reg query "HKEY_CURRENT_USER\\Environment" /v matlab_1'
    result_salt = subprocess.check_output(cmd_salt, shell=True).decode('utf-8')
    matlab_1     = result_salt.split('REG_SZ')[1].strip()
    private_key = de_key(python_file, word,matlab_1)
    return private_key
def get_token_balance_for_wallet(w3, wallet_address, token_address):
    """
    检查指定钱包地址的特定代币余额
    
    Args:
        w3 (Web3): Web3实例
        wallet_address (str): 要查询的钱包地址
        token_address (str): 代币合约地址
    
    Returns:
        float: 代币余额（以ether为单位）
        str: 代币符号
    """
    try:
        # 加载ERC20合约
        erc20_abi = json.load(open('erc20_abi.json', 'r'))
        token_contract = w3.eth.contract(address=token_address, abi=erc20_abi)
        
        # 获取代币余额
        balance_wei = token_contract.functions.balanceOf(wallet_address).call()
        balance_ether = w3.from_wei(balance_wei, 'ether')
        
        # 获取代币符号
        token_symbol = token_contract.functions.symbol().call()
        
        print(f"钱包地址: {wallet_address}")
        print(f"代币地址: {token_address}")
        print(f"代币余额: {balance_ether} {token_symbol}")
        
        return balance_ether,token_symbol
        
    except Exception as e:
        print(f"检查余额时发生错误: {str(e)}")
        return None
def approve_token(w3, token_contract, account, dex_address, amount_in_wei, key,gas_price):
    """授权代币给DEX合约"""
    approve_nonce = w3.eth.get_transaction_count(account.address)
    approve_txn = token_contract.functions.approve(
        dex_address,
        amount_in_wei
    ).build_transaction({
        'from': account.address,
        'gas': 300000,
        'maxFeePerGas':gas_price,
        'maxPriorityFeePerGas':int(gas_price/2),
        'nonce': approve_nonce,
    })
    
    signed_approve_txn = w3.eth.account.sign_transaction(approve_txn, key)
    approve_tx_hash = w3.eth.send_raw_transaction(signed_approve_txn.raw_transaction)
    print(f"授权交易已发送，交易哈希: {approve_tx_hash.hex()}")
    
    approve_receipt = w3.eth.wait_for_transaction_receipt(approve_tx_hash)
    if approve_receipt['status'] != 1:
        raise Exception("授权失败")
    print("授权成功!")
def buy_token(w3, contract, account, amount_in_wei, token_address, key, gas_price):
    """执行代币购买"""
    max_retries = 3
    retry_delay = 1  # 秒
    
    try:
        for attempt in range(max_retries):
            try:
                nonce = w3.eth.get_transaction_count(account.address)
                transaction = contract.functions.buy(
                    amount_in_wei,
                    token_address
                ).build_transaction({
                    'from': account.address,
                    'value': 0,
                    'gas': 3000000,
                    'maxFeePerGas': gas_price,
                    'maxPriorityFeePerGas': int(gas_price/2),
                    'nonce': nonce,
                })
                
                signed_txn = w3.eth.account.sign_transaction(transaction, key)
                tx_hash_buy = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
                print(f"交易已发送，交易哈希: {tx_hash_buy.hex()}")
                
                tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash_buy)
                print(f"交易状态: {'成功' if tx_receipt['status'] == 1 else '失败'}")
                
                transfer_event_signature = w3.keccak(text="Transfer(address,address,uint256)").hex()
                token_address_lower = Web3.to_checksum_address(token_address).lower()
                
                for log in tx_receipt['logs']:
                    if log['topics'][0].hex() == transfer_event_signature and log['address'].lower() == token_address_lower:
                        token_received = w3.to_int(log['data'])
                        token_received_SP = w3.from_wei(token_received, 'ether')
                        print(f"获得的代币数量: {token_received_SP}")
                        break
                
                eth_spent = float(w3.from_wei(tx_receipt['gasUsed'] * tx_receipt['effectiveGasPrice'], 'ether'))
                eth_price = 4000
                usd_spent = eth_spent * eth_price
                print(f"交易消耗的ETH: {eth_spent}(USD:{usd_spent})")
                return eth_spent, token_received_SP, tx_hash_buy
                
            except Exception as e:
                if attempt == max_retries - 1:  # 最后一次尝试失败
                    print(f"购买交易失败: 在{max_retries}次尝试后仍然失败 - {str(e)}")
                    raise
                print(f"购买交易失败: {str(e)}，正在进行第{attempt + 1}次重试...")
                time.sleep(retry_delay)
    finally:
        # 清除私钥
        key = None
def sell_token(w3, contract, account, amount_in_wei, token_address, key, gas_price):
    """执行代币出售"""
    max_retries = 3
    retry_delay = 1  # 秒
    
    try:
        for attempt in range(max_retries):
            try:
                nonce = w3.eth.get_transaction_count(account.address)
                transaction = contract.functions.sell(
                    amount_in_wei,
                    token_address
                ).build_transaction({
                    'from': account.address,
                    'value': 0,
                    'gas': 3000000,
                    'maxFeePerGas': gas_price,
                    'maxPriorityFeePerGas': int(gas_price/2),
                    'nonce': nonce,
                })
                
                signed_txn = w3.eth.account.sign_transaction(transaction, key)
                tx_hash_sell = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
                print(f"交易已发送，交易哈希: {tx_hash_sell.hex()}")
                
                tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash_sell)
                print(f"交易状态: {'成功' if tx_receipt['status'] == 1 else '失败'}")
                
                # 解析Transfer事件获取收到的代币数量
                transfer_event_signature = w3.keccak(text="Transfer(address,address,uint256)").hex()
                virtual_token_address = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b".lower()
                
                for log in tx_receipt['logs']:
                    if log['topics'][0].hex() == transfer_event_signature and log['address'].lower() == virtual_token_address:
                        vfun_received = w3.to_int(log['data'])
                        vfun_received_VIRTUAL = w3.from_wei(vfun_received, 'ether')
                        print(f"获得的VIRTUAL代币数量: {vfun_received_VIRTUAL}")
                        break
                        
                eth_spent = float(w3.from_wei(tx_receipt['gasUsed'] * tx_receipt['effectiveGasPrice'], 'ether'))
                eth_price = 4000
                usd_spent = eth_spent * eth_price
                print(f"交易消耗的ETH: {eth_spent}(USD:{usd_spent})")        
                return eth_spent, vfun_received_VIRTUAL, tx_hash_sell
                
            except Exception as e:
                if attempt == max_retries - 1:  # 最后一次尝试失败
                    print(f"出售交易失败: 在{max_retries}次尝试后仍然失败 - {str(e)}")
                    raise
                print(f"出售交易失败: {str(e)}，正在进行第{attempt + 1}次重试...")
                time.sleep(retry_delay)
    finally:
        # 清除私钥
        key = None
def buy_virtualfun_token(token_buy_address,amount_buy,word,buy_rate=0.1):
    # 初始化连接和配置
    time_start=time.time()
    w3 = connect_to_base()
    virtual_contract_address = Web3.to_checksum_address("0xF66DeA7b3e897cD44A5a231c61B6B4423d613259")
    token_buy_address = Web3.to_checksum_address(token_buy_address)
    virtual_token_address = Web3.to_checksum_address("0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b")
    dex_address = Web3.to_checksum_address("0x8292B43aB73EfAC11FAF357419C38ACF448202C5")
    
    amount_buy=amount_buy*buy_rate  #跟单系数
    virtual_abi = [
        {
            "constant": True,
            "inputs": [
                {"name": "_owner", "type": "address"},
                {"name": "_spender", "type": "address"}
            ],
            "name": "allowance",
            "outputs": [{"name": "", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [{"internalType": "address", "name": "target", "type": "address"}],
            "name": "AddressEmptyCode",
            "type": "error"
        },
        {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "internalType": "address", "name": "token", "type": "address"},
                {"indexed": False, "internalType": "uint256", "name": "amount0", "type": "uint256"},
                {"indexed": False, "internalType": "uint256", "name": "amount1", "type": "uint256"}
            ],
            "name": "Deployed",
            "type": "event"
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "address", "name": "tokenAddress", "type": "address"}
            ],
            "name": "buy",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "stateMutability": "payable",
            "type": "function"
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "address", "name": "tokenAddress", "type": "address"}
            ],
            "name": "sell",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "inputs": [{"internalType": "address", "name": "", "type": "address"}],
            "name": "tokenInfo",
            "outputs": [
                {"internalType": "address", "name": "creator", "type": "address"},
                {"internalType": "address", "name": "token", "type": "address"},
                {"internalType": "address", "name": "pair", "type": "address"},
                {"internalType": "address", "name": "agentToken", "type": "address"},
                {
                    "components": [
                        {"internalType": "address", "name": "token", "type": "address"},
                        {"internalType": "string", "name": "name", "type": "string"},
                        {"internalType": "string", "name": "_name", "type": "string"},
                        {"internalType": "string", "name": "ticker", "type": "string"},
                        {"internalType": "uint256", "name": "supply", "type": "uint256"},
                        {"internalType": "uint256", "name": "price", "type": "uint256"},
                        {"internalType": "uint256", "name": "marketCap", "type": "uint256"},
                        {"internalType": "uint256", "name": "liquidity", "type": "uint256"},
                        {"internalType": "uint256", "name": "volume", "type": "uint256"},
                        {"internalType": "uint256", "name": "volume24H", "type": "uint256"},
                        {"internalType": "uint256", "name": "prevPrice", "type": "uint256"},
                        {"internalType": "uint256", "name": "lastUpdated", "type": "uint256"}
                    ],
                    "internalType": "struct Bonding.Data",
                    "name": "data",
                    "type": "tuple"
                },
                {"internalType": "string", "name": "description", "type": "string"},
                {"internalType": "string", "name": "image", "type": "string"},
                {"internalType": "string", "name": "twitter", "type": "string"},
                {"internalType": "string", "name": "telegram", "type": "string"},
                {"internalType": "string", "name": "youtube", "type": "string"},
                {"internalType": "string", "name": "website", "type": "string"},
                {"internalType": "bool", "name": "trading", "type": "bool"},
                {"internalType": "bool", "name": "tradingOnUniswap", "type": "bool"}
            ],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
            "name": "AddressInsufficientBalance",
            "type": "error"
        },
        {
            "inputs": [],
            "name": "FailedInnerCall",
            "type": "error"
        },
        {
            "inputs": [],
            "name": "InvalidInitialization",
            "type": "error"
        },
        {
            "inputs": [],
            "name": "NotInitializing",
            "type": "error"
        },
        {
            "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
            "name": "OwnableInvalidOwner",
            "type": "error"
        },
        {
            "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
            "name": "OwnableUnauthorizedAccount",
            "type": "error"
        },
        {
            "inputs": [],
            "name": "ReentrancyGuardReentrantCall",
            "type": "error"
        },
        {
            "inputs": [{"internalType": "address", "name": "token", "type": "address"}],
            "name": "SafeERC20FailedOperation",
            "type": "error"
        },
        {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "internalType": "address", "name": "token", "type": "address"},
                {"indexed": False, "internalType": "address", "name": "agentToken", "type": "address"}
            ],
            "name": "Graduated",
            "type": "event"
        },
        {
            "anonymous": False,
            "inputs": [{"indexed": False, "internalType": "uint64", "name": "version", "type": "uint64"}],
            "name": "Initialized",
            "type": "event"
        }
    ]
    erc20_abi = [
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
    #virtual_abi = json.load(open('virtual_abi.json', 'r'))
    #erc20_abi = json.load(open('erc20_abi.json', 'r'))
    contract = w3.eth.contract(address=virtual_contract_address, abi=virtual_abi)
    token_trade_contract = w3.eth.contract(address=virtual_token_address, abi=erc20_abi)
    # 获取账户信息
    key = de_key_from_word(word)
    account = w3.eth.account.from_key(key)
    amount_buy_wei = w3.to_wei(float(amount_buy), 'ether')
    gas_price=w3.eth.gas_price
    gas_price=int(gas_price*3)
    max_retries = 2
    retry_delay = 5  # 秒
    try:
        for attempt in range(max_retries):
            try:
                # 执行授权
                balance, symbol = get_token_balance_for_wallet(w3, MY_wallet_address, virtual_token_address)
                print(f"当前{symbol}余额{balance}  购买数量{amount_buy}")
                if balance == 0 or balance is None:
                    print(f"想购买的代币{symbol}余额为0")
                    return None, None, None, None, None, None, None
                if balance < amount_buy:
                    amount_buy_wei = w3.to_wei(balance, 'ether')
                    print(f"代币余额不足，使用全部{symbol}余额交易")
                approve_token(w3, token_trade_contract, account, dex_address, amount_buy_wei, key, gas_price)
                # 执行购买
                eth_spent, token_received_SP, tx_hash_buy = buy_token(w3, contract, account, amount_buy_wei, token_buy_address, key, gas_price)
                amount_buy_real = w3.from_wei(amount_buy_wei, 'ether')
                price_SP = float(np.format_float_positional(float(amount_buy_real)/float(token_received_SP), precision=3, unique=False, fractional=False, trim='k'))
                approve_token(w3, token_trade_contract, account, dex_address, 0, key, gas_price)
                time_end = time.time()
                time_used = time_end-time_start
                virtual_token_left = round(float(balance)-float(amount_buy_real), 1)
                print(f"购买完成，耗时{time_used}秒")
                return eth_spent, round(float(token_received_SP), 1), round(float(time_used), 1), price_SP, tx_hash_buy.hex(), round(float(amount_buy_real), 1), virtual_token_left
                
            except Exception as e:
                if attempt == max_retries - 1:  # 最后一次尝试失败
                    print(f"购买失败: 在{max_retries}次尝试后仍然失败 - {str(e)}")
                    return None, None, None, None, None, None, None
                print(f"购买失败: {str(e)}，正在进行第{attempt + 1}次重试...")
                time.sleep(retry_delay)
                
    finally:    # 清除私钥
        key = None
def sell_virtualfun_token(token_sell_address,amount_sell,word,sell_rate=0.1):
    time_start=time.time()
    w3 = connect_to_base()
    virtual_contract_address = Web3.to_checksum_address("0xF66DeA7b3e897cD44A5a231c61B6B4423d613259")
    token_sell_address = Web3.to_checksum_address(token_sell_address)
    virtual_token_address = Web3.to_checksum_address("0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b")
    dex_address = Web3.to_checksum_address("0x8292B43aB73EfAC11FAF357419C38ACF448202C5")
    #定义售卖规则
    amount_sell=amount_sell*sell_rate
    # 加载合约
    abi = json.load(open('virtual_abi.json', 'r'))
    erc20_abi = json.load(open('erc20_abi.json', 'r'))
    contract = w3.eth.contract(address=virtual_contract_address, abi=abi)
    token_trade_contract = w3.eth.contract(address=token_sell_address, abi=erc20_abi)
    # 获取账户信息
    key = de_key_from_word(word)
    account = w3.eth.account.from_key(key)
    amount_sell_wei = w3.to_wei(float(amount_sell), 'ether')
    gas_price=w3.eth.gas_price
    gas_price=int(gas_price*3)
    max_retries = 2
    retry_delay = 5  # 秒
    try:
        for attempt in range(max_retries):
            try:
                # 执行授权
                balance,symbol = get_token_balance_for_wallet(w3,MY_wallet_address,token_sell_address)
                print(f"当前{symbol}余额{balance}")
                print(f"出售数量{amount_sell}")
                if balance==0 or balance is None:
                    print(f"想出售的代币{symbol}余额为0")
                    return None, None, None, None, None, None, None
                if balance<amount_sell:
                    amount_sell_wei=w3.to_wei(balance, 'ether')
                    print(f"代币余额不足，使用全部{symbol}余额进行出售")
                approve_token(w3, token_trade_contract, account, dex_address, amount_sell_wei, key,gas_price)
                
                # 执行出售
                eth_spent,vfun_received_VIRTUAL,tx_hash_sell  = sell_token(w3, contract, account, amount_sell_wei, token_sell_address, key,gas_price)
                amount_sell_real=w3.from_wei(amount_sell_wei, 'ether')
                price_SP = float(np.format_float_positional(float(vfun_received_VIRTUAL)/float(amount_sell_real), precision=3, unique=False, fractional=False, trim='k'))
                approve_token(w3, token_trade_contract, account, dex_address, 0, key,gas_price)
                time_end=time.time()
                time_used=time_end-time_start
                print(f"出售完成，耗时{time_used}秒")
                balance_virtual,symbol_virtual = get_token_balance_for_wallet(w3,account.address,virtual_token_address)
                virtual_token_left=round(float(balance_virtual),1)
                return eth_spent, round(float(vfun_received_VIRTUAL), 1), round(float(time_used), 1), price_SP, tx_hash_sell.hex(), round(float(amount_sell_real), 1),virtual_token_left
            except Exception as e:
                print(f"出售失败: {str(e)}余额为0")
                return None, None, None, None, None, None, None
    finally:
        # 清除私钥
        private_key = None

if __name__ == "__main__":
    a=2
    if a==1:
        try:
            eth_spent, token_received_SP, time_used, price_SP, tx_hash_buy, amount_buy_real,virtual_token_left = buy_virtualfun_token("0x651759aa0b35f3e9590E0AC45f712965892A7C24", 0.1,"nickfollowbot")
            print(f"购买消耗的ETH: {eth_spent}")
            print(f"购买获得的代币数量: {token_received_SP}")
            print(f"购买耗时: {time_used}秒")
            print(f"购买价格: {price_SP} VIRTUAL/代币")
            print(f"购买交易哈希: {tx_hash_buy}")
            print(f"实际购买代币数量: {amount_buy_real}")
        except Exception as e:
            print(f"购买失败: {str(e)}VIRTUAL代币余额为0")
    if a==2:
        try:
            eth_spent,vfun_received_VIRTUAL,time_used,price_SP,tx_hash_sell,amount_sell_real,virtual_token_left=sell_virtualfun_token("0x651759aa0b35f3e9590E0AC45f712965892A7C24",10000000,"nickfollowbot")
            print(f"出售消耗的ETH:{eth_spent}")
            print(f"出售获得的代币数量:{vfun_received_VIRTUAL}")
            print(f"出售耗时:{time_used}秒")
            print(f"出售价格:{price_SP}VIRTUAL/代币")
            print(f"出售交易哈希:{tx_hash_sell}")
            print(f"实际出售代币数量:{amount_sell_real}")
        except Exception as e:
            print(f"出售失败: {str(e)}SP代币余额为0")
