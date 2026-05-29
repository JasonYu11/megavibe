from __future__ import annotations

import json
from decimal import Decimal

from app.copy_trading.models import CopyTargetConfig, CopyTargetStatus
from app.storage.sqlite_store import SQLiteStore


ADDRESS = "0x138ab382c889add23de09a78fd7a75b9b4fe5c25"


def test_store_persists_copy_targets_seen_transactions_and_events(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    target = CopyTargetConfig(address=ADDRESS, copy_ratio=Decimal("0.00001"))

    store.create_or_update_copy_target(target)
    store.update_copy_target(ADDRESS, status=CopyTargetStatus.ACTIVE, max_copy_trade_usd=Decimal("0.01"))
    loaded = store.get_copy_target(ADDRESS)

    assert loaded is not None
    assert loaded.address == ADDRESS.lower()
    assert loaded.status == CopyTargetStatus.ACTIVE
    assert loaded.max_copy_trade_usd == Decimal("0.01")
    assert store.list_copy_targets(CopyTargetStatus.ACTIVE) == [loaded]

    assert store.is_copy_seen(ADDRESS, "h1", "0xhash") is False
    store.mark_copy_seen(ADDRESS, "h1", "0xhash")
    store.mark_copy_seen(ADDRESS, "h1", "0xhash")
    assert store.is_copy_seen(ADDRESS, "h1", "0xother") is True
    assert store.is_copy_seen(ADDRESS, "h2", "0xhash") is True

    store.insert_copy_trade_event(ADDRESS, "h1", "0xhash", "PROCESSED", {"order_id": "ord_1"})
    rows = store.list_copy_trade_events(ADDRESS)

    assert len(rows) == 1
    assert rows[0]["status"] == "PROCESSED"
    assert json.loads(rows[0]["payload_json"])["order_id"] == "ord_1"
