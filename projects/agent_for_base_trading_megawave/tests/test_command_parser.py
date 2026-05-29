from __future__ import annotations

from decimal import Decimal

import pytest

from app.bot.command_parser import CommandParseError, TelegramCommandParser
from app.core.order_info import ConditionalOrder, MarketOrder

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
ETH = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
VIRTUAL = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"


def test_buy_command_parses_to_market_order() -> None:
    order = TelegramCommandParser().parse(f"/buy {VIRTUAL} 5")

    assert isinstance(order, MarketOrder)
    assert order.source == "telegram_command"
    assert order.token_in.symbol == "USDC"
    assert order.token_out.symbol == "VIRTUAL"
    assert order.amount.value == Decimal("5")


def test_buy_command_can_override_default_input_token() -> None:
    order = TelegramCommandParser().parse(f"/buy {VIRTUAL} 0.01 --with {ETH}")

    assert isinstance(order, MarketOrder)
    assert order.token_in.symbol == "ETH"
    assert order.token_out.symbol == "VIRTUAL"
    assert order.amount.value == Decimal("0.01")


def test_sell_command_defaults_output_to_usdc() -> None:
    order = TelegramCommandParser().parse(f"/sell {VIRTUAL} 10000")

    assert isinstance(order, MarketOrder)
    assert order.token_in.symbol == "VIRTUAL"
    assert order.token_out.symbol == "USDC"
    assert order.amount.value == Decimal("10000")


def test_sell_command_can_override_default_output_token() -> None:
    order = TelegramCommandParser().parse(f"/sell {VIRTUAL} 10000 --to {ETH}")

    assert isinstance(order, MarketOrder)
    assert order.token_in.symbol == "VIRTUAL"
    assert order.token_out.symbol == "ETH"
    assert order.amount.value == Decimal("10000")


def test_quote_command_does_not_create_order() -> None:
    result = TelegramCommandParser().parse(f"/quote {USDC} {VIRTUAL} 5")

    assert isinstance(result, dict)
    assert result["command"] == "quote"
    assert result["amount"] == Decimal("5")


def test_limit_buy_command_parses_to_conditional_order() -> None:
    order = TelegramCommandParser().parse(f"/limit_buy {VIRTUAL} 5 at 1.2")

    assert isinstance(order, ConditionalOrder)
    assert order.trigger.operator == "<="
    assert order.trigger.target_price_usd == Decimal("1.2")
    market = order.build_market_order()
    assert market.token_in.symbol == "USDC"
    assert market.token_out.symbol == "VIRTUAL"


def test_limit_sell_command_parses_to_conditional_order() -> None:
    order = TelegramCommandParser().parse(f"/limit_sell {VIRTUAL} 10000 at 1.8")

    assert isinstance(order, ConditionalOrder)
    assert order.trigger.operator == ">="
    assert order.trigger.target_price_usd == Decimal("1.8")
    market = order.build_market_order()
    assert market.token_in.symbol == "VIRTUAL"
    assert market.token_out.symbol == "USDC"
    assert market.amount.value == Decimal("10000")


def test_confirm_reject_cancel_parse_order_id() -> None:
    parser = TelegramCommandParser()

    assert parser.parse("/status") == {"command": "status"}
    assert parser.parse("/mode") == {"command": "mode"}
    assert parser.parse("/balance") == {"command": "balance"}
    assert parser.parse("/orders") == {"command": "orders"}
    assert parser.parse("/start") == {"command": "start"}
    assert parser.parse("/help") == {"command": "help"}
    assert parser.parse("/history") == {"command": "history"}
    assert parser.parse("/order ord_1") == {"command": "order", "order_id": "ord_1"}
    assert parser.parse("/confirm ord_1") == {"command": "confirm", "order_id": "ord_1"}
    assert parser.parse("/reject ord_1") == {"command": "reject", "order_id": "ord_1"}
    assert parser.parse("/cancel ord_1") == {"command": "cancel", "order_id": "ord_1"}


def test_market_order_includes_configured_wallet_address() -> None:
    wallet = "0x0000000000000000000000000000000000000001"
    parser = TelegramCommandParser(wallet_address=wallet)

    order = parser.parse(f"/buy {VIRTUAL} 1")

    assert isinstance(order, MarketOrder)
    assert order.wallet.address == wallet


def test_unknown_command_fails() -> None:
    with pytest.raises(CommandParseError, match="unknown command"):
        TelegramCommandParser().parse("/nope")


def test_trade_commands_reject_symbol_token_input() -> None:
    with pytest.raises(CommandParseError, match="token address required"):
        TelegramCommandParser().parse("/buy VIRTUAL 5")


@pytest.mark.parametrize(
    "command, message",
    [
        (f"/buy {VIRTUAL} nope", "invalid amount"),
        (f"/buy {VIRTUAL} 0", "amount must be positive"),
        (f"/quote {USDC} {VIRTUAL} -1", "amount must be positive"),
        (f"/limit_buy {VIRTUAL} 5 at 0", "target_price must be positive"),
        (f"/limit_sell {VIRTUAL} 0 at 1.8", "amount must be positive"),
    ],
)
def test_amount_parse_errors_are_command_parse_errors(command: str, message: str) -> None:
    with pytest.raises(CommandParseError, match=message):
        TelegramCommandParser().parse(command)
