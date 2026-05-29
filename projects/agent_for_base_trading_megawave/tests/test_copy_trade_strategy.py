from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.core.order_info import TokenInfo
from app.strategies.copy_trade import CopyTradeConfig, CopyTradeStrategy


USDC_TOKEN = TokenInfo(
    symbol="USDC",
    address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    decimals=6,
)


def test_copy_trade_generates_order_intent_without_execution() -> None:
    history = {
        "history_list": [
            {
                "id": "0xhash",
                "sends": [{"token_id": "usdc", "amount": "1000"}],
                "receives": [{"token_id": "token", "amount": "10"}],
            }
        ],
        "token_dict": {
            "usdc": {"id": USDC_TOKEN.address, "symbol": "USDC", "decimals": 6},
            "token": {"id": "0x0000000000000000000000000000000000000001", "symbol": "TOKEN", "decimals": 18},
        },
    }
    strategy = CopyTradeStrategy(
        CopyTradeConfig(buy_ratio=Decimal("0.3"), max_copy_trade_usd=Decimal("3")),
        pay_token=USDC_TOKEN,
    )

    orders = strategy.generate_orders(history)

    assert len(orders) == 1
    assert orders[0].source == "copy_trade"
    assert orders[0].token_in.symbol == "USDC"
    assert orders[0].token_out.symbol == "TOKEN"
    assert orders[0].amount.value == Decimal("3")


def test_copy_trade_generates_sell_order_from_realistic_debank_swap() -> None:
    history = {
        "history_list": [
            {
                "id": "0xsell",
                "chain": "base",
                "cate_id": "swap",
                "tx": {"status": 1},
                "sends": [{"token_id": "token", "amount": 8}],
                "receives": [{"token_id": "usdc", "amount": 20}],
                "token_dict": {
                    "usdc": {"id": USDC_TOKEN.address, "optimized_symbol": "USDC", "decimals": 6},
                    "token": {"id": "0x0000000000000000000000000000000000000002", "display_symbol": "TOKEN", "decimals": 18},
                },
            }
        ]
    }
    strategy = CopyTradeStrategy(CopyTradeConfig(sell_ratio=Decimal("0.25")), pay_token=USDC_TOKEN)

    orders = strategy.generate_orders(history)

    assert len(orders) == 1
    assert orders[0].trade.side == "sell"
    assert orders[0].token_in.symbol == "TOKEN"
    assert orders[0].token_out.symbol == "USDC"
    assert orders[0].amount.value == Decimal("2.00")


def test_copy_trade_supports_inline_token_metadata_and_dict_transfer_shape() -> None:
    history = {
        "history_list": [
            {
                "id": "0xbuy",
                "chain": "base",
                "cate_id": "swap",
                "sends": {"token_id": "usdc", "amount": "4", "token": {"id": USDC_TOKEN.address, "symbol": "USDC", "decimals": 6}},
                "receives": {
                    "token_id": "token",
                    "amount": "100",
                    "token": {"id": "0x0000000000000000000000000000000000000003", "optimized_symbol": "COIN", "decimals": 18},
                },
            }
        ]
    }
    strategy = CopyTradeStrategy(CopyTradeConfig(buy_ratio=Decimal("0.5"), max_copy_trade_usd=Decimal("10")), pay_token=USDC_TOKEN)

    orders = strategy.generate_orders(history)

    assert len(orders) == 1
    assert orders[0].trade.side == "buy"
    assert orders[0].token_out.symbol == "COIN"
    assert orders[0].amount.value == Decimal("2.0")


def test_copy_trade_skips_failed_approval_and_non_base_history_items() -> None:
    history = {
        "history_list": [
            {
                "id": "0xfailed",
                "chain": "base",
                "cate_id": "swap",
                "tx": {"status": 0},
                "sends": [{"token_id": "usdc", "amount": "2"}],
                "receives": [{"token_id": "token", "amount": "1"}],
            },
            {
                "id": "0xapprove",
                "chain": "base",
                "cate_id": "approve",
                "sends": [{"token_id": "usdc", "amount": "2"}],
                "receives": [{"token_id": "token", "amount": "1"}],
            },
            {
                "id": "0xeth",
                "chain": "eth",
                "cate_id": "swap",
                "sends": [{"token_id": "usdc", "amount": "2"}],
                "receives": [{"token_id": "token", "amount": "1"}],
            },
        ],
        "token_dict": {
            "usdc": {"id": USDC_TOKEN.address, "symbol": "USDC", "decimals": 6},
            "token": {"id": "0x0000000000000000000000000000000000000004", "symbol": "TOKEN", "decimals": 18},
        },
    }
    strategy = CopyTradeStrategy(CopyTradeConfig(), pay_token=USDC_TOKEN)

    orders = strategy.generate_orders(history)

    assert orders == []


def test_copy_trade_debank_history_fixture_generates_buy_and_sell_intents() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "debank_history_base_swap.json"
    history = json.loads(fixture_path.read_text(encoding="utf-8"))
    strategy = CopyTradeStrategy(
        CopyTradeConfig(buy_ratio=Decimal("0.1"), sell_ratio=Decimal("0.25"), max_copy_trade_usd=Decimal("50")),
        pay_token=USDC_TOKEN,
    )

    orders = strategy.generate_orders(history)

    assert len(orders) == 2
    assert [order.trade.side for order in orders] == ["buy", "sell"]
    assert orders[0].source == "copy_trade"
    assert orders[0].token_in.symbol == "USDC"
    assert orders[0].token_out.symbol == "TARGET"
    assert orders[0].amount.value == Decimal("10.0")
    assert orders[1].token_in.symbol == "TARGET"
    assert orders[1].token_out.symbol == "USDC"
    assert orders[1].amount.value == Decimal("10.00")
