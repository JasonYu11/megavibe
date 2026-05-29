from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from eth_account import Account

from app.config.settings import AppConfig, load_app_config
from app.secrets.provider import CompositeSecretProvider, SecretError, SecretProvider


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class EnvironmentReport:
    checks: list[CheckResult]

    @property
    def ok(self) -> bool:
        return all(check.status == "OK" for check in self.checks)

    def to_text(self) -> str:
        rows = ["name | status | detail", "--- | --- | ---"]
        for check in self.checks:
            rows.append(f"{check.name} | {check.status} | {check.detail}")
        return "\n".join(rows)


def _env_name(secret_ref: str) -> str:
    return secret_ref.split(":", 1)[1]


def _check_env_ref(name: str, secret_ref: str) -> CheckResult:
    env_name = _env_name(secret_ref)
    value = os.environ.get(env_name)
    if value:
        return CheckResult(name, "OK", f"{env_name} is set")
    return CheckResult(name, "MISSING", f"{env_name} is not set")


def _check_wallet(config: AppConfig, secret_provider: SecretProvider) -> CheckResult:
    wallet = config.runtime["wallets"]["base_main_test"]
    signer_ref = os.environ.get("LIVE_WALLET_SECRET_REF") or wallet["signer_ref"]
    check_name = "wallet.signer"
    try:
        private_key = secret_provider.resolve(signer_ref)
        address = Account.from_key(private_key).address
    except SecretError as exc:
        return CheckResult(check_name, "MISSING", str(exc))
    except Exception as exc:  # pragma: no cover - defensive for malformed test keys
        return CheckResult(check_name, "ERROR", f"configured signer key is invalid: {exc.__class__.__name__}")
    finally:
        private_key = ""

    configured_address = str(wallet.get("address", "")).lower()
    if configured_address and configured_address != "0x0000000000000000000000000000000000000000":
        if configured_address != address.lower():
            return CheckResult("wallet.address", "ERROR", f"derived address {address} does not match runtime config")
    source = "LIVE_WALLET_SECRET_REF" if os.environ.get("LIVE_WALLET_SECRET_REF") else "runtime signer_ref"
    return CheckResult(check_name, "OK", f"signer resolves via {source}; derived address {address}")


def build_environment_report(
    config: AppConfig | None = None,
    secret_provider: SecretProvider | None = None,
    env_path: str | None = ".env",
) -> EnvironmentReport:
    if env_path:
        load_dotenv(env_path, override=False)
    config = config or load_app_config(env_path=env_path)
    secret_provider = secret_provider or CompositeSecretProvider()

    checks: list[CheckResult] = []

    chain_id = int(config.runtime["chains"]["base"]["chain_id"])
    checks.append(
        CheckResult(
            "chain.base",
            "OK" if chain_id == 8453 else "ERROR",
            f"chain_id={chain_id}",
        )
    )
    checks.append(_check_env_ref("debank.access_key", config.runtime["providers"]["debank"]["access_key_ref"]))

    okx = config.runtime["providers"]["okx"]
    checks.extend(
        [
            _check_env_ref("okx.api_key", okx["api_key_ref"]),
            _check_env_ref("okx.secret_key", okx["secret_key_ref"]),
            _check_env_ref("okx.passphrase", okx["passphrase_ref"]),
            _check_env_ref("okx.project_id", okx["project_id_ref"]),
        ]
    )

    telegram = config.runtime.get("telegram", {})
    bot_token_ref = telegram.get("bot_token_ref")
    if bot_token_ref:
        checks.append(_check_env_ref("telegram.bot_token", bot_token_ref))
    chat_id = str(os.environ.get("TELEGRAM_DEFAULT_CHAT_ID") or telegram.get("default_chat_id", ""))
    checks.append(CheckResult("telegram.default_chat_id", "OK" if chat_id else "MISSING", "configured" if chat_id else "not set"))

    rpc_ref = config.runtime["chains"]["base"].get("rpc_url_ref")
    if isinstance(rpc_ref, str) and rpc_ref.startswith("ENV:"):
        checks.append(_check_env_ref("base.rpc_url", rpc_ref))

    checks.append(_check_wallet(config, secret_provider))
    return EnvironmentReport(checks)


def main() -> None:
    report = build_environment_report()
    print(report.to_text())


if __name__ == "__main__":
    main()
