from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.order_info import MarketOrder
from app.core.order_state import OrderStatus
from app.storage.sqlite_store import SQLiteStore


COUNTED_DAILY_STATUSES = {
    OrderStatus.DRY_RUN_COMPLETED.value,
    OrderStatus.SIGNED_NOT_BROADCASTED.value,
    OrderStatus.BROADCASTED.value,
    OrderStatus.FILLED.value,
}


@dataclass
class SQLiteRiskContextProvider:
    store: SQLiteStore
    balance_service: Any | None = None

    def get_context(self, order: MarketOrder) -> dict[str, Any]:
        context: dict[str, Any] = {"daily_trade_usd": str(self.daily_trade_usd())}
        if self.balance_service is not None:
            context["wallet_balances"] = self._wallet_balances()
        return context

    def daily_trade_usd(self, day: str | None = None) -> Decimal:
        day = day or datetime.now(UTC).date().isoformat()
        total = Decimal("0")
        for row in self.store.list_orders(limit=1000):
            if not str(row["created_at"]).startswith(day):
                continue
            if row["status"] not in COUNTED_DAILY_STATUSES:
                continue
            payload = json.loads(row["payload_json"])
            order = MarketOrder.from_dict(payload)
            if order.token_in.symbol.upper() in {"USDC", "USDT", "DAI", "USD"}:
                total += order.amount.value
        return total

    def _wallet_balances(self) -> dict[str, str]:
        data = self.balance_service.get_balance()
        balances: dict[str, str] = {}
        if isinstance(data, dict) and isinstance(data.get("tokens"), list):
            for token in data["tokens"]:
                if not isinstance(token, dict):
                    continue
                amount = token.get("amount")
                if amount is None:
                    continue
                if token.get("symbol"):
                    balances[str(token["symbol"]).upper()] = str(amount)
                if token.get("id"):
                    balances[str(token["id"]).lower()] = str(amount)
        return balances
