from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

from app.data.debank_client import DebankClient


@dataclass(frozen=True)
class DebankBalanceService:
    debank_client: DebankClient
    wallet_address: str
    chain_id: str = "base"
    cache_ttl_seconds: float = 60.0
    _cached_balance: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _cached_at: float = field(default=0.0, init=False, repr=False)

    def get_balance(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._cached_balance is not None and now - self._cached_at < self.cache_ttl_seconds:
            return dict(self._cached_balance)
        balance = dict(self.debank_client.get_user_chain_balance(self.wallet_address, chain_id=self.chain_id))
        if hasattr(self.debank_client, "get_user_token_list"):
            try:
                tokens = self.debank_client.get_user_token_list(self.wallet_address, chain_id=self.chain_id, is_all=True)
            except Exception:
                tokens = []
            key_tokens = []
            for token in tokens:
                symbol = str(token.get("symbol") or "").upper()
                if symbol in {"ETH", "USDC"}:
                    key_tokens.append(
                        {
                            "symbol": symbol,
                            "amount": token.get("amount"),
                            "price": token.get("price"),
                            "usd_value": token.get("usd_value"),
                        }
                    )
            if key_tokens:
                balance["key_tokens"] = key_tokens
        object.__setattr__(self, "_cached_balance", dict(balance))
        object.__setattr__(self, "_cached_at", now)
        return balance
