import requests
import json
from typing import Dict, List, Optional, Union
from datetime import datetime
import time # Added for retry mechanism
import sys  # for CLI token input
import os

class DebankTokenAPI:
    """Debank API 代币信息获取类"""
    
    def __init__(self, access_key: str):
        """
        初始化Debank API客户端
        
        Args:
            access_key: Debank API访问密钥
        """
        self.access_key = access_key
        self.base_url = "https://pro-openapi.debank.com/v1"
        self.headers = {
            'accept': 'application/json',
            'AccessKey': access_key
        }
    
    def get_token_info_by_ids(self, chain_id: str, token_ids: List[str]) -> Dict:
        """
        根据代币ID列表获取代币信息
        
        Args:
            chain_id: 链ID (如 'eth', 'bsc', 'polygon' 等)
            token_ids: 代币ID列表
            
        Returns:
            Dict: API响应数据
        """
        endpoint = f"{self.base_url}/token/list_by_ids"
        
        # 将代币ID列表转换为逗号分隔的字符串
        ids_param = ','.join(token_ids)
        
        params = {
            'chain_id': chain_id,
            'ids': ids_param
        }
        
        try:
            response = requests.get(endpoint, headers=self.headers, params=params)
            response.raise_for_status()  # 检查HTTP错误
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ API请求失败: {e}")
            return {"error": str(e)}
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {e}")
            return {"error": "Invalid JSON response"}
    
    def get_token_info(self, chain_id: str, token_address: str) -> Dict:
        """
        获取单个代币信息
        
        Args:
            chain_id: 链ID
            token_address: 代币合约地址
            
        Returns:
            Dict: 代币信息
        """
        result = self.get_token_info_by_ids(chain_id, [token_address])
        
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        elif "error" in result:
            return result
        else:
            return {"error": "Token not found"}
    def get_token_price(self, chain_id: str, token_address: str) -> Dict:
        """
        获取单个代币信息
        
        Args:
            chain_id: 链ID
            token_address: 代币合约地址
            
        Returns:
            Dict: 代币信息
        """
        result = self.get_token_info_by_ids(chain_id, [token_address])
        price = result[0]["price"]
        if price==None:
            return -1
        if isinstance(result, list) and len(result) > 0:
            return price
        elif "error" in result:
            return -1
        else:
            return -1
    def format_token_info(self, token_data: Dict) -> str:
        """
        格式化代币信息为可读字符串
        
        Args:
            token_data: 代币数据
            
        Returns:
            str: 格式化的代币信息
        """
        if "error" in token_data:
            return f"❌ 错误: {token_data['error']}"
        
        try:
            # 首先显示原始JSON数据
            json_lines = [
                "📄 原始JSON数据:",
                json.dumps(token_data, indent=2, ensure_ascii=False),
                "",
                "📋 格式化信息:"
            ]
            
            # 基本信息
            name = token_data.get('name', 'Unknown')
            symbol = token_data.get('symbol', 'Unknown')
            address = token_data.get('id', 'Unknown')
            decimals = token_data.get('decimals', 0)
            
            # 价格信息
            price = token_data.get('price', 0)
            price_24h_change = token_data.get('price_24h_change', 0)
            
            # 市值和流通量
            market_cap = token_data.get('market_cap', 0)
            total_supply = token_data.get('total_supply', 0)
            
            # 格式化输出
            info_lines = [
                f"🪙 代币信息",
                f"📝 名称: {name}",
                f"💎 符号: {symbol}",
                f"🔗 地址: {address}",
                f"🔢 小数位: {decimals}",
                f"💰 价格: ${price:.6f}" if price else "💰 价格: N/A",
            ]
            
            if price_24h_change is not None:
                change_emoji = "📈" if price_24h_change >= 0 else "📉"
                info_lines.append(f"{change_emoji} 24h变化: {price_24h_change:.2f}%")
            
            if market_cap:
                info_lines.append(f"💼 市值: ${market_cap:,.0f}")
            
            if total_supply:
                info_lines.append(f"📊 总供应量: {total_supply:,.0f}")
            
            # 合并JSON数据和格式化信息
            return "\n".join(json_lines + info_lines)
            
        except Exception as e:
            return f"❌ 格式化错误: {e}"
    
    def batch_get_token_info(self, chain_id: str, token_addresses: List[str]) -> List[Dict]:
        """
        批量获取代币信息
        
        Args:
            chain_id: 链ID
            token_addresses: 代币地址列表
            
        Returns:
            List[Dict]: 代币信息列表
        """
        # 分批处理，每批最多50个地址（API限制）
        batch_size = 50
        all_results = []
        
        for i in range(0, len(token_addresses), batch_size):
            batch = token_addresses[i:i + batch_size]
            result = self.get_token_info_by_ids(chain_id, batch)
            
            if isinstance(result, list):
                all_results.extend(result)
            elif "error" in result:
                print(f"❌ 批次 {i//batch_size + 1} 失败: {result['error']}")
        
        return all_results

    def get_token_top_holders(self, chain_id: str, token_id: str, limit: int = 10) -> Dict:
        """
        获取代币前N持有人信息
        
        Args:
            chain_id: 链ID (如 'eth', 'bsc', 'polygon' 等)
            token_id: 代币ID
            limit: 获取持有人数量 (默认10，最大100)
            
        Returns:
            Dict: API响应数据
        """
        # 限制最大值为100
        if limit > 100:
            limit = 100
            print(f"⚠️ 持有人数量限制为100，已自动调整为100")
        
        endpoint = f"{self.base_url}/token/top_holders"
        
        params = {
            'chain_id': chain_id,
            'id': token_id,
            'start': 0,  # 从第0个开始
            'limit': limit
        }
        
        try:
            response = requests.get(endpoint, headers=self.headers, params=params)
            response.raise_for_status()  # 检查HTTP错误
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ API请求失败: {e}")
            return {"error": str(e)}
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {e}")
            return {"error": "Invalid JSON response"}
    
    def format_top_holders(self, holders_data: List, token_symbol: str = "Unknown") -> str:
        """
        格式化持有人信息为可读字符串
        
        Args:
            holders_data: 持有人数据列表
            token_symbol: 代币符号
            
        Returns:
            str: 格式化的持有人信息
        """
        if isinstance(holders_data, dict) and "error" in holders_data:
            return f"❌ 错误: {holders_data['error']}"
        
        if not isinstance(holders_data, list):
            return "❌ 无效的持有人数据"
        
        try:
            result_lines = [
                f"🏆 {token_symbol} 前{len(holders_data)}持有人",
                "=" * 50
            ]
            
            for i, holder in enumerate(holders_data, 1):
                if isinstance(holder, list) and len(holder) >= 2:
                    address = holder[0]
                    amount = holder[1]
                    
                    # 格式化地址显示（显示前6位和后4位）
                    short_address = f"{address[:8]}...{address[-6:]}"
                    
                    # 格式化数量
                    if amount >= 1_000_000:
                        formatted_amount = f"{amount:,.2f}"
                    elif amount >= 1_000:
                        formatted_amount = f"{amount:,.3f}"
                    else:
                        formatted_amount = f"{amount:.6f}"
                    
                    result_lines.append(f"{i:2d}. {short_address}")
                    result_lines.append(f"     💰 持有量: {formatted_amount} {token_symbol}")
                    result_lines.append("")
                else:
                    result_lines.append(f"{i:2d}. ❌ 数据格式错误")
                    result_lines.append("")
            
            return "\n".join(result_lines)
            
        except Exception as e:
            return f"❌ 格式化错误: {e}"
    
    def get_token_info_with_holders(self, chain_id: str, token_address: str, holders_limit: int = 10) -> str:
        """
        获取代币信息并包含持有人信息
        
        Args:
            chain_id: 链ID
            token_address: 代币合约地址
            holders_limit: 持有人数量限制 (默认10，最大100)
            
        Returns:
            str: 完整的代币信息（包含持有人）
        """
        # 获取代币基本信息
        token_info = self.get_token_info(chain_id, token_address)
        
        if "error" in token_info:
            return f"❌ 获取代币信息失败: {token_info['error']}"
        
        # 格式化代币基本信息
        basic_info = self.format_token_info(token_info)
        
        # 获取持有人信息
        holders_data = self.get_token_top_holders(chain_id, token_address, holders_limit)
        symbol = token_info.get('symbol', 'Unknown')
        holders_info = self.format_top_holders(holders_data, symbol)
        
        # 组合信息
        result_lines = [
            "🪙 代币详细信息",
            "=" * 60,
            basic_info,
            "",
            "🏆 持有人信息",
            "=" * 60,
            holders_info
        ]
        
        return "\n".join(result_lines)

    def get_user_chain_balance(self, user_id: str, chain_id: str = 'eth') -> Dict:
        """
        获取用户在指定链上的钱包余额信息
        
        Args:
            user_id: 用户地址
            chain_id: 链ID (如 'eth', 'bsc', 'polygon' 等)
            
        Returns:
            Dict: API响应数据
        """
        endpoint = f"{self.base_url}/user/chain_balance"
        
        params = {
            'id': user_id,
            'chain_id': chain_id
        }
        
        # 添加重试机制
        max_retries = 3
        retry_delay = 2  # 秒
        
        for attempt in range(max_retries):
            try:
                response = requests.get(endpoint, headers=self.headers, params=params, timeout=30)
                
                # 检查HTTP状态码
                if response.status_code == 500:
                    print(f"⚠️ 服务器错误 (500) - 地址: {user_id[:10]}...{user_id[-6:]}")
                    if attempt < max_retries - 1:
                        print(f"🔄 重试 {attempt + 1}/{max_retries}...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        return {"error": f"服务器错误 (500) - 地址可能无效或服务器暂时不可用"}
                
                response.raise_for_status()  # 检查其他HTTP错误
                return response.json()
                
            except requests.exceptions.Timeout:
                print(f"⏰ 请求超时 - 地址: {user_id[:10]}...{user_id[-6:]}")
                if attempt < max_retries - 1:
                    print(f"🔄 重试 {attempt + 1}/{max_retries}...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return {"error": "请求超时"}
                    
            except requests.exceptions.RequestException as e:
                print(f"❌ API请求失败: {e}")
                if attempt < max_retries - 1:
                    print(f"🔄 重试 {attempt + 1}/{max_retries}...")
                    time.sleep(retry_delay)
                    continue
                else:
                    return {"error": str(e)}
                    
            except json.JSONDecodeError as e:
                print(f"❌ JSON解析失败: {e}")
                return {"error": "Invalid JSON response"}
        
        return {"error": "所有重试都失败了"}
    
    def format_user_balance(self, balance_data: Dict, user_address: str, chain_id: str = 'eth') -> str:
        """
        格式化用户余额信息为可读字符串
        
        Args:
            balance_data: 余额数据
            user_address: 用户地址
            chain_id: 链ID
            
        Returns:
            str: 格式化的余额信息
        """
        if isinstance(balance_data, dict) and "error" in balance_data:
            return f"❌ 错误: {balance_data['error']}"
        
        try:
            # 首先显示原始JSON数据
            json_lines = [
                "📄 原始JSON数据:",
                json.dumps(balance_data, indent=2, ensure_ascii=False),
                "",
                "📋 格式化信息:"
            ]
            
            # 基本信息
            result_lines = [
                f"💰 钱包余额信息",
                f"👤 地址: {user_address}",
                f"🌐 链: {chain_id.upper()}",
                "=" * 50
            ]
            
            # 解析余额数据
            if isinstance(balance_data, dict):
                # 总资产价值 - 检查不同的可能字段名
                total_usd_value = (
                    balance_data.get('total_usd_value') or 
                    balance_data.get('usd_value') or 
                    0
                )
                
                if total_usd_value:
                    result_lines.append(f"💵 总资产价值: ${total_usd_value:,.2f}")
                
                # 代币列表
                token_list = balance_data.get('token_list', [])
                if token_list:
                    result_lines.append(f"🪙 代币数量: {len(token_list)}")
                    result_lines.append("")
                    
                    # 显示前10个代币
                    for i, token in enumerate(token_list[:10], 1):
                        symbol = token.get('symbol', 'Unknown')
                        amount = token.get('amount', 0)
                        usd_value = token.get('usd_value', 0)
                        price = token.get('price', 0)
                        
                        result_lines.append(f"{i:2d}. {symbol}")
                        if amount:
                            result_lines.append(f"     💰 数量: {amount:,.6f}")
                        if usd_value:
                            result_lines.append(f"     💵 价值: ${usd_value:,.2f}")
                        if price:
                            result_lines.append(f"     📈 价格: ${price:.6f}")
                        result_lines.append("")
                    
                    if len(token_list) > 10:
                        result_lines.append(f"... 还有 {len(token_list) - 10} 个代币")
                else:
                    # 如果没有token_list，但有钱包总价值，说明这是一个简化的余额信息
                    if total_usd_value:
                        result_lines.append(f"💵 钱包总价值: ${total_usd_value:,.2f}")
                    else:
                        result_lines.append("📭 该地址在此链上无代币余额")
            
            # 合并JSON数据和格式化信息
            return "\n".join(json_lines + result_lines)
            
        except Exception as e:
            return f"❌ 格式化错误: {e}"
    
    def get_holders_with_balance(self, chain_id: str, token_id: str, limit: int = 10) -> str:
        """
        获取代币持有人信息并查询每个持有人的钱包余额
        
        Args:
            chain_id: 链ID
            token_id: 代币ID
            limit: 持有人数量限制 (默认10，最大100)
            
        Returns:
            str: 持有人信息和余额信息
        """
        # 获取持有人信息
        holders_data = self.get_token_top_holders(chain_id, token_id, limit)
        
        if isinstance(holders_data, dict) and "error" in holders_data:
            return f"❌ 获取持有人信息失败: {holders_data['error']}"
        
        if not isinstance(holders_data, list):
            return "❌ 无效的持有人数据"
        
        try:
            result_lines = [
                f"🏆 代币持有人信息及余额查询",
                f"🌐 链: {chain_id.upper()}",
                f"🪙 代币: {token_id}",
                f"👥 持有人数量: {len(holders_data)}",
                "=" * 60
            ]
            
            successful_queries = 0
            failed_queries = 0
            
            for i, holder in enumerate(holders_data, 1):
                if isinstance(holder, list) and len(holder) >= 2:
                    address = holder[0]
                    amount = holder[1]
                    
                    result_lines.append(f"\n--- 持有人 {i}: {address} ---")
                    result_lines.append(f"💰 持有代币数量: {amount:,.6f}")
                    
                    # 查询该地址的余额信息
                    print(f"🔍 正在查询地址 {address[:10]}...{address[-6:]} 的余额信息...")
                    balance_data = self.get_user_chain_balance(address, chain_id)
                    
                    if isinstance(balance_data, dict) and "error" not in balance_data:
                        # 显示余额信息
                        balance_info = self.format_user_balance(balance_data, address, chain_id)
                        result_lines.append(balance_info)
                        successful_queries += 1
                    else:
                        error_msg = balance_data.get('error', 'Unknown error')
                        result_lines.append(f"❌ 获取余额信息失败: {error_msg}")
                        failed_queries += 1
                    
                    result_lines.append("-" * 40)
                else:
                    result_lines.append(f"{i:2d}. ❌ 数据格式错误")
                    failed_queries += 1
            
            # 添加统计信息
            result_lines.append(f"\n📊 查询统计:")
            result_lines.append(f"✅ 成功查询: {successful_queries} 个地址")
            result_lines.append(f"❌ 查询失败: {failed_queries} 个地址")
            result_lines.append(f"📈 成功率: {successful_queries/(successful_queries+failed_queries)*100:.1f}%" if (successful_queries+failed_queries) > 0 else "📈 成功率: 0%")
            
            return "\n".join(result_lines)
            
        except Exception as e:
            return f"❌ 处理错误: {e}"

    def _format_age_from_timestamp(self, time_at: Optional[int]) -> Optional[str]:
        """根据时间戳格式化与当前的相对时间。
        规则:
        - 大于3天: 仅用天
        - 大于0.5天(12小时)且不超过3天: 仅用天和小时（包括0天X小时）
        - 否则: 用小时和分钟
        """
        try:
            if not time_at or time_at <= 0:
                return None
            now = int(time.time())
            delta = max(0, now - int(time_at))
            days = delta // 86400
            hours = (delta % 86400) // 3600
            minutes = (delta % 3600) // 60
            if delta > 3 * 86400:
                return f"{days}天"
            if delta > 12 * 3600:
                # 始终返回天和小时，包括 0天X小时
                return f"{days}天{hours}小时"
            return f"{hours}小时{minutes}分钟"
        except Exception:
            return None

    def _etherscan_chainid_from_chain(self, chain_id: str) -> Optional[int]:
        """将常用链ID映射到Etherscan v2所需的chainid参数。"""
        chain_id_lower = (chain_id or "").lower()
        if chain_id_lower in ("eth", "ethereum", "1"):
            return 1
        if chain_id_lower in ("base", "8453"):
            return 8453
        return None

    def get_total_supply_via_etherscan(self, chain_id: str, contract_address: str, api_key: str) -> Optional[int]:
        """
        通过Etherscan v2 API查询代币总量（原始单位，未按decimals归一）。
        返回整数（可能很大），失败返回None。
        """
        chainid = self._etherscan_chainid_from_chain(chain_id)
        if chainid is None:
            return None
        endpoint = "https://api.etherscan.io/v2/api"
        params = {
            "chainid": chainid,
            "module": "stats",
            "action": "tokensupply",
            "contractaddress": contract_address,
            "apikey": api_key,
        }
        try:
            resp = requests.get(endpoint, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            # 期望 { status: "1", message: "OK", result: "12345..." }
            result = data.get("result")
            if result is None:
                return None
            # result有时是字符串数字
            return int(result)
        except Exception:
            return None

    def get_token_snapshot(self, chain_id: str, token_address: str, holders_limit: int = 10, etherscan_api_key: Optional[str] = None) -> Dict:
        """
        获取代币的概览数据结构:
        - 代币基本信息(地址/名称/符号/创建时间及相对时间/价格)
        - 前N(默认10)持有人地址与持仓数量
        - 这些地址的钱包USD余额
        - Etherscan总量与前N持有占比（保留一位小数）
        - 汇总前N持仓总量与钱包USD 总值
        返回: Dict
        """
        # 1) 基本信息
        token_info = self.get_token_info(chain_id, token_address)
        if isinstance(token_info, dict) and token_info.get("error"):
            return {"error": token_info.get("error", "failed to fetch token info")}

        address = token_info.get("id", token_address)
        name = token_info.get("name")
        symbol = token_info.get("symbol")
        time_at = token_info.get("time_at")
        price = token_info.get("price")
        decimals = token_info.get("decimals", 0) or 0
        age = self._format_age_from_timestamp(time_at)

        result: Dict[str, Union[str, int, float, List, Dict]] = {
            "chain_id": chain_id,
            "token_id": address,
            "token": {
                "address": address,
                "name": name,
                "symbol": symbol,
                "time_at": time_at,
                "age": age,
                "price": price,
                "decimals": decimals,
            },
            "holders_limit": min(max(holders_limit, 1), 100),
            "holders": [],
            "wallets": [],
            "supply": {
                "total_supply_raw": None,
                "total_supply": None,
            },
            "totals": {
                "top_holders_token_amount": 0.0,
                "top_wallets_usd_value": 0.0,
                "top_holders_ratio_percent_sum": None,
            },
            "meta": {
                "generated_at": datetime.utcnow().isoformat() + "Z",
            },
        }

        # 2) 前N持有人
        holders_raw = self.get_token_top_holders(chain_id, address, result["holders_limit"])  # type: ignore[index]
        if isinstance(holders_raw, dict) and holders_raw.get("error"):
            result["errors"] = [f"holders_error: {holders_raw.get('error')}"]
            return result

        holders_list: List[Dict[str, Union[int, str, float]]] = []
        total_amount = 0.0
        if isinstance(holders_raw, list):
            for idx, item in enumerate(holders_raw[: result["holders_limit"]], start=1):  # type: ignore[index]
                if isinstance(item, list) and len(item) >= 2:
                    holder_address = item[0]
                    holder_amount = float(item[1]) if item[1] is not None else 0.0
                    holders_list.append({
                        "rank": idx,
                        "address": holder_address,
                        "amount": holder_amount,
                    })
                    total_amount += holder_amount
        result["holders"] = holders_list
        result["totals"]["top_holders_token_amount"] = total_amount

        # 3) 代币总量（Etherscan）
        total_supply_raw: Optional[int] = None
        total_supply_norm: Optional[float] = None
        if etherscan_api_key:
            total_supply_raw = self.get_total_supply_via_etherscan(chain_id, address, etherscan_api_key)
            if total_supply_raw is not None:
                if decimals and decimals > 0:
                    try:
                        total_supply_norm = float(total_supply_raw) / float(10 ** int(decimals))
                    except Exception:
                        total_supply_norm = None
                else:
                    total_supply_norm = float(total_supply_raw)
        result["supply"]["total_supply_raw"] = str(total_supply_raw) if total_supply_raw is not None else None
        result["supply"]["total_supply"] = total_supply_norm

        # 4) 持有人钱包USD余额
        wallets: List[Dict[str, Union[int, str, float]]] = []
        total_usd = 0.0
        errors: List[str] = []
        for h in holders_list:
            addr = h["address"]  # type: ignore[index]
            balance_data = self.get_user_chain_balance(addr, chain_id)
            if isinstance(balance_data, dict) and "error" in balance_data:
                errors.append(f"wallet_error:{addr}:{balance_data['error']}")
                continue
            usd_value = 0.0
            try:
                usd_value = float(balance_data.get("total_usd_value") or balance_data.get("usd_value") or 0.0)  # type: ignore[attr-defined]
            except Exception:
                usd_value = 0.0
            wallets.append({
                "rank": h["rank"],  # type: ignore[index]
                "address": addr,
                "usd_value": usd_value,
            })
            total_usd += usd_value
        result["wallets"] = wallets
        result["totals"]["top_wallets_usd_value"] = total_usd
        if errors:
            result.setdefault("errors", []).extend(errors)

        # 5) 计算前N地址的代币持有比例（基于Etherscan总量），保留1位小数
        if total_supply_norm and total_supply_norm > 0:
            # 为每个holder添加 ratio_percent（相对总量）
            sum_amounts = 0.0
            for h in result["holders"]:  # type: ignore[index]
                amt = float(h["amount"])  # type: ignore[index]
                sum_amounts += amt
                ratio = amt / total_supply_norm * 100.0
                h["ratio_percent"] = round(ratio, 1)  # type: ignore[index]
            # 总比例（用总和计算后四舍五入，避免逐个取整的累计误差）
            result["totals"]["top_holders_ratio_percent_sum"] = round(sum_amounts / total_supply_norm * 100.0, 1)
        else:
            result["totals"]["top_holders_ratio_percent_sum"] = None
            sum_amounts = sum(float(h["amount"]) for h in result["holders"])  # type: ignore[index]
        
        # 6) 为每个holder增加相对前10合计的比例 top10_ratio_percent（总量不可用时依旧可算）
        if sum_amounts > 0:
            for h in result["holders"]:  # type: ignore[index]
                amt = float(h["amount"])  # type: ignore[index]
                h["top10_ratio_percent"] = round(amt / sum_amounts * 100.0, 1)  # type: ignore[index]
        
        return result

def format_telegram_message(snapshot_data: Dict) -> str:
    """
    将代币快照数据格式化为电报机器人消息样式
    Args:
        snapshot_data: get_token_snapshot 返回的数据
    Returns:
        str: 格式化的电报消息
    """
    if not snapshot_data:
        return "❌ 无法获取代币信息"
    
    # 提取基本信息
    token_info = snapshot_data.get("token", {})
    holders = snapshot_data.get("holders", [])
    wallets = snapshot_data.get("wallets", [])
    totals = snapshot_data.get("totals", {})
    supply = snapshot_data.get("supply", {})
    
    # 1. 代币地址
    contract_address = token_info.get("address", "N/A")
    
    # 2. 代币名称符号
    token_name = token_info.get("name", "N/A")
    token_symbol = token_info.get("symbol", "N/A")
    
    # 3. 代币age
    token_age = token_info.get("age", "N/A")
    
    # 4. 代币价格
    token_price = token_info.get("price", "N/A")
    price_str = f"💰 价格: ${token_price}" if token_price and token_price != "N/A" else "💰 价格: 暂无数据"
    
    # 5. 前10持有者信息
    holders_text = "🏆 前10持有者:\n"
    if holders:
        for i, holder in enumerate(holders[:10], 1):
            address = holder.get("address", "N/A")
            ratio_percent = holder.get("ratio_percent", "N/A")
            
            # 获取钱包价值 - wallets是列表，需要按地址查找
            wallet_value = "N/A"
            for wallet in wallets:
                if wallet.get("address") == address:
                    wallet_value = wallet.get("usd_value", "N/A")
                    break
            
            # 格式化钱包价值显示
            if isinstance(wallet_value, (int, float)):
                if wallet_value >= 10000:
                    wallet_str = f"{wallet_value/10000:.1f}w"
                else:
                    wallet_str = f"${wallet_value:,.0f}"
            else:
                wallet_str = str(wallet_value)
            
            # 格式化地址显示（只显示后4位）
            short_addr = address[-4:] if len(address) == 42 else address
            
            # 创建Debank超链接（只显示地址后4位作为链接文本）
            debank_url = f"https://debank.com/profile/{address}"
            
            holders_text += f"{i}.{short_addr}(<a href='{debank_url}'>{short_addr}</a>)   {ratio_percent}%   钱包价值 {wallet_str}\n"
    else:
        holders_text += "暂无持有者数据\n\n"
    
    # 6. 前10持有者总比例和平均钱包价值
    total_ratio = totals.get("top_holders_ratio_percent_sum", "N/A")
    total_wallet_value = totals.get("top_wallets_usd_value", "N/A")
    
    # 计算平均钱包价值
    valid_wallets = [w for w in wallets if isinstance(w.get("usd_value"), (int, float))]
    avg_wallet_value = sum(w["usd_value"] for w in valid_wallets) / len(valid_wallets) if valid_wallets else "N/A"
    avg_str = f"${avg_wallet_value:,.2f}" if isinstance(avg_wallet_value, (int, float)) else str(avg_wallet_value)
    
    summary_text = f"📊 汇总统计:\n"
    summary_text += f"前10总占比: {total_ratio}%\n"
    summary_text += f"前10总钱包价值: ${total_wallet_value:,.2f}\n"
    summary_text += f"平均钱包价值: {avg_str}\n\n"
    
    # 7. DexScreener链接
    dexscreener_url = f"https://dexscreener.com/base/{contract_address}"
    
    # 组装完整消息
    message = f"🔍 代币信息\n\n"
    message += f"📍 合约地址: {contract_address}\n"
    message += f"🪙 代币: {token_name} ({token_symbol})\n"
    message += f"⏰ 创建时间: {token_age}\n"
    message += f"{price_str}\n\n"
    message += f"{holders_text}"
    message += f"{summary_text}"
    message += f"🔗 DexScreener: {dexscreener_url}"
    
    return message
ACCESS_KEY = os.getenv("DEBANK_ACCESS_KEY", "")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
a=3
if a==1:
    """仅测试 get_token_snapshot。使用: python debank_token_info.py [token_address]"""
    # 请替换为您的实际AccessKey

    
    debank_api = DebankTokenAPI(ACCESS_KEY)
    chain_id = "base"
    token = sys.argv[1] if len(sys.argv) > 1 else "0x774eaF7A53471628768dc679dA945847d34b9a55"
    holders_limit = 10

    print("🧪 获取代币快照 (get_token_snapshot)")
    print("=" * 60)
    print(f"链: {chain_id}")
    print(f"代币: {token}")
    print(f"前{holders_limit}持有人")
    print("-" * 60)

    snapshot = debank_api.get_token_snapshot(chain_id, token, holders_limit, etherscan_api_key=ETHERSCAN_API_KEY)
    
    # 输出原始JSON
    print("\n📄 原始JSON数据:")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    
    # 输出电报消息格式
    print("\n" + "=" * 60)
    print("📱 电报消息格式:")
    print("=" * 60)
    telegram_msg = format_telegram_message(snapshot)
    print(telegram_msg)

if a==2:
    debank_api = DebankTokenAPI(ACCESS_KEY)
    aa=debank_api.get_token_price("base","0x599323ddE62723a736e0Ba00c578070643f2bb07")
    print(aa)