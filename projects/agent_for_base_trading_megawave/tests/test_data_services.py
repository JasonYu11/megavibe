from __future__ import annotations

from decimal import Decimal

from app.data.balance_service import DebankBalanceService
from app.data.price_provider import DebankPriceProvider
from app.data.token_resolver import TokenResolveError, TokenResolver


class FakeDebankClient:
    def get_token_price(self, token_address: str, chain_id: str = "base") -> str:
        assert chain_id == "base"
        return "1.23"

    def get_user_chain_balance(self, address: str, chain_id: str = "base") -> dict:
        assert address == "0xwallet"
        assert chain_id == "base"
        return {"total_usd_value": 12.34}

    def get_token_info(self, token_address: str, chain_id: str = "base") -> dict:
        assert chain_id == "base"
        return {"id": token_address, "symbol": "TEST", "decimals": 9, "price": "0.5"}


class CountingDebankClient:
    def __init__(self) -> None:
        self.balance_calls = 0
        self.token_list_calls = 0

    def get_user_chain_balance(self, address: str, chain_id: str = "base") -> dict:
        self.balance_calls += 1
        return {"total_usd_value": self.balance_calls}

    def get_user_token_list(self, address: str, chain_id: str = "base", is_all: bool = True) -> list[dict]:
        self.token_list_calls += 1
        return [{"symbol": "USDC", "amount": "9", "price": "1", "usd_value": "9"}]


def test_debank_price_provider_returns_decimal() -> None:
    provider = DebankPriceProvider(FakeDebankClient())

    assert provider.get_price_usd("0xtoken") == Decimal("1.23")


def test_debank_balance_service_returns_chain_balance() -> None:
    service = DebankBalanceService(FakeDebankClient(), wallet_address="0xwallet")

    assert service.get_balance()["total_usd_value"] == 12.34


def test_debank_balance_service_caches_short_repeated_reads() -> None:
    client = CountingDebankClient()
    service = DebankBalanceService(client, wallet_address="0xwallet", cache_ttl_seconds=60)

    first = service.get_balance()
    second = service.get_balance()

    assert first["total_usd_value"] == 1
    assert second["total_usd_value"] == 1
    assert client.balance_calls == 1
    assert client.token_list_calls == 1
    assert second["key_tokens"][0]["symbol"] == "USDC"


def test_token_resolver_uses_known_base_fallback_without_network() -> None:
    resolver = TokenResolver()

    token = resolver.resolve("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

    assert token["symbol"] == "USDC"
    assert token["decimals"] == 6
    assert token["metadata_source"] == "fallback"


def test_token_resolver_uses_debank_for_unknown_address() -> None:
    resolver = TokenResolver(FakeDebankClient())

    token = resolver.resolve("0x1111111111111111111111111111111111111111")

    assert token["symbol"] == "TEST"
    assert token["decimals"] == 9
    assert token["price_usd"] == "0.5"
    assert token["metadata_source"] == "debank"


def test_token_resolver_requires_debank_metadata_for_unknown_address() -> None:
    resolver = TokenResolver()

    try:
        resolver.resolve("0x1111111111111111111111111111111111111111")
    except TokenResolveError as exc:
        assert "token metadata unavailable" in str(exc)
    else:
        raise AssertionError("expected TokenResolveError")
