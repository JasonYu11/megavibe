from __future__ import annotations

import time
from decimal import Decimal

from app.copy_trading.action_builder import CopyTradeActionBuilder
from app.copy_trading.classifier import CopyTradeClassifier
from app.copy_trading.history_parser import DebankHistoryParser
from app.copy_trading.models import CopyActionStatus, CopyTargetConfig, CopyTargetStatus
from app.copy_trading.watcher import CopyTradeWatcher
from app.orders.order_service import OrderService
from app.risk.risk_engine import RiskEngine
from app.storage.sqlite_store import SQLiteStore
from tests.test_order_service import FakeQuoteClient
from tests.test_risk_engine import policy


ADDRESS = "0x138ab382c889add23de09a78fd7a75b9b4fe5c25"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TOKEN = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
B_TOKEN = "0x0000000000000000000000000000000000000002"


class FakeDebankClient:
    def __init__(self, history):  # type: ignore[no-untyped-def]
        self.history = history
        self.calls = []

    def get_user_history(self, address: str, chain_id: str = "base", page_count: int = 20):  # type: ignore[no-untyped-def]
        self.calls.append((address, chain_id, page_count))
        return self.history


def swap_item(history_id="h1", sends=None, receives=None):  # type: ignore[no-untyped-def]
    return {
        "id": history_id,
        "chain": "base",
        "cate_id": "swap",
        "time_at": int(time.time()),
        "tx": {"status": 1, "id": f"0x{history_id}"},
        "sends": sends or [{"token_id": "usdc", "amount": "100"}],
        "receives": receives or [{"token_id": "token", "amount": "5"}],
        "token_dict": {
            "usdc": {"id": USDC, "symbol": "USDC", "decimals": 6, "price": 1},
            "token": {"id": TOKEN, "symbol": "COIN", "decimals": 18, "price": "2"},
            "b": {"id": B_TOKEN, "symbol": "B", "decimals": 18, "price": "5"},
        },
    }


def make_watcher(tmp_path, history, balance_provider=None):  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    store.create_or_update_copy_target(CopyTargetConfig(address=ADDRESS, status=CopyTargetStatus.ACTIVE))
    service = OrderService(store, RiskEngine(policy()), FakeQuoteClient(), execution_mode="dry_run")
    watcher = CopyTradeWatcher(
        store=store,
        debank_client=FakeDebankClient(history),
        order_service=service,
        history_parser=DebankHistoryParser(),
        classifier=CopyTradeClassifier(),
        action_builder=CopyTradeActionBuilder(balance_provider=balance_provider),
    )
    return watcher, store


def test_copy_watcher_submits_recent_usdc_buy_and_deduplicates_second_tick(tmp_path) -> None:  # type: ignore[no-untyped-def]
    watcher, store = make_watcher(tmp_path, {"history_list": [swap_item()]})

    first = watcher.process_once()
    second = watcher.process_once()

    assert first.checked_targets == 1
    assert first.processed_events == 1
    assert first.submitted_orders == 1
    assert first.action_groups[0].actions[0].order_status == "DRY_RUN_COMPLETED"
    assert len(store.list_orders(limit=10)) == 1
    assert len(store.list_copy_trade_events(ADDRESS)) == 1
    assert second.processed_events == 0
    assert second.skipped_events == 1


def test_copy_watcher_token_to_token_continues_buy_when_sell_balance_zero(tmp_path) -> None:  # type: ignore[no-untyped-def]
    history = {"history_list": [swap_item("h2", sends=[{"token_id": "b", "amount": "2"}], receives=[{"token_id": "token", "amount": "3"}])]}
    watcher, _store = make_watcher(tmp_path, history, balance_provider=lambda token: Decimal("0"))

    result = watcher.process_once()
    actions = result.action_groups[0].actions

    assert [action.side for action in actions] == ["buy", "sell"]
    assert actions[0].status == CopyActionStatus.SUBMITTED
    assert actions[1].status == CopyActionStatus.FAILED
    assert actions[1].reason == "balance_zero"


def test_copy_watcher_ignores_inactive_targets(tmp_path) -> None:  # type: ignore[no-untyped-def]
    watcher, store = make_watcher(tmp_path, {"history_list": [swap_item()]})
    store.update_copy_target(ADDRESS, status=CopyTargetStatus.PAUSED)

    result = watcher.process_once()

    assert result.checked_targets == 0
    assert store.list_orders(limit=10) == []


def test_copy_watcher_refuses_auto_submit_outside_dry_run(tmp_path) -> None:  # type: ignore[no-untyped-def]
    watcher, store = make_watcher(tmp_path, {"history_list": [swap_item()]})
    watcher.order_service.execution_mode = "sign_only"

    result = watcher.process_once()

    assert result.processed_events == 1
    assert result.submitted_orders == 0
    assert result.action_groups[0].actions[0].status == CopyActionStatus.FAILED
    assert result.action_groups[0].actions[0].reason == "copy_auto_execution_requires_dry_run_or_live"
    assert store.list_orders(limit=10) == []


def test_copy_watcher_live_requires_copy_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    watcher, store = make_watcher(tmp_path, {"history_list": [swap_item()]})
    watcher.order_service.execution_mode = "live"
    watcher.order_service.live_enabled = True

    result = watcher.process_once()

    assert result.processed_events == 1
    assert result.submitted_orders == 0
    assert result.action_groups[0].actions[0].status == CopyActionStatus.FAILED
    assert result.action_groups[0].actions[0].reason == "copy_live_disabled"
    assert store.list_orders(limit=10) == []


class LiveLikeOrderService:
    execution_mode = "live"
    live_enabled = True

    def __init__(self) -> None:
        self.submitted = []
        self.confirmed = []

    def submit_market_order(self, order):  # type: ignore[no-untyped-def]
        self.submitted.append(order)

        class Result:
            order_id = "ord_live_copy"
            status = "PENDING_CONFIRMATION"
            reason = ""

        return Result()

    def confirm_order(self, order_id: str, actor: str = "system"):  # type: ignore[no-untyped-def]
        self.confirmed.append((order_id, actor))

        class Result:
            status = "BROADCASTED"
            reason = ""

        result = Result()
        result.order_id = order_id
        return result


def test_copy_watcher_live_copy_gate_auto_confirms_and_broadcasts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    store.create_or_update_copy_target(CopyTargetConfig(address=ADDRESS, status=CopyTargetStatus.ACTIVE))
    service = LiveLikeOrderService()
    watcher = CopyTradeWatcher(
        store=store,
        debank_client=FakeDebankClient({"history_list": [swap_item()]}),
        order_service=service,
        history_parser=DebankHistoryParser(),
        classifier=CopyTradeClassifier(),
        action_builder=CopyTradeActionBuilder(),
        live_copy_enabled=True,
    )

    result = watcher.process_once()

    assert result.submitted_orders == 1
    assert service.submitted
    assert service.confirmed == [("ord_live_copy", "copy_watcher")]
    assert result.action_groups[0].actions[0].order_status == "BROADCASTED"
