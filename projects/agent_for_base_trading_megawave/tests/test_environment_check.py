from __future__ import annotations

from eth_account import Account

from app.config.environment_check import build_environment_report
from app.config.settings import load_app_config
from app.secrets.provider import SecretProvider


class StaticWalletSecretProvider(SecretProvider):
    def __init__(self, private_key: str) -> None:
        self.private_key = private_key

    def resolve(self, secret_ref: str) -> str:
        assert secret_ref in {
            "KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1",
            "ENV:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1",
        }
        return self.private_key


def test_environment_report_marks_configured_and_missing_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    monkeypatch.setenv("DEBANK_ACCESS_KEY", "debank-secret")
    monkeypatch.setenv("BASE_RPC_URL", "https://mainnet.base.org")
    for name in ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_API_PASSPHRASE", "OKX_PROJECT_ID", "TELEGRAM_BOT_TOKEN"]:
        monkeypatch.delenv(name, raising=False)

    config = load_app_config(env_path=None)
    report = build_environment_report(config, StaticWalletSecretProvider(account.key.hex()), env_path=None)
    by_name = {check.name: check for check in report.checks}

    assert by_name["chain.base"].status == "OK"
    assert by_name["debank.access_key"].status == "OK"
    assert by_name["okx.api_key"].status == "MISSING"
    assert by_name["telegram.bot_token"].status == "MISSING"
    assert by_name["base.rpc_url"].status == "OK"
    assert by_name["wallet.signer"].status == "OK"
    assert "debank-secret" not in report.to_text()
    assert account.key.hex() not in report.to_text()


def test_environment_report_detects_wallet_address_mismatch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    monkeypatch.setenv("DEBANK_ACCESS_KEY", "debank-secret")
    monkeypatch.setenv("BASE_RPC_URL", "https://mainnet.base.org")
    config = load_app_config(env_path=None)
    config.runtime["wallets"]["base_main_test"]["address"] = "0x0000000000000000000000000000000000000001"

    report = build_environment_report(config, StaticWalletSecretProvider(account.key.hex()), env_path=None)
    by_name = {check.name: check for check in report.checks}

    assert by_name["wallet.address"].status == "ERROR"


def test_environment_report_uses_live_wallet_secret_ref_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    account = Account.create()
    monkeypatch.setenv("DEBANK_ACCESS_KEY", "debank-secret")
    monkeypatch.setenv("BASE_RPC_URL", "https://mainnet.base.org")
    monkeypatch.setenv("LIVE_WALLET_SECRET_REF", "ENV:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1")
    config = load_app_config(env_path=None)

    report = build_environment_report(config, StaticWalletSecretProvider(account.key.hex()), env_path=None)
    by_name = {check.name: check for check in report.checks}

    assert by_name["wallet.signer"].status == "OK"
    assert "LIVE_WALLET_SECRET_REF" in by_name["wallet.signer"].detail
    assert account.key.hex() not in report.to_text()
