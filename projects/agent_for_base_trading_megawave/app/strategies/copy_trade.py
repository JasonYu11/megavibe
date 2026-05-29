from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.order_info import MarketOrder, TokenInfo


STABLE_SYMBOLS = {"USDC", "USDT", "DAI"}


@dataclass(frozen=True)
class CopyTradeConfig:
    wallet_id: str = "base_main_test"
    chain: str = "base"
    buy_ratio: Decimal = Decimal("0.3")
    sell_ratio: Decimal = Decimal("0.5")
    max_copy_trade_usd: Decimal = Decimal("3")


@dataclass(frozen=True)
class CopyTradeStrategy:
    config: CopyTradeConfig
    pay_token: TokenInfo

    def generate_orders(self, debank_history: dict[str, Any]) -> list[MarketOrder]:
        orders: list[MarketOrder] = []
        root_token_dict = debank_history.get("token_dict") or {}
        for item in debank_history.get("history_list") or []:
            if not self._is_relevant_history_item(item):
                continue
            token_dict = item.get("token_dict") or root_token_dict
            sends = self._transfer_list(item.get("sends"))
            receives = self._transfer_list(item.get("receives"))
            trade = self._classify(sends, receives, token_dict)
            if trade is None:
                continue
            side, target_token, source_amount = trade
            if side == "buy":
                amount = min(source_amount * self.config.buy_ratio, self.config.max_copy_trade_usd)
                token_in = self.pay_token
                token_out = target_token
            else:
                amount = source_amount * self.config.sell_ratio
                token_in = target_token
                token_out = self.pay_token
            orders.append(
                MarketOrder.from_dict(
                    {
                        "order_type": "market",
                        "source": "copy_trade",
                        "chain": {"namespace": "evm", "chain_id": 8453, "chain_name": "base"},
                        "wallet": {"wallet_id": self.config.wallet_id},
                        "token_in": token_in.__dict__,
                        "token_out": token_out.__dict__,
                        "amount": {"type": "exact_in", "value": str(amount), "unit": "token"},
                        "trade": {"side": side, "route_provider": "okx", "execution_mode": "immediate"},
                        "approval": {"require_confirmation": True, "confirmation_channel": "telegram"},
                    }
                )
            )
        return orders

    def _is_relevant_history_item(self, item: dict[str, Any]) -> bool:
        chain = item.get("chain")
        if chain and str(chain).lower() != self.config.chain:
            return False
        tx = item.get("tx")
        if isinstance(tx, dict) and tx.get("status") == 0:
            return False
        cate_id = str(item.get("cate_id") or "").lower()
        if cate_id in {"approve", "cancel", "deploy"}:
            return False
        return True

    def _classify(
        self,
        sends: list[dict[str, Any]],
        receives: list[dict[str, Any]],
        token_dict: dict[str, Any],
    ) -> tuple[str, TokenInfo, Decimal] | None:
        send_stable = self._first_stable(sends, token_dict)
        receive_non_stable = self._first_non_stable(receives, token_dict)
        if send_stable and receive_non_stable:
            return ("buy", receive_non_stable[0], send_stable[1])

        send_non_stable = self._first_non_stable(sends, token_dict)
        receive_stable = self._first_stable(receives, token_dict)
        if send_non_stable and receive_stable:
            return ("sell", send_non_stable[0], send_non_stable[1])

        return None

    def _first_stable(
        self,
        transfers: list[dict[str, Any]],
        token_dict: dict[str, Any],
    ) -> tuple[TokenInfo, Decimal] | None:
        for transfer in transfers:
            token = self._token_from_transfer(transfer, token_dict)
            if token.symbol.upper() in STABLE_SYMBOLS:
                return token, self._transfer_amount(transfer)
        return None

    def _first_non_stable(
        self,
        transfers: list[dict[str, Any]],
        token_dict: dict[str, Any],
    ) -> tuple[TokenInfo, Decimal] | None:
        for transfer in transfers:
            token = self._token_from_transfer(transfer, token_dict)
            if token.symbol.upper() not in STABLE_SYMBOLS:
                return token, self._transfer_amount(transfer)
        return None

    @staticmethod
    def _token_from_transfer(transfer: dict[str, Any], token_dict: dict[str, Any]) -> TokenInfo:
        token_id = str(transfer.get("token_id") or transfer.get("id") or "")
        meta = transfer.get("token") if isinstance(transfer.get("token"), dict) else token_dict.get(token_id) or {}
        symbol = meta.get("optimized_symbol") or meta.get("display_symbol") or meta.get("symbol") or transfer.get("symbol") or token_id
        address = meta.get("id") or meta.get("address") or token_id
        return TokenInfo(
            symbol=str(symbol),
            address=str(address),
            decimals=int(meta.get("decimals") or 18),
        )

    @staticmethod
    def _transfer_amount(transfer: dict[str, Any]) -> Decimal:
        amount = transfer.get("amount")
        if amount is not None:
            return Decimal(str(amount))
        raw_amount = transfer.get("raw_amount")
        decimals = transfer.get("decimals")
        if raw_amount is not None and decimals is not None:
            return Decimal(str(raw_amount)) / (Decimal(10) ** int(decimals))
        return Decimal("0")

    @staticmethod
    def _transfer_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
        return []
