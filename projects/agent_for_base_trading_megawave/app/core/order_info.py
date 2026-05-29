from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4


class OrderValidationError(ValueError):
    """Raised when order info is incomplete or invalid."""


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except Exception as exc:
        raise OrderValidationError(f"invalid decimal field: {field_name}") from exc
    if not decimal.is_finite():
        raise OrderValidationError(f"invalid decimal field: {field_name}")
    return decimal


def _require(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise OrderValidationError(f"missing required field: {key}")
    return mapping[key]


@dataclass(frozen=True)
class ChainInfo:
    namespace: str = "evm"
    chain_id: int = 8453
    chain_name: str = "base"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChainInfo":
        chain_id = int(data.get("chain_id", 8453))
        if chain_id != 8453:
            raise OrderValidationError("phase1 default chain must be Base chain_id 8453")
        return cls(
            namespace=str(data.get("namespace", "evm")),
            chain_id=chain_id,
            chain_name=str(data.get("chain_name", "base")),
        )


@dataclass(frozen=True)
class WalletRef:
    wallet_id: str
    address: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WalletRef":
        return cls(wallet_id=str(_require(data, "wallet_id")), address=data.get("address"))


@dataclass(frozen=True)
class TokenInfo:
    symbol: str
    address: str
    decimals: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenInfo":
        return cls(
            symbol=str(_require(data, "symbol")),
            address=str(_require(data, "address")),
            decimals=int(_require(data, "decimals")),
        )


@dataclass(frozen=True)
class AmountInfo:
    type: str
    value: Decimal
    unit: str = "token"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AmountInfo":
        value = _decimal(_require(data, "value"), "amount.value")
        if value <= 0:
            raise OrderValidationError("amount.value must be positive")
        return cls(
            type=str(data.get("type", "exact_in")),
            value=value,
            unit=str(data.get("unit", "token")),
        )

    def to_base_units(self, decimals: int) -> int:
        scale = Decimal(10) ** decimals
        scaled = self.value * scale
        try:
            integral = scaled.to_integral_exact()
        except InvalidOperation as exc:
            raise OrderValidationError("amount.value has more precision than token decimals") from exc
        if scaled != integral:
            raise OrderValidationError("amount.value has more precision than token decimals")
        base_units = int(integral)
        if base_units <= 0:
            raise OrderValidationError("amount.value converts to zero base units")
        return base_units


@dataclass(frozen=True)
class SafetyInfo:
    max_slippage_percent: Decimal = Decimal("1.0")
    max_price_impact_percent: Decimal = Decimal("3.0")
    allow_partial_fill: bool = False
    allow_honeypot: bool = False
    max_buy_tax_percent: Decimal = Decimal("5.0")
    max_sell_tax_percent: Decimal = Decimal("5.0")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SafetyInfo":
        data = data or {}
        return cls(
            max_slippage_percent=_decimal(data.get("max_slippage_percent", "1.0"), "safety.max_slippage_percent"),
            max_price_impact_percent=_decimal(data.get("max_price_impact_percent", "3.0"), "safety.max_price_impact_percent"),
            allow_partial_fill=bool(data.get("allow_partial_fill", False)),
            allow_honeypot=bool(data.get("allow_honeypot", False)),
            max_buy_tax_percent=_decimal(data.get("max_buy_tax_percent", "5.0"), "safety.max_buy_tax_percent"),
            max_sell_tax_percent=_decimal(data.get("max_sell_tax_percent", "5.0"), "safety.max_sell_tax_percent"),
        )


@dataclass(frozen=True)
class ApprovalInfo:
    require_confirmation: bool = True
    confirmation_channel: str = "telegram"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ApprovalInfo":
        data = data or {}
        return cls(
            require_confirmation=bool(data.get("require_confirmation", True)),
            confirmation_channel=str(data.get("confirmation_channel", "telegram")),
        )


@dataclass(frozen=True)
class TradeInfo:
    side: str = "swap"
    route_provider: str = "okx"
    execution_mode: str = "immediate"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TradeInfo":
        data = data or {}
        return cls(
            side=str(data.get("side", "swap")),
            route_provider=str(data.get("route_provider", "okx")),
            execution_mode=str(data.get("execution_mode", "immediate")),
        )


@dataclass(frozen=True)
class MarketOrder:
    source: str
    chain: ChainInfo
    wallet: WalletRef
    token_in: TokenInfo
    token_out: TokenInfo
    amount: AmountInfo
    trade: TradeInfo = field(default_factory=TradeInfo)
    safety: SafetyInfo = field(default_factory=SafetyInfo)
    approval: ApprovalInfo = field(default_factory=ApprovalInfo)
    order_type: str = "market"
    id: str = field(default_factory=lambda: f"ord_{uuid4().hex}")
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketOrder":
        order_type = data.get("order_type", "market")
        if order_type != "market":
            raise OrderValidationError("MarketOrder requires order_type=market")
        return cls(
            id=str(data.get("id") or f"ord_{uuid4().hex}"),
            source=str(_require(data, "source")),
            chain=ChainInfo.from_dict(_require(data, "chain")),
            wallet=WalletRef.from_dict(_require(data, "wallet")),
            token_in=TokenInfo.from_dict(_require(data, "token_in")),
            token_out=TokenInfo.from_dict(_require(data, "token_out")),
            amount=AmountInfo.from_dict(_require(data, "amount")),
            trade=TradeInfo.from_dict(data.get("trade")),
            safety=SafetyInfo.from_dict(data.get("safety")),
            approval=ApprovalInfo.from_dict(data.get("approval")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "order_type": self.order_type,
            "created_at": self.created_at,
            "chain": self.chain.__dict__,
            "wallet": self.wallet.__dict__,
            "token_in": self.token_in.__dict__,
            "token_out": self.token_out.__dict__,
            "amount": {**self.amount.__dict__, "value": str(self.amount.value)},
            "trade": self.trade.__dict__,
            "safety": {k: str(v) if isinstance(v, Decimal) else v for k, v in self.safety.__dict__.items()},
            "approval": self.approval.__dict__,
        }


@dataclass(frozen=True)
class PriceTrigger:
    source: str
    token: TokenInfo
    operator: str
    target_price_usd: Decimal
    poll_interval_seconds: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PriceTrigger":
        operator = str(_require(data, "operator"))
        if operator not in {"<=", ">=", "<", ">"}:
            raise OrderValidationError("trigger.operator must be <=, >=, <, or >")
        return cls(
            source=str(data.get("source", "debank")),
            token=TokenInfo.from_dict(_require(data, "token")),
            operator=operator,
            target_price_usd=_decimal(_require(data, "target_price_usd"), "trigger.target_price_usd"),
            poll_interval_seconds=int(data.get("poll_interval_seconds", 30)),
        )


@dataclass(frozen=True)
class ConditionalOrder:
    source: str
    chain: ChainInfo
    wallet: WalletRef
    trigger: PriceTrigger
    action: dict[str, Any]
    safety: SafetyInfo = field(default_factory=SafetyInfo)
    approval: dict[str, Any] = field(default_factory=dict)
    lifecycle: dict[str, Any] = field(default_factory=dict)
    order_type: str = "conditional"
    id: str = field(default_factory=lambda: f"cond_{uuid4().hex}")
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConditionalOrder":
        order_type = data.get("order_type", "conditional")
        if order_type != "conditional":
            raise OrderValidationError("ConditionalOrder requires order_type=conditional")
        return cls(
            id=str(data.get("id") or f"cond_{uuid4().hex}"),
            source=str(_require(data, "source")),
            chain=ChainInfo.from_dict(_require(data, "chain")),
            wallet=WalletRef.from_dict(_require(data, "wallet")),
            trigger=PriceTrigger.from_dict(_require(data, "trigger")),
            action=dict(_require(data, "action")),
            safety=SafetyInfo.from_dict(data.get("safety")),
            approval=dict(data.get("approval") or {}),
            lifecycle=dict(data.get("lifecycle") or {}),
        )

    def build_market_order(self) -> MarketOrder:
        payload = {
            "source": self.source,
            "order_type": "market",
            "chain": self.chain.__dict__,
            "wallet": self.wallet.__dict__,
            "token_in": _require(self.action, "token_in"),
            "token_out": _require(self.action, "token_out"),
            "amount": _require(self.action, "amount"),
            "trade": {**dict(self.action.get("trade") or {}), "execution_mode": "watcher_triggered"},
            "safety": {k: str(v) if isinstance(v, Decimal) else v for k, v in self.safety.__dict__.items()},
            "approval": {
                "require_confirmation": bool(self.approval.get("require_confirmation_on_trigger", True)),
                "confirmation_channel": str(self.approval.get("confirmation_channel", "telegram")),
            },
        }
        return MarketOrder.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "order_type": self.order_type,
            "created_at": self.created_at,
            "chain": self.chain.__dict__,
            "wallet": self.wallet.__dict__,
            "trigger": {
                "source": self.trigger.source,
                "token": self.trigger.token.__dict__,
                "operator": self.trigger.operator,
                "target_price_usd": str(self.trigger.target_price_usd),
                "poll_interval_seconds": self.trigger.poll_interval_seconds,
            },
            "action": self.action,
            "safety": {k: str(v) if isinstance(v, Decimal) else v for k, v in self.safety.__dict__.items()},
            "approval": self.approval,
            "lifecycle": self.lifecycle,
        }
