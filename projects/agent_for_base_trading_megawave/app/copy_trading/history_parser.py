from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.copy_trading.models import BASE_CHAIN, ParsedHistoryItem, TokenTransfer
from app.core.order_info import TokenInfo


IGNORED_CATE_IDS = {"approve", "transfer", "deploy", "cancel"}
NATIVE_ETH_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


@dataclass(frozen=True)
class DebankHistoryParser:
    chain: str = BASE_CHAIN
    max_age_seconds: int = 300

    def parse(self, history_response: dict[str, Any], now_ts: int | float | None = None) -> list[ParsedHistoryItem]:
        now = int(now_ts if now_ts is not None else time.time())
        root_token_dict = history_response.get("token_dict") if isinstance(history_response, dict) else {}
        if not isinstance(root_token_dict, dict):
            root_token_dict = {}

        parsed: list[ParsedHistoryItem] = []
        for item in history_response.get("history_list") or []:
            if not isinstance(item, dict) or not self._is_candidate(item, now):
                continue
            item_token_dict = item.get("token_dict") if isinstance(item.get("token_dict"), dict) else root_token_dict
            sends = self._transfer_list(item.get("sends"), item_token_dict)
            receives = self._transfer_list(item.get("receives"), item_token_dict)
            if not sends or not receives:
                continue
            history_id = str(item.get("id") or item.get("history_id") or self._tx_hash(item))
            tx_hash = self._tx_hash(item) or history_id
            parsed.append(
                ParsedHistoryItem(
                    history_id=history_id,
                    tx_hash=tx_hash,
                    chain=str(item.get("chain") or self.chain).lower(),
                    cate_id=str(item.get("cate_id") or ""),
                    time_at=int(item.get("time_at") or 0),
                    sends=sends,
                    receives=receives,
                    raw=item,
                )
            )
        return parsed

    def _is_candidate(self, item: dict[str, Any], now_ts: int) -> bool:
        chain = str(item.get("chain") or self.chain).lower()
        if chain != self.chain:
            return False
        time_at = int(item.get("time_at") or 0)
        if time_at <= 0 or now_ts - time_at > self.max_age_seconds:
            return False
        cate_id = str(item.get("cate_id") or "").lower()
        if cate_id in IGNORED_CATE_IDS:
            return False
        tx = item.get("tx")
        if isinstance(tx, dict) and tx.get("status") == 0:
            return False
        return True

    @classmethod
    def _transfer_list(cls, value: Any, token_dict: dict[str, Any]) -> list[TokenTransfer]:
        raw_items = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        transfers: list[TokenTransfer] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            token = cls._token_from_transfer(raw, token_dict)
            amount = cls._amount_from_transfer(raw, token.decimals)
            if amount <= 0:
                continue
            transfers.append(TokenTransfer(token=token, amount=amount, price_usd=cls._price_from_transfer(raw, token_dict)))
        return transfers

    @staticmethod
    def _token_from_transfer(transfer: dict[str, Any], token_dict: dict[str, Any]) -> TokenInfo:
        token_id = str(transfer.get("token_id") or transfer.get("id") or transfer.get("address") or "")
        inline = transfer.get("token") if isinstance(transfer.get("token"), dict) else None
        meta = inline or token_dict.get(token_id) or {}
        symbol = (
            meta.get("optimized_symbol")
            or meta.get("display_symbol")
            or meta.get("symbol")
            or transfer.get("symbol")
            or token_id
        )
        address = meta.get("id") or meta.get("address") or token_id
        if str(symbol).upper() == "ETH" and not str(address).startswith("0x"):
            address = NATIVE_ETH_ADDRESS
        return TokenInfo(symbol=str(symbol), address=str(address), decimals=int(meta.get("decimals") or transfer.get("decimals") or 18))

    @staticmethod
    def _amount_from_transfer(transfer: dict[str, Any], decimals: int) -> Decimal:
        amount = transfer.get("amount")
        if amount is not None:
            return _safe_decimal(amount)
        raw_amount = transfer.get("raw_amount")
        if raw_amount is not None:
            return _safe_decimal(raw_amount) / (Decimal(10) ** decimals)
        return Decimal("0")

    @staticmethod
    def _price_from_transfer(transfer: dict[str, Any], token_dict: dict[str, Any]) -> Decimal | None:
        token_id = str(transfer.get("token_id") or transfer.get("id") or transfer.get("address") or "")
        inline = transfer.get("token") if isinstance(transfer.get("token"), dict) else None
        meta = inline or token_dict.get(token_id) or {}
        price = transfer.get("price") if transfer.get("price") is not None else meta.get("price")
        if price is None:
            return None
        value = _safe_decimal(price)
        return value if value > 0 else None

    @staticmethod
    def _tx_hash(item: dict[str, Any]) -> str:
        tx = item.get("tx")
        if isinstance(tx, dict):
            value = tx.get("id") or tx.get("hash") or tx.get("tx_hash")
            if value:
                return str(value)
        value = item.get("tx_hash")
        return str(value) if value else ""


def _safe_decimal(value: Any) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return decimal if decimal.is_finite() else Decimal("0")
