from __future__ import annotations

from app.core.order_info import MarketOrder
from app.risk.risk_engine import RiskEngine
from tests.test_order_info import market_payload


def policy() -> dict:
    return {
        "risk": {
            "max_single_trade_usd": 5,
            "max_daily_trade_usd": 20,
            "max_slippage_percent": 1.0,
            "max_price_impact_percent": 3.0,
            "copy_trade_max_price_impact_percent": 7.0,
            "allow_honeypot": False,
            "max_buy_tax_percent": 5.0,
            "max_sell_tax_percent": 5.0,
            "require_confirmation_for_all": True,
            "require_confirmation_for_natural_language": True,
        },
        "tokens": {
            "allow_unknown_tokens": False,
            "allowed_tokens": [
                {"symbol": "USDC", "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
                {"symbol": "VIRTUAL", "address": "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"},
            ],
        },
    }


def test_amount_over_limit_is_rejected() -> None:
    payload = market_payload()
    payload["amount"]["value"] = "10"
    order = MarketOrder.from_dict(payload)

    decision = RiskEngine(policy()).evaluate(order, {"priceImpactPercent": "0.1"})

    assert decision.decision == "REJECTED"
    assert decision.reason == "max_single_trade_usd"


def test_unknown_token_is_rejected() -> None:
    payload = market_payload()
    payload["token_out"] = {"symbol": "BAD", "address": "0x000000000000000000000000000000000000bAd0", "decimals": 18}
    order = MarketOrder.from_dict(payload)

    decision = RiskEngine(policy()).evaluate(order, {"priceImpactPercent": "0.1"})

    assert decision.decision == "REJECTED"
    assert decision.reason == "token_not_allowed"


def test_price_impact_over_limit_is_rejected() -> None:
    order = MarketOrder.from_dict(market_payload())

    decision = RiskEngine(policy()).evaluate(order, {"priceImpactPercent": "10"})

    assert decision.decision == "REJECTED"
    assert decision.reason == "max_price_impact_percent"


def test_copy_trade_uses_copy_specific_price_impact_limit() -> None:
    payload = market_payload()
    payload["source"] = "copy_trade"
    order = MarketOrder.from_dict(payload)

    decision = RiskEngine(policy()).evaluate(order, {"priceImpactPercent": "6.5"})

    assert decision.decision == "APPROVED"


def test_manual_trade_keeps_default_price_impact_limit() -> None:
    order = MarketOrder.from_dict(market_payload())

    decision = RiskEngine(policy()).evaluate(order, {"priceImpactPercent": "6.5"})

    assert decision.decision == "REJECTED"
    assert decision.reason == "max_price_impact_percent"


def test_natural_language_requires_confirmation() -> None:
    payload = market_payload()
    payload["source"] = "telegram_nl"
    order = MarketOrder.from_dict(payload)

    decision = RiskEngine(policy()).evaluate(order, {"priceImpactPercent": "0.1"})

    assert decision.decision == "APPROVED"
    assert decision.requires_confirmation is True


def test_daily_limit_rejects_when_context_total_would_exceed_policy() -> None:
    order = MarketOrder.from_dict(market_payload())

    decision = RiskEngine(policy()).evaluate(order, {"priceImpactPercent": "0.1"}, {"daily_trade_usd": "19"})

    assert decision.decision == "REJECTED"
    assert decision.reason == "max_daily_trade_usd"


def test_slippage_over_policy_limit_is_rejected() -> None:
    payload = market_payload()
    payload["safety"]["max_slippage_percent"] = "2"
    order = MarketOrder.from_dict(payload)

    decision = RiskEngine(policy()).evaluate(order, {"priceImpactPercent": "0.1"})

    assert decision.decision == "REJECTED"
    assert decision.reason == "max_slippage_percent"


def test_blocked_token_is_rejected_before_allowlist() -> None:
    risk_policy = policy()
    risk_policy["tokens"]["blocked_tokens"] = [{"address": "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"}]
    order = MarketOrder.from_dict(market_payload())

    decision = RiskEngine(risk_policy).evaluate(order, {"priceImpactPercent": "0.1"})

    assert decision.decision == "REJECTED"
    assert decision.reason == "token_blocked"


def test_blocked_contract_string_is_rejected() -> None:
    risk_policy = policy()
    risk_policy["tokens"]["blocked_contracts"] = ["0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"]
    order = MarketOrder.from_dict(market_payload())

    decision = RiskEngine(risk_policy).evaluate(order, {"priceImpactPercent": "0.1"})

    assert decision.decision == "REJECTED"
    assert decision.reason == "token_blocked"


def test_wallet_balance_context_rejects_insufficient_input_token() -> None:
    order = MarketOrder.from_dict(market_payload())

    decision = RiskEngine(policy()).evaluate(
        order,
        {"priceImpactPercent": "0.1"},
        {"wallet_balances": {"USDC": "1.99"}},
    )

    assert decision.decision == "REJECTED"
    assert decision.reason == "insufficient_balance"
