from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.copy_trading.models import CopyTradeIntent, CopyTradeKind, ParsedHistoryItem, TokenTransfer


QUOTE_SYMBOLS = {"USDC", "ETH", "WETH"}
STABLE_SYMBOLS = {"USDC", "USDT", "DAI"}


@dataclass(frozen=True)
class CopyTradeClassifier:
    quote_symbols: frozenset[str] = frozenset(QUOTE_SYMBOLS)

    def classify(self, item: ParsedHistoryItem) -> CopyTradeIntent:
        if len(item.sends) != 1 or len(item.receives) != 1:
            return self._ignored(item, CopyTradeKind.COMPLEX)
        sent = item.sends[0]
        received = item.receives[0]
        if sent.token.address.lower() == received.token.address.lower():
            return self._ignored(item, CopyTradeKind.IGNORED)

        sent_quote = self._is_quote(sent)
        received_quote = self._is_quote(received)
        if sent_quote and not received_quote:
            return self._intent(item, CopyTradeKind.STABLE_OR_ETH_TO_TOKEN, sent, received, self._usd_value(sent))
        if not sent_quote and received_quote:
            return self._intent(item, CopyTradeKind.TOKEN_TO_STABLE_OR_ETH, sent, received, self._usd_value(received))
        if not sent_quote and not received_quote:
            return self._intent(item, CopyTradeKind.TOKEN_TO_TOKEN, sent, received, self._usd_value(sent) or self._usd_value(received))
        return self._ignored(item, CopyTradeKind.IGNORED)

    def _is_quote(self, transfer: TokenTransfer) -> bool:
        return transfer.token.symbol.upper() in self.quote_symbols

    @staticmethod
    def _usd_value(transfer: TokenTransfer) -> Decimal:
        symbol = transfer.token.symbol.upper()
        if symbol in STABLE_SYMBOLS:
            return transfer.amount
        if transfer.price_usd is not None:
            return transfer.amount * transfer.price_usd
        return Decimal("0")

    @staticmethod
    def _intent(
        item: ParsedHistoryItem,
        kind: CopyTradeKind,
        sent: TokenTransfer,
        received: TokenTransfer,
        estimated_usd_value: Decimal,
    ) -> CopyTradeIntent:
        return CopyTradeIntent(
            kind=kind,
            history_id=item.history_id,
            tx_hash=item.tx_hash,
            time_at=item.time_at,
            sent=sent,
            received=received,
            estimated_usd_value=estimated_usd_value,
        )

    def _ignored(self, item: ParsedHistoryItem, kind: CopyTradeKind) -> CopyTradeIntent:
        empty = item.sends[0] if item.sends else item.receives[0]
        return self._intent(item, kind, empty, empty, Decimal("0"))
