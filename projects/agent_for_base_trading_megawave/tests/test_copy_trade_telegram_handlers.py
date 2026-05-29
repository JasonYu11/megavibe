from __future__ import annotations

from decimal import Decimal

from app.bot.command_parser import TelegramCommandParser
from app.bot.telegram_handlers import TelegramCommandHandler
from app.copy_trading.models import CopyTargetStatus
from app.orders.order_service import OrderService
from app.risk.risk_engine import RiskEngine
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_service import FakeQuoteClient
from tests.test_risk_engine import policy


ADDRESS = "0x138ab382c889add23de09a78fd7a75b9b4fe5c25"


def make_handler(tmp_path):  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    return TelegramCommandHandler(TelegramCommandParser(), service, store), store


def test_copy_add_review_and_callback_confirm(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)

    added = handler.handle(f"/copy_add {ADDRESS}", actor="user1")
    confirmed = handler.handle_callback(f"copy_confirm:{ADDRESS.lower()}", actor="user1")
    target = store.get_copy_target(ADDRESS)

    assert added.payload["status"] == CopyTargetStatus.PENDING_CONFIRMATION.value
    assert "跟单地址确认" in added.text
    assert added.reply_markup["inline_keyboard"][0][0]["callback_data"].startswith("copy_confirm:")
    assert confirmed.payload["status"] == CopyTargetStatus.ACTIVE.value
    assert target is not None
    assert target.status == CopyTargetStatus.ACTIVE


def test_copy_set_list_pause_resume_remove(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)
    handler.handle(f"/copy_add {ADDRESS}", actor="user1")
    handler.handle(f"/copy_confirm {ADDRESS}", actor="user1")

    updated = handler.handle(f"/copy_set {ADDRESS} ratio 0.00002 max 0.02", actor="user1")
    listed = handler.handle("/copy_list", actor="user1")
    paused = handler.handle(f"/copy_pause {ADDRESS}", actor="user1")
    resumed = handler.handle(f"/copy_resume {ADDRESS}", actor="user1")
    removed = handler.handle(f"/copy_remove {ADDRESS}", actor="user1")
    target = store.get_copy_target(ADDRESS)

    assert updated.payload["copy_ratio"] == str(Decimal("0.00002"))
    assert "跟单管理" in listed.text
    assert paused.payload["status"] == CopyTargetStatus.PAUSED.value
    assert resumed.payload["status"] == CopyTargetStatus.ACTIVE.value
    assert removed.payload["status"] == CopyTargetStatus.REMOVED.value
    assert target.status == CopyTargetStatus.REMOVED


def test_copy_command_validation_rejects_invalid_address(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, _store = make_handler(tmp_path)

    response = handler.handle("/copy_add not-address", actor="user1")

    assert response.payload["command"] == "error"
    assert "address required" in response.text
