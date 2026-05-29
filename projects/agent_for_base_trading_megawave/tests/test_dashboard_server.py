from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.bot.nl_command_agent import NLCommandAgent
from app.bot.telegram_handlers import HandlerResponse
from app.core.order_info import MarketOrder
from app.core.order_state import OrderStatus
from app.dashboard.server import DashboardApp
from app.storage.sqlite_store import SQLiteStore


USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
VIRTUAL = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
TARGET = "0x138ab382c889add23de09a78fd7a75b9b4fe5c25"


class FakeNLClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def complete_json(self, messages: list[dict[str, str]], *, purpose: str) -> dict[str, object]:
        if purpose == "review":
            return {"approved": True, "summary": "审查通过", "warnings": []}
        return self.payload


class FakeHandler:
    def __init__(
        self,
        store: SQLiteStore,
        *,
        allowed_user_ids: set[str] | None = None,
        allowed_chat_ids: set[str] | None = None,
    ) -> None:
        self.store = store
        self.calls: list[str] = []
        self.order_service = SimpleNamespace(execution_mode="dry_run", live_enabled=False)
        self.balance_service = SimpleNamespace(wallet_address="0x8EF454c23822C5373df37e8c5E8987aC64dB96F1")
        self.allowed_user_ids = allowed_user_ids
        self.allowed_chat_ids = allowed_chat_ids

    def handle(self, text: str, actor: str = "telegram", chat_id: str | None = None) -> HandlerResponse:
        self.calls.append(f"{actor}:{chat_id}:{text}")
        return HandlerResponse(text=f"handled {text}", payload={"text": text}, reply_markup={"inline_keyboard": []})

    def handle_callback(self, data: str, actor: str = "telegram", chat_id: str | None = None) -> HandlerResponse:
        self.calls.append(f"{actor}:{chat_id}:callback:{data}")
        return HandlerResponse(text=f"callback {data}", payload={"data": data}, reply_markup=None)

    def _order_detail(self, order_id: str) -> dict[str, object] | None:
        row = self.store.get_order(order_id)
        return None if row is None else {"order": dict(row)}


def test_dashboard_status_orders_commands_and_confirm_bridge(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    order = _market_order("ord_dash_1", source="manual", side="buy", amount="0.01")
    store.create_order(order, status=OrderStatus.PENDING_CONFIRMATION)
    store.insert_risk_decision(order.id, "ALLOW", "", {"max_price_impact_percent": "3"})
    store.insert_quote(order.id, {"data": [{"toTokenAmount": "2000000000000000000"}]})
    app = DashboardApp(store=store, handler=FakeHandler(store))

    status_code, status = app.handle_api("GET", "/api/status", {}, None)
    orders_code, orders = app.handle_api("GET", "/api/orders", {"limit": ["10"]}, None)
    command_code, command = app.handle_api("POST", "/api/commands", {}, {"text": "/status"})
    confirm_code, confirm = app.handle_api("POST", f"/api/orders/{order.id}/confirm", {}, {})

    assert status_code == 200
    assert status["execution_mode"] == "dry_run"
    assert status["wallet_address"].startswith("0x8EF454")
    assert status["orders"] == 1
    assert orders_code == 200
    assert orders["orders"][0]["route"] == "0.01 USDC -> VIRTUAL"
    assert orders["orders"][0]["risk"][0]["decision"] == "ALLOW"
    assert command_code == 200
    assert command["text"] == "handled /status"
    assert confirm_code == 200
    assert confirm["text"] == f"handled /confirm {order.id}"


def test_dashboard_uses_configured_telegram_identity_for_handler_calls(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    handler = FakeHandler(store, allowed_user_ids={"7433362014"}, allowed_chat_ids={"7433362014"})
    app = DashboardApp(store=store, handler=handler)

    status_code, payload = app.handle_api("POST", "/api/commands", {}, {"text": "/status"})

    assert status_code == 200
    assert payload["text"] == "handled /status"
    assert handler.calls == ["7433362014:7433362014:/status"]


def test_dashboard_callback_endpoint_uses_handler_callbacks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    handler = FakeHandler(store, allowed_user_ids={"7433362014"}, allowed_chat_ids={"7433362014"})
    app = DashboardApp(store=store, handler=handler)

    status_code, payload = app.handle_api("POST", "/api/callbacks", {}, {"data": "confirm:ord_1"})

    assert status_code == 200
    assert payload["text"] == "callback confirm:ord_1"
    assert handler.calls == ["7433362014:7433362014:callback:confirm:ord_1"]


def test_dashboard_nl_command_parse_returns_preview_without_executing_handler(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    handler = FakeHandler(store)
    nl_agent = NLCommandAgent(client=FakeNLClient({"status": "mapped", "intent": "status", "slots": {}, "summary": "查看状态"}))
    app = DashboardApp(store=store, handler=handler, nl_agent=nl_agent)

    status_code, payload = app.handle_api("POST", "/api/nl-commands/parse", {}, {"text": "看一下系统状态"})

    assert status_code == 200
    assert payload["result"]["status"] == "mapped"
    assert payload["result"]["command"] == "/status"
    assert payload["result"]["risk"] == "read_only"
    assert handler.calls == []


def test_dashboard_nl_command_parse_blocks_manual_confirmation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    handler = FakeHandler(store)
    nl_agent = NLCommandAgent(client=FakeNLClient({"status": "mapped", "intent": "status", "slots": {}}))
    app = DashboardApp(store=store, handler=handler, nl_agent=nl_agent)

    status_code, payload = app.handle_api("POST", "/api/nl-commands/parse", {}, {"text": "帮我确认 ord_1"})

    assert status_code == 200
    assert payload["result"]["status"] == "blocked_manual_only"
    assert payload["result"]["command"] is None
    assert handler.calls == []


def test_dashboard_runtime_settings_are_editable_and_estimated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    app = DashboardApp(store=store, handler=FakeHandler(store))

    initial_code, initial = app.handle_api("GET", "/api/settings", {}, None)
    updated_code, updated = app.handle_api(
        "PATCH",
        "/api/settings",
        {},
        {"conditional_watcher_interval_seconds": "60", "copy_watcher_interval_seconds": "30"},
    )

    assert initial_code == 200
    assert initial["conditional_watcher_interval_seconds"] == 30
    assert initial["copy_watcher_interval_seconds"] == 30
    assert updated_code == 200
    assert updated["conditional_watcher_interval_seconds"] == 60
    assert updated["copy_watcher_interval_seconds"] == 30
    assert updated["daily_estimates"]["conditional_order_calls_per_day"] == 1440
    assert updated["daily_estimates"]["copy_target_calls_per_day"] == 2880
    assert store.get_runtime_value("conditional_watcher_interval_seconds") == "60"
    assert store.get_runtime_value("copy_watcher_interval_seconds") == "30"


def test_dashboard_copy_target_crud_and_copy_position_summary(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteStore(tmp_path / "orders.sqlite")
    app = DashboardApp(store=store, handler=FakeHandler(store))

    created_code, created = app.handle_api(
        "POST",
        "/api/copy-targets",
        {},
        {"address": TARGET, "copy_ratio": "0.1", "max_copy_trade_usd": "0.01", "max_age_seconds": 300},
    )
    updated_code, updated = app.handle_api(
        "PATCH",
        f"/api/copy-targets/{TARGET}",
        {},
        {"status": "ACTIVE", "copy_ratio": "0.2", "max_copy_trade_usd": "0.02", "max_age_seconds": 180},
    )

    assert created_code == 200
    assert created["target"]["address"] == TARGET
    assert updated_code == 200
    assert updated["target"]["status"] == "ACTIVE"
    assert updated["target"]["copy_ratio"] == "0.2"

    buy = _market_order("ord_copy_buy", source="copy_trade", side="buy", amount="0.001")
    sell = _market_order("ord_copy_sell", source="copy_trade", side="sell", amount="0.4", token_in=VIRTUAL, token_out=USDC)
    store.create_order(buy, status=OrderStatus.FILLED)
    store.create_order(sell, status=OrderStatus.FILLED)
    store.insert_quote(buy.id, {"data": [{"toTokenAmount": "2000000000000000000"}]})
    store.insert_copy_trade_event(
        TARGET,
        "history-1",
        "0xhash1",
        "PROCESSED",
        {
            "kind": "STABLE_OR_ETH_TO_TOKEN",
            "estimated_usd_value": "0.01",
            "actions": [{"order_id": buy.id, "status": "SUBMITTED"}, {"order_id": sell.id, "status": "SUBMITTED"}],
        },
    )

    events_code, events = app.handle_api("GET", "/api/copy-events", {"limit": ["10"]}, None)
    positions_code, positions = app.handle_api("GET", "/api/copy-positions", {}, None)

    assert events_code == 200
    assert events["events"][0]["kind"] == "STABLE_OR_ETH_TO_TOKEN"
    assert positions_code == 200
    assert positions["positions"] == [
        {
            "target_address": TARGET,
            "token_address": VIRTUAL.lower(),
            "token_symbol": "VIRTUAL",
            "total_bought_amount": "2",
            "total_sold_amount": "0.4",
            "net_amount": "1.6",
        }
    ]


def _market_order(
    order_id: str,
    *,
    source: str,
    side: str,
    amount: str,
    token_in: str = USDC,
    token_out: str = VIRTUAL,
) -> MarketOrder:
    return MarketOrder.from_dict(
        {
            "id": order_id,
            "source": source,
            "order_type": "market",
            "chain": {"namespace": "evm", "chain_id": 8453, "chain_name": "base"},
            "wallet": {"wallet_id": "base_main_test", "address": "0x8EF454c23822C5373df37e8c5E8987aC64dB96F1"},
            "token_in": _token(token_in),
            "token_out": _token(token_out),
            "amount": {"type": "exact_in", "value": amount, "unit": "token"},
            "trade": {"side": side, "route_provider": "okx", "execution_mode": "immediate"},
            "approval": {"require_confirmation": True, "confirmation_channel": "dashboard"},
        }
    )


def _token(address: str) -> dict[str, object]:
    if address.lower() == USDC.lower():
        return {"symbol": "USDC", "address": USDC, "decimals": 6}
    if address.lower() == VIRTUAL.lower():
        return {"symbol": "VIRTUAL", "address": VIRTUAL, "decimals": 18}
    raise AssertionError(address)
