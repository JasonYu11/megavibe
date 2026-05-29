from __future__ import annotations

import json

from app.execution.okx_client import OkxDexClient
from app.secrets.provider import EnvSecretProvider, SecretError


class StaticSecretProvider:
    values = {
        "ENV:OKX_API_KEY": "api-key",
        "ENV:OKX_SECRET_KEY": "secret",
        "ENV:OKX_API_PASSPHRASE": "passphrase",
        "ENV:OKX_PROJECT_ID": "project",
    }

    def resolve(self, secret_ref: str) -> str:
        return self.values[secret_ref]


class FakeResponse:
    def __init__(self, payload):  # type: ignore[no-untyped-def]
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):  # type: ignore[no-untyped-def]
        return self.payload


class FakeSession:
    def __init__(self):  # type: ignore[no-untyped-def]
        self.get_calls = []
        self.post_calls = []

    def get(self, url, params, headers, timeout):  # type: ignore[no-untyped-def]
        self.get_calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if url.endswith("/api/v6/dex/aggregator/swap"):
            return FakeResponse(
                {
                    "code": "0",
                    "data": [
                        {
                            "tx": {
                                "to": "0x000000000000000000000000000000000000dEaD",
                                "data": "0xabcdef",
                                "value": "0",
                                "gas": "21000",
                                "gasPrice": "1",
                            }
                        }
                    ],
                }
            )
        if url.endswith("/api/v6/dex/aggregator/approve-transaction"):
            return FakeResponse(
                {
                    "code": "0",
                    "data": [
                        {
                            "dexContractAddress": "0x000000000000000000000000000000000000dEaD",
                            "data": "0x095ea7b3",
                            "gasLimit": "50000",
                        }
                    ],
                }
            )
        if url.endswith("/api/v6/dex/post-transaction/orders"):
            return FakeResponse({"code": "0", "data": [{"orderId": "abc", "status": "success"}]})
        return FakeResponse({"code": "0", "data": [{"priceImpactPercent": "0.1"}]})

    def post(self, url, data, headers, timeout):  # type: ignore[no-untyped-def]
        self.post_calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return FakeResponse({"code": "0", "data": [{"orderId": "abc"}]})


def client_with_fake_session() -> tuple[OkxDexClient, FakeSession]:
    session = FakeSession()
    client = OkxDexClient(
        "ENV:OKX_API_KEY",
        "ENV:OKX_SECRET_KEY",
        "ENV:OKX_API_PASSPHRASE",
        "ENV:OKX_PROJECT_ID",
        StaticSecretProvider(),
        session=session,
    )
    return client, session


def test_okx_quote_uses_v6_path_and_does_not_broadcast() -> None:
    client, session = client_with_fake_session()

    data = client.quote(8453, "USDC", "VIRTUAL", 2_000_000, "0.8")

    assert data["code"] == "0"
    assert session.get_calls[0]["url"].endswith("/api/v6/dex/aggregator/quote")
    assert session.get_calls[0]["params"]["chainIndex"] == "8453"
    assert not session.post_calls


def test_okx_swap_uses_v6_path() -> None:
    client, session = client_with_fake_session()

    response = client.swap(8453, "USDC", "VIRTUAL", 2_000_000, "0.8", "0xwallet")

    assert session.get_calls[0]["url"].endswith("/api/v6/dex/aggregator/swap")
    assert session.get_calls[0]["params"]["userWalletAddress"] == "0xwallet"
    assert session.get_calls[0]["params"]["slippagePercent"] == "0.8"
    assert "slippage" not in session.get_calls[0]["params"]
    tx = response["data"][0]["tx"]
    assert {"to", "data", "value", "gas", "gasPrice"}.issubset(tx)
    assert not session.post_calls


def test_okx_approve_transaction_uses_v6_path_and_does_not_broadcast() -> None:
    client, session = client_with_fake_session()

    response = client.approve_transaction(8453, "USDC", 2_000_000)

    assert response["code"] == "0"
    assert session.get_calls[0]["url"].endswith("/api/v6/dex/aggregator/approve-transaction")
    assert session.get_calls[0]["params"]["tokenContractAddress"] == "USDC"
    assert session.get_calls[0]["params"]["approveAmount"] == "2000000"
    assert response["data"][0]["data"].startswith("0x")
    assert not session.post_calls


def test_okx_broadcast_is_separate_explicit_call() -> None:
    client, session = client_with_fake_session()

    data = client.broadcast(8453, "0xsigned", "0xwallet", enable_mev_protection=True)

    assert data["data"][0]["orderId"] == "abc"
    assert session.post_calls[0]["url"].endswith("/api/v6/dex/pre-transaction/broadcast-transaction")
    body = json.loads(session.post_calls[0]["data"])
    assert body["signedTx"] == "0xsigned"


def test_okx_get_order_status_uses_v5_path() -> None:
    client, session = client_with_fake_session()

    response = client.get_order_status(8453, "okx_order_1", "0xwallet")

    assert response["data"][0]["status"] == "success"
    assert session.get_calls[0]["url"].endswith("/api/v6/dex/post-transaction/orders")
    assert session.get_calls[0]["params"] == {
        "chainIndex": "8453",
        "orderId": "okx_order_1",
        "address": "0xwallet",
        "limit": "1",
    }
    assert not session.post_calls


def test_okx_missing_key_fails_before_network_without_secret_value(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OKX_API_KEY", raising=False)
    monkeypatch.setenv("OKX_SECRET_KEY", "do-not-leak-secret-key")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "do-not-leak-passphrase")
    monkeypatch.setenv("OKX_PROJECT_ID", "do-not-leak-project")
    session = FakeSession()
    client = OkxDexClient(
        "ENV:OKX_API_KEY",
        "ENV:OKX_SECRET_KEY",
        "ENV:OKX_API_PASSPHRASE",
        "ENV:OKX_PROJECT_ID",
        EnvSecretProvider(env_path=None),
        session=session,
    )

    try:
        client.quote(8453, "USDC", "VIRTUAL", 2_000_000, "0.8")
    except SecretError as exc:
        assert "missing environment secret: OKX_API_KEY" in str(exc)
        assert "do-not-leak" not in str(exc)
        assert session.get_calls == []
    else:
        raise AssertionError("missing OKX_API_KEY should fail before network")
