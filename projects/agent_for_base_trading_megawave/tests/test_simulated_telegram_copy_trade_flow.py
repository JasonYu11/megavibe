from __future__ import annotations

import time

from app.bot.orchestrator import RuntimeOrchestrator
from app.copy_trading.action_builder import CopyTradeActionBuilder
from app.copy_trading.classifier import CopyTradeClassifier
from app.copy_trading.history_parser import DebankHistoryParser
from app.copy_trading.watcher import CopyTradeWatcher
from tests.test_copy_trade_telegram_handlers import ADDRESS, make_handler
from tests.test_copy_trade_watcher import TOKEN, USDC, FakeDebankClient
from tests.test_runtime_orchestrator import FakeTelegramRuntime


def test_simulated_telegram_copy_trade_flow_reaches_dry_run_notification(tmp_path) -> None:  # type: ignore[no-untyped-def]
    handler, store = make_handler(tmp_path)
    telegram = FakeTelegramRuntime(next_offset=None)
    history = {
        "history_list": [
            {
                "id": "h_flow",
                "chain": "base",
                "cate_id": "swap",
                "time_at": int(time.time()),
                "tx": {"status": 1, "id": "0xflow"},
                "sends": [{"token_id": "usdc", "amount": "100"}],
                "receives": [{"token_id": "token", "amount": "4"}],
                "token_dict": {
                    "usdc": {"id": USDC, "symbol": "USDC", "decimals": 6, "price": 1},
                    "token": {"id": TOKEN, "symbol": "COIN", "decimals": 18, "price": "2"},
                },
            }
        ]
    }
    watcher = CopyTradeWatcher(
        store=store,
        debank_client=FakeDebankClient(history),
        order_service=handler.order_service,
        history_parser=DebankHistoryParser(),
        classifier=CopyTradeClassifier(),
        action_builder=CopyTradeActionBuilder(),
    )
    orchestrator = RuntimeOrchestrator(store, telegram_runtime=telegram, copy_trade_watcher=watcher)

    added = handler.handle(f"/copy_add {ADDRESS}", actor="user1")
    confirmed = handler.handle_callback(added.reply_markup["inline_keyboard"][0][0]["callback_data"], actor="user1")
    updated = handler.handle(f"/copy_set {ADDRESS} ratio 0.00001 max 0.01", actor="user1")
    status = handler.handle("/copy_status", actor="user1")
    result = orchestrator.tick_once()

    assert confirmed.payload["status"] == "ACTIVE"
    assert updated.payload["copy_ratio"] == "0.00001"
    assert status.payload["targets"] == 1
    assert result.copy_watcher_ok is True
    assert len(store.list_orders(limit=10)) == 1
    assert len(telegram.system_messages) == 1
    assert "跟单触发" in telegram.system_messages[0][0]
    assert "状态: 完成" in telegram.system_messages[0][0]
    assert "DRY_RUN_COMPLETED" not in telegram.system_messages[0][0]
