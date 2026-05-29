from __future__ import annotations

from decimal import Decimal

from app.copy_trading.classifier import CopyTradeClassifier
from app.copy_trading.models import CopyTradeKind, ParsedHistoryItem, TokenTransfer
from app.core.order_info import TokenInfo


USDC = TokenInfo("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6)
ETH = TokenInfo("ETH", "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", 18)
A = TokenInfo("A", "0x0000000000000000000000000000000000000001", 18)
B = TokenInfo("B", "0x0000000000000000000000000000000000000002", 18)


def item(sent: TokenTransfer, received: TokenTransfer) -> ParsedHistoryItem:
    return ParsedHistoryItem("h1", "0xhash", "base", "swap", 1000, [sent], [received])


def test_classifier_identifies_usdc_buy() -> None:
    intent = CopyTradeClassifier().classify(item(TokenTransfer(USDC, Decimal("100")), TokenTransfer(A, Decimal("5"))))

    assert intent.kind == CopyTradeKind.STABLE_OR_ETH_TO_TOKEN
    assert intent.estimated_usd_value == Decimal("100")


def test_classifier_identifies_eth_buy_with_usd_estimate() -> None:
    intent = CopyTradeClassifier().classify(
        item(TokenTransfer(ETH, Decimal("0.05"), Decimal("3000")), TokenTransfer(A, Decimal("5")))
    )

    assert intent.kind == CopyTradeKind.STABLE_OR_ETH_TO_TOKEN
    assert intent.estimated_usd_value == Decimal("150.00")


def test_classifier_identifies_sell_and_token_to_token() -> None:
    classifier = CopyTradeClassifier()
    sell = classifier.classify(item(TokenTransfer(A, Decimal("4")), TokenTransfer(USDC, Decimal("20"))))
    pair = classifier.classify(item(TokenTransfer(B, Decimal("2"), Decimal("3")), TokenTransfer(A, Decimal("7"))))

    assert sell.kind == CopyTradeKind.TOKEN_TO_STABLE_OR_ETH
    assert sell.estimated_usd_value == Decimal("20")
    assert pair.kind == CopyTradeKind.TOKEN_TO_TOKEN
    assert pair.estimated_usd_value == Decimal("6")


def test_classifier_marks_complex_multi_transfer() -> None:
    parsed = ParsedHistoryItem(
        "h1",
        "0xhash",
        "base",
        "swap",
        1000,
        [TokenTransfer(USDC, Decimal("1")), TokenTransfer(B, Decimal("2"))],
        [TokenTransfer(A, Decimal("1"))],
    )

    assert CopyTradeClassifier().classify(parsed).kind == CopyTradeKind.COMPLEX
