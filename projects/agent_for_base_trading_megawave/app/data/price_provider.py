from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.debank_client import DebankClient


@dataclass(frozen=True)
class DebankPriceProvider:
    debank_client: DebankClient
    chain_id: str = "base"

    def get_price_usd(self, token_address: str) -> Decimal:
        price = self.debank_client.get_token_price(token_address, chain_id=self.chain_id)
        if price is None:
            raise ValueError(f"missing DeBank price for token: {token_address}")
        return Decimal(str(price))

