from __future__ import annotations

from types import SimpleNamespace

from pathlib import Path

import pytest

from app.config.settings import load_app_config
from app.run_bot import DEFAULT_DASHBOARD_HOST, DEFAULT_DASHBOARD_PORT, DEFAULT_RUNTIME_CONFIG, build_arg_parser, start_dashboard_for_runtime
from app.storage.sqlite_store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]


def test_main_entrypoint_defaults_to_local_dry_run_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_EXECUTION_MODE", raising=False)
    args = build_arg_parser().parse_args([])

    assert args.runtime_config == DEFAULT_RUNTIME_CONFIG
    assert args.runtime_config == "configs/runtime.local.yaml"
    assert args.no_dashboard is False
    assert args.dashboard_host == DEFAULT_DASHBOARD_HOST
    assert args.dashboard_port == DEFAULT_DASHBOARD_PORT

    config = load_app_config(
        ROOT / args.runtime_config,
        ROOT / args.risk_config,
        ROOT / args.strategies_config,
        env_path=None,
    )
    assert config.execution_mode == "dry_run"
    assert config.runtime["storage"]["sqlite_path"] == "var/orders.sqlite"


def test_dry_run_script_uses_same_runtime_config_as_main_entrypoint() -> None:
    script = (ROOT / "scripts/start_bot_dry_run.sh").read_text(encoding="utf-8")

    assert f'RUNTIME_CONFIG:-{DEFAULT_RUNTIME_CONFIG}' in script
    assert "APP_EXECUTION_MODE=dry_run" in script
    assert "python -m app.run_bot" in script


def test_start_dashboard_for_runtime_serves_same_store_and_records_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    runtime = SimpleNamespace(store=store, handler=_fake_handler(store))
    server = _FakeServer(8899)
    captured = {}

    def fake_serve(dashboard, host, port):  # type: ignore[no-untyped-def]
        captured["dashboard"] = dashboard
        captured["host"] = host
        captured["port"] = port
        return server

    monkeypatch.setattr("app.run_bot.serve", fake_serve)

    handle = start_dashboard_for_runtime(runtime, port=8787, open_browser=False)
    handle.stop()

    assert captured["dashboard"].store is store
    assert captured["dashboard"].handler is runtime.handler
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8787
    assert handle.url == "http://127.0.0.1:8899/"
    assert store.get_runtime_value("dashboard_url") == handle.url
    assert server.started is True
    assert server.stopped is True


def test_start_dashboard_for_runtime_falls_back_when_requested_port_is_busy(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    runtime = SimpleNamespace(store=store, handler=_fake_handler(store))
    calls = []

    def fake_serve(_dashboard, host, port):  # type: ignore[no-untyped-def]
        calls.append(port)
        if len(calls) == 1:
            raise OSError("address already in use")
        return _FakeServer(port)

    monkeypatch.setattr("app.run_bot.serve", fake_serve)

    handle = start_dashboard_for_runtime(runtime, port=8787, open_browser=False, max_port_attempts=3)
    handle.stop()

    assert calls == [8787, 8788]
    assert handle.url == "http://127.0.0.1:8788/"


def _fake_handler(store: SQLiteStore) -> SimpleNamespace:
    return SimpleNamespace(
        store=store,
        order_service=SimpleNamespace(execution_mode="dry_run", live_enabled=False),
        balance_service=SimpleNamespace(wallet_address="0x8EF454c23822C5373df37e8c5E8987aC64dB96F1"),
        allowed_user_ids=None,
        allowed_chat_ids=None,
        handle=lambda *_args, **_kwargs: SimpleNamespace(text="ok", payload={}, reply_markup=None),
    )


class _FakeServer:
    def __init__(self, port: int) -> None:
        self.server_port = port
        self.started = False
        self.stopped = False

    def serve_forever(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.stopped = True

    def server_close(self) -> None:
        return
