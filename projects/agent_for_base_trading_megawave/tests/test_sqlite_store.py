from __future__ import annotations

import json

from app.core.order_info import ConditionalOrder, MarketOrder
from app.core.order_state import ConditionalOrderStatus, OrderStatus
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_info import conditional_payload, market_payload


def test_create_order_persists_draft_status(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = MarketOrder.from_dict(market_payload())

    store.create_order(order)
    row = store.get_order(order.id)

    assert row is not None
    assert row["status"] == OrderStatus.DRAFT.value
    payload = json.loads(row["payload_json"])
    assert payload["id"] == order.id
    assert row["created_at"]


def test_order_status_transitions_are_evented(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = MarketOrder.from_dict(market_payload())
    store.create_order(order)

    store.update_order_status(order.id, OrderStatus.RISK_CHECKED)
    store.update_order_status(order.id, OrderStatus.QUOTED)
    store.update_order_status(order.id, OrderStatus.PENDING_CONFIRMATION)

    row = store.get_order(order.id)
    events = store.get_events(order.id)

    assert row is not None
    assert row["status"] == OrderStatus.PENDING_CONFIRMATION.value
    assert [event["to_status"] for event in events] == [
        OrderStatus.DRAFT.value,
        OrderStatus.RISK_CHECKED.value,
        OrderStatus.QUOTED.value,
        OrderStatus.PENDING_CONFIRMATION.value,
    ]


def test_execution_records_are_queryable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = MarketOrder.from_dict(market_payload())
    store.create_order(order)

    store.insert_execution(order.id, OrderStatus.SIGNED_NOT_BROADCASTED.value, "0xhash", {"mode": "sign_only"})
    executions = store.get_executions(order.id)

    assert len(executions) == 1
    assert executions[0]["tx_hash"] == "0xhash"


def test_quote_and_risk_records_are_queryable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = MarketOrder.from_dict(market_payload())
    store.create_order(order)

    store.insert_quote(order.id, {"priceImpactPercent": "0.1"})
    store.insert_risk_decision(order.id, "APPROVED", "", {"requires_confirmation": True})
    quotes = store.get_quotes(order.id)
    risks = store.get_risk_decisions(order.id)

    assert json.loads(quotes[0]["payload_json"])["priceImpactPercent"] == "0.1"
    assert risks[0]["decision"] == "APPROVED"
    assert json.loads(risks[0]["payload_json"])["requires_confirmation"] is True


def test_active_conditional_orders_recover_after_new_store_instance(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "orders.sqlite"
    store = SQLiteStore(db_path)
    active = ConditionalOrder.from_dict(conditional_payload())
    filled = ConditionalOrder.from_dict({**conditional_payload(), "id": "cond_filled"})
    store.create_conditional_order(active)
    store.create_conditional_order(filled)
    store.update_conditional_status(filled.id, ConditionalOrderStatus.FILLED)

    reopened = SQLiteStore(db_path)
    active_rows = reopened.list_active_conditional_orders()

    assert [row["id"] for row in active_rows] == [active.id]


def test_current_and_history_order_groups_are_separate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    current = MarketOrder.from_dict({**market_payload(), "id": "ord_current"})
    history = MarketOrder.from_dict({**market_payload(), "id": "ord_history"})
    store.create_order(current, status=OrderStatus.PENDING_CONFIRMATION)
    store.create_order(history, status=OrderStatus.DRY_RUN_COMPLETED)

    assert [row["id"] for row in store.list_current_orders()] == ["ord_current"]
    assert [row["id"] for row in store.list_history_orders()] == ["ord_history"]


def test_current_and_history_conditional_groups_are_separate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    current = ConditionalOrder.from_dict({**conditional_payload(), "id": "cond_current"})
    history = ConditionalOrder.from_dict({**conditional_payload(), "id": "cond_history"})
    store.create_conditional_order(current, status=ConditionalOrderStatus.ACTIVE)
    store.create_conditional_order(history, status=ConditionalOrderStatus.CANCELLED)

    assert [row["id"] for row in store.list_current_conditional_orders()] == ["cond_current"]
    assert [row["id"] for row in store.list_history_conditional_orders()] == ["cond_history"]
