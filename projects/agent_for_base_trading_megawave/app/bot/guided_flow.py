from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.bot.command_parser import CommandParseError, TelegramCommandParser
from app.core.order_info import ConditionalOrder, MarketOrder
from app.storage.sqlite_store import SQLiteStore


class GuidedFlowError(ValueError):
    """Raised when guided flow input cannot be applied."""


@dataclass(frozen=True)
class GuidedFlowResult:
    text: str
    order: MarketOrder | ConditionalOrder | None = None
    cancelled: bool = False


class GuidedTradeFlow:
    def __init__(self, store: SQLiteStore, parser: TelegramCommandParser) -> None:
        self.store = store
        self.parser = parser

    @staticmethod
    def scope(chat_id: str, user_id: str) -> str:
        return f"{chat_id}:{user_id}"

    def start(self, chat_id: str, user_id: str) -> GuidedFlowResult:
        state = {
            "mode": "guided_trade",
            "step": "awaiting_kind",
            "draft": {"kind": None, "token": None, "amount": None, "target_price_usd": None},
        }
        self.store.save_conversation_state(self.scope(chat_id, user_id), state)
        return GuidedFlowResult("Choose trade type: Buy, Sell, Limit Buy, Limit Sell")

    def handle(self, chat_id: str, user_id: str, text: str) -> GuidedFlowResult:
        scope_id = self.scope(chat_id, user_id)
        if text.strip().lower() in {"/cancel", "cancel"}:
            self.store.clear_conversation_state(scope_id)
            return GuidedFlowResult("Trade flow cancelled", cancelled=True)
        state = self.store.get_conversation_state(scope_id)
        if state is None:
            raise GuidedFlowError("no active guided trade")

        step = state["step"]
        draft = dict(state["draft"])
        value = text.strip()

        if step == "awaiting_kind":
            draft["kind"] = self._kind(value)
            state["step"] = "awaiting_token"
            state["draft"] = draft
            self.store.save_conversation_state(scope_id, state)
            return GuidedFlowResult("Send token contract address")

        if step == "awaiting_token":
            draft["token"] = value
            self._validate_token(value)
            state["step"] = "awaiting_amount"
            state["draft"] = draft
            self.store.save_conversation_state(scope_id, state)
            return GuidedFlowResult("Send amount")

        if step == "awaiting_amount":
            draft["amount"] = value
            self._validate_amount(value)
            if str(draft["kind"]).startswith("limit_"):
                state["step"] = "awaiting_target_price"
                state["draft"] = draft
                self.store.save_conversation_state(scope_id, state)
                return GuidedFlowResult("Send target USD price")
            return self._save_review(scope_id, state, draft)

        if step == "awaiting_target_price":
            draft["target_price_usd"] = value
            self._validate_amount(value, field_name="target_price")
            return self._save_review(scope_id, state, draft)

        if step == "awaiting_confirm":
            if value.lower() != "confirm":
                raise GuidedFlowError("send Confirm to create the order or Cancel to stop")
            order = self._build_order(draft)
            self.store.clear_conversation_state(scope_id)
            return GuidedFlowResult("Guided order confirmed", order=order)

        raise GuidedFlowError(f"unsupported guided step: {step}")

    def is_active(self, chat_id: str, user_id: str) -> bool:
        return self.store.get_conversation_state(self.scope(chat_id, user_id)) is not None

    def _save_review(self, scope_id: str, state: dict[str, Any], draft: dict[str, Any]) -> GuidedFlowResult:
        command = self._command(draft)
        # Parse once before review so confirm cannot create an invalid order.
        try:
            self.parser.parse(command)
        except CommandParseError as exc:
            raise GuidedFlowError(str(exc)) from exc
        draft["pending_command"] = command
        state["step"] = "awaiting_confirm"
        state["draft"] = draft
        self.store.save_conversation_state(scope_id, state)
        return GuidedFlowResult(f"Review: {command}. Send Confirm to create or Cancel to stop")

    def _build_order(self, draft: dict[str, Any]) -> MarketOrder | ConditionalOrder:
        command = draft.get("pending_command") or self._command(draft)
        try:
            return self.parser.parse(command)
        except CommandParseError as exc:
            raise GuidedFlowError(str(exc)) from exc

    @staticmethod
    def _command(draft: dict[str, Any]) -> str:
        kind = draft["kind"]
        token = draft["token"]
        amount = draft["amount"]
        price = draft.get("target_price_usd")
        if kind == "buy":
            return f"/buy {token} {amount}"
        elif kind == "sell":
            return f"/sell {token} {amount}"
        elif kind == "limit_buy":
            return f"/limit_buy {token} {amount} at {price}"
        elif kind == "limit_sell":
            return f"/limit_sell {token} {amount} at {price}"
        raise GuidedFlowError(f"unsupported trade type: {kind}")

    def _validate_token(self, token: str) -> None:
        try:
            self.parser.parse(f"/buy {token} 1")
        except CommandParseError as exc:
            raise GuidedFlowError(str(exc)) from exc

    def _validate_amount(self, amount: str, field_name: str = "amount") -> None:
        try:
            self.parser._amount(amount, field_name)  # noqa: SLF001
        except CommandParseError as exc:
            raise GuidedFlowError(str(exc)) from exc

    @staticmethod
    def _kind(text: str) -> str:
        normalized = text.strip().lower().replace("_", " ").replace("-", " ")
        choices = {
            "buy": "buy",
            "market buy": "buy",
            "sell": "sell",
            "market sell": "sell",
            "limit buy": "limit_buy",
            "limitbuy": "limit_buy",
            "limit sell": "limit_sell",
            "limitsell": "limit_sell",
        }
        if normalized not in choices:
            raise GuidedFlowError("trade type must be Buy, Sell, Limit Buy, or Limit Sell")
        return choices[normalized]
