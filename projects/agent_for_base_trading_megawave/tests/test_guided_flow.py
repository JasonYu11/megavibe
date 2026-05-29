from __future__ import annotations

from decimal import Decimal

from app.bot.command_parser import TelegramCommandParser
from app.bot.guided_flow import GuidedTradeFlow
from app.core.order_info import ConditionalOrder, MarketOrder
from app.storage.sqlite_store import SQLiteStore

VIRTUAL = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"


def test_guided_flow_market_buy_requires_confirm_and_builds_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    flow = GuidedTradeFlow(store, TelegramCommandParser())

    assert "Choose trade type" in flow.start("chat1", "user1").text
    assert "token contract" in flow.handle("chat1", "user1", "Buy").text
    assert "amount" in flow.handle("chat1", "user1", VIRTUAL).text
    review = flow.handle("chat1", "user1", "0.01")

    assert review.order is None
    assert "Review: /buy" in review.text
    assert store.get_conversation_state("chat1:user1")["step"] == "awaiting_confirm"

    confirmed = flow.handle("chat1", "user1", "Confirm")

    assert isinstance(confirmed.order, MarketOrder)
    assert confirmed.order.token_in.symbol == "USDC"
    assert confirmed.order.token_out.symbol == "VIRTUAL"
    assert confirmed.order.amount.value == Decimal("0.01")
    assert store.get_conversation_state("chat1:user1") is None


def test_guided_flow_limit_sell_restores_from_sqlite_and_builds_conditional_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "orders.sqlite"
    first_flow = GuidedTradeFlow(SQLiteStore(db_path), TelegramCommandParser())
    first_flow.start("chat1", "user1")
    first_flow.handle("chat1", "user1", "Limit Sell")
    first_flow.handle("chat1", "user1", VIRTUAL)
    first_flow.handle("chat1", "user1", "10000")

    restored_flow = GuidedTradeFlow(SQLiteStore(db_path), TelegramCommandParser())
    review = restored_flow.handle("chat1", "user1", "1.8")
    confirmed = restored_flow.handle("chat1", "user1", "Confirm")

    assert "Review: /limit_sell" in review.text
    assert isinstance(confirmed.order, ConditionalOrder)
    assert confirmed.order.trigger.operator == ">="
    assert confirmed.order.trigger.target_price_usd == Decimal("1.8")
    market = confirmed.order.build_market_order()
    assert market.token_in.symbol == "VIRTUAL"
    assert market.token_out.symbol == "USDC"


def test_guided_flow_cancel_clears_state(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    flow = GuidedTradeFlow(store, TelegramCommandParser())
    flow.start("chat1", "user1")
    flow.handle("chat1", "user1", "Buy")

    result = flow.handle("chat1", "user1", "/cancel")

    assert result.cancelled is True
    assert store.get_conversation_state("chat1:user1") is None

