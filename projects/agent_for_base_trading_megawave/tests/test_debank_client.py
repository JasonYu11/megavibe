from __future__ import annotations

import pytest
import requests

from app.data.debank_client import DebankClient, DebankClientError
from app.secrets.provider import EnvSecretProvider, SecretError


class StaticSecretProvider:
    def resolve(self, secret_ref: str) -> str:
        assert secret_ref == "ENV:DEBANK_ACCESS_KEY"
        return "test-key"


class FakeResponse:
    def __init__(self, payload, status_error: Exception | None = None):  # type: ignore[no-untyped-def]
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self) -> None:
        if self.status_error:
            raise self.status_error

    def json(self):  # type: ignore[no-untyped-def]
        return self.payload


class FakeSession:
    def __init__(self, payload):  # type: ignore[no-untyped-def]
        self.payload = payload
        self.calls = []

    def get(self, url, params, headers, timeout):  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse(self.payload)


def test_token_info_query_uses_debank_not_basescan() -> None:
    session = FakeSession([{"symbol": "USDC", "decimals": 6, "price": 1}])
    client = DebankClient("ENV:DEBANK_ACCESS_KEY", StaticSecretProvider(), session=session)

    info = client.get_token_info("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

    assert info["symbol"] == "USDC"
    assert session.calls[0]["url"].endswith("/token/list_by_ids")
    assert "basescan" not in session.calls[0]["url"].lower()
    assert session.calls[0]["headers"]["AccessKey"] == "test-key"


def test_user_history_parse_transfers() -> None:
    payload = {
        "history_list": [
            {
                "id": "0xhash",
                "time_at": 123,
                "cate_id": "swap",
                "sends": [{"token_id": "usdc", "amount": 2}],
                "receives": [{"token_id": "virtual", "amount": 1}],
            }
        ],
        "token_dict": {"usdc": {"symbol": "USDC"}},
    }
    client = DebankClient("ENV:DEBANK_ACCESS_KEY", StaticSecretProvider(), session=FakeSession(payload))

    history = client.get_user_history("0x0000000000000000000000000000000000000001")
    parsed = client.parse_history_transfers(history)

    assert parsed[0]["id"] == "0xhash"
    assert parsed[0]["sends"][0]["token_id"] == "usdc"
    assert parsed[0]["receives"][0]["token_id"] == "virtual"
    assert parsed[0]["token_dict"]["usdc"]["symbol"] == "USDC"


def test_top_holders_query_returns_list() -> None:
    client = DebankClient("ENV:DEBANK_ACCESS_KEY", StaticSecretProvider(), session=FakeSession([["0xabc", 100]]))

    holders = client.get_top_holders("0xtoken", limit=10)

    assert holders == [["0xabc", 100]]


def test_debank_http_error_is_explicit() -> None:
    class ErrorSession(FakeSession):
        def get(self, url, params, headers, timeout):  # type: ignore[no-untyped-def]
            return FakeResponse({}, requests.HTTPError("boom"))

    client = DebankClient("ENV:DEBANK_ACCESS_KEY", StaticSecretProvider(), session=ErrorSession({}))

    with pytest.raises(DebankClientError, match="debank request failed"):
        client.get_token_info("0xtoken")


def test_debank_missing_api_key_fails_without_secret_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEBANK_ACCESS_KEY", raising=False)
    client = DebankClient("ENV:DEBANK_ACCESS_KEY", EnvSecretProvider(env_path=None), session=FakeSession([]))

    with pytest.raises(SecretError) as exc:
        client.get_token_info("0xtoken")

    assert "missing environment secret: DEBANK_ACCESS_KEY" in str(exc.value)
    assert "test-key" not in str(exc.value)
