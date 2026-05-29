from __future__ import annotations

import json

from app.core.order_info import MarketOrder
from app.core.order_state import OrderStatus
from app.execution.receipt_tracker import OkxReceiptTracker, ReceiptTrackerError
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_info import market_payload


class FakeStatusClient:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls = []

    def get_order_status(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return {"code": "0", "data": [{"status": self.status}]}


class FakeRpcResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeRpcSession:
    def __init__(self, results: dict[str, dict | None]) -> None:
        self.results = results
        self.calls = []

    def post(self, url: str, json: dict, timeout: int):  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeRpcResponse({"jsonrpc": "2.0", "id": json["id"], "result": self.results.get(json["method"])})


def order_with_wallet() -> MarketOrder:
    payload = market_payload()
    payload["wallet"] = {
        "wallet_id": "base_main_test",
        "address": "0x0000000000000000000000000000000000000001",
    }
    return MarketOrder.from_dict(payload)


def test_receipt_tracker_marks_success_as_filled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = order_with_wallet()
    store.create_order(order)
    store.update_order_status(order.id, OrderStatus.BROADCASTED)
    store.insert_execution(order.id, OrderStatus.BROADCASTED.value, "okx_order_1", {"mode": "live"})
    client = FakeStatusClient("success")

    status = OkxReceiptTracker(store, client).refresh_order(order.id)
    row = store.get_order(order.id)
    executions = store.get_executions(order.id)

    assert status == OrderStatus.FILLED
    assert row is not None
    assert row["status"] == OrderStatus.FILLED.value
    assert executions[-1]["status"] == OrderStatus.FILLED.value
    assert client.calls[0]["order_id"] == "okx_order_1"


def test_receipt_tracker_marks_failure_as_failed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = order_with_wallet()
    store.create_order(order)
    store.update_order_status(order.id, OrderStatus.BROADCASTED)
    store.insert_execution(order.id, OrderStatus.BROADCASTED.value, "okx_order_1", {"mode": "live"})

    status = OkxReceiptTracker(store, FakeStatusClient("failed")).refresh_order(order.id)
    row = store.get_order(order.id)

    assert status == OrderStatus.FAILED
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value


def test_receipt_tracker_keeps_pending_status_broadcasted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = order_with_wallet()
    store.create_order(order)
    store.update_order_status(order.id, OrderStatus.BROADCASTED)
    store.insert_execution(order.id, OrderStatus.BROADCASTED.value, "okx_order_1", {"mode": "live"})

    status = OkxReceiptTracker(store, FakeStatusClient("pending")).refresh_order(order.id)
    row = store.get_order(order.id)
    executions = store.get_executions(order.id)

    assert status == OrderStatus.BROADCASTED
    assert row is not None
    assert row["status"] == OrderStatus.BROADCASTED.value
    assert executions[-1]["status"] == OrderStatus.BROADCASTED.value
    assert "receipt" in executions[-1]["payload_json"]


def test_receipt_tracker_uses_rpc_receipt_when_okx_is_pending(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = order_with_wallet()
    tx_hash = "0x" + "1" * 64
    store.create_order(order)
    store.update_order_status(order.id, OrderStatus.BROADCASTED)
    store.insert_execution(order.id, OrderStatus.BROADCASTED.value, tx_hash, {"mode": "live"})
    rpc_session = FakeRpcSession(
        {
            "eth_getTransactionReceipt": {
                "transactionHash": tx_hash,
                "status": "0x0",
                "gasUsed": "0xfd6b0",
                "blockNumber": "0x1",
            },
            "eth_getTransactionByHash": {
                "hash": tx_hash,
                "from": "0x0000000000000000000000000000000000000001",
                "to": "0x000000000000000000000000000000000000dEaD",
                "gas": "0xfd6b0",
            },
        }
    )

    status = OkxReceiptTracker(store, FakeStatusClient("pending"), rpc_url="https://base.rpc.test", rpc_session=rpc_session).refresh_order(order.id)
    row = store.get_order(order.id)
    executions = store.get_executions(order.id)
    payload = json.loads(executions[-1]["payload_json"])

    assert status == OrderStatus.FAILED
    assert row is not None
    assert row["status"] == OrderStatus.FAILED.value
    assert executions[-1]["status"] == OrderStatus.FAILED.value
    assert payload["source"] == "rpc"
    assert payload["receipt"]["reason"] == "out_of_gas"


def test_receipt_tracker_requires_execution_record(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = order_with_wallet()
    store.create_order(order)

    try:
        OkxReceiptTracker(store, FakeStatusClient("success")).refresh_order(order.id)
    except ReceiptTrackerError as exc:
        assert "no execution record" in str(exc)
    else:
        raise AssertionError("missing execution record should fail")
