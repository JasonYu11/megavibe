from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.core.order_info import ConditionalOrder, MarketOrder, OrderValidationError


USDC = {
    "symbol": "USDC",
    "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "decimals": 6,
}
VIRTUAL = {
    "symbol": "VIRTUAL",
    "address": "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b",
    "decimals": 18,
}


def market_payload() -> dict:
    return {
        "order_type": "market",
        "source": "cli",
        "chain": {"chain_id": 8453},
        "wallet": {"wallet_id": "base_main_test"},
        "token_in": USDC,
        "token_out": VIRTUAL,
        "amount": {"type": "exact_in", "value": "2"},
        "safety": {"max_slippage_percent": "0.8"},
    }


def conditional_payload() -> dict:
    return {
        "order_type": "conditional",
        "source": "telegram_nl",
        "chain": {"chain_id": 8453},
        "wallet": {"wallet_id": "base_main_test"},
        "trigger": {
            "type": "price",
            "source": "debank",
            "token": VIRTUAL,
            "operator": "<=",
            "target_price_usd": "1.20",
            "poll_interval_seconds": 30,
        },
        "action": {
            "order_type": "market",
            "token_in": USDC,
            "token_out": VIRTUAL,
            "amount": {"type": "exact_in", "value": "2"},
            "trade": {"side": "buy", "route_provider": "okx"},
        },
        "safety": {"max_slippage_percent": "0.8", "max_price_impact_percent": "3.0"},
        "approval": {"require_confirmation_on_trigger": True, "confirmation_channel": "telegram"},
        "lifecycle": {"status": "active"},
    }


def test_market_order_minimal_payload_validates() -> None:
    order = MarketOrder.from_dict(market_payload())

    assert order.order_type == "market"
    assert order.chain.chain_id == 8453
    assert order.wallet.wallet_id == "base_main_test"
    assert order.amount.value == Decimal("2")
    assert order.amount.to_base_units(order.token_in.decimals) == 2_000_000


def test_market_order_missing_amount_fails() -> None:
    payload = market_payload()
    del payload["amount"]

    with pytest.raises(OrderValidationError, match="amount"):
        MarketOrder.from_dict(payload)


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity"])
def test_market_order_non_positive_or_non_finite_amount_fails(value: str) -> None:
    payload = market_payload()
    payload["amount"]["value"] = value

    with pytest.raises(OrderValidationError, match="amount.value"):
        MarketOrder.from_dict(payload)


def test_conditional_order_builds_market_order() -> None:
    conditional = ConditionalOrder.from_dict(conditional_payload())
    market = conditional.build_market_order()

    assert market.order_type == "market"
    assert market.source == "telegram_nl"
    assert market.wallet.wallet_id == "base_main_test"
    assert market.token_in.symbol == "USDC"
    assert market.token_out.symbol == "VIRTUAL"
    assert market.amount.value == Decimal("2")
    assert market.safety.max_slippage_percent == Decimal("0.8")
    assert market.trade.execution_mode == "watcher_triggered"


def test_market_order_payload_does_not_contain_secret_material() -> None:
    order = MarketOrder.from_dict(market_payload())

    serialized = json.dumps(order.to_dict()).lower()

    for forbidden in ["private_key", "signer_ref", "secret_ref", "api_key", "debank_access_key", "okx_secret"]:
        assert forbidden not in serialized
    assert "base_main_test" in serialized


def test_conditional_order_payload_does_not_contain_secret_material() -> None:
    order = ConditionalOrder.from_dict(conditional_payload())

    serialized = json.dumps(order.to_dict()).lower()

    for forbidden in ["private_key", "signer_ref", "secret_ref", "api_key", "debank_access_key", "okx_secret"]:
        assert forbidden not in serialized
    assert "base_main_test" in serialized


@pytest.mark.parametrize("value", ["0.1", "0.000001", "1000000000.123456"])
def test_amount_uses_decimal_precision(value: str) -> None:
    payload = market_payload()
    payload["amount"]["value"] = value
    order = MarketOrder.from_dict(payload)

    assert isinstance(order.amount.value, Decimal)
    base_units = order.amount.to_base_units(order.token_in.decimals)
    restored = Decimal(base_units) / (Decimal(10) ** order.token_in.decimals)
    assert restored == Decimal(value)


def test_amount_rejects_more_precision_than_token_decimals() -> None:
    payload = market_payload()
    payload["amount"]["value"] = "0.0000001"
    order = MarketOrder.from_dict(payload)

    with pytest.raises(OrderValidationError, match="more precision"):
        order.amount.to_base_units(order.token_in.decimals)
