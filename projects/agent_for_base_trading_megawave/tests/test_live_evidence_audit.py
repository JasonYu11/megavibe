from __future__ import annotations

from app.core.order_info import ConditionalOrder, MarketOrder
from app.core.order_state import ConditionalOrderStatus, OrderStatus
from app.storage.sqlite_store import SQLiteStore
from app.verification.live_evidence_audit import audit_live_evidence
from tests.test_order_info import conditional_payload, market_payload


def _wallet_payload(payload: dict) -> dict:
    payload = dict(payload)
    payload["wallet"] = {
        "wallet_id": "base_main_test",
        "address": "0x0000000000000000000000000000000000000001",
    }
    return payload


def _record_complete_live_order(store: SQLiteStore, order: MarketOrder) -> None:
    store.create_order(order)
    store.insert_quote(order.id, {"code": "0", "data": [{"routerResult": {}}]})
    store.update_order_status(order.id, OrderStatus.QUOTED)
    store.insert_risk_decision(order.id, "APPROVED", "", {"requires_confirmation": True})
    store.update_order_status(order.id, OrderStatus.RISK_CHECKED)
    store.update_order_status(order.id, OrderStatus.PENDING_CONFIRMATION)
    store.insert_approval(order.id, "CONFIRMED", "test")
    store.update_order_status(order.id, OrderStatus.SIGNING)
    store.update_order_status(order.id, OrderStatus.BROADCASTED)
    store.insert_execution(
        order.id,
        OrderStatus.BROADCASTED.value,
        "0x" + "1" * 64,
        {"mode": "live", "broadcast": {"code": "0"}},
    )
    store.insert_execution(
        order.id,
        OrderStatus.BROADCASTED.value,
        "0x" + "1" * 64,
        {"receipt": {"code": "0", "data": [{"status": "pending"}]}},
    )
    store.update_order_status(
        order.id,
        OrderStatus.BROADCASTED,
        {"post_trade_observation": {"source": "debank.user_history", "history_count": 1}},
    )


def test_live_evidence_audit_accepts_complete_phase2_evidence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "phase2_live_evidence.sqlite")
    direct_order = MarketOrder.from_dict(_wallet_payload(market_payload()))
    _record_complete_live_order(store, direct_order)

    conditional = ConditionalOrder.from_dict(_wallet_payload(conditional_payload()))
    store.create_conditional_order(conditional)
    store.update_conditional_status(conditional.id, ConditionalOrderStatus.TRIGGERED, {"current_price": "1.0"})
    watcher_order = conditional.build_market_order()
    _record_complete_live_order(store, watcher_order)

    result = audit_live_evidence(store.db_path)

    assert result.ok
    assert result.counts["orders.live_direct_market"] == 1
    assert result.counts["orders.live_watcher_triggered"] == 1
    assert result.counts["conditional_orders.triggered"] == 1


def test_live_evidence_audit_rejects_missing_limit_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "phase2_live_evidence.sqlite")
    direct_order = MarketOrder.from_dict(_wallet_payload(market_payload()))
    _record_complete_live_order(store, direct_order)

    result = audit_live_evidence(store.db_path)

    assert not result.ok
    assert any("watcher-triggered limit" in error for error in result.errors)
    assert any("triggered conditional" in error for error in result.errors)


def test_live_evidence_audit_rejects_missing_receipt_payload(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "phase2_live_evidence.sqlite")
    direct_order = MarketOrder.from_dict(_wallet_payload(market_payload()))
    _record_complete_live_order(store, direct_order)
    with store.connect() as conn:
        conn.execute("DELETE FROM executions WHERE payload_json LIKE '%receipt%'")

    result = audit_live_evidence(store.db_path, require_limit=False)

    assert not result.ok
    assert any("receipt payload" in error for error in result.errors)


def test_live_evidence_audit_rejects_secret_markers(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "phase2_live_evidence.sqlite")
    direct_order = MarketOrder.from_dict(_wallet_payload(market_payload()))
    _record_complete_live_order(store, direct_order)
    store.insert_execution(direct_order.id, OrderStatus.BROADCASTED.value, "0x" + "2" * 64, {"secret_ref": "x"})

    result = audit_live_evidence(store.db_path, require_limit=False)

    assert not result.ok
    assert any("secret marker" in error for error in result.errors)


def test_live_evidence_audit_rejects_missing_db(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = audit_live_evidence(tmp_path / "missing.sqlite")

    assert not result.ok
    assert "does not exist" in result.errors[0]

