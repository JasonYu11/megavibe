from __future__ import annotations

from app.core.order_info import MarketOrder
from app.core.order_state import OrderStatus
from app.risk.context import SQLiteRiskContextProvider
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_info import market_payload


class FakeBalanceService:
    def get_balance(self):  # type: ignore[no-untyped-def]
        return {
            "tokens": [
                {
                    "id": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                    "symbol": "USDC",
                    "amount": "4.5",
                }
            ]
        }


def test_sqlite_risk_context_sums_counted_daily_stable_orders(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    filled = MarketOrder.from_dict(market_payload())
    dry = MarketOrder.from_dict({**market_payload(), "id": "ord_dry"})
    pending = MarketOrder.from_dict({**market_payload(), "id": "ord_pending"})
    store.create_order(filled)
    store.update_order_status(filled.id, OrderStatus.FILLED)
    store.create_order(dry)
    store.update_order_status(dry.id, OrderStatus.DRY_RUN_COMPLETED)
    store.create_order(pending)
    store.update_order_status(pending.id, OrderStatus.PENDING_CONFIRMATION)

    context = SQLiteRiskContextProvider(store).get_context(filled)

    assert context["daily_trade_usd"] == "4"


def test_sqlite_risk_context_maps_balance_tokens_by_symbol_and_address(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = MarketOrder.from_dict(market_payload())

    context = SQLiteRiskContextProvider(store, FakeBalanceService()).get_context(order)

    assert context["wallet_balances"]["USDC"] == "4.5"
    assert context["wallet_balances"]["0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"] == "4.5"
