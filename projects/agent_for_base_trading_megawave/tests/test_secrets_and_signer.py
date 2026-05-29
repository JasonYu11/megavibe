from __future__ import annotations

import subprocess

import pytest
from eth_account import Account

from app.secrets.provider import EnvSecretProvider, KeychainSecretProvider, SecretError
from app.signing.local_signer import LocalSigner


class StaticSecretProvider:
    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.calls = 0

    def resolve(self, secret_ref: str) -> str:
        self.calls += 1
        assert secret_ref == "TEST:PRIVATE_KEY"
        return self.secret


def test_env_secret_provider_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SECRET_VALUE", "secret-value")
    provider = EnvSecretProvider(env_path=None)

    assert provider.resolve("ENV:TEST_SECRET_VALUE") == "secret-value"


def test_env_secret_provider_missing_secret_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_SECRET_VALUE", raising=False)
    provider = EnvSecretProvider(env_path=None)

    with pytest.raises(SecretError, match="missing environment secret: TEST_SECRET_VALUE"):
        provider.resolve("ENV:TEST_SECRET_VALUE")


def test_keychain_secret_provider_reads_configured_test_secret() -> None:
    provider = KeychainSecretProvider()
    try:
        value = provider.resolve("KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1")
    except SecretError as exc:
        pytest.skip(f"local keychain test secret not available: {exc}")

    assert value
    assert len(value) >= 32


def test_local_signer_signs_without_broadcasting() -> None:
    account = Account.create()
    provider = StaticSecretProvider(account.key.hex())
    signer = LocalSigner(provider, {"base_main_test": "TEST:PRIVATE_KEY"})
    tx = {
        "nonce": 0,
        "gasPrice": 1,
        "gas": 21000,
        "to": "0x000000000000000000000000000000000000dEaD",
        "value": 0,
        "chainId": 8453,
    }

    signed = signer.sign_transaction("base_main_test", tx)

    assert signed.raw_transaction_hex.startswith("0x")
    assert signed.transaction_hash.startswith("0x")
    assert signed.signer_address == account.address
    assert signer.recover_signer(signed.raw_transaction_hex) == account.address
    assert provider.calls == 1


def test_local_signer_derives_address_without_exposing_private_key() -> None:
    account = Account.create()
    provider = StaticSecretProvider(account.key.hex())
    signer = LocalSigner(provider, {"base_main_test": "TEST:PRIVATE_KEY"})

    assert signer.get_address("base_main_test") == account.address
    assert provider.calls == 1


def test_importing_app_modules_does_not_touch_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("subprocess.run should not be called during import")

    monkeypatch.setattr(subprocess, "run", fail_run)
    import app.config.settings as settings
    import app.core.order_info as order_info
    import app.storage.sqlite_store as sqlite_store

    assert settings is not None
    assert order_info is not None
    assert sqlite_store is not None
