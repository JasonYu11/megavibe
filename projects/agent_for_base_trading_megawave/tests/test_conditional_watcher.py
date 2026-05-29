from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.order_info import ConditionalOrder
from app.core.order_state import ConditionalOrderStatus, OrderStatus
from app.orders.conditional_watcher import ConditionalOrderWatcher
from app.orders.order_service import OrderService
from app.risk.risk_engine import RiskEngine
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_info import conditional_payload
from tests.test_order_service import FakeQuoteClient
from tests.test_risk_engine import policy


class StaticPriceProvider:
    def __init__(self, price: str) -> None:
        self.price = Decimal(price)
        self.calls = 0

    def get_price_usd(self, token_address: str) -> Decimal:
        assert token_address
        self.calls += 1
        return self.price


def make_watcher(tmp_path, price: str):  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    price_provider = StaticPriceProvider(price)
    watcher = ConditionalOrderWatcher(store, price_provider, service)
    return store, watcher, price_provider


def test_conditional_order_not_triggered_when_price_condition_false(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store, watcher, _price_provider = make_watcher(tmp_path, "2.0")
    order = ConditionalOrder.from_dict(conditional_payload())
    store.create_conditional_order(order)

    result = watcher.process_once()
    active = store.list_active_conditional_orders()

    assert result.checked == 1
    assert result.triggered == 0
    assert active[0]["status"] == ConditionalOrderStatus.ACTIVE.value


def test_conditional_order_triggers_market_order_through_order_service(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store, watcher, _price_provider = make_watcher(tmp_path, "1.0")
    order = ConditionalOrder.from_dict(conditional_payload())
    store.create_conditional_order(order)

    result = watcher.process_once()

    assert result.checked == 1
    assert result.triggered == 1
    assert len(result.executions) == 1
    assert result.executions[0].status == OrderStatus.DRY_RUN_COMPLETED.value
    market_row = store.get_order(result.executions[0].order_id)
    conditional_row = store.get_conditional_order(order.id)
    approvals = store.get_approvals(result.executions[0].order_id)
    assert market_row is not None
    assert market_row["status"] == OrderStatus.DRY_RUN_COMPLETED.value
    assert conditional_row is not None
    assert conditional_row["status"] == ConditionalOrderStatus.FILLED.value
    assert approvals[0]["actor"] == "watcher"
    events = store.get_events(order.id)
    assert events[-3]["to_status"] == ConditionalOrderStatus.TRIGGERED.value
    assert events[-2]["to_status"] == ConditionalOrderStatus.FILLED.value
    assert events[-1]["event_type"] == "conditional_triggered_market_order"
    assert result.executions[0].order_id in events[-1]["payload_json"]


def test_conditional_order_does_not_retrigger_after_triggered_status(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store, watcher, price_provider = make_watcher(tmp_path, "1.0")
    order = ConditionalOrder.from_dict(conditional_payload())
    store.create_conditional_order(order)

    first = watcher.process_once()
    second = watcher.process_once()
    orders = store.list_orders(limit=10)

    assert first.triggered == 1
    assert second.triggered == 0
    assert len(orders) == 1
    assert price_provider.calls == 1


def test_conditional_order_paused_is_not_polled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store, watcher, price_provider = make_watcher(tmp_path, "1.0")
    order = ConditionalOrder.from_dict(conditional_payload())
    store.create_conditional_order(order)
    store.update_conditional_status(order.id, ConditionalOrderStatus.PAUSED)

    result = watcher.process_once()

    assert result.checked == 1
    assert result.triggered == 0
    assert price_provider.calls == 0


def test_conditional_order_expires_without_execution(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store, watcher, _price_provider = make_watcher(tmp_path, "1.0")
    payload = conditional_payload()
    payload["lifecycle"]["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    order = ConditionalOrder.from_dict(payload)
    store.create_conditional_order(order)

    result = watcher.process_once()
    active = store.list_active_conditional_orders()

    assert result.expired == 1
    assert result.triggered == 0
    assert active == []
