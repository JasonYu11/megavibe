from __future__ import annotations

from decimal import Decimal

from app.bot.command_parser import TelegramCommandParser
from app.bot.guided_flow import GuidedTradeFlow
from app.bot.telegram_handlers import TelegramCommandHandler
from app.core.order_state import OrderStatus
from app.orders.order_service import OrderService
from app.risk.risk_engine import RiskEngine
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_service import FakeQuoteClient
from tests.test_risk_engine import policy

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
VIRTUAL = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"


class StaticPriceProvider:
    def __init__(self, price: str) -> None:
        self.price = Decimal(price)
        self.calls = []

    def get_price_usd(self, token_address: str) -> Decimal:
        self.calls.append(token_address)
        return self.price


def make_handler(tmp_path, price_provider=None, execution_mode="dry_run", live_enabled=False, allowed_user_ids=None, allowed_chat_ids=None):  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(
        store,
        RiskEngine(policy()),
        FakeQuoteClient(),
        execution_mode=execution_mode,
        live_enabled=live_enabled,
    )
    return (
        TelegramCommandHandler(
            TelegramCommandParser(wallet_address="0x0000000000000000000000000000000000000001"),
            service,
            store,
            price_provider=price_provider,
            allowed_user_ids=allowed_user_ids,
            allowed_chat_ids=allowed_chat_ids,
        ),
        store,
    )


def make_guided_handler(tmp_path):  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    parser = TelegramCommandParser()
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    flow = GuidedTradeFlow(store, parser)
    return TelegramCommandHandler(parser, service, store, guided_flow=flow), store


def test_handler_buy_then_reject_persists_decision(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)

    created = handler.handle(f"/buy {VIRTUAL} 2", actor="user1")
    rejected = handler.handle(f"/reject {created.payload['order_id']}", actor="user1")
    approvals = store.get_approvals(created.payload["order_id"])

    assert created.payload["status"] == "PENDING_CONFIRMATION"
    assert rejected.payload["status"] == "REJECTED_BY_USER"
    assert approvals[0]["decision"] == "REJECTED"
    assert created.reply_markup["inline_keyboard"][0][0]["callback_data"].startswith("confirm:")


def test_handler_callback_reject_matches_text_command(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)
    created = handler.handle(f"/buy {VIRTUAL} 2", actor="user1")

    rejected = handler.handle_callback(f"reject:{created.payload['order_id']}", actor="user1")
    approvals = store.get_approvals(created.payload["order_id"])

    assert rejected.payload["status"] == "REJECTED_BY_USER"
    assert approvals[0]["decision"] == "REJECTED"


def test_handler_limit_buy_requires_confirmation_before_active(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)

    response = handler.handle(f"/limit_buy {VIRTUAL} 2 at 1.2", actor="user1")
    active = store.list_active_conditional_orders()

    assert response.payload["status"] == "PENDING_CONFIRMATION"
    assert response.reply_markup["inline_keyboard"][0][0]["callback_data"].startswith("confirm:")
    assert len(active) == 1
    assert active[0]["status"] == "PENDING_CONFIRMATION"


def test_handler_limit_sell_confirm_activates_conditional_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)

    response = handler.handle(f"/limit_sell {VIRTUAL} 10000 at 1.8", actor="user1")
    confirmed = handler.handle(f"/confirm {response.payload['order_id']}", actor="user1")
    active = store.list_active_conditional_orders()
    approvals = store.get_approvals(response.payload["order_id"])

    assert response.payload["status"] == "PENDING_CONFIRMATION"
    assert confirmed.payload["status"] == "ACTIVE"
    assert approvals[0]["decision"] == "CONFIRMED"
    assert len(active) == 1
    assert active[0]["status"] == "ACTIVE"


def test_handler_limit_order_review_shows_current_price_distance(tmp_path) -> None:  # type: ignore[no-untyped-def]
    price_provider = StaticPriceProvider("1.2")
    handler, _store = make_handler(tmp_path, price_provider=price_provider)

    response = handler.handle(f"/limit_sell {VIRTUAL} 10000 at 1.8", actor="user1")

    assert "当前价格: 1.2 USD" in response.text
    assert "距离目标: +50%" in response.text
    assert response.payload["current_price_usd"] == "1.2"
    assert price_provider.calls == [VIRTUAL]


def test_handler_limit_order_review_allows_missing_current_price(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)

    response = handler.handle(f"/limit_buy {VIRTUAL} 2 at 1.2", actor="user1")

    assert "当前价格: 暂不可用" in response.text
    assert response.payload["status"] == "PENDING_CONFIRMATION"
    assert len(store.list_active_conditional_orders()) == 1


def test_handler_guided_trade_creates_pending_market_order_after_confirm(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_guided_handler(tmp_path)

    assert handler.handle("/trade", actor="user1", chat_id="chat1").payload["status"] == "STARTED"
    handler.handle("Buy", actor="user1", chat_id="chat1")
    handler.handle(VIRTUAL, actor="user1", chat_id="chat1")
    review = handler.handle("0.01", actor="user1", chat_id="chat1")
    created = handler.handle("Confirm", actor="user1", chat_id="chat1")

    assert "Review: /buy" in review.text
    assert created.payload["status"] == "PENDING_CONFIRMATION"
    assert len(store.list_orders(limit=10)) == 1
    assert store.get_conversation_state("chat1:user1") is None


def test_handler_guided_trade_supports_callback_choices(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_guided_handler(tmp_path)

    started = handler.handle_callback("trade:start", actor="user1", chat_id="chat1")
    token_prompt = handler.handle_callback("trade:limit_buy", actor="user1", chat_id="chat1")
    amount_prompt = handler.handle(VIRTUAL, actor="user1", chat_id="chat1")
    price_prompt = handler.handle("0.01", actor="user1", chat_id="chat1")
    review = handler.handle("1.2", actor="user1", chat_id="chat1")
    created = handler.handle_callback("trade:confirm", actor="user1", chat_id="chat1")

    assert started.reply_markup["inline_keyboard"][0][0]["callback_data"] == "trade:buy"
    assert "token contract" in token_prompt.text
    assert "amount" in amount_prompt.text
    assert "target USD price" in price_prompt.text
    assert review.reply_markup["inline_keyboard"][0][0]["callback_data"] == "trade:confirm"
    assert created.payload["status"] == "PENDING_CONFIRMATION"
    assert len(store.list_active_conditional_orders()) == 1


def test_handler_guided_trade_cancel_does_not_create_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_guided_handler(tmp_path)

    handler.handle("/trade", actor="user1", chat_id="chat1")
    handler.handle("Sell", actor="user1", chat_id="chat1")
    response = handler.handle("/cancel", actor="user1", chat_id="chat1")

    assert response.payload["status"] == "CANCELLED"
    assert store.list_orders(limit=10) == []


def test_handler_cancel_market_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)

    created = handler.handle(f"/buy {VIRTUAL} 2", actor="user1")
    cancelled = handler.handle(f"/cancel {created.payload['order_id']}", actor="user1")
    row = store.get_order(created.payload["order_id"])

    assert cancelled.payload["status"] == "CANCELLED"
    assert row is not None
    assert row["status"] == "CANCELLED"


def test_handler_cancel_conditional_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)
    created = handler.handle(f"/limit_buy {VIRTUAL} 2 at 1.2", actor="user1")

    cancelled = handler.handle(f"/cancel {created.payload['order_id']}", actor="user1")
    active = store.list_active_conditional_orders()

    assert cancelled.payload["status"] == "CANCELLED"
    assert active == []


def test_handler_cancel_unknown_order_is_explicit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path)

    response = handler.handle("/cancel missing_order", actor="user1")

    assert response.payload["status"] == "NOT_FOUND"
    assert response.text == "未找到订单: missing_order"


def test_handler_parse_error_returns_safe_response_without_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)

    response = handler.handle(f"/buy {VIRTUAL}", actor="user1")

    assert response.payload["command"] == "error"
    assert response.text == "Command error: /buy TOKEN_OUT_ADDRESS AMOUNT [--with TOKEN_IN_ADDRESS]"
    assert store.list_orders(limit=10) == []


def test_handler_status_and_orders_report_persisted_records(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path)
    handler.handle(f"/buy {VIRTUAL} 2", actor="user1")
    handler.handle(f"/limit_buy {VIRTUAL} 2 at 1.2", actor="user1")

    status = handler.handle("/status", actor="user1")
    orders = handler.handle("/orders", actor="user1")

    assert status.payload["orders"] == 1
    assert status.payload["conditional_orders"] == 1
    assert status.payload["live_enabled"] is False
    assert status.payload["wallet_address"] is None
    assert "live_enabled=false" in status.text
    assert len(orders.payload["orders"]) == 1
    assert len(orders.payload["conditional_orders"]) == 1
    assert "当前订单" in orders.text


def test_handler_start_help_history_and_order_detail_commands(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path)
    market = handler.handle(f"/buy {VIRTUAL} 2", actor="user1")
    limit_order = handler.handle(f"/limit_sell {VIRTUAL} 10000 at 1.8", actor="user1")
    handler.handle(f"/reject {limit_order.payload['order_id']}", actor="user1")

    start = handler.handle("/start", actor="user1")
    help_response = handler.handle("/help", actor="user1")
    history = handler.handle("/history", actor="user1")
    detail = handler.handle(f"/order {market.payload['order_id']}", actor="user1")
    missing = handler.handle("/order missing_order", actor="user1")

    assert "Base 交易助手" in start.text
    assert start.reply_markup["inline_keyboard"][0][0]["callback_data"] == "trade:start"
    assert "命令说明" in help_response.text
    assert history.payload["command"] == "history"
    assert len(history.payload["conditional_orders"]) == 1
    assert "历史订单" in history.text
    assert "市价单详情" in detail.text
    assert detail.payload["found"] is True
    assert detail.reply_markup["inline_keyboard"][0][0]["callback_data"].startswith("order:")
    assert missing.text == "未找到订单"
    assert missing.payload["found"] is False


def test_handler_mode_reports_execution_mode_and_live_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path, execution_mode="live", live_enabled=False)

    response = handler.handle("/mode", actor="user1")

    assert response.payload["execution_mode"] == "live"
    assert response.payload["live_enabled"] is False
    assert response.text == "运行模式: execution_mode=live\nlive=已关闭"


def test_handler_allowlist_rejects_unauthorized_user(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path, allowed_user_ids={"user1"}, allowed_chat_ids={"chat1"})

    response = handler.handle(f"/buy {VIRTUAL} 2", actor="user2", chat_id="chat1")

    assert response.payload["status"] == "UNAUTHORIZED"
    assert response.text == "Unauthorized"
    assert store.list_orders(limit=10) == []


def test_handler_live_confirm_requires_explicit_live_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path, execution_mode="live", live_enabled=False)
    created = handler.handle(f"/buy {VIRTUAL} 0.01", actor="user1")

    confirmed = handler.handle(f"/confirm {created.payload['order_id']}", actor="user1")

    assert confirmed.payload["status"] == "LIVE_DISABLED"
    assert store.get_approvals(created.payload["order_id"]) == []
    row = store.get_order(created.payload["order_id"])
    assert row is not None
    assert row["status"] == "PENDING_CONFIRMATION"


def test_handler_quote_returns_summary_without_creating_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)

    response = handler.handle(f"/quote {USDC} {VIRTUAL} 2", actor="user1")

    assert response.payload["command"] == "quote"
    assert "报价\n" in response.text
    assert "路径: USDC -> VIRTUAL" in response.text
    assert "价格影响: 0.1%" in response.text
    assert store.list_orders(limit=10) == []
    assert handler.order_service.quote_client.calls[0]["amount_base_units"] == 2_000_000


def test_handler_quote_message_does_not_include_secret_like_values(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path)
    fake_private_key = "0x" + "a" * 64
    fake_api_key = "debank-secret-value"

    response = handler.handle(f"/quote {USDC} {VIRTUAL} 2", actor="user1")

    assert fake_private_key not in response.text
    assert fake_api_key not in response.text


def test_handler_messages_and_buttons_do_not_include_secret_refs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_guided_handler(tmp_path)
    forbidden = [
        "KEYCHAIN:",
        "AGENT_WALLET_PRIVATE_KEY_BASE_TEST1",
        "OKX_SECRET_KEY",
        "DEBANK_ACCESS_KEY",
        "TELEGRAM_BOT_TOKEN",
        "0x" + "a" * 64,
    ]

    responses = [
        handler.handle("/status", actor="user1", chat_id="chat1"),
        handler.handle(f"/buy {VIRTUAL} 2", actor="user1", chat_id="chat1"),
        handler.handle("/trade", actor="user1", chat_id="chat1"),
        handler.handle_callback("trade:buy", actor="user1", chat_id="chat1"),
    ]

    rendered = "\n".join(response.text + "\n" + str(response.reply_markup) for response in responses)

    for value in forbidden:
        assert value not in rendered


def test_handler_balance_uses_injected_service(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path)

    class BalanceService:
        def get_balance(self):  # type: ignore[no-untyped-def]
            return {"total_usd_value": 12.3}

    handler.balance_service = BalanceService()
    response = handler.handle("/balance", actor="user1")

    assert response.payload["available"] is True
    assert response.payload["balance"]["total_usd_value"] == 12.3


def test_handler_confirm_market_order_does_not_auto_query_balance(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path)

    class CountingBalanceService:
        calls = 0

        def get_balance(self):  # type: ignore[no-untyped-def]
            self.calls += 1
            return {"total_usd_value": 12.3}

    balance_service = CountingBalanceService()
    handler.balance_service = balance_service
    created = handler.handle(f"/buy {VIRTUAL} 2", actor="user1")

    confirmed = handler.handle(f"/confirm {created.payload['order_id']}", actor="user1")

    assert balance_service.calls == 0
    assert "钱包余额" not in confirmed.text
    assert "需要时输入 /balance" in confirmed.text


def test_handler_confirm_market_order_returns_chinese_execution_result(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path)
    created = handler.handle(f"/buy {VIRTUAL} 2", actor="user1")

    confirmed = handler.handle(f"/confirm {created.payload['order_id']}", actor="user1")

    assert "交易结果" in confirmed.text
    assert "状态: DRY_RUN_COMPLETED" in confirmed.text
    assert "订单编号:" in confirmed.text
