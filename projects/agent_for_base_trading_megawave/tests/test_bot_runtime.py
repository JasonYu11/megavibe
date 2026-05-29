from __future__ import annotations

import requests

from app.bot.command_parser import TelegramCommandParser
from app.bot.runtime import TelegramHttpTransport, TelegramRuntime, TelegramTransportError
from app.bot.telegram_handlers import TelegramCommandHandler
from app.orders.order_service import OrderService
from app.risk.risk_engine import RiskEngine
from app.secrets.provider import SecretProvider
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_service import FakeQuoteClient
from tests.test_risk_engine import policy

VIRTUAL = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"


class FakeTransport:
    def __init__(self) -> None:
        self.messages = []
        self.updates = []
        self.answered_callbacks = []

    def send_message(self, chat_id: str, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        self.messages.append((chat_id, text, reply_markup))

    def answer_callback_query(self, callback_query_id: str, text=None) -> None:  # type: ignore[no-untyped-def]
        self.answered_callbacks.append((callback_query_id, text))

    def get_updates(self, offset=None):  # type: ignore[no-untyped-def]
        return self.updates


class StaticSecretProvider(SecretProvider):
    def resolve(self, secret_ref: str) -> str:
        assert secret_ref == "ENV:TELEGRAM_BOT_TOKEN"
        return "token"


class FakeTelegramResponse:
    def __init__(self, data):  # type: ignore[no-untyped-def]
        self.data = data

    def raise_for_status(self) -> None:
        return None

    def json(self):  # type: ignore[no-untyped-def]
        return self.data


class FakeTelegramSession:
    def __init__(self) -> None:
        self.posts = []
        self.gets = []

    def post(self, url, json, timeout):  # type: ignore[no-untyped-def]
        self.posts.append({"url": url, "json": json, "timeout": timeout})
        return FakeTelegramResponse({"ok": True, "result": {"message_id": 1}})

    def get(self, url, params, timeout):  # type: ignore[no-untyped-def]
        self.gets.append({"url": url, "params": params, "timeout": timeout})
        return FakeTelegramResponse(
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 7,
                        "message": {
                            "chat": {"id": "chat1"},
                            "from": {"id": "user1"},
                            "text": "/status",
                        },
                    }
                ],
            }
        )


class FailingTelegramSession:
    def post(self, url, json, timeout):  # type: ignore[no-untyped-def]
        request = requests.Request("POST", url).prepare()
        response = requests.Response()
        response.url = url
        raise requests.exceptions.SSLError("network failure", request=request, response=response)

    def get(self, url, params, timeout):  # type: ignore[no-untyped-def]
        request = requests.Request("GET", url).prepare()
        response = requests.Response()
        response.url = url
        raise requests.exceptions.SSLError("network failure", request=request, response=response)


def test_telegram_runtime_sends_handler_response(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    handler = TelegramCommandHandler(TelegramCommandParser(), service, store)
    transport = FakeTransport()
    runtime = TelegramRuntime(handler, transport, chat_id="chat1")

    text = runtime.handle_text(f"/buy {VIRTUAL} 2", actor="user1")

    assert "市价单确认" in text
    assert len(transport.messages) == 1
    assert transport.messages[0][0] == "chat1"
    assert transport.messages[0][1] == text
    assert transport.messages[0][2]["inline_keyboard"][0][0]["text"] == "确认"


def test_telegram_http_transport_uses_bot_api_without_exposing_token() -> None:
    session = FakeTelegramSession()
    transport = TelegramHttpTransport(
        "ENV:TELEGRAM_BOT_TOKEN",
        StaticSecretProvider(),
        base_url="https://telegram.test",
        session=session,  # type: ignore[arg-type]
    )

    transport.send_message("chat1", "hello")

    assert session.posts[0]["url"] == "https://telegram.test/bottoken/sendMessage"
    assert session.posts[0]["json"] == {"chat_id": "chat1", "text": "hello"}


def test_telegram_http_transport_sets_bot_commands() -> None:
    session = FakeTelegramSession()
    transport = TelegramHttpTransport(
        "ENV:TELEGRAM_BOT_TOKEN",
        StaticSecretProvider(),
        base_url="https://telegram.test",
        session=session,  # type: ignore[arg-type]
    )

    transport.set_my_commands([{"command": "orders", "description": "当前订单"}])

    assert session.posts[0]["url"] == "https://telegram.test/bottoken/setMyCommands"
    assert session.posts[0]["json"] == {"commands": [{"command": "orders", "description": "当前订单"}]}


def test_telegram_http_transport_failure_suppresses_token_exception_chain() -> None:
    transport = TelegramHttpTransport(
        "ENV:TELEGRAM_BOT_TOKEN",
        StaticSecretProvider(),
        base_url="https://telegram.test",
        session=FailingTelegramSession(),  # type: ignore[arg-type]
    )

    try:
        transport.send_message("chat1", "hello")
    except TelegramTransportError as exc:
        assert str(exc) == "telegram request failed: sendMessage"
        assert exc.__cause__ is None
        assert exc.__suppress_context__ is True
    else:
        raise AssertionError("telegram transport failure should raise")


def test_telegram_runtime_poll_once_handles_allowed_chat(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    handler = TelegramCommandHandler(TelegramCommandParser(), service, store)
    transport = FakeTransport()
    transport.updates = [
        {
            "update_id": 7,
            "message": {"chat": {"id": "chat1"}, "from": {"id": "user1"}, "text": "/status"},
        }
    ]
    runtime = TelegramRuntime(handler, transport, chat_id="chat1")

    next_offset = runtime.poll_once()

    assert next_offset == 8
    assert len(transport.messages) == 1
    assert transport.messages[0][0] == "chat1"
    assert "运行状态" in transport.messages[0][1]
    assert "execution_mode=dry_run" in transport.messages[0][1]
    assert "市价单: 0" in transport.messages[0][1]
    assert "限价单: 0" in transport.messages[0][1]


def test_telegram_runtime_poll_once_handles_callback_query(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    handler = TelegramCommandHandler(TelegramCommandParser(), service, store)
    created = handler.handle(f"/buy {VIRTUAL} 2", actor="user1")
    transport = FakeTransport()
    transport.updates = [
        {
            "update_id": 8,
            "callback_query": {
                "id": "callback1",
                "from": {"id": "user1"},
                "message": {"chat": {"id": "chat1"}},
                "data": f"reject:{created.payload['order_id']}",
            },
        }
    ]
    runtime = TelegramRuntime(handler, transport, chat_id="chat1")

    next_offset = runtime.poll_once()

    assert next_offset == 9
    assert transport.answered_callbacks == [("callback1", None)]
    assert "订单已拒绝" in transport.messages[0][1]


def test_telegram_http_transport_get_updates() -> None:
    session = FakeTelegramSession()
    transport = TelegramHttpTransport(
        "ENV:TELEGRAM_BOT_TOKEN",
        StaticSecretProvider(),
        base_url="https://telegram.test",
        session=session,  # type: ignore[arg-type]
    )

    updates = transport.get_updates(offset=5)

    assert updates[0]["update_id"] == 7
    assert session.gets[0]["params"]["offset"] == 5
