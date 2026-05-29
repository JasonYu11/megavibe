from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.order_info import MarketOrder


@dataclass(frozen=True)
class RiskDecision:
    decision: str
    reason: str = ""
    requires_confirmation: bool = False

    @property
    def approved(self) -> bool:
        return self.decision == "APPROVED"


@dataclass(frozen=True)
class RiskEngine:
    policy: dict[str, Any]

    def evaluate(
        self,
        order: MarketOrder,
        quote: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> RiskDecision:
        risk = self.policy.get("risk", {})
        tokens = self.policy.get("tokens", {})
        context = context or {}
        amount_usd = self._estimate_amount_usd(order, quote)
        max_single = Decimal(str(risk.get("max_single_trade_usd", "0")))
        if max_single and amount_usd > max_single:
            return RiskDecision("REJECTED", "max_single_trade_usd")

        max_daily = Decimal(str(risk.get("max_daily_trade_usd", "0")))
        if max_daily:
            daily_used = self._decimal_or_zero(context.get("daily_trade_usd"))
            if daily_used + amount_usd > max_daily:
                return RiskDecision("REJECTED", "max_daily_trade_usd")

        max_slippage = Decimal(str(risk.get("max_slippage_percent", "0")))
        if max_slippage and order.safety.max_slippage_percent > max_slippage:
            return RiskDecision("REJECTED", "max_slippage_percent")

        blocked = self._blocked_addresses(tokens)
        if order.token_in.address.lower() in blocked or order.token_out.address.lower() in blocked:
            return RiskDecision("REJECTED", "token_blocked")

        if not self._has_sufficient_balance(order, context):
            return RiskDecision("REJECTED", "insufficient_balance")

        allow_unknown = bool(tokens.get("allow_unknown_tokens", False))
        allow_copy_unknown = order.source == "copy_trade" and bool(tokens.get("allow_unknown_copy_trade_tokens", False))
        if not allow_unknown and not allow_copy_unknown:
            allowed = {t["address"].lower() for t in tokens.get("allowed_tokens", []) if "address" in t}
            if order.token_in.address.lower() not in allowed or order.token_out.address.lower() not in allowed:
                return RiskDecision("REJECTED", "token_not_allowed")

        if quote:
            impact = self._quote_decimal(quote, "priceImpactPercent")
            max_impact = self._max_price_impact(order, risk)
            if impact is not None and max_impact and impact > max_impact:
                return RiskDecision("REJECTED", "max_price_impact_percent")

            if self._quote_bool(quote, "isHoneyPot") and not bool(risk.get("allow_honeypot", False)):
                return RiskDecision("REJECTED", "honeypot")

            tax = quote.get("taxRate") or {}
            if isinstance(tax, dict):
                buy_tax = self._decimal_or_zero(tax.get("buyTaxRate"))
                sell_tax = self._decimal_or_zero(tax.get("sellTaxRate"))
                if buy_tax > Decimal(str(risk.get("max_buy_tax_percent", "5"))):
                    return RiskDecision("REJECTED", "max_buy_tax_percent")
                if sell_tax > Decimal(str(risk.get("max_sell_tax_percent", "5"))):
                    return RiskDecision("REJECTED", "max_sell_tax_percent")

        requires_confirmation = bool(risk.get("require_confirmation_for_all", False))
        if order.source in {"telegram_nl", "agent"} and bool(risk.get("require_confirmation_for_natural_language", True)):
            requires_confirmation = True
        if order.approval.require_confirmation:
            requires_confirmation = True

        return RiskDecision("APPROVED", requires_confirmation=requires_confirmation)

    @staticmethod
    def _estimate_amount_usd(order: MarketOrder, quote: dict[str, Any] | None) -> Decimal:
        if order.token_in.symbol.upper() in {"USDC", "USDT", "DAI", "USD"}:
            return order.amount.value
        if quote and "amountUsd" in quote:
            return Decimal(str(quote["amountUsd"]))
        return Decimal("0")

    @staticmethod
    def _max_price_impact(order: MarketOrder, risk: dict[str, Any]) -> Decimal:
        if order.source == "copy_trade" and risk.get("copy_trade_max_price_impact_percent") is not None:
            return Decimal(str(risk.get("copy_trade_max_price_impact_percent", "0")))
        return Decimal(str(risk.get("max_price_impact_percent", "0")))

    @staticmethod
    def _decimal_or_zero(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value))

    @staticmethod
    def _blocked_addresses(tokens: dict[str, Any]) -> set[str]:
        blocked: set[str] = set()
        for key in ("blocked_tokens", "blocked_contracts"):
            for item in tokens.get(key, []) or []:
                if isinstance(item, str):
                    blocked.add(item.lower())
                elif isinstance(item, dict) and item.get("address"):
                    blocked.add(str(item["address"]).lower())
        return blocked

    @staticmethod
    def _has_sufficient_balance(order: MarketOrder, context: dict[str, Any]) -> bool:
        balances = context.get("wallet_balances")
        if not isinstance(balances, dict):
            return True
        candidates = [
            order.token_in.address.lower(),
            order.token_in.symbol.upper(),
            order.token_in.symbol,
        ]
        available = None
        for key in candidates:
            if key in balances:
                available = balances[key]
                break
        if available is None:
            return True
        return Decimal(str(available)) >= order.amount.value

    @classmethod
    def _quote_decimal(cls, quote: dict[str, Any], key: str) -> Decimal | None:
        if key in quote:
            return cls._decimal_or_zero(quote[key])
        data = quote.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict) and key in data[0]:
            return cls._decimal_or_zero(data[0][key])
        return None

    @staticmethod
    def _quote_bool(quote: dict[str, Any], key: str) -> bool:
        if key in quote:
            return str(quote[key]).lower() == "true"
        data = quote.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict) and key in data[0]:
            return str(data[0][key]).lower() == "true"
        return False
