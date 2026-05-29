from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


class TokenResolveError(ValueError):
    """Raised when token metadata cannot be resolved safely."""


BASE_USDC = {
    "symbol": "USDC",
    "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "decimals": 6,
}

BASE_NATIVE_ETH = {
    "symbol": "ETH",
    "address": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    "decimals": 18,
}

BASE_WETH = {
    "symbol": "WETH",
    "address": "0x4200000000000000000000000000000000000006",
    "decimals": 18,
}

BASE_VIRTUAL = {
    "symbol": "VIRTUAL",
    "address": "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b",
    "decimals": 18,
}


@dataclass
class TokenResolver:
    debank_client: Any | None = None
    chain_id: str = "base"
    fallback_tokens: list[dict[str, Any]] = field(
        default_factory=lambda: [BASE_USDC, BASE_NATIVE_ETH, BASE_WETH, BASE_VIRTUAL]
    )

    def resolve(self, address: str) -> dict[str, Any]:
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", address):
            raise TokenResolveError(f"token address required: {address}")
        fallback = self._fallback(address)
        if fallback is not None:
            return {**fallback, "metadata_source": "fallback"}
        if self.debank_client is None:
            raise TokenResolveError(f"token metadata unavailable: {address}")
        info = self.debank_client.get_token_info(address, chain_id=self.chain_id)
        return self._from_debank(address, info)

    def _fallback(self, address: str) -> dict[str, Any] | None:
        normalized = address.lower()
        for token in self.fallback_tokens:
            if str(token["address"]).lower() == normalized:
                return dict(token)
        return None

    @staticmethod
    def _from_debank(address: str, info: dict[str, Any]) -> dict[str, Any]:
        decimals = info.get("decimals")
        if decimals is None:
            raise TokenResolveError(f"token decimals unavailable: {address}")
        try:
            decimals_int = int(decimals)
        except (TypeError, ValueError) as exc:
            raise TokenResolveError(f"invalid token decimals: {address}") from exc
        if decimals_int < 0:
            raise TokenResolveError(f"invalid token decimals: {address}")
        token = {
            "symbol": str(info.get("symbol") or address),
            "address": str(info.get("id") or info.get("address") or address),
            "decimals": decimals_int,
            "metadata_source": "debank",
        }
        price = info.get("price")
        if price is not None:
            token["price_usd"] = str(Decimal(str(price)))
        return token

