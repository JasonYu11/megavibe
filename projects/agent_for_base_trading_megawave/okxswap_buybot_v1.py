# -*- coding: utf-8 -*-
import time
import hmac
import json
import base64
import hashlib
import typing as t
from datetime import datetime, timezone
import os
import subprocess
import requests
from web3 import Web3, HTTPProvider

# =========================
# 全局配置（请务必填写）
# =========================

# OKX Onchain Gateway / DEX Aggregator 认证参数
OKX_API_KEY: str = "834ca70d-cf75-4108-bd37-9eb5f1376c96"          # 必填
OKX_SECRET_KEY: str = "D7F86ED786571D372BAB373DEF47917D"       # 必填
OKX_API_PASSPHRASE: str = "20001014aA!"   # 必填
OKX_PROJECT_ID: str = "9ae775da4ca800690791459a6b7f0376"       # 必填

# EVM 网络（Base 主网）
EVM_RPC_URL: str = "https://mainnet.base.org"   # 可替换自有 RPC
CHAIN_ID: int = 8453

# 钱包
WALLET_ADDRESS: str = "0x8EF454c23822C5373df37e8c5E8987aC64dB96F1"  # 必填：你的地址，0x 开头

cmd = 'security find-generic-password -a myuser -s MY_SECRET_VAR2 -w'
result = subprocess.check_output(cmd, shell=True).decode('utf-8')
openai_key = result.strip()
print(openai_key)
PRIVATE_KEY = openai_key + "9a41ba"

# API 基础路径
OKX_BASE_URL: str = "https://web3.okx.com/api/v5/"
NATIVE_ETH: str = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # 原生 ETH 占位

# Web3 with retry mechanism
w3 = None
for attempt in range(5):  # 5次重试
    try:
        w3 = Web3(HTTPProvider(EVM_RPC_URL))
        # 测试连接
        w3.eth.block_number
        break
    except Exception as e:
        if attempt == 4:  # 最后一次尝试
            raise e
        print(f"Web3连接失败，第 {attempt + 1} 次重试: {e}")
        time.sleep(1)  # 等待1秒后重试

# =========================
# 工具函数
# =========================

def cs(addr: str) -> str:
    """转换为 checksum 地址格式"""
    return Web3.to_checksum_address(addr)

def _iso_ts() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _sign_headers(method: str, path: str, query: str = "", body: str = "") -> dict:
    if not (OKX_API_KEY and OKX_SECRET_KEY and OKX_API_PASSPHRASE and OKX_PROJECT_ID):
        raise RuntimeError("缺少 OKX 网关认证参数：OKX_API_KEY/OKX_SECRET_KEY/OKX_API_PASSPHRASE/OKX_PROJECT_ID")
    ts = _iso_ts()
    to_sign = ts + method.upper() + path + (query or body)
    digest = hmac.new(OKX_SECRET_KEY.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha256).digest()
    return {
        "Content-Type": "application/json",
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": base64.b64encode(digest).decode("utf-8"),
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": OKX_API_PASSPHRASE,
        "OK-ACCESS-PROJECT": OKX_PROJECT_ID,
    }

def _encode_params(params: dict) -> str:
    # 让签名用的 query 与 requests 实际发送一致
    return requests.models.RequestEncodingMixin._encode_params(params)

def _okx_get(path: str, params: dict) -> dict:
    """GET 请求带重试机制"""
    query = "?" + _encode_params(params)
    headers = _sign_headers("GET", f"/api/v5/{path}", query=query)
    url = OKX_BASE_URL + path
    
    for attempt in range(4):  # 4次重试
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 3:  # 最后一次尝试
                raise e
            print(f"GET 请求失败，第 {attempt + 1} 次重试: {e}")
            time.sleep(1)  # 等待1秒后重试

def _okx_post(path: str, body: dict) -> dict:
    """POST 请求带重试机制"""
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    headers = _sign_headers("POST", f"/api/v5/{path}", body=body_str)
    url = OKX_BASE_URL + path
    
    for attempt in range(4):  # 4次重试
        try:
            r = requests.post(url, data=body_str, headers=headers, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 3:  # 最后一次尝试 (0,1,2,3)
                raise e
            print(f"POST 请求失败，第 {attempt + 1} 次重试: {e}")
            time.sleep(1)  # 等待1秒后重试

def _parse_int_maybe_hex(x: t.Union[str, int, None]) -> int:
    if x is None:
        return 0
    if isinstance(x, int):
        return x
    s = str(x).strip()
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    return int(s)

# =========================
# OKX 聚合器与预估 gas
# =========================

def get_swap_data(token_in: str, token_out: str, amount_in_wei: t.Union[int, str], slippage_percent: t.Union[float, str]) -> dict:
    if not WALLET_ADDRESS:
        raise RuntimeError("缺少 WALLET_ADDRESS")
    # 规范化滑点为 OKX 接受的百分数字符串，限制 (0,100]
    try:
        s = float(slippage_percent)
    except Exception:
        raise RuntimeError("滑点参数错误，请提供数字")
    if not (0 < s <= 100):
        raise RuntimeError("滑点必须在 (0, 100] 范围内")
    # 有些聚合器仅接受整数百分数，向上取整可避免过低导致下单失败
    s_int = int(max(1, round(s)))
    params = {
        "chainIndex": str(CHAIN_ID),
        "fromTokenAddress": cs(token_in),
        "toTokenAddress": cs(token_out),
        "amount": str(amount_in_wei),
        "slippage": str(s_int),
        "userWalletAddress": cs(WALLET_ADDRESS),
    }
    data = _okx_get("dex/aggregator/swap", params)
    if data.get("code") != "0":
        raise RuntimeError(f"Swap API 错误: {data.get('msg') or data}")
    arr = data.get("data") or []
    if not arr:
        raise RuntimeError("Swap API 返回空 data")
    return arr[0]

def get_gas_limit_okx(from_addr: str, to_addr: str, tx_value: str, input_data: str) -> int:
    body = {
        "chainIndex": str(CHAIN_ID),
        "fromAddress": from_addr,
        "toAddress": to_addr,
        "txAmount": tx_value or "0",
        "extJson": {"inputData": input_data or ""}
    }
    data = _okx_post("dex/pre-transaction/gas-limit", body)
    if data.get("code") != "0":
        raise RuntimeError(f"GasLimit API 错误: {data.get('msg') or data}")
    arr = data.get("data") or []
    if not arr:
        raise RuntimeError("GasLimit API 返回空 data")
    return int(arr[0]["gasLimit"])

def estimate_gas_fallback(tx_dict: dict) -> int:
    # RPC 估算作为兜底
    est = w3.eth.estimate_gas(tx_dict)
    # 留一点 buffer
    return int(est * 1.2)

def get_safe_nonce(address: str) -> int:
    """Safely get nonce with fallback from pending to latest"""
    try:
        return w3.eth.get_transaction_count(address, "pending")
    except Exception as e:
        print(f"Warning: Could not get pending nonce: {e}")
        try:
            return w3.eth.get_transaction_count(address, "latest")
        except Exception as e2:
            print(f"Warning: Could not get latest nonce: {e2}")
            # Final fallback - get the current nonce
            return w3.eth.get_transaction_count(address)

def suggest_eip1559_fees() -> t.Tuple[int, int]:
    # Try different block identifiers in order of preference
    block_identifiers = ["pending", "latest"]
    
    for block_id in block_identifiers:
        try:
            blk = w3.eth.get_block(block_id)
            base_fee = blk.get("baseFeePerGas")
            if base_fee:
                priority = w3.to_wei(2, "gwei")
                max_fee = base_fee * 2 + priority
                return int(max_fee), int(priority)
        except Exception as e:
            print(f"Warning: Could not get block '{block_id}': {e}")
            continue
    
    # Fallback to gas_price if EIP-1559 is not supported
    try:
        gas_price = w3.eth.gas_price
        priority = w3.to_wei(2, "gwei")
        max_fee = gas_price + priority
        return int(max_fee), int(priority)
    except Exception as e:
        print(f"Warning: Could not get gas price: {e}")
        # Final fallback with hardcoded values
        return int(w3.to_wei(50, "gwei")), int(w3.to_wei(2, "gwei"))

# =========================
# ERC20 允许额度与授权
# =========================

ERC20_ABI = [
    {"constant": True, "inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"name":"","type":"uint256"}], "payable": False, "stateMutability":"view", "type":"function"},
    {"constant": False, "inputs":[{"name":"spender","type":"address"},{"name":"value","type":"uint256"}],
     "name":"approve","outputs":[{"name":"","type":"bool"}], "payable": False, "stateMutability":"nonpayable", "type":"function"},
    {"constant": True, "inputs":[{"name":"account","type":"address"}],
     "name":"balanceOf","outputs":[{"name":"","type":"uint256"}], "payable": False, "stateMutability":"view", "type":"function"},
]

def get_token_balance(token_address: str, wallet_address: str) -> int:
    """
    获取指定代币的余额
    
    Args:
        token_address: 代币合约地址
        wallet_address: 钱包地址
    
    Returns:
        int: 代币余额（wei 单位）
    """
    if token_address.lower() == NATIVE_ETH.lower():
        # 原生 ETH 余额
        return w3.eth.get_balance(wallet_address)
    else:
        # ERC20 代币余额
        erc20 = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return erc20.functions.balanceOf(wallet_address).call()

def ensure_allowance(token: str, owner: str, spender: str, required_amount: int) -> str:
    """
    确保 allowance >= required_amount；不足则发起 approve。
    返回 txHash（如果未发起则返回空字符串）
    """
    token = Web3.to_checksum_address(token)
    spender = Web3.to_checksum_address(spender)
    owner = Web3.to_checksum_address(owner)

    erc20 = w3.eth.contract(address=token, abi=ERC20_ABI)
    current = erc20.functions.allowance(owner, spender).call()
    if current >= int(required_amount):
        return ""

    # 构造批准交易（EIP-1559）
    nonce = get_safe_nonce(owner)
    max_fee, priority = suggest_eip1559_fees()
    # 使用当前 gas price 作为基础（兼容性更强），并设置更低的上限
    gas_price = w3.eth.gas_price
    tx = erc20.functions.approve(spender, int(required_amount)).build_transaction({
        "chainId": CHAIN_ID,
        "from": owner,
        "nonce": nonce,
        "maxFeePerGas": int(gas_price * 2),
        "maxPriorityFeePerGas": int(gas_price),
        "type": 2,
    })

    # 固定 approve 的 gas 上限为 300000
    tx["gas"] = 300000

    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
    # 等确认，避免后续 swap 因额度未上链失败
    rcpt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if rcpt and rcpt.status != 1:
        raise RuntimeError("approve 交易失败")
    return tx_hash

# =========================
# 带 MEV 保护的广播与跟踪
# =========================

def broadcast_with_mev(raw_tx_hex: str, address: str, enable_mev_protection: bool = True) -> str:
    """
    POST /dex/pre-transaction/broadcast-transaction
    使用 extraData.enableMevProtection 控制 MEV 保护
    返回 orderId
    """
    body = {
        "signedTx": raw_tx_hex,
        "chainIndex": str(CHAIN_ID),
        "address": address,
        "extraData": json.dumps({"enableMevProtection": bool(enable_mev_protection)})
    }
    data = _okx_post("dex/pre-transaction/broadcast-transaction", body)
    if data.get("code") != "0":
        raise RuntimeError(f"Broadcast API 错误: {data.get('msg') or data}")
    arr = data.get("data") or []
    if not arr:
        raise RuntimeError("Broadcast API 返回空 data")
    return arr[0]["orderId"]

def track_okx_order(order_id: str, timeout_sec: int = 300, poll_sec: int = 5) -> dict:
    start = time.time()
    while time.time() - start < timeout_sec:
        params = {
            "orderId": order_id,
            "chainIndex": str(CHAIN_ID),
            "address": WALLET_ADDRESS,
            "limit": "1"
        }
        try:
            data = _okx_get("dex/post-transaction/orders", params)
            if data.get("code") == "0":
                groups = data.get("data") or []
                if groups and groups[0].get("orders"):
                    txd = groups[0]["orders"][0]
                    status = txd.get("txStatus")  # 1: pending, 2: success, 3: failed
                    if status == "2":
                        return txd
                    if status == "3":
                        reason = txd.get("failReason") or "Unknown"
                        raise RuntimeError(f"交易失败: {reason}")
        except Exception:
            pass
        time.sleep(poll_sec)
    raise TimeoutError("订单确认超时")

def rpc_broadcast_with_retry(raw_tx_hex: str) -> str:
    """
    RPC 广播带简单重试机制
    """
    for attempt in range(3):  # 3次重试
        try:
            tx_hash = w3.eth.send_raw_transaction(bytes.fromhex(raw_tx_hex[2:] if raw_tx_hex.startswith("0x") else raw_tx_hex))
            return tx_hash.hex()
        except Exception as e:
            if attempt == 2:  # 最后一次尝试
                raise e
            
            print(f"RPC 广播失败，第 {attempt + 1} 次重试: {e}")
            time.sleep(2)  # 等待2秒后重试
    
    raise RuntimeError("RPC 广播重试3次后仍然失败")

def rpc_broadcast(raw_tx_hex: str) -> str:
    """原始 RPC 广播函数（保持兼容性）"""
    tx_hash = w3.eth.send_raw_transaction(bytes.fromhex(raw_tx_hex[2:] if raw_tx_hex.startswith("0x") else raw_tx_hex))
    return tx_hash.hex()

# =========================
# 主函数：MEV 模式一键 Swap（无模拟）
# =========================

def okx_swap_mev(
    token_in: str,
    token_out: str,
    amount_eth: t.Union[float, str],
    slippage_percent: t.Union[float, str] = 0.5,
    enable_mev: bool = True,
) -> t.Tuple[str, float]:
    """
    一键链上 Swap（Base 链，MEV 保护，去掉模拟），返回最终 txHash 和总用时。
    
    Args:
        token_in: 输入代币地址
        token_out: 输出代币地址
        amount_eth: 输入数量（ETH）
        slippage_percent: 滑点百分比
        enable_mev: 是否启用 MEV 保护
    
    Returns:
        Tuple[str, float]: (交易哈希, 总用时秒数)
    """
    start_time = time.time()
    
    # 基本检查
    if not Web3.is_address(WALLET_ADDRESS):
        raise RuntimeError("WALLET_ADDRESS 非法或未设置")
    if not PRIVATE_KEY:
        raise RuntimeError("未设置 PRIVATE_KEY")

    # 转换 ETH 数量到 wei
    amount_in_wei = w3.to_wei(amount_eth, "ether")

    # 0) 检查代币余额并调整交易数量
    print(f"检查 {token_in} 余额...")
    token_balance = get_token_balance(token_in, WALLET_ADDRESS)
    balance_eth = w3.from_wei(token_balance, "ether")
    
    print(f"当前余额(token_in): {balance_eth} ({token_balance} wei)")
    print(f"请求数量(token_in): {amount_eth} ({amount_in_wei} wei)")
    
    if token_balance <= amount_in_wei:
        # 余额不足，使用全部余额
        amount_in_wei = token_balance
        amount_eth = w3.from_wei(token_balance, "ether")
        print(f"⚠️  余额不足，调整为使用全部余额(token_in): {amount_eth}")
        
        # 检查余额是否足够支付 gas 费用（仅对 ETH）
        if token_in.lower() == NATIVE_ETH.lower():
            # 估算 gas 费用（将预留用的粗略 gas 下调 20 倍，至少 21000）
            rough_gas = 200000
            estimated_gas = max(21000, rough_gas // 20)
            max_fee, priority_fee = suggest_eip1559_fees()
            estimated_gas_cost = estimated_gas * max_fee
            
            if token_balance <= estimated_gas_cost:
                raise RuntimeError(f"ETH 余额不足支付 gas 费用。余额: {balance_eth} ETH, 估算 gas 费用: {w3.from_wei(estimated_gas_cost, 'ether')} ETH")
            
            # 预留 gas 费用
            amount_in_wei = token_balance - estimated_gas_cost
            amount_eth = w3.from_wei(amount_in_wei, "ether")
            print(f"预留 gas 费用后可用数量(token_in): {amount_eth}")
            print(f"用于预留的估算 gas: {estimated_gas}")
    else:
        print(f"✅ 余额充足，使用请求数量")

    # 1) 路由
    swap = get_swap_data(token_in, token_out, amount_in_wei, slippage_percent)
    tx = swap.get("tx") or {}
    if not tx:
        raise RuntimeError("聚合器未返回 tx 字段")

    # 2) allowance & approve （仅 ERC20 -> 非原生）
    if token_in.lower() != NATIVE_ETH.lower():
        spender = (swap.get("spender") or tx.get("to"))
        if not spender:
            raise RuntimeError("未获取到 spender")
        ensure_allowance(token_in, WALLET_ADDRESS, spender, int(amount_in_wei))

    # 3) 预估 gasLimit（优先 OKX）
    from_addr = tx.get("from")
    to_addr = tx.get("to")
    value_hex_or_dec = tx.get("value") or "0"
    data_hex = tx.get("data") or "0x"
    value_int = _parse_int_maybe_hex(value_hex_or_dec)

    try:
        gas_limit = get_gas_limit_okx(from_addr, to_addr, str(value_int), data_hex)
    except Exception:
        # 兜底用 RPC 估算
        tmp_tx = {
            "from": Web3.to_checksum_address(from_addr),
            "to": Web3.to_checksum_address(to_addr),
            "value": value_int,
            "data": data_hex,
        }
        gas_limit = estimate_gas_fallback(tmp_tx)

    # 使用固定的交易 gas 上限（按需可替换为估算值）
    gas_limit = 3000000

    # 4) 构造并签名交易（EIP-1559）
    nonce = get_safe_nonce(WALLET_ADDRESS)
    # 使用 web3 模块获取 gas 价格，并应用适度倍数
    current_gas_price = w3.eth.gas_price
    gas_price = int(current_gas_price * 1.5)
    max_fee_per_gas = gas_price
    max_priority_fee_per_gas = gas_price // 2

    tx_dict = {
        "chainId": CHAIN_ID,
        "nonce": nonce,
        "to": Web3.to_checksum_address(to_addr),
        "from": Web3.to_checksum_address(from_addr),
        "value": value_int,
        "data": data_hex,
        "gas": int(gas_limit),
        "maxFeePerGas": int(max_fee_per_gas),
        "maxPriorityFeePerGas": int(max_priority_fee_per_gas),
        "type": 2,
    }
    signed = w3.eth.account.sign_transaction(tx_dict, PRIVATE_KEY)
    raw_hex = signed.raw_transaction.hex()

    # 5) 广播 - 带重试机制
    base_max_fee = max_fee_per_gas
    base_priority_fee = max_priority_fee_per_gas
    
    for attempt in range(3):  # 3次重试
        try:
            if enable_mev:
                # 使用 OKX 广播（MEV 可选），失败则回退 RPC
                try:
                    order_id = broadcast_with_mev(raw_hex, WALLET_ADDRESS, enable_mev)
                    order = track_okx_order(order_id)
                    tx_hash = order.get("txHash")
                    if not tx_hash:
                        print("订单成功但未返回 txHash")
                        return None, None
                    total_time = time.time() - start_time
                    return tx_hash, total_time
                except Exception as mev_error:
                    print(f"MEV 广播失败，回退到 RPC: {mev_error}")
                    # 回退到 RPC 广播
                    tx_hash = rpc_broadcast(raw_hex)
                    rcpt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
                    if rcpt and rcpt.status != 1:
                        print(f"RPC 广播失败，tx={tx_hash}")
                        return None, None
                    total_time = time.time() - start_time
                    return tx_hash, total_time
            else:
                # 不启用 MEV：直接用 RPC 广播
                tx_hash = rpc_broadcast(raw_hex)
                rcpt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
                if rcpt and rcpt.status != 1:
                    print(f"RPC 广播失败，tx={tx_hash}")
                    return None, None
                total_time = time.time() - start_time
                return tx_hash, total_time
                
        except Exception as e:
            if attempt == 2:  # 最后一次尝试
                print(f"交易失败: {e}")
                return None, None
            
            print(f"广播失败，第 {attempt + 1} 次重试，提升 gas 费用: {e}")
            
            # 提升 gas 费用 20%
            max_fee_per_gas = int(base_max_fee * (1.2 ** (attempt + 1)))
            max_priority_fee_per_gas = int(base_priority_fee * (1.2 ** (attempt + 1)))
            
            # 重新构造交易
            try:
                nonce = get_safe_nonce(WALLET_ADDRESS)
                tx_dict = {
                    "chainId": CHAIN_ID,
                    "nonce": nonce,
                    "to": Web3.to_checksum_address(to_addr),
                    "from": Web3.to_checksum_address(from_addr),
                    "value": value_int,
                    "data": data_hex,
                    "gas": int(gas_limit),
                    "maxFeePerGas": int(max_fee_per_gas),
                    "maxPriorityFeePerGas": int(max_priority_fee_per_gas),
                    "type": 2,
                }
                signed = w3.eth.account.sign_transaction(tx_dict, PRIVATE_KEY)
                raw_hex = signed.raw_transaction.hex()
                print(f"重新构造交易，提升 gas 费用: max_fee={max_fee_per_gas}, priority_fee={max_priority_fee_per_gas}")
            except Exception as recreate_error:
                print(f"重新构造交易失败: {recreate_error}")
                return None, None
            
            time.sleep(2)  # 等待2秒后重试
    
    return None, None

# =========================
# 主程序
# =========================
a=5
if a==1:
    print("=" * 60)
    print("OKX SWAP BOT - 增强版")
    print("=" * 60)
    
    # =========================
    # 方式1: 直接在这里修改参数
    # =========================
    
    # 输入代币地址 (输入 'ETH' 使用原生 ETH，或输入具体的代币地址)
    token_in = "ETH"  # 修改这里：输入代币地址或 'ETH'
    
    # 输出代币地址
    token_out = cs("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")  # 修改这里：输出代币地址 (USDC)
    
    # 交易数量 (ETH)
    amount_eth = 0.00001  # 修改这里：交易数量
    
    # 滑点百分比
    slippage = 0.5  # 修改这里：滑点百分比
    
    # 是否启用 MEV 保护
    enable_mev = False  # 修改这里：True=启用，False=禁用
    
    # =========================
    # 方式2: 使用配置文件 (取消注释下面的代码)
    # =========================
    
    # try:
    #     from trade_config import get_trade_config
    #     config = get_trade_config()
    #     token_in = config["token_in"]
    #     token_out = config["token_out"]
    #     amount_eth = config["amount_eth"]
    #     slippage = config["slippage"]
    #     enable_mev = config["enable_mev"]
    #     print("✅ 已加载配置文件")
    # except ImportError:
    #     print("⚠️  未找到配置文件，使用默认参数")
    
    # =========================
    # 参数处理
    # =========================
    
    # 处理输入代币地址
    if token_in.upper() == 'ETH':
        token_in = NATIVE_ETH
    elif not Web3.is_address(token_in):
        raise ValueError("输入代币地址格式错误")
    
    # 验证输出代币地址
    if not Web3.is_address(token_out):
        raise ValueError("输出代币地址格式错误")
    
    # =========================
    # 显示交易参数
    # =========================
    
    print("\n" + "=" * 60)
    print("交易参数确认:")
    print(f"输入代币(token_in): {token_in}")
    print(f"输出代币(token_out): {token_out}")
    print(f"数量(token_in): {amount_eth}")
    print(f"滑点: {slippage}%")
    print(f"MEV 保护: {'启用' if enable_mev else '禁用'}")
    print("=" * 60)
    
    print("\n开始执行交易...")
    
    try:
        # 执行交易
        tx_hash, total_time = okx_swap_mev(
            token_in, 
            token_out, 
            amount_eth, 
            slippage, 
            enable_mev
        )
        
        if tx_hash and total_time is not None:
            print("\n" + "=" * 60)
            print("✅ 交易成功!")
            print("=" * 60)
            print(f"交易哈希: {tx_hash}")
            print(f"总用时: {total_time:.2f} 秒")
            print(f"区块浏览器: https://basescan.org/tx/{tx_hash}")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ 交易失败!")
            print("=" * 60)
            print("交易返回空值")
            print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 交易失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        print("=" * 60)
if a==2:
    try:
        # 执行交易
        tx_hash, total_time = okx_swap_mev(
        cs("0x0bc945e3Ea693ad1527683d9cfE999407EBAAbB0"),
        cs("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
        1, 
        0.5, 
        False,
        )
        
        print("\n" + "=" * 60)
        print("✅ 交易成功!")
        print("=" * 60)
        print(f"交易哈希: {tx_hash}")
        print(f"总用时: {total_time:.2f} 秒")
        print(f"区块浏览器: https://basescan.org/tx/{tx_hash}")
        print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 交易失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        print("=" * 60)
        
if a==3:
    try:
        # 执行交易
        tx_hash, total_time = okx_swap_mev(
        cs("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
        cs("0x0bc945e3Ea693ad1527683d9cfE999407EBAAbB0"),
        0.0001*10**-12, 
        0.08, 
        False,
        )
        
        print("\n" + "=" * 60)
        print("✅ 交易成功!")
        print("=" * 60)
        print(f"交易哈希: {tx_hash}")
        print(f"总用时: {total_time:.2f} 秒")
        print(f"区块浏览器: https://basescan.org/tx/{tx_hash}")
        print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 交易失败!")
        print("=" * 60)
        print(f"错误信息: {e}")
        print("=" * 60)