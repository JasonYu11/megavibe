from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from typing import Any

import requests
from eth_utils import to_checksum_address

from app.core.order_info import MarketOrder
from app.core.order_state import OrderStatus
from app.risk.risk_engine import RiskEngine
from app.storage.sqlite_store import SQLiteStore


@dataclass(frozen=True)
class OrderServiceResult:
    order_id: str
    status: str
    quote: dict[str, Any] | None
    risk_decision: str
    reason: str = ""
    tracking_id: str | None = None


@dataclass
class OrderService:
    store: SQLiteStore
    risk_engine: RiskEngine
    quote_client: Any
    execution_mode: str = "dry_run"
    execution_client: Any | None = None
    signer: Any | None = None
    risk_context_provider: Any | None = None
    balance_provider: Any | None = None
    live_enabled: bool = False
    rpc_url: str | None = None
    gas_limit_multiplier: Decimal = Decimal("1.5")
    min_swap_gas_limit: int = 3_000_000
    max_swap_gas_limit: int = 5_000_000
    min_approve_gas_limit: int = 300_000
    approve_receipt_timeout_seconds: int = 90

    def submit_market_order(self, order: MarketOrder) -> OrderServiceResult:
        self._validate_live_token_metadata(order)
        order, balance_adjustment = self._clamp_order_to_available_balance(order)
        self.store.create_order(order)
        if balance_adjustment:
            self.store.insert_event(
                order.id,
                "order_amount_clamped_to_balance",
                balance_adjustment,
            )
        amount_base_units = order.amount.to_base_units(order.token_in.decimals)
        quote = self.quote_client.quote(
            chain_id=order.chain.chain_id,
            from_token_address=order.token_in.address,
            to_token_address=order.token_out.address,
            amount_base_units=amount_base_units,
            slippage_percent=str(order.safety.max_slippage_percent),
        )
        self.store.insert_quote(order.id, quote)
        self.store.update_order_status(order.id, OrderStatus.QUOTED)
        quote_unavailable = self._quote_unavailable_reason(quote)
        if quote_unavailable:
            self.store.update_order_status(order.id, OrderStatus.FAILED, {"reason": quote_unavailable})
            return OrderServiceResult(order.id, OrderStatus.FAILED.value, quote, "REJECTED", quote_unavailable)

        risk = self.risk_engine.evaluate(order, quote, self._risk_context(order))
        self.store.insert_risk_decision(order.id, risk.decision, risk.reason, {"requires_confirmation": risk.requires_confirmation})
        if not risk.approved:
            self.store.update_order_status(order.id, OrderStatus.FAILED, {"reason": risk.reason})
            return OrderServiceResult(order.id, OrderStatus.FAILED.value, quote, risk.decision, risk.reason)

        self.store.update_order_status(order.id, OrderStatus.RISK_CHECKED)

        if risk.requires_confirmation:
            self.store.update_order_status(order.id, OrderStatus.PENDING_CONFIRMATION)
            return OrderServiceResult(order.id, OrderStatus.PENDING_CONFIRMATION.value, quote, risk.decision)

        if self.execution_mode == "dry_run":
            self.store.update_order_status(order.id, OrderStatus.DRY_RUN_COMPLETED)
            return OrderServiceResult(order.id, OrderStatus.DRY_RUN_COMPLETED.value, quote, risk.decision)

        raise NotImplementedError("sign_only and live execution are handled after explicit approval")

    def _risk_context(self, order: MarketOrder) -> dict[str, Any]:
        if self.risk_context_provider is None:
            return {}
        if callable(self.risk_context_provider):
            return dict(self.risk_context_provider(order))
        if hasattr(self.risk_context_provider, "get_context"):
            return dict(self.risk_context_provider.get_context(order))
        raise TypeError("risk_context_provider must be callable or expose get_context(order)")

    def _validate_live_token_metadata(self, order: MarketOrder) -> None:
        if self.execution_mode != "live":
            return
        unresolved = [
            token.address
            for token in (order.token_in, order.token_out)
            if token.symbol == token.address and token.decimals == 18
        ]
        if unresolved:
            raise ValueError(f"live token metadata unresolved: {', '.join(unresolved)}")

    def _clamp_order_to_available_balance(self, order: MarketOrder) -> tuple[MarketOrder, dict[str, Any] | None]:
        balance = self._token_balance(order.token_in)
        if balance is None:
            return order, None
        normalized_balance = self._normalize_token_amount(order.token_in.decimals, balance)
        if normalized_balance <= 0:
            raise ValueError(f"insufficient_balance: {order.token_in.symbol} balance is zero")
        if normalized_balance >= order.amount.value:
            return order, None
        adjusted = replace(order, amount=replace(order.amount, value=normalized_balance))
        return adjusted, {
            "token": {
                "symbol": order.token_in.symbol,
                "address": order.token_in.address,
                "decimals": order.token_in.decimals,
            },
            "requested_amount": str(order.amount.value),
            "available_amount": str(normalized_balance),
            "adjusted_amount": str(adjusted.amount.value),
        }

    def _token_balance(self, token: Any) -> Decimal | None:
        provider = self.balance_provider
        if provider is None:
            return None
        if callable(provider):
            return self._optional_decimal(provider(token))
        if hasattr(provider, "get_token_balance"):
            return self._optional_decimal(provider.get_token_balance(token))
        if hasattr(provider, "get_balance"):
            return self._balance_from_summary(provider.get_balance(), token)
        return None

    @classmethod
    def _balance_from_summary(cls, balance: dict[str, Any], token: Any) -> Decimal | None:
        tokens = []
        for key in ("tokens", "key_tokens"):
            value = balance.get(key)
            if isinstance(value, list):
                tokens.extend(item for item in value if isinstance(item, dict))
        for item in tokens:
            address = str(item.get("id") or item.get("address") or "").lower()
            symbol = str(item.get("symbol") or "").upper()
            if address == token.address.lower() or symbol == token.symbol.upper():
                return cls._optional_decimal(item.get("amount"))
        return None

    @staticmethod
    def _optional_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            decimal = Decimal(str(value))
        except Exception:
            return None
        return decimal if decimal.is_finite() else None

    @staticmethod
    def _normalize_token_amount(decimals: int, amount: Decimal) -> Decimal:
        if amount <= 0:
            return Decimal("0")
        step = Decimal(1) / (Decimal(10) ** decimals)
        return amount.quantize(step, rounding=ROUND_DOWN)

    def confirm_order(self, order_id: str, actor: str = "system") -> OrderServiceResult:
        row = self.store.get_order(order_id)
        if row is None:
            raise KeyError(f"unknown order_id: {order_id}")
        if row["status"] != OrderStatus.PENDING_CONFIRMATION.value:
            raise ValueError(f"order is not pending confirmation: {row['status']}")

        self.store.insert_approval(order_id, "CONFIRMED", actor)
        order = MarketOrder.from_dict(json.loads(row["payload_json"]))

        if self.execution_mode == "dry_run":
            self.store.update_order_status(order_id, OrderStatus.DRY_RUN_COMPLETED, {"confirmed_by": actor})
            self.store.insert_execution(order_id, OrderStatus.DRY_RUN_COMPLETED.value, None, {"mode": "dry_run"})
            return OrderServiceResult(order_id, OrderStatus.DRY_RUN_COMPLETED.value, None, "APPROVED")

        if self.execution_mode not in {"sign_only", "live"}:
            raise ValueError(f"unsupported execution_mode: {self.execution_mode}")
        if self.execution_client is None:
            raise RuntimeError("execution_client is required for sign_only/live")
        if self.signer is None:
            raise RuntimeError("signer is required for sign_only/live")
        if not order.wallet.address:
            raise RuntimeError("wallet.address is required for sign_only/live")
        if self.execution_mode == "live" and not self.live_enabled:
            raise RuntimeError("live execution is disabled; set live_enabled=True explicitly")

        self.store.update_order_status(order_id, OrderStatus.SIGNING)
        try:
            unsigned_tx = self._build_swap_tx(order)
            signed = self.signer.sign_transaction(order.wallet.wallet_id, unsigned_tx)

            if self.execution_mode == "sign_only":
                self.store.update_order_status(order_id, OrderStatus.SIGNED_NOT_BROADCASTED)
                self.store.insert_execution(
                    order_id,
                    OrderStatus.SIGNED_NOT_BROADCASTED.value,
                    signed.transaction_hash,
                    {"mode": "sign_only", "signer_address": signed.signer_address},
                )
                return OrderServiceResult(
                    order_id,
                    OrderStatus.SIGNED_NOT_BROADCASTED.value,
                    None,
                    "APPROVED",
                    tracking_id=signed.transaction_hash,
                )

            broadcast = self.execution_client.broadcast(
                chain_id=order.chain.chain_id,
                signed_tx=signed.raw_transaction_hex,
                address=order.wallet.address,
                enable_mev_protection=True,
            )
            tx_hash = self._extract_tx_hash_or_order_id(broadcast)
            if not tx_hash:
                raise RuntimeError("broadcast response does not contain tx hash or order id")
            self.store.update_order_status(order_id, OrderStatus.BROADCASTED)
            self.store.insert_execution(order_id, OrderStatus.BROADCASTED.value, tx_hash, {"mode": "live", "broadcast": broadcast})
            return OrderServiceResult(order_id, OrderStatus.BROADCASTED.value, None, "APPROVED", tracking_id=tx_hash)
        except Exception as exc:
            self._record_execution_failure(order_id, self.execution_mode, exc)
            raise

    def reject_order(self, order_id: str, actor: str = "system") -> OrderServiceResult:
        row = self.store.get_order(order_id)
        if row is None:
            raise KeyError(f"unknown order_id: {order_id}")
        if row["status"] != OrderStatus.PENDING_CONFIRMATION.value:
            raise ValueError(f"order is not pending confirmation: {row['status']}")
        self.store.insert_approval(order_id, "REJECTED", actor)
        self.store.update_order_status(order_id, OrderStatus.REJECTED_BY_USER, {"rejected_by": actor})
        return OrderServiceResult(order_id, OrderStatus.REJECTED_BY_USER.value, None, "REJECTED_BY_USER")

    def _record_execution_failure(self, order_id: str, mode: str, exc: Exception) -> None:
        payload = {"mode": mode, "reason": str(exc), "error_type": exc.__class__.__name__}
        self.store.update_order_status(order_id, OrderStatus.FAILED, payload)
        self.store.insert_execution(order_id, OrderStatus.FAILED.value, None, payload)

    def _build_swap_tx(self, order: MarketOrder) -> dict[str, Any]:
        amount_base_units = order.amount.to_base_units(order.token_in.decimals)
        swap = self.execution_client.swap(
            chain_id=order.chain.chain_id,
            from_token_address=order.token_in.address,
            to_token_address=order.token_out.address,
            amount_base_units=amount_base_units,
            slippage_percent=str(order.safety.max_slippage_percent),
            user_wallet_address=order.wallet.address,
        )
        tx = self._extract_tx(swap)
        next_nonce = self._ensure_live_erc20_allowance(order, swap, tx, amount_base_units)
        tx.setdefault("chainId", order.chain.chain_id)
        if "from" in tx:
            tx.pop("from")
        signable_tx = self._filter_signable_tx_fields(tx)
        normalized = {k: self._normalize_tx_value(k, v) for k, v in signable_tx.items()}
        if "to" in normalized:
            normalized["to"] = self._checksum_address(normalized["to"])
        normalized = self._apply_gas_limit_buffer(normalized)
        self._validate_unsigned_tx(normalized, expected_chain_id=order.chain.chain_id, require_nonce=False)
        if next_nonce is not None:
            normalized["nonce"] = next_nonce
        elif "nonce" not in normalized:
            normalized["nonce"] = self._fetch_pending_nonce(order.wallet.address)
        self._validate_unsigned_tx(normalized, expected_chain_id=order.chain.chain_id)
        return normalized

    def _ensure_live_erc20_allowance(
        self,
        order: MarketOrder,
        swap_response: dict[str, Any],
        swap_tx: dict[str, Any],
        amount_base_units: int,
    ) -> int | None:
        if self.execution_mode != "live" or self._is_native_token(order.token_in.address):
            return None
        if not self.rpc_url:
            return None
        approve_response = self.execution_client.approve_transaction(
            chain_id=order.chain.chain_id,
            token_address=order.token_in.address,
            approve_amount=amount_base_units,
        )
        approve_item = self._first_response_item(approve_response)
        spender = str(
            approve_item.get("dexContractAddress")
            or self._first_response_item(swap_response).get("spender")
            or swap_tx.get("to")
            or ""
        )
        if not self._is_evm_address(spender):
            raise RuntimeError("approve spender is missing or invalid")
        current_allowance = self._fetch_erc20_allowance(order.token_in.address, order.wallet.address, spender)
        if current_allowance >= amount_base_units:
            return None

        approve_nonce = self._fetch_pending_nonce(order.wallet.address)
        approve_tx = self._build_approve_tx(
            chain_id=order.chain.chain_id,
            token_address=order.token_in.address,
            approve_item=approve_item,
            swap_tx=swap_tx,
            nonce=approve_nonce,
        )
        signed = self.signer.sign_transaction(order.wallet.wallet_id, approve_tx)
        broadcast = self.execution_client.broadcast(
            chain_id=order.chain.chain_id,
            signed_tx=signed.raw_transaction_hex,
            address=order.wallet.address,
            enable_mev_protection=False,
        )
        tracking_id = self._extract_tx_hash_or_order_id(broadcast) or signed.transaction_hash
        receipt = self._wait_for_rpc_receipt(signed.transaction_hash)
        receipt_status = str(receipt.get("status") or "").lower()
        self.store.insert_execution(
            order.id,
            "APPROVAL_FILLED" if receipt_status == "0x1" else "APPROVAL_FAILED",
            signed.transaction_hash,
            {
                "mode": "live",
                "approval": {
                    "broadcast": broadcast,
                    "receipt": receipt,
                    "spender": spender,
                    "token_contract": order.token_in.address,
                },
            },
        )
        if receipt_status != "0x1":
            raise RuntimeError(f"approve transaction reverted: {tracking_id}")
        return approve_nonce + 1

    def _build_approve_tx(
        self,
        chain_id: int,
        token_address: str,
        approve_item: dict[str, Any],
        swap_tx: dict[str, Any],
        nonce: int,
    ) -> dict[str, Any]:
        gas = self._normalize_tx_value("gas", approve_item.get("gasLimit") or approve_item.get("gas") or self.min_approve_gas_limit)
        tx: dict[str, Any] = {
            "chainId": chain_id,
            "nonce": nonce,
            "to": self._checksum_address(token_address),
            "data": approve_item["data"],
            "value": 0,
            "gas": max(int(gas), self.min_approve_gas_limit),
        }
        if approve_item.get("gasPrice") is not None:
            tx["gasPrice"] = self._normalize_tx_value("gasPrice", approve_item["gasPrice"])
        elif swap_tx.get("gasPrice") is not None:
            tx["gasPrice"] = self._normalize_tx_value("gasPrice", swap_tx["gasPrice"])
        elif swap_tx.get("maxFeePerGas") is not None and swap_tx.get("maxPriorityFeePerGas") is not None:
            tx["maxFeePerGas"] = self._normalize_tx_value("maxFeePerGas", swap_tx["maxFeePerGas"])
            tx["maxPriorityFeePerGas"] = self._normalize_tx_value("maxPriorityFeePerGas", swap_tx["maxPriorityFeePerGas"])
            tx["type"] = self._normalize_tx_value("type", swap_tx.get("type", 2))
        else:
            raise RuntimeError("approve tx missing gas price fields")
        self._validate_unsigned_tx(tx, expected_chain_id=chain_id)
        return tx

    def _apply_gas_limit_buffer(self, tx: dict[str, Any]) -> dict[str, Any]:
        gas = tx.get("gas")
        if not isinstance(gas, int) or gas <= 0:
            return tx
        buffered = gas
        if self.gas_limit_multiplier > 1:
            buffered = int((Decimal(gas) * self.gas_limit_multiplier).to_integral_value(rounding=ROUND_CEILING))
        if self.min_swap_gas_limit > 0:
            buffered = max(buffered, self.min_swap_gas_limit)
        if self.max_swap_gas_limit > 0:
            buffered = min(buffered, self.max_swap_gas_limit)
        return {**tx, "gas": buffered}

    @staticmethod
    def _filter_signable_tx_fields(tx: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "accessList",
            "chainId",
            "data",
            "gas",
            "gasPrice",
            "maxFeePerGas",
            "maxPriorityFeePerGas",
            "nonce",
            "to",
            "type",
            "value",
        }
        filtered = {key: value for key, value in tx.items() if key in allowed}
        if "maxFeePerGas" in filtered and "maxPriorityFeePerGas" in filtered:
            filtered.pop("gasPrice", None)
        elif "gasPrice" in filtered:
            filtered.pop("maxPriorityFeePerGas", None)
        return filtered

    def _fetch_pending_nonce(self, address: str) -> int:
        if not self.rpc_url:
            raise RuntimeError("swap tx missing nonce and rpc_url is not configured")
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionCount",
            "params": [address, "pending"],
        }
        try:
            response = requests.post(self.rpc_url, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise RuntimeError("failed to fetch pending nonce from RPC") from exc
        except ValueError as exc:
            raise RuntimeError("invalid RPC json while fetching pending nonce") from exc
        nonce = data.get("result")
        if not isinstance(nonce, str) or not nonce.startswith("0x"):
            raise RuntimeError("RPC nonce response missing result")
        return int(nonce, 16)

    def _fetch_erc20_allowance(self, token_address: str, owner: str, spender: str) -> int:
        data = "0xdd62ed3e" + self._address_arg(owner) + self._address_arg(spender)
        result = self._rpc_call(
            "eth_call",
            [{"to": token_address, "data": data}, "latest"],
            "failed to fetch ERC20 allowance from RPC",
        )
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RuntimeError("RPC allowance response missing result")
        return int(result, 16)

    def _wait_for_rpc_receipt(self, tx_hash: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.approve_receipt_timeout_seconds
        while time.monotonic() < deadline:
            receipt = self._rpc_call(
                "eth_getTransactionReceipt",
                [tx_hash],
                "failed to fetch approve receipt from RPC",
            )
            if isinstance(receipt, dict):
                return receipt
            time.sleep(2)
        raise RuntimeError("approve transaction receipt timeout")

    def _rpc_call(self, method: str, params: list[Any], error_message: str) -> Any:
        if not self.rpc_url:
            raise RuntimeError("rpc_url is not configured")
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_request_error: requests.RequestException | None = None
        for attempt in range(3):
            try:
                response = requests.post(self.rpc_url, json=payload, timeout=20)
                response.raise_for_status()
                data = response.json()
                break
            except requests.RequestException as exc:
                last_request_error = exc
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise RuntimeError(f"{error_message}: {exc}") from exc
            except ValueError as exc:
                raise RuntimeError(f"invalid RPC json: {method}") from exc
        else:
            raise RuntimeError(f"{error_message}: {last_request_error}")
        if "error" in data:
            raise RuntimeError(f"RPC error during {method}: {data['error']}")
        return data.get("result")

    @staticmethod
    def _extract_tx(swap_response: dict[str, Any]) -> dict[str, Any]:
        if "tx" in swap_response and isinstance(swap_response["tx"], dict):
            return dict(swap_response["tx"])
        data = swap_response.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            tx = data[0].get("tx")
            if isinstance(tx, dict):
                return dict(tx)
        reason = OrderService._okx_response_reason(swap_response)
        raise RuntimeError(f"swap response does not contain tx: {reason}" if reason else "swap response does not contain tx")

    @staticmethod
    def _quote_unavailable_reason(quote: dict[str, Any]) -> str:
        code = str(quote.get("code") or "")
        data = quote.get("data")
        if code and code != "0":
            return f"quote_unavailable: {OrderService._okx_response_reason(quote)}"
        if isinstance(data, list) and not data:
            return f"quote_unavailable: {OrderService._okx_response_reason(quote) or 'empty route'}"
        return ""

    @staticmethod
    def _okx_response_reason(response: dict[str, Any]) -> str:
        code = str(response.get("code") or "")
        msg = str(response.get("msg") or response.get("message") or "").strip()
        if code and msg:
            return f"{code} {msg}"
        return msg or code

    @staticmethod
    def _first_response_item(response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return response

    @staticmethod
    def _is_native_token(address: str) -> bool:
        return address.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

    @staticmethod
    def _is_evm_address(address: str) -> bool:
        return address.startswith("0x") and len(address) == 42

    @staticmethod
    def _checksum_address(address: str) -> str:
        if not OrderService._is_evm_address(str(address)):
            raise RuntimeError(f"invalid EVM address: {address}")
        return to_checksum_address(str(address))

    @staticmethod
    def _address_arg(address: str) -> str:
        if not OrderService._is_evm_address(address):
            raise RuntimeError(f"invalid EVM address: {address}")
        return address.lower().removeprefix("0x").rjust(64, "0")

    @staticmethod
    def _normalize_tx_value(key: str, value: Any) -> Any:
        int_fields = {"chainId", "nonce", "gas", "gasPrice", "value", "maxFeePerGas", "maxPriorityFeePerGas", "type"}
        if key not in int_fields:
            return value
        if isinstance(value, int):
            return value
        text = str(value)
        return int(text, 16) if text.startswith("0x") else int(text)

    @staticmethod
    def _validate_unsigned_tx(tx: dict[str, Any], expected_chain_id: int, require_nonce: bool = True) -> None:
        required = ["to", "data", "value", "gas", "chainId"]
        if require_nonce:
            required.append("nonce")
        missing = [field for field in required if field not in tx]
        if missing:
            raise RuntimeError(f"swap tx missing required fields: {', '.join(missing)}")
        if "gasPrice" not in tx and ("maxFeePerGas" not in tx or "maxPriorityFeePerGas" not in tx):
            raise RuntimeError("swap tx missing gas price fields")
        if int(tx["chainId"]) != int(expected_chain_id):
            raise RuntimeError(f"swap tx chainId mismatch: expected {expected_chain_id}, got {tx['chainId']}")
        if not str(tx["to"]).startswith("0x") or len(str(tx["to"])) != 42:
            raise RuntimeError("swap tx has invalid to address")
        if not str(tx["data"]).startswith("0x"):
            raise RuntimeError("swap tx data must be hex")

    @staticmethod
    def _extract_tx_hash_or_order_id(response: dict[str, Any]) -> str | None:
        data = response.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0].get("txHash") or data[0].get("orderId")
        return response.get("txHash") or response.get("orderId")
