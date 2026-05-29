from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.bot.nl_command_agent import NLCommandAgent
from app.bot.telegram_handlers import TelegramCommandHandler
from app.copy_trading.models import CopyTargetConfig, CopyTargetStatus
from app.dashboard.serializers import (
    compute_copy_positions,
    row_to_dict,
    summarize_conditional,
    summarize_copy_event,
    summarize_copy_target,
    summarize_order,
)
from app.storage.sqlite_store import SQLiteStore


@dataclass
class DashboardApp:
    store: SQLiteStore
    handler: TelegramCommandHandler
    static_dir: Path = Path(__file__).with_name("static")
    nl_agent: NLCommandAgent | None = None

    def handle_api(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        if method == "GET" and path == "/api/status":
            return 200, self.status()
        if method == "GET" and path == "/api/settings":
            return 200, self.settings()
        if method == "PATCH" and path == "/api/settings":
            return 200, self.update_settings(body or {})
        if method == "GET" and path == "/api/orders":
            limit = int((query.get("limit") or ["50"])[0])
            return 200, self.orders(limit=limit)
        match = re.fullmatch(r"/api/orders/([^/]+)", path)
        if method == "GET" and match:
            return 200, self.order_detail(unquote(match.group(1)))
        match = re.fullmatch(r"/api/orders/([^/]+)/(confirm|reject)", path)
        if method == "POST" and match:
            command = "confirm" if match.group(2) == "confirm" else "reject"
            actor, chat_id = self._handler_identity()
            response = self.handler.handle(f"/{command} {unquote(match.group(1))}", actor=actor, chat_id=chat_id)
            return 200, {"text": response.text, "payload": response.payload}
        if method == "GET" and path == "/api/copy-targets":
            return 200, self.copy_targets()
        if method == "POST" and path == "/api/copy-targets":
            return 200, self.create_copy_target(body or {})
        match = re.fullmatch(r"/api/copy-targets/(0x[a-fA-F0-9]{40})", path)
        if method == "PATCH" and match:
            return 200, self.update_copy_target(match.group(1), body or {})
        if method == "GET" and path == "/api/copy-events":
            limit = int((query.get("limit") or ["50"])[0])
            target = (query.get("target") or [None])[0]
            return 200, self.copy_events(target=target, limit=limit)
        if method == "GET" and path == "/api/copy-positions":
            return 200, {"positions": compute_copy_positions(self.store)}
        if method == "POST" and path == "/api/commands":
            text = str((body or {}).get("text") or "")
            actor, chat_id = self._handler_identity()
            response = self.handler.handle(text, actor=actor, chat_id=chat_id)
            return 200, {"text": response.text, "payload": response.payload, "reply_markup": response.reply_markup}
        if method == "POST" and path == "/api/nl-commands/parse":
            text = str((body or {}).get("text") or "")
            agent = self.nl_agent or NLCommandAgent()
            return 200, {"result": agent.parse(text).to_dict()}
        if method == "POST" and path == "/api/callbacks":
            data = str((body or {}).get("data") or "")
            actor, chat_id = self._handler_identity()
            response = self.handler.handle_callback(data, actor=actor, chat_id=chat_id)
            return 200, {"text": response.text, "payload": response.payload, "reply_markup": response.reply_markup}
        return 404, {"error": "not_found"}

    def status(self) -> dict[str, Any]:
        orders = self.store.list_orders(limit=1000)
        today = orders[:]
        filled = sum(1 for row in today if row["status"] == "FILLED")
        failed = sum(1 for row in today if row["status"] == "FAILED")
        return {
            "execution_mode": self.handler.order_service.execution_mode,
            "live_enabled": self.handler.order_service.live_enabled,
            "wallet_address": self._wallet_address(),
            "db_path": str(self.store.db_path),
            "orders": len(orders),
            "filled_orders": filled,
            "failed_orders": failed,
            "copy_targets": len(self.store.list_copy_targets()),
            "watcher_last_ok": self.store.get_runtime_value("watcher_last_ok"),
            "copy_watcher_ok": self.store.get_runtime_value("copy_watcher_ok"),
            "receipt_last_ok": self.store.get_runtime_value("receipt_last_ok"),
            "heartbeat_at": self.store.get_runtime_value("heartbeat_at"),
            "dashboard_url": self.store.get_runtime_value("dashboard_url"),
        }

    def settings(self) -> dict[str, Any]:
        conditional = self._interval("conditional_watcher_interval_seconds", 30)
        copy = self._interval("copy_watcher_interval_seconds", 30)
        return {
            "conditional_watcher_interval_seconds": conditional,
            "copy_watcher_interval_seconds": copy,
            "daily_estimates": {
                "conditional_order_calls_per_day": _calls_per_day(conditional),
                "copy_target_calls_per_day": _calls_per_day(copy),
            },
        }

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        updates = {
            "conditional_watcher_interval_seconds": payload.get("conditional_watcher_interval_seconds"),
            "copy_watcher_interval_seconds": payload.get("copy_watcher_interval_seconds"),
        }
        for key, value in updates.items():
            if value is None or value == "":
                continue
            self.store.set_runtime_value(key, str(_interval_value(value)))
        return self.settings()

    def orders(self, limit: int = 50) -> dict[str, Any]:
        return {
            "orders": [summarize_order(self.store, row) for row in self.store.list_orders(limit=limit)],
            "conditional_orders": [summarize_conditional(row) for row in self.store.list_conditional_orders(limit=limit)],
        }

    def order_detail(self, order_id: str) -> dict[str, Any]:
        detail = self.handler._order_detail(order_id)
        if not detail:
            return {"found": False}
        return {"found": True, "detail": _jsonable(detail)}

    def copy_targets(self) -> dict[str, Any]:
        events = self.store.list_copy_trade_events(limit=200)
        return {"targets": [summarize_copy_target(target, events) for target in self.store.list_copy_targets()]}

    def create_copy_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        address = _address(payload.get("address"))
        status = CopyTargetStatus(str(payload.get("status") or CopyTargetStatus.PENDING_CONFIRMATION.value))
        target = CopyTargetConfig(
            address=address,
            status=status,
            copy_ratio=Decimal(str(payload.get("copy_ratio") or "0.1")),
            max_copy_trade_usd=Decimal(str(payload.get("max_copy_trade_usd") or "0.01")),
            max_age_seconds=int(payload.get("max_age_seconds") or 300),
        )
        self.store.create_or_update_copy_target(target)
        return {"target": summarize_copy_target(self.store.get_copy_target(address), self.store.list_copy_trade_events(limit=50))}

    def update_copy_target(self, address: str, payload: dict[str, Any]) -> dict[str, Any]:
        status = CopyTargetStatus(str(payload["status"])) if payload.get("status") else None
        self.store.update_copy_target(
            address,
            status=status,
            copy_ratio=payload.get("copy_ratio"),
            max_copy_trade_usd=payload.get("max_copy_trade_usd"),
            max_age_seconds=int(payload["max_age_seconds"]) if payload.get("max_age_seconds") is not None else None,
        )
        return {"target": summarize_copy_target(self.store.get_copy_target(address), self.store.list_copy_trade_events(limit=50))}

    def copy_events(self, target: str | None, limit: int) -> dict[str, Any]:
        rows = self.store.list_copy_trade_events(target_address=target, limit=limit)
        return {"events": [summarize_copy_event(row) for row in rows]}

    def _wallet_address(self) -> str | None:
        balance_service = self.handler.balance_service
        return str(balance_service.wallet_address) if balance_service is not None and hasattr(balance_service, "wallet_address") else None

    def _handler_identity(self) -> tuple[str, str]:
        actor = _first_configured(getattr(self.handler, "allowed_user_ids", None)) or "dashboard"
        chat_id = _first_configured(getattr(self.handler, "allowed_chat_ids", None)) or actor
        return actor, chat_id

    def _interval(self, key: str, default: int) -> int:
        raw = self.store.get_runtime_value(key)
        if raw is None:
            return default
        try:
            return _interval_value(raw)
        except ValueError:
            return default


def make_handler(app: DashboardApp) -> type[BaseHTTPRequestHandler]:
    class DashboardRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle()

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _handle(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self._handle_api(parsed)
                return
            self._handle_static(parsed.path)

        def _handle_api(self, parsed: Any) -> None:
            try:
                body = self._json_body()
                status, payload = app.handle_api(self.command, parsed.path, parse_qs(parsed.query), body)
                self._send_json(status, payload)
            except Exception as exc:
                self._send_json(500, {"error": str(exc), "error_type": exc.__class__.__name__})

        def _handle_static(self, path: str) -> None:
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            file_path = (app.static_dir / relative).resolve()
            static_root = app.static_dir.resolve()
            if not str(file_path).startswith(str(static_root)) or not file_path.exists() or not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _json_body(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return None
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(_jsonable(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return DashboardRequestHandler


def serve(app: DashboardApp, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    return server


def _address(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", text):
        raise ValueError(f"invalid address: {value}")
    return text.lower()


def _first_configured(values: Any) -> str | None:
    if not values:
        return None
    return sorted(str(value) for value in values)[0]


def _interval_value(value: Any) -> int:
    try:
        parsed = int(float(str(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid interval seconds: {value}") from exc
    if parsed < 5 or parsed > 86400:
        raise ValueError("interval seconds must be between 5 and 86400")
    return parsed


def _calls_per_day(interval_seconds: int) -> int:
    return int((86400 + interval_seconds - 1) // interval_seconds)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
