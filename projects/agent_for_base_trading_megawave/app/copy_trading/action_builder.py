from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any

from app.copy_trading.models import CopyActionStatus, CopyTargetConfig, CopyTradeAction, CopyTradeActionGroup, CopyTradeIntent, CopyTradeKind
from app.core.order_info import MarketOrder, TokenInfo


USDC_TOKEN = TokenInfo(
    symbol="USDC",
    address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    decimals=6,
)


@dataclass(frozen=True)
class CopyTradeActionBuilder:
    pay_token: TokenInfo = USDC_TOKEN
    wallet_id: str = "base_main_test"
    wallet_address: str | None = None
    balance_provider: Any | None = None

    def build(self, target: CopyTargetConfig, intent: CopyTradeIntent) -> CopyTradeActionGroup:
        if intent.kind == CopyTradeKind.STABLE_OR_ETH_TO_TOKEN:
            amount = self._copy_usd_amount(target, intent.estimated_usd_value)
            actions = [self._buy_action(intent.received.token, amount)]
        elif intent.kind == CopyTradeKind.TOKEN_TO_STABLE_OR_ETH:
            actions = [self._sell_action(intent.sent.token, target)]
        elif intent.kind == CopyTradeKind.TOKEN_TO_TOKEN:
            amount = self._copy_usd_amount(target, intent.estimated_usd_value)
            actions = [self._buy_action(intent.received.token, amount), self._sell_action(intent.sent.token, target)]
        else:
            actions = [CopyTradeAction(label="忽略", side="skip", status=CopyActionStatus.SKIPPED, reason=intent.kind.value)]
        return CopyTradeActionGroup(target=target, intent=intent, actions=actions)

    def _copy_usd_amount(self, target: CopyTargetConfig, source_usd_value: Decimal) -> Decimal:
        amount = source_usd_value * target.copy_ratio
        if amount > target.max_copy_trade_usd:
            amount = target.max_copy_trade_usd
        return amount

    def _buy_action(self, token_out: TokenInfo, amount: Decimal) -> CopyTradeAction:
        amount = _normalize_amount(self.pay_token, amount)
        if amount <= 0:
            return CopyTradeAction(
                label="买入",
                side="buy",
                token_in=self.pay_token,
                token_out=token_out,
                amount=amount,
                status=CopyActionStatus.FAILED,
                reason="amount_below_token_precision",
            )
        order = self._market_order(token_in=self.pay_token, token_out=token_out, amount=amount, side="buy")
        return CopyTradeAction(label="买入", side="buy", token_in=self.pay_token, token_out=token_out, amount=amount, order=order)

    def _sell_action(self, token_in: TokenInfo, target: CopyTargetConfig) -> CopyTradeAction:
        balance = self._token_balance(token_in)
        if balance <= 0:
            return CopyTradeAction(
                label="卖出",
                side="sell",
                token_in=token_in,
                token_out=self.pay_token,
                amount=Decimal("0"),
                status=CopyActionStatus.FAILED,
                reason="balance_zero",
            )
        amount = balance * target.copy_ratio
        amount = _normalize_amount(token_in, amount)
        if amount <= 0:
            return CopyTradeAction(
                label="卖出",
                side="sell",
                token_in=token_in,
                token_out=self.pay_token,
                amount=amount,
                status=CopyActionStatus.FAILED,
                reason="amount_below_token_precision",
            )
        order = self._market_order(token_in=token_in, token_out=self.pay_token, amount=amount, side="sell")
        return CopyTradeAction(label="卖出", side="sell", token_in=token_in, token_out=self.pay_token, amount=amount, order=order)

    def _market_order(self, token_in: TokenInfo, token_out: TokenInfo, amount: Decimal, side: str) -> MarketOrder:
        wallet = {"wallet_id": self.wallet_id}
        if self.wallet_address:
            wallet["address"] = self.wallet_address
        return MarketOrder.from_dict(
            {
                "order_type": "market",
                "source": "copy_trade",
                "chain": {"namespace": "evm", "chain_id": 8453, "chain_name": "base"},
                "wallet": wallet,
                "token_in": token_in.__dict__,
                "token_out": token_out.__dict__,
                "amount": {"type": "exact_in", "value": str(amount), "unit": "token"},
                "trade": {"side": side, "route_provider": "okx", "execution_mode": "copy_watcher"},
                "approval": {"require_confirmation": False, "confirmation_channel": "copy_watcher"},
            }
        )

    def _token_balance(self, token: TokenInfo) -> Decimal:
        provider = self.balance_provider
        if provider is None:
            return Decimal("0")
        if callable(provider):
            return _decimal(provider(token))
        if hasattr(provider, "get_token_balance"):
            return _decimal(provider.get_token_balance(token))
        if hasattr(provider, "get_balance"):
            return _balance_from_summary(provider.get_balance(), token)
        return Decimal("0")


@dataclass(frozen=True)
class DebankTokenBalanceProvider:
    debank_client: Any
    wallet_address: str
    chain_id: str = "base"

    def get_token_balance(self, token: TokenInfo) -> Decimal:
        try:
            tokens = self.debank_client.get_user_token_list(self.wallet_address, chain_id=self.chain_id, is_all=True)
        except Exception:
            return Decimal("0")
        for item in tokens:
            if not isinstance(item, dict):
                continue
            address = str(item.get("id") or item.get("address") or "").lower()
            symbol = str(item.get("symbol") or "").upper()
            if address == token.address.lower() or symbol == token.symbol.upper():
                return _decimal(item.get("amount"))
        return Decimal("0")


def _balance_from_summary(balance: dict[str, Any], token: TokenInfo) -> Decimal:
    tokens = []
    for key in ("tokens", "key_tokens"):
        value = balance.get(key)
        if isinstance(value, list):
            tokens.extend(item for item in value if isinstance(item, dict))
    for item in tokens:
        address = str(item.get("address") or "").lower()
        symbol = str(item.get("symbol") or "").upper()
        if address == token.address.lower() or symbol == token.symbol.upper():
            return _decimal(item.get("amount"))
    return Decimal("0")


def _decimal(value: Any) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except Exception:
        return Decimal("0")
    return decimal if decimal.is_finite() else Decimal("0")


def _normalize_amount(token: TokenInfo, amount: Decimal) -> Decimal:
    if amount <= 0:
        return Decimal("0")
    step = Decimal(1) / (Decimal(10) ** token.decimals)
    return amount.quantize(step, rounding=ROUND_DOWN)
