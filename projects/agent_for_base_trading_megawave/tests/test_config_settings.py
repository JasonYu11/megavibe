from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import ConfigError, load_app_config


ROOT = Path(__file__).resolve().parents[1]


def test_example_configs_parse_and_validate() -> None:
    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=ROOT / ".env",
    )

    assert config.execution_mode == "dry_run"
    assert config.runtime["chains"]["base"]["chain_id"] == 8453
    assert config.runtime["chains"]["base"]["chain_name"] == "base"
    assert (
        config.runtime["wallets"]["base_main_test"]["signer_ref"]
        == "KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1"
    )
    assert config.strategies["conditional_order"]["poll_interval_seconds"] == 30
    assert config.strategies["copy_trade"]["poll_interval_seconds"] == 30
    assert config.risk_policy["risk"]["max_single_trade_usd"] <= 5


def test_app_execution_mode_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_EXECUTION_MODE", "sign_only")

    config = load_app_config(
        ROOT / "configs/runtime.example.yaml",
        ROOT / "configs/risk_policy.example.yaml",
        ROOT / "configs/strategies.example.yaml",
        env_path=None,
    )

    assert config.execution_mode == "sign_only"


def test_missing_wallets_config_fails(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.yaml"
    runtime.write_text(
        """
app:
  execution_mode: dry_run
chains:
  base:
    chain_id: 8453
    chain_name: base
providers:
  debank:
    access_key_ref: ENV:DEBANK_ACCESS_KEY
  okx:
    api_key_ref: ENV:OKX_API_KEY
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="wallets.base_main_test.signer_ref"):
        load_app_config(
            runtime,
            ROOT / "configs/risk_policy.example.yaml",
            ROOT / "configs/strategies.example.yaml",
            env_path=None,
        )


def test_missing_risk_field_fails(tmp_path: Path) -> None:
    risk = tmp_path / "risk.yaml"
    risk.write_text(
        """
risk:
  max_daily_trade_usd: 20
  max_slippage_percent: 1.0
tokens:
  allowed_tokens: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="risk.max_single_trade_usd"):
        load_app_config(
            ROOT / "configs/runtime.example.yaml",
            risk,
            ROOT / "configs/strategies.example.yaml",
            env_path=None,
        )
