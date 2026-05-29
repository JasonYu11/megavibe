from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.core.order_info import MarketOrder, TokenInfo


BASE_CHAIN = "base"
DEFAULT_COPY_ADDRESS = "0x138ab382c889add23de09a78fd7a75b9b4fe5c25"


class CopyTargetStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


class CopyTradeKind(StrEnum):
    STABLE_OR_ETH_TO_TOKEN = "STABLE_OR_ETH_TO_TOKEN"
    TOKEN_TO_STABLE_OR_ETH = "TOKEN_TO_STABLE_OR_ETH"
    TOKEN_TO_TOKEN = "TOKEN_TO_TOKEN"
    IGNORED = "IGNORED"
    COMPLEX = "COMPLEX"


class CopyActionStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CopyTargetConfig:
    address: str
    chain: str = BASE_CHAIN
    status: CopyTargetStatus = CopyTargetStatus.PENDING_CONFIRMATION
    copy_ratio: Decimal = Decimal("0.00001")
    max_copy_trade_usd: Decimal = Decimal("0.01")
    max_age_seconds: int = 300


@dataclass(frozen=True)
class TokenTransfer:
    token: TokenInfo
    amount: Decimal
    price_usd: Decimal | None = None


@dataclass(frozen=True)
class ParsedHistoryItem:
    history_id: str
    tx_hash: str
    chain: str
    cate_id: str
    time_at: int
    sends: list[TokenTransfer]
    receives: list[TokenTransfer]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CopyTradeIntent:
    kind: CopyTradeKind
    history_id: str
    tx_hash: str
    time_at: int
    sent: TokenTransfer
    received: TokenTransfer
    estimated_usd_value: Decimal


@dataclass(frozen=True)
class CopyTradeAction:
    label: str
    side: str
    token_in: TokenInfo | None = None
    token_out: TokenInfo | None = None
    amount: Decimal = Decimal("0")
    order: MarketOrder | None = None
    status: CopyActionStatus = CopyActionStatus.PENDING
    reason: str = ""
    order_id: str | None = None
    order_status: str | None = None


@dataclass(frozen=True)
class CopyTradeActionGroup:
    target: CopyTargetConfig
    intent: CopyTradeIntent
    actions: list[CopyTradeAction]


@dataclass(frozen=True)
class CopyWatcherResult:
    checked_targets: int
    processed_events: int
    submitted_orders: int
    skipped_events: int
    action_groups: list[CopyTradeActionGroup]
