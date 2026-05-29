from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event
from typing import Any

from app.bot.message_format import format_copy_trade_notification, format_limit_trigger_notification
from app.bot.runtime import TelegramRuntime
from app.core.order_state import OrderStatus
from app.storage.sqlite_store import SQLiteStore


@dataclass(frozen=True)
class RuntimeTickResult:
    telegram_ok: bool
    watcher_ok: bool
    copy_watcher_ok: bool
    receipt_ok: bool
    heartbeat_ok: bool


@dataclass
class RuntimeOrchestrator:
    store: SQLiteStore
    telegram_runtime: TelegramRuntime | None = None
    conditional_watcher: Any | None = None
    copy_trade_watcher: Any | None = None
    receipt_tracker: Any | None = None
    poll_interval_seconds: float = 5.0
    conditional_watcher_interval_seconds: float = 0.0
    copy_watcher_interval_seconds: float = 0.0

    def tick_once(self) -> RuntimeTickResult:
        telegram_ok = self._run_telegram_once()
        watcher_ok = self._run_watcher_once() if self._component_due("conditional_watcher", self.conditional_watcher_interval_seconds) else True
        copy_watcher_ok = self._run_copy_watcher_once() if self._component_due("copy_watcher", self.copy_watcher_interval_seconds) else True
        receipt_ok = self._run_receipts_once()
        heartbeat_ok = self._run_heartbeat_once()
        return RuntimeTickResult(
            telegram_ok=telegram_ok,
            watcher_ok=watcher_ok,
            copy_watcher_ok=copy_watcher_ok,
            receipt_ok=receipt_ok,
            heartbeat_ok=heartbeat_ok,
        )

    def run_forever(self, stop_event: Event | None = None) -> None:
        stop_event = stop_event or Event()
        while not stop_event.is_set():
            self.tick_once()
            stop_event.wait(self.poll_interval_seconds)

    def _run_telegram_once(self) -> bool:
        if self.telegram_runtime is None:
            return True
        try:
            saved = self.store.get_runtime_value("telegram_offset")
            offset = int(saved) if saved is not None else None
            next_offset = self.telegram_runtime.poll_once(offset=offset)
            if next_offset is not None:
                self.store.set_runtime_value("telegram_offset", str(next_offset))
            return True
        except Exception as exc:
            self._record_error("telegram", exc)
            return False

    def _run_watcher_once(self) -> bool:
        if self.conditional_watcher is None:
            return True
        try:
            result = self.conditional_watcher.process_once()
            self.store.insert_event(
                "runtime",
                "watcher_tick",
                {"checked": result.checked, "triggered": result.triggered, "expired": result.expired},
            )
            self._notify_triggered_orders(result)
            self.store.set_runtime_value("watcher_last_ok", "true")
            return True
        except Exception as exc:
            self.store.set_runtime_value("watcher_last_ok", "false")
            self._record_error("watcher", exc)
            return False

    def _run_copy_watcher_once(self) -> bool:
        if self.copy_trade_watcher is None:
            return True
        try:
            result = self.copy_trade_watcher.process_once()
            self.store.insert_event(
                "runtime",
                "copy_watcher_tick",
                {
                    "checked_targets": result.checked_targets,
                    "processed_events": result.processed_events,
                    "submitted_orders": result.submitted_orders,
                    "skipped_events": result.skipped_events,
                },
            )
            self._notify_copy_trades(result)
            self.store.set_runtime_value("copy_watcher_ok", "true")
            return True
        except Exception as exc:
            self.store.set_runtime_value("copy_watcher_ok", "false")
            self._record_error("copy_watcher", exc)
            return False

    def _run_receipts_once(self) -> bool:
        if self.receipt_tracker is None:
            return True
        ok = True
        for row in self.store.list_orders(limit=100):
            if row["status"] != OrderStatus.BROADCASTED.value:
                continue
            try:
                self.receipt_tracker.refresh_order(row["id"])
            except Exception as exc:
                ok = False
                self._record_error("receipt_tracker", exc, {"order_id": row["id"]})
        self.store.set_runtime_value("receipt_last_ok", "true" if ok else "false")
        return ok

    def _notify_triggered_orders(self, result: Any) -> None:
        if self.telegram_runtime is None:
            return
        for triggered in getattr(result, "triggered_orders", None) or []:
            try:
                market_order_id = triggered.market_order_id
                self.telegram_runtime.send_system_message(
                    format_limit_trigger_notification(
                        conditional_order_id=triggered.conditional_order_id,
                        current_price=triggered.current_price,
                        market_order_id=market_order_id,
                        market_order_status=triggered.market_order_status,
                        tracking_id=getattr(triggered, "tracking_id", None),
                    ),
                    reply_markup={
                        "inline_keyboard": [
                            [{"text": "查看订单", "callback_data": f"order:{market_order_id}"}],
                            [{"text": "历史订单", "callback_data": "nav:history"}],
                        ]
                    },
                )
            except Exception as exc:
                self._record_error(
                    "watcher_notification",
                    exc,
                    {"market_order_id": getattr(triggered, "market_order_id", None)},
                )

    def _notify_copy_trades(self, result: Any) -> None:
        if self.telegram_runtime is None:
            return
        for group in getattr(result, "action_groups", None) or []:
            try:
                first_order_id = next((action.order_id for action in group.actions if action.order_id), None)
                buttons = [[{"text": "跟单管理", "callback_data": "nav:copy_status"}]]
                if first_order_id:
                    buttons.insert(0, [{"text": "查看订单", "callback_data": f"order:{first_order_id}"}])
                self.telegram_runtime.send_system_message(
                    format_copy_trade_notification(group),
                    reply_markup={"inline_keyboard": buttons},
                )
            except Exception as exc:
                self._record_error(
                    "copy_watcher_notification",
                    exc,
                    {"history_id": getattr(getattr(group, "intent", None), "history_id", None)},
                )

    def _run_heartbeat_once(self) -> bool:
        try:
            self.store.set_runtime_value("heartbeat_at", str(time.time()))
            return True
        except Exception as exc:
            self._record_error("heartbeat", exc)
            return False

    def _component_due(self, component: str, default_interval_seconds: float) -> bool:
        if default_interval_seconds <= 0:
            return True
        now = time.time()
        interval = self._runtime_interval(component, default_interval_seconds)
        last_key = f"{component}_last_checked_at"
        last_raw = self.store.get_runtime_value(last_key)
        try:
            last = float(last_raw) if last_raw is not None else 0.0
        except ValueError:
            last = 0.0
        if now - last < interval:
            return False
        self.store.set_runtime_value(last_key, str(now))
        return True

    def _runtime_interval(self, component: str, default_interval_seconds: float) -> float:
        raw = self.store.get_runtime_value(f"{component}_interval_seconds")
        if raw is None:
            return default_interval_seconds
        try:
            value = float(raw)
        except ValueError:
            return default_interval_seconds
        return value if value > 0 else default_interval_seconds

    def _record_error(self, component: str, exc: Exception, extra: dict[str, Any] | None = None) -> None:
        payload = {"component": component, "error_type": exc.__class__.__name__, "reason": str(exc)}
        if extra:
            payload.update(extra)
        self.store.insert_event("runtime", "runtime_error", payload)
