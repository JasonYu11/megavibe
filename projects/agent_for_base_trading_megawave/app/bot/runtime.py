from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from app.bot.telegram_handlers import TelegramCommandHandler
from app.secrets.provider import SecretProvider


class MessageTransport(Protocol):
    def send_message(self, chat_id: str, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        """Send a message to the user."""


class TelegramTransportError(RuntimeError):
    """Raised when Telegram Bot API communication fails."""


@dataclass
class TelegramHttpTransport:
    token_ref: str
    secret_provider: SecretProvider
    base_url: str = "https://api.telegram.org"
    session: requests.Session = field(default_factory=requests.Session)
    timeout: int = 30

    def _token(self) -> str:
        return self.secret_provider.resolve(self.token_ref)

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/bot{self._token()}/{method}"
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            raise TelegramTransportError(f"telegram request failed: {method}") from None
        except ValueError:
            raise TelegramTransportError(f"telegram invalid json: {method}") from None
        if not isinstance(data, dict) or not data.get("ok"):
            raise TelegramTransportError(f"telegram api error: {method}")
        return data

    def _get(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/bot{self._token()}/{method}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            raise TelegramTransportError(f"telegram request failed: {method}") from None
        except ValueError:
            raise TelegramTransportError(f"telegram invalid json: {method}") from None
        if not isinstance(data, dict) or not data.get("ok"):
            raise TelegramTransportError(f"telegram api error: {method}")
        return data

    def send_message(self, chat_id: str, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        self._post("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self._post("answerCallbackQuery", payload)

    def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        self._post("setMyCommands", {"commands": commands})

    def get_updates(self, offset: int | None = None, timeout: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if offset is not None:
            params["offset"] = offset
        data = self._get("getUpdates", params)
        result = data.get("result", [])
        if not isinstance(result, list):
            raise TelegramTransportError("telegram api error: getUpdates returned non-list result")
        return [item for item in result if isinstance(item, dict)]


@dataclass
class TelegramRuntime:
    """Small transport-agnostic runtime wrapper for Telegram command handling.

    This class intentionally avoids importing python-telegram-bot directly so
    command handling remains testable even when the local Telegram package is
    unavailable or misinstalled.
    """

    handler: TelegramCommandHandler
    transport: MessageTransport
    chat_id: str

    def handle_text(self, text: str, actor: str = "telegram") -> str:
        response = self.handler.handle(text, actor=actor, chat_id=self.chat_id)
        self.transport.send_message(self.chat_id, response.text, reply_markup=response.reply_markup)
        return response.text

    def handle_callback(self, data: str, actor: str = "telegram", callback_query_id: str | None = None) -> str:
        response = self.handler.handle_callback(data, actor=actor, chat_id=self.chat_id)
        if callback_query_id and hasattr(self.transport, "answer_callback_query"):
            self.transport.answer_callback_query(callback_query_id)  # type: ignore[attr-defined]
        self.transport.send_message(self.chat_id, response.text, reply_markup=response.reply_markup)
        return response.text

    def send_system_message(self, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        self.transport.send_message(self.chat_id, text, reply_markup=reply_markup)

    def poll_once(self, offset: int | None = None) -> int | None:
        if not hasattr(self.transport, "get_updates"):
            raise TelegramTransportError("transport does not support polling")

        next_offset = offset
        updates = self.transport.get_updates(offset=offset)  # type: ignore[attr-defined]
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                next_offset = max(next_offset or 0, update_id + 1)
            callback_query = update.get("callback_query")
            if isinstance(callback_query, dict):
                self._handle_callback_update(callback_query)
                continue
            message = update.get("message") or {}
            if not isinstance(message, dict):
                continue
            chat = message.get("chat") or {}
            text = message.get("text")
            if not isinstance(chat, dict) or not isinstance(text, str):
                continue
            chat_id = str(chat.get("id", ""))
            if chat_id != str(self.chat_id):
                continue
            actor = str(message.get("from", {}).get("id", "telegram")) if isinstance(message.get("from"), dict) else "telegram"
            self.handle_text(text, actor=actor)
        return next_offset

    def _handle_callback_update(self, callback_query: dict[str, Any]) -> None:
        data = callback_query.get("data")
        if not isinstance(data, str):
            return
        message = callback_query.get("message") or {}
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        if not isinstance(chat, dict):
            return
        chat_id = str(chat.get("id", ""))
        if chat_id != str(self.chat_id):
            return
        actor = str(callback_query.get("from", {}).get("id", "telegram")) if isinstance(callback_query.get("from"), dict) else "telegram"
        callback_query_id = str(callback_query.get("id", "")) or None
        self.handle_callback(data, actor=actor, callback_query_id=callback_query_id)
