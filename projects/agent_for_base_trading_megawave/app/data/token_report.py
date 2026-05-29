from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.data.debank_client import DebankClient


@dataclass(frozen=True)
class TokenReport:
    token_info: dict[str, Any]
    price: str | None
    top_holders: list[Any]

    def format_telegram_message(self) -> str:
        symbol = self.token_info.get("symbol", "UNKNOWN")
        name = self.token_info.get("name", "UNKNOWN")
        address = self.token_info.get("id", self.token_info.get("address", ""))
        holder_count = len(self.top_holders)
        price = self.price if self.price is not None else "N/A"
        return (
            f"Token: {name} ({symbol})\n"
            f"Address: {address}\n"
            f"Price: {price}\n"
            f"Top holders: {holder_count}"
        )


@dataclass(frozen=True)
class TokenReportService:
    debank_client: DebankClient

    def build(self, token_address: str, chain_id: str = "base", holders_limit: int = 10) -> TokenReport:
        info = self.debank_client.get_token_info(token_address, chain_id=chain_id)
        price = None if info.get("price") is None else str(info.get("price"))
        holders = self.debank_client.get_top_holders(token_address, chain_id=chain_id, limit=holders_limit)
        return TokenReport(token_info=info, price=price, top_holders=holders)

