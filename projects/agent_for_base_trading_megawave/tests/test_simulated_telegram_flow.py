from __future__ import annotations

from decimal import Decimal

from app.bot.command_parser import TelegramCommandParser
from app.bot.orchestrator import RuntimeOrchestrator
from app.bot.runtime import TelegramRuntime
from app.bot.telegram_handlers import TelegramCommandHandler
from app.orders.conditional_watcher import ConditionalOrderWatcher
from app.orders.order_service import OrderService
from app.risk.risk_engine import RiskEngine
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_service import FakeQuoteClient
from tests.test_risk_engine import policy

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
VIRTUAL = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"


class SimulatedTelegramTransport:
    def __init__(self) -> None:
        self.updates = []
        self.messages = []
        self.answered_callbacks = []
        self.next_update_id = 1

    def push_text(self, text: str, chat_id: str = "chat1", user_id: str = "user1") -> None:
        self.updates.append(
            {
                "update_id": self.next_update_id,
                "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": text},
            }
        )
        self.next_update_id += 1

    def push_callback(self, data: str, chat_id: str = "chat1", user_id: str = "user1") -> None:
        self.updates.append(
            {
                "update_id": self.next_update_id,
                "callback_query": {
                    "id": f"callback_{self.next_update_id}",
                    "from": {"id": user_id},
                    "message": {"chat": {"id": chat_id}},
                    "data": data,
                },
            }
        )
        self.next_update_id += 1

    def get_updates(self, offset=None):  # type: ignore[no-untyped-def]
        if offset is None:
            return list(self.updates)
        return [update for update in self.updates if update["update_id"] >= offset]

    def send_message(self, chat_id: str, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        self.messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    def answer_callback_query(self, callback_query_id: str, text=None) -> None:  # type: ignore[no-untyped-def]
        self.answered_callbacks.append({"id": callback_query_id, "text": text})

    @property
    def last_message(self) -> dict:
        return self.messages[-1]


class StaticPriceProvider:
    def __init__(self, price: str) -> None:
        self.price = Decimal(price)

    def get_price_usd(self, token_address: str) -> Decimal:
        assert token_address
        return self.price


class StaticBalanceService:
    wallet_address = "0x0000000000000000000000000000000000000001"

    def get_balance(self):  # type: ignore[no-untyped-def]
        return {
            "total_usd_value": "10.50",
            "key_tokens": [
                {"symbol": "ETH", "amount": "0.001", "usd_value": "3.00"},
                {"symbol": "USDC", "amount": "7.50", "usd_value": "7.50"},
            ],
        }


def _build_simulation(tmp_path):  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    quote_client = FakeQuoteClient()
    price_provider = StaticPriceProvider("0.7")
    service = OrderService(store, RiskEngine(policy()), quote_client, execution_mode="dry_run")
    parser = TelegramCommandParser(wallet_address=StaticBalanceService.wallet_address)
    handler = TelegramCommandHandler(
        parser,
        service,
        store,
        balance_service=StaticBalanceService(),
        price_provider=price_provider,
    )
    transport = SimulatedTelegramTransport()
    runtime = TelegramRuntime(handler, transport, chat_id="chat1")
    watcher = ConditionalOrderWatcher(store, price_provider, service)
    orchestrator = RuntimeOrchestrator(store, telegram_runtime=runtime, conditional_watcher=watcher)
    return store, transport, orchestrator


def _tick(orchestrator: RuntimeOrchestrator) -> None:
    result = orchestrator.tick_once()
    assert result.telegram_ok is True
    assert result.watcher_ok is True
    assert result.receipt_ok is True
    assert result.heartbeat_ok is True


def _callback_from_last_message(transport: SimulatedTelegramTransport, prefix: str) -> str:
    markup = transport.last_message["reply_markup"]
    for row in markup["inline_keyboard"]:
        for item in row:
            data = item["callback_data"]
            if data.startswith(prefix):
                return data
    raise AssertionError(f"missing callback prefix: {prefix}")


def test_simulated_telegram_market_limit_and_order_management_flow(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store, transport, orchestrator = _build_simulation(tmp_path)

    transport.push_text("/start")
    _tick(orchestrator)
    assert "Base 交易助手" in transport.last_message["text"]
    assert transport.last_message["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "trade:start"

    transport.push_text("/status")
    _tick(orchestrator)
    assert "运行状态" in transport.last_message["text"]
    assert "execution_mode=dry_run" in transport.last_message["text"]

    transport.push_text("/balance")
    _tick(orchestrator)
    assert "钱包余额" in transport.last_message["text"]
    assert "USDC: 7.5" in transport.last_message["text"]

    transport.push_text(f"/quote {USDC} {VIRTUAL} 0.01")
    _tick(orchestrator)
    assert "报价" in transport.last_message["text"]
    assert "路径: USDC -> VIRTUAL" in transport.last_message["text"]
    assert store.list_orders(limit=10) == []

    transport.push_text(f"/buy {VIRTUAL} 0.01")
    _tick(orchestrator)
    assert "市价单确认" in transport.last_message["text"]
    confirm_market = _callback_from_last_message(transport, "confirm:")

    transport.push_callback(confirm_market)
    _tick(orchestrator)
    assert "交易结果" in transport.last_message["text"]
    assert "状态: DRY_RUN_COMPLETED" in transport.last_message["text"]

    transport.push_text(f"/limit_buy {VIRTUAL} 0.01 at 1")
    _tick(orchestrator)
    assert "限价单确认" in transport.last_message["text"]
    assert "到价后自动执行" in transport.last_message["text"]
    confirm_limit = _callback_from_last_message(transport, "confirm:")

    transport.push_callback(confirm_limit)
    _tick(orchestrator)
    assert any("限价单已启用" in message["text"] for message in transport.messages)
    assert "限价单已自动执行" in transport.last_message["text"]
    assert "执行状态: DRY_RUN_COMPLETED" in transport.last_message["text"]

    transport.push_text("/orders")
    _tick(orchestrator)
    assert "当前订单" in transport.last_message["text"]
    assert "限价单: 0" in transport.last_message["text"]

    transport.push_text("/history")
    _tick(orchestrator)
    assert "历史订单" in transport.last_message["text"]
    assert "DRY_RUN_COMPLETED" in transport.last_message["text"]
    assert store.list_history_orders(limit=10)
    assert store.list_history_conditional_orders(limit=10)


def test_simulated_telegram_rejects_bad_and_unauthorized_inputs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    handler = TelegramCommandHandler(
        TelegramCommandParser(),
        service,
        store,
        allowed_user_ids={"user1"},
        allowed_chat_ids={"chat1"},
    )
    transport = SimulatedTelegramTransport()
    runtime = TelegramRuntime(handler, transport, chat_id="chat1")
    orchestrator = RuntimeOrchestrator(store, telegram_runtime=runtime)

    transport.push_text(f"/buy {VIRTUAL} 0.01", user_id="user2")
    _tick(orchestrator)
    assert transport.last_message["text"] == "Unauthorized"
    assert store.list_orders(limit=10) == []

    transport.push_text(f"/buy {VIRTUAL}", user_id="user1")
    _tick(orchestrator)
    assert "Command error" in transport.last_message["text"]
    assert store.list_orders(limit=10) == []
