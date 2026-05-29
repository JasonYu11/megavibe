from __future__ import annotations

from decimal import Decimal

from app.copy_trading.action_builder import CopyTradeActionBuilder
from app.copy_trading.models import CopyActionStatus, CopyTargetConfig, CopyTradeIntent, CopyTradeKind, TokenTransfer
from app.core.order_info import TokenInfo


USDC = TokenInfo("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6)
A = TokenInfo("A", "0x0000000000000000000000000000000000000001", 18)
B = TokenInfo("B", "0x0000000000000000000000000000000000000002", 18)


def intent(kind: CopyTradeKind, sent_token: TokenInfo, received_token: TokenInfo, usd: str) -> CopyTradeIntent:
    return CopyTradeIntent(
        kind=kind,
        history_id="h1",
        tx_hash="0xhash",
        time_at=1000,
        sent=TokenTransfer(sent_token, Decimal("100")),
        received=TokenTransfer(received_token, Decimal("10")),
        estimated_usd_value=Decimal(usd),
    )


def test_builder_generates_usdc_buy_capped_by_max() -> None:
    group = CopyTradeActionBuilder().build(
        CopyTargetConfig(address="0x138ab382c889add23de09a78fd7a75b9b4fe5c25"),
        intent(CopyTradeKind.STABLE_OR_ETH_TO_TOKEN, USDC, A, "1000"),
    )

    action = group.actions[0]
    assert action.side == "buy"
    assert action.amount == Decimal("0.01")
    assert action.order is not None
    assert action.order.source == "copy_trade"
    assert action.order.trade.execution_mode == "copy_watcher"


def test_builder_sell_uses_local_balance_ratio_and_zero_balance_fails() -> None:
    target = CopyTargetConfig(address="0x138ab382c889add23de09a78fd7a75b9b4fe5c25")
    group = CopyTradeActionBuilder(balance_provider=lambda token: Decimal("20")).build(
        target,
        intent(CopyTradeKind.TOKEN_TO_STABLE_OR_ETH, A, USDC, "100"),
    )
    zero = CopyTradeActionBuilder(balance_provider=lambda token: Decimal("0")).build(
        target,
        intent(CopyTradeKind.TOKEN_TO_STABLE_OR_ETH, A, USDC, "100"),
    )

    assert group.actions[0].side == "sell"
    assert group.actions[0].amount == Decimal("0.00020")
    assert group.actions[0].order is not None
    assert zero.actions[0].status == CopyActionStatus.FAILED
    assert zero.actions[0].reason == "balance_zero"


def test_builder_token_to_token_generates_buy_and_sell_actions() -> None:
    group = CopyTradeActionBuilder(balance_provider=lambda token: Decimal("0")).build(
        CopyTargetConfig(address="0x138ab382c889add23de09a78fd7a75b9b4fe5c25"),
        intent(CopyTradeKind.TOKEN_TO_TOKEN, B, A, "100"),
    )

    assert [action.side for action in group.actions] == ["buy", "sell"]
    assert group.actions[0].amount == Decimal("0.00100")
    assert group.actions[1].status == CopyActionStatus.FAILED
