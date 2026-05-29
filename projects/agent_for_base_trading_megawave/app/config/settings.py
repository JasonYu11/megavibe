from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class AppConfig:
    runtime: dict[str, Any]
    risk_policy: dict[str, Any]
    strategies: dict[str, Any]

    @property
    def execution_mode(self) -> str:
        return str(self.runtime["app"]["execution_mode"])


def _load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain a mapping: {path}")
    return data


def _require_path(data: dict[str, Any], dotted_path: str) -> Any:
    cur: Any = data
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise ConfigError(f"missing required config field: {dotted_path}")
        cur = cur[part]
    return cur


def validate_runtime_config(runtime: dict[str, Any]) -> None:
    _require_path(runtime, "app.execution_mode")
    _require_path(runtime, "chains.base.chain_id")
    _require_path(runtime, "chains.base.chain_name")
    _require_path(runtime, "wallets.base_main_test.signer_ref")
    _require_path(runtime, "providers.debank.access_key_ref")
    _require_path(runtime, "providers.okx.api_key_ref")
    if runtime["app"]["execution_mode"] not in {"dry_run", "sign_only", "live"}:
        raise ConfigError("app.execution_mode must be dry_run, sign_only, or live")
    if int(runtime["chains"]["base"]["chain_id"]) != 8453:
        raise ConfigError("default base chain_id must be 8453")


def validate_risk_policy(policy: dict[str, Any]) -> None:
    max_single = _require_path(policy, "risk.max_single_trade_usd")
    _require_path(policy, "risk.max_daily_trade_usd")
    _require_path(policy, "risk.max_slippage_percent")
    _require_path(policy, "tokens.allowed_tokens")
    if float(max_single) > 5:
        raise ConfigError("example risk.max_single_trade_usd must be <= 5 for test safety")


def validate_strategies_config(strategies: dict[str, Any]) -> None:
    _require_path(strategies, "copy_trade.enabled")
    _require_path(strategies, "copy_trade.poll_interval_seconds")
    _require_path(strategies, "conditional_order.enabled")
    _require_path(strategies, "conditional_order.poll_interval_seconds")


def load_app_config(
    runtime_path: str | Path = "configs/runtime.example.yaml",
    risk_policy_path: str | Path = "configs/risk_policy.example.yaml",
    strategies_path: str | Path = "configs/strategies.example.yaml",
    env_path: str | Path | None = ".env",
) -> AppConfig:
    if env_path:
        load_dotenv(env_path, override=False)

    runtime = _load_yaml(runtime_path)
    risk_policy = _load_yaml(risk_policy_path)
    strategies = _load_yaml(strategies_path)
    if os.environ.get("APP_EXECUTION_MODE"):
        runtime.setdefault("app", {})["execution_mode"] = os.environ["APP_EXECUTION_MODE"]

    validate_runtime_config(runtime)
    validate_risk_policy(risk_policy)
    validate_strategies_config(strategies)

    return AppConfig(runtime=runtime, risk_policy=risk_policy, strategies=strategies)
