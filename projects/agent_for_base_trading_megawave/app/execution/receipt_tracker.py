from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from app.core.order_info import MarketOrder
from app.core.order_state import OrderStatus
from app.storage.sqlite_store import SQLiteStore


class ReceiptTrackerError(RuntimeError):
    """Raised when a broadcasted order cannot be tracked."""


@dataclass
class OkxReceiptTracker:
    store: SQLiteStore
    execution_client: Any
    rpc_url: str | None = None
    rpc_session: Any = requests

    def refresh_order(self, order_id: str) -> OrderStatus:
        row = self.store.get_order(order_id)
        if row is None:
            raise ReceiptTrackerError(f"unknown order_id: {order_id}")
        order = MarketOrder.from_dict(json.loads(row["payload_json"]))
        if not order.wallet.address:
            raise ReceiptTrackerError("wallet.address is required for receipt tracking")

        executions = self.store.get_executions(order_id)
        if not executions:
            raise ReceiptTrackerError("no execution record to track")
        tracked_id = executions[-1]["tx_hash"]
        if not tracked_id:
            raise ReceiptTrackerError("execution record has no tx hash or order id")

        response = self.execution_client.get_order_status(
            chain_id=order.chain.chain_id,
            order_id=tracked_id,
            address=order.wallet.address,
        )
        status = self._map_status(response)
        payload = {"receipt": response, "source": "okx"}
        if status == OrderStatus.BROADCASTED:
            rpc_status, rpc_payload = self._rpc_receipt_status(tracked_id)
            if rpc_status is not None:
                status = rpc_status
                payload = {"receipt": rpc_payload, "source": "rpc"}
        if status in {OrderStatus.FILLED, OrderStatus.FAILED}:
            self.store.update_order_status(order_id, status, payload)
        self.store.insert_execution(order_id, status.value, tracked_id, payload)
        return status

    def _rpc_receipt_status(self, tx_hash: str) -> tuple[OrderStatus | None, dict[str, Any] | None]:
        if not self.rpc_url or not tx_hash.startswith("0x"):
            return None, None
        receipt = self._rpc_call("eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            return None, None
        payload: dict[str, Any] = {"receipt": self._compact_receipt(receipt)}
        raw_status = str(receipt.get("status") or "").lower()
        if raw_status == "0x1":
            return OrderStatus.FILLED, payload
        if raw_status == "0x0":
            tx = self._rpc_call("eth_getTransactionByHash", [tx_hash])
            if isinstance(tx, dict):
                payload["transaction"] = self._compact_transaction(tx)
                if self._hex_int(receipt.get("gasUsed")) == self._hex_int(tx.get("gas")):
                    payload["reason"] = "out_of_gas"
            return OrderStatus.FAILED, payload
        return None, payload

    def _rpc_call(self, method: str, params: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for attempt in range(4):
            try:
                response = self.rpc_session.post(self.rpc_url, json=body, timeout=20)
                response.raise_for_status()
                data = response.json()
                break
            except requests.RequestException:
                if attempt < 3:
                    time.sleep(1 + attempt)
                    continue
                raise
            except ValueError:
                if attempt < 3:
                    time.sleep(1 + attempt)
                    continue
                raise
        else:
            return None
        return data.get("result")

    @staticmethod
    def _compact_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
        keys = ["transactionHash", "status", "gasUsed", "blockNumber", "effectiveGasPrice"]
        return {key: receipt.get(key) for key in keys if key in receipt}

    @staticmethod
    def _compact_transaction(tx: dict[str, Any]) -> dict[str, Any]:
        keys = ["hash", "from", "to", "nonce", "gas", "gasPrice", "maxFeePerGas", "maxPriorityFeePerGas"]
        return {key: tx.get(key) for key in keys if key in tx}

    @staticmethod
    def _hex_int(value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.startswith("0x"):
            return int(value, 16)
        return None

    @classmethod
    def _map_status(cls, response: dict[str, Any]) -> OrderStatus:
        item = cls._first_item(response)
        raw = str(
            item.get("txStatus")
            or item.get("status")
            or item.get("state")
            or item.get("transactionStatus")
            or ""
        ).lower()
        if raw in {"success", "succeeded", "filled", "confirmed", "completed", "2"}:
            return OrderStatus.FILLED
        if raw in {"failed", "failure", "reverted", "dropped", "cancelled", "3"}:
            return OrderStatus.FAILED
        return OrderStatus.BROADCASTED

    @staticmethod
    def _first_item(response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return response
