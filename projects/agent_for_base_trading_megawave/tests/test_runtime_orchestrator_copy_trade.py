from __future__ import annotations

import json

from app.bot.orchestrator import RuntimeOrchestrator
from app.copy_trading.models import CopyWatcherResult
from app.storage.sqlite_store import SQLiteStore
from tests.test_runtime_orchestrator import FakeTelegramRuntime, FakeWatcher


class FakeCopyWatcher:
    def __init__(self, fail: bool = False, result=None) -> None:  # type: ignore[no-untyped-def]
        self.fail = fail
        self.result = result or CopyWatcherResult(checked_targets=1, processed_events=0, submitted_orders=0, skipped_events=0, action_groups=[])
        self.calls = 0

    def process_once(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise RuntimeError("copy watcher failed")
        return self.result


def test_orchestrator_runs_copy_watcher_between_conditional_and_receipts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    conditional = FakeWatcher()
    copy = FakeCopyWatcher()

    result = RuntimeOrchestrator(store, conditional_watcher=conditional, copy_trade_watcher=copy).tick_once()

    assert result.watcher_ok is True
    assert result.copy_watcher_ok is True
    assert conditional.calls == 1
    assert copy.calls == 1
    assert store.get_runtime_value("copy_watcher_ok") == "true"


def test_orchestrator_isolates_copy_watcher_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    conditional = FakeWatcher()

    result = RuntimeOrchestrator(
        store,
        telegram_runtime=FakeTelegramRuntime(next_offset=None),
        conditional_watcher=conditional,
        copy_trade_watcher=FakeCopyWatcher(fail=True),
    ).tick_once()
    payloads = [json.loads(row["payload_json"]) for row in store.get_events("runtime") if row["event_type"] == "runtime_error"]

    assert result.copy_watcher_ok is False
    assert result.receipt_ok is True
    assert result.heartbeat_ok is True
    assert store.get_runtime_value("copy_watcher_ok") == "false"
    assert conditional.calls == 1
    assert payloads[-1]["component"] == "copy_watcher"


def test_orchestrator_throttles_copy_watcher_by_runtime_interval(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    copy = FakeCopyWatcher()
    orchestrator = RuntimeOrchestrator(store, copy_trade_watcher=copy, copy_watcher_interval_seconds=30)

    orchestrator.tick_once()
    orchestrator.tick_once()

    assert copy.calls == 1
    assert store.get_runtime_value("copy_watcher_last_checked_at") is not None
