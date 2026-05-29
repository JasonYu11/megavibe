from __future__ import annotations

import json

from app.bot.orchestrator import RuntimeOrchestrator
from app.core.order_state import OrderStatus
from app.orders.conditional_watcher import TriggeredConditionalOrder
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_info import market_payload


class FakeTelegramRuntime:
    def __init__(self, next_offset: int | None = 8, fail: bool = False) -> None:
        self.next_offset = next_offset
        self.fail = fail
        self.offsets = []
        self.system_messages = []

    def poll_once(self, offset=None):  # type: ignore[no-untyped-def]
        self.offsets.append(offset)
        if self.fail:
            raise RuntimeError("telegram failed")
        return self.next_offset

    def send_system_message(self, text, reply_markup=None):  # type: ignore[no-untyped-def]
        self.system_messages.append((text, reply_markup))


class FakeWatcher:
    def __init__(self, fail: bool = False, triggered: bool = False) -> None:
        self.fail = fail
        self.triggered = triggered
        self.calls = 0

    def process_once(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise RuntimeError("watcher failed")

        class Result:
            checked = 1
            triggered = 1 if self.triggered else 0
            expired = 0
            triggered_orders = (
                [
                    TriggeredConditionalOrder(
                        conditional_order_id="cond_1",
                        current_price="0.9",  # type: ignore[arg-type]
                        market_order_id="ord_1",
                        market_order_status=OrderStatus.DRY_RUN_COMPLETED.value,
                    )
                ]
                if self.triggered
                else []
            )

        return Result()


class FakeReceiptTracker:
    def __init__(self) -> None:
        self.refreshed = []

    def refresh_order(self, order_id: str):  # type: ignore[no-untyped-def]
        self.refreshed.append(order_id)
        return OrderStatus.FILLED


def test_orchestrator_tick_persists_telegram_offset_and_runs_watcher(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    telegram = FakeTelegramRuntime(next_offset=8)
    watcher = FakeWatcher()
    orchestrator = RuntimeOrchestrator(store, telegram_runtime=telegram, conditional_watcher=watcher)

    result = orchestrator.tick_once()

    assert result.telegram_ok is True
    assert result.watcher_ok is True
    assert store.get_runtime_value("telegram_offset") == "8"
    assert store.get_runtime_value("heartbeat_at") is not None
    assert store.get_runtime_value("watcher_last_ok") == "true"
    assert watcher.calls == 1


def test_orchestrator_restores_saved_telegram_offset(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    store.set_runtime_value("telegram_offset", "9")
    telegram = FakeTelegramRuntime(next_offset=10)

    RuntimeOrchestrator(store, telegram_runtime=telegram).tick_once()

    assert telegram.offsets == [9]
    assert store.get_runtime_value("telegram_offset") == "10"


def test_orchestrator_isolates_telegram_error_and_still_runs_watcher(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    watcher = FakeWatcher()

    result = RuntimeOrchestrator(
        store,
        telegram_runtime=FakeTelegramRuntime(fail=True),
        conditional_watcher=watcher,
    ).tick_once()

    events = store.get_events("runtime")
    payloads = [json.loads(row["payload_json"]) for row in events if row["event_type"] == "runtime_error"]

    assert result.telegram_ok is False
    assert result.watcher_ok is True
    assert store.get_runtime_value("watcher_last_ok") == "true"
    assert watcher.calls == 1
    assert payloads[0]["component"] == "telegram"
    assert "telegram failed" in payloads[0]["reason"]


def test_orchestrator_refreshes_broadcasted_orders(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order_payload = market_payload()
    order_payload["id"] = "ord_broadcasted"
    from app.core.order_info import MarketOrder

    order = MarketOrder.from_dict(order_payload)
    store.create_order(order, OrderStatus.BROADCASTED)
    tracker = FakeReceiptTracker()

    result = RuntimeOrchestrator(store, receipt_tracker=tracker).tick_once()

    assert result.receipt_ok is True
    assert tracker.refreshed == ["ord_broadcasted"]
    assert store.get_runtime_value("receipt_last_ok") == "true"


def test_orchestrator_notifies_telegram_when_limit_order_triggers(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    telegram = FakeTelegramRuntime(next_offset=None)
    watcher = FakeWatcher(triggered=True)

    result = RuntimeOrchestrator(store, telegram_runtime=telegram, conditional_watcher=watcher).tick_once()

    assert result.watcher_ok is True
    assert len(telegram.system_messages) == 1
    text, markup = telegram.system_messages[0]
    assert "限价单已自动执行" in text
    assert "限价单: cond_1" in text
    assert "市价单: ord_1" in text
    assert "执行状态: DRY_RUN_COMPLETED" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == "order:ord_1"


def test_orchestrator_throttles_conditional_watcher_by_runtime_interval(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    watcher = FakeWatcher()
    orchestrator = RuntimeOrchestrator(store, conditional_watcher=watcher, conditional_watcher_interval_seconds=30)

    first = orchestrator.tick_once()
    second = orchestrator.tick_once()

    assert first.watcher_ok is True
    assert second.watcher_ok is True
    assert watcher.calls == 1
    assert store.get_runtime_value("conditional_watcher_last_checked_at") is not None


def test_orchestrator_runtime_interval_override_controls_conditional_watcher(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    store.set_runtime_value("conditional_watcher_interval_seconds", "86400")
    watcher = FakeWatcher()
    orchestrator = RuntimeOrchestrator(store, conditional_watcher=watcher, conditional_watcher_interval_seconds=30)

    orchestrator.tick_once()
    store.set_runtime_value("conditional_watcher_last_checked_at", "999999999999")
    orchestrator.tick_once()

    assert watcher.calls == 1
