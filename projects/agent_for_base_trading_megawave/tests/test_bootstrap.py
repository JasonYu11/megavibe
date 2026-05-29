from __future__ import annotations

from pathlib import Path

import pytest
from eth_account import Account

from app.bootstrap import build_trading_runtime_app
from app.config.settings import load_app_config

ROOT = Path(__file__).resolve().parents[1]


class StaticSecretProvider:
    def resolve(self, secret_ref: str) -> str:
        values = {
            "ENV:BASE_RPC_URL": "https://base.rpc.test",
            "ENV:DEBANK_ACCESS_KEY": "debank-key",
            "ENV:OKX_API_KEY": "okx-key",
            "ENV:OKX_SECRET_KEY": "okx-secret",
            "ENV:OKX_API_PASSPHRASE": "okx-passphrase",
            "ENV:OKX_PROJECT_ID": "okx-project",
            "ENV:TELEGRAM_BOT_TOKEN": "telegram-token",
            "KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1": "0x" + "1" * 64,
        }
        if secret_ref not in values:
            raise KeyError(secret_ref)
        return values[secret_ref]


def test_build_trading_runtime_app_wires_phase2_components(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=None,
    )
    runtime = dict(config.runtime)
    runtime["telegram"] = {**runtime["telegram"], "default_chat_id": "chat1"}
    config = type(config)(runtime=runtime, risk_policy=config.risk_policy, strategies=config.strategies)

    app = build_trading_runtime_app(config, db_path=tmp_path / "orders.sqlite", secret_provider=StaticSecretProvider())

    assert app.parser.token_resolver is app.token_resolver
    assert app.handler.guided_flow is not None
    assert app.handler.price_provider is not None
    assert app.handler.balance_service is not None
    assert app.orchestrator.telegram_runtime is not None
    assert app.orchestrator.conditional_watcher is not None
    assert app.orchestrator.receipt_tracker is not None
    assert app.orchestrator.conditional_watcher_interval_seconds == 30
    assert app.orchestrator.copy_watcher_interval_seconds == 30
    assert app.store.get_runtime_value("conditional_watcher_interval_seconds") == "30"
    assert app.store.get_runtime_value("copy_watcher_interval_seconds") == "30"
    assert app.store.db_path == tmp_path / "orders.sqlite"


def test_build_trading_runtime_app_allows_missing_telegram_chat(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=None,
    )

    app = build_trading_runtime_app(config, db_path=tmp_path / "orders.sqlite", secret_provider=StaticSecretProvider())

    assert app.orchestrator.telegram_runtime is None
    assert app.orchestrator.conditional_watcher is not None


def test_build_trading_runtime_app_uses_env_default_chat_id(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=None,
    )
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "chat-from-env")

    app = build_trading_runtime_app(config, db_path=tmp_path / "orders.sqlite", secret_provider=StaticSecretProvider())

    assert app.orchestrator.telegram_runtime is not None
    assert app.orchestrator.telegram_runtime.chat_id == "chat-from-env"


def test_build_trading_runtime_app_derives_balance_wallet_from_signer(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=None,
    )
    expected = Account.from_key("0x" + "1" * 64).address

    app = build_trading_runtime_app(config, db_path=tmp_path / "orders.sqlite", secret_provider=StaticSecretProvider())

    assert app.handler.balance_service.wallet_address == expected
    assert app.parser.wallet_address == expected


def test_build_trading_runtime_app_enables_live_only_with_explicit_flags(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("RUN_LIVE_TRADE_TESTS", raising=False)
    monkeypatch.delenv("CONFIRM_LIVE_TRADE_BASE", raising=False)
    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=None,
    )
    runtime = dict(config.runtime)
    runtime["app"] = {**runtime["app"], "execution_mode": "live"}
    config = type(config)(runtime=runtime, risk_policy=config.risk_policy, strategies=config.strategies)

    app = build_trading_runtime_app(config, db_path=tmp_path / "orders.sqlite", secret_provider=StaticSecretProvider())
    assert app.handler.order_service.live_enabled is False

    monkeypatch.setenv("RUN_LIVE_TRADE_TESTS", "1")
    monkeypatch.setenv("CONFIRM_LIVE_TRADE_BASE", "YES")
    app = build_trading_runtime_app(config, db_path=tmp_path / "orders2.sqlite", secret_provider=StaticSecretProvider())
    assert app.handler.order_service.live_enabled is True


def test_build_trading_runtime_app_enables_live_copy_only_with_extra_flag(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=None,
    )
    runtime = dict(config.runtime)
    runtime["app"] = {**runtime["app"], "execution_mode": "live"}
    config = type(config)(runtime=runtime, risk_policy=config.risk_policy, strategies=config.strategies)
    monkeypatch.setenv("RUN_LIVE_TRADE_TESTS", "1")
    monkeypatch.setenv("CONFIRM_LIVE_TRADE_BASE", "YES")
    monkeypatch.delenv("CONFIRM_LIVE_COPY_TRADE_BASE", raising=False)

    app = build_trading_runtime_app(config, db_path=tmp_path / "orders.sqlite", secret_provider=StaticSecretProvider())
    assert app.orchestrator.copy_trade_watcher.live_copy_enabled is False

    monkeypatch.setenv("CONFIRM_LIVE_COPY_TRADE_BASE", "YES")
    app = build_trading_runtime_app(config, db_path=tmp_path / "orders2.sqlite", secret_provider=StaticSecretProvider())
    assert app.orchestrator.copy_trade_watcher.live_copy_enabled is True


def test_build_trading_runtime_app_wires_allowlist_from_env(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=None,
    )
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "chat1")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "user1,user2")

    app = build_trading_runtime_app(config, db_path=tmp_path / "orders.sqlite", secret_provider=StaticSecretProvider())

    assert app.handler.allowed_chat_ids == {"chat1"}
    assert app.handler.allowed_user_ids == {"user1", "user2"}
