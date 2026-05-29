from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from app.bot.command_parser import TelegramCommandParser
from app.bot.nl_command_agent import NLCommandAgent
from app.bot.telegram_handlers import TelegramCommandHandler
from app.copy_trading.models import CopyTargetConfig, CopyTargetStatus
from app.dashboard.server import DashboardApp, serve
from app.orders.order_service import OrderService
from app.risk.risk_engine import RiskEngine
from app.storage.sqlite_store import SQLiteStore

TOKEN_ADDRESS = "0x5F980Dcfc4c0fa3911554cf5ab288ed0eb13DBa3"
USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
DEMO_WALLET = "0x8EF454c23822C5373df37e8c5E8987aC64dB96F1"
COPY_TARGET = "0x138ab382c889add23de09a78fd7a75b9b4fe5c25"


class DemoTokenResolver:
    def resolve(self, address: str) -> dict[str, object]:
        normalized = address.lower()
        if normalized == TOKEN_ADDRESS.lower():
            return {"symbol": "GITLAWB", "address": TOKEN_ADDRESS, "decimals": 18}
        if normalized == USDC_ADDRESS.lower():
            return {"symbol": "USDC", "address": USDC_ADDRESS, "decimals": 6}
        return {"symbol": address, "address": address, "decimals": 18}


class DemoQuoteClient:
    def quote(self, **kwargs: object) -> dict[str, object]:
        amount = Decimal(str(kwargs["amount_base_units"])) / Decimal("1000000")
        to_amount = int((amount / Decimal("0.0001")) * (Decimal(10) ** 18))
        min_receive = int(Decimal(to_amount) * Decimal("0.99"))
        return {
            "code": "0",
            "data": [
                {
                    "routerResult": {
                        "toTokenAmount": str(to_amount),
                        "minReceiveAmount": str(min_receive),
                        "priceImpactPercent": "0.12",
                    },
                    "toTokenAmount": str(to_amount),
                    "minReceiveAmount": str(min_receive),
                    "priceImpactPercent": "0.12",
                }
            ],
            "isHoneyPot": False,
            "taxRate": {"buyTaxRate": "0", "sellTaxRate": "0"},
        }


class DemoBalanceService:
    wallet_address = DEMO_WALLET

    def get_balance(self) -> dict[str, object]:
        return {
            "total_usd_value": "128.40",
            "key_tokens": [
                {"symbol": "USDC", "amount": "42.5", "usd_value": "42.5"},
                {"symbol": "ETH", "amount": "0.025", "usd_value": "85.9"},
            ],
        }


class DemoPriceProvider:
    def get_price_usd(self, token_address: str) -> Decimal:
        return Decimal("0.00008")


def demo_risk_policy() -> dict[str, object]:
    return {
        "risk": {
            "max_single_trade_usd": 5,
            "max_daily_trade_usd": 20,
            "max_slippage_percent": 1.0,
            "max_price_impact_percent": 3.0,
            "copy_trade_max_price_impact_percent": 7.0,
            "allow_honeypot": False,
            "max_buy_tax_percent": 5.0,
            "max_sell_tax_percent": 5.0,
            "require_confirmation_for_all": True,
            "require_confirmation_for_natural_language": True,
        },
        "tokens": {
            "allow_unknown_tokens": True,
            "allowed_tokens": [
                {"symbol": "USDC", "address": USDC_ADDRESS},
                {"symbol": "GITLAWB", "address": TOKEN_ADDRESS},
            ],
            "blocked_tokens": [],
            "blocked_contracts": [],
        },
    }


@dataclass
class DemoServer:
    app: DashboardApp
    base_url: str
    thread: threading.Thread
    server: object

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def build_demo_app(db_path: Path) -> DashboardApp:
    store = SQLiteStore(db_path)
    store.set_runtime_value("watcher_last_ok", "true")
    store.set_runtime_value("copy_watcher_ok", "true")
    store.set_runtime_value("receipt_last_ok", "true")
    store.set_runtime_value("heartbeat_at", str(int(time.time())))
    store.set_runtime_value("conditional_watcher_interval_seconds", "30")
    store.set_runtime_value("copy_watcher_interval_seconds", "30")
    store.create_or_update_copy_target(
        CopyTargetConfig(
            address=COPY_TARGET,
            status=CopyTargetStatus.ACTIVE,
            copy_ratio=Decimal("0.1"),
            max_copy_trade_usd=Decimal("0.01"),
            max_age_seconds=300,
        )
    )
    store.insert_copy_trade_event(
        COPY_TARGET,
        "demo-history-1",
        "0x" + "4" * 64,
        "PROCESSED",
        {
            "kind": "STABLE_OR_ETH_TO_TOKEN",
            "estimated_usd_value": "0.01",
            "actions": [{"label": "买入", "amount": "0.1", "token_in": {"symbol": "USDC"}, "token_out": {"symbol": "GITLAWB"}, "status": "SUBMITTED"}],
        },
    )

    parser = TelegramCommandParser(token_resolver=DemoTokenResolver(), wallet_address=DEMO_WALLET)
    order_service = OrderService(
        store=store,
        risk_engine=RiskEngine(demo_risk_policy()),
        quote_client=DemoQuoteClient(),
        execution_mode="dry_run",
        live_enabled=False,
    )
    handler = TelegramCommandHandler(
        parser=parser,
        order_service=order_service,
        store=store,
        balance_service=DemoBalanceService(),
        price_provider=DemoPriceProvider(),
        allowed_user_ids={"dashboard"},
        allowed_chat_ids={"dashboard"},
    )
    return DashboardApp(store=store, handler=handler, nl_agent=NLCommandAgent(parser=parser))


@contextmanager
def running_demo_server(output_dir: Path, host: str = "127.0.0.1", port: int = 8792) -> Iterator[DemoServer]:
    db_path = output_dir / "demo" / "orders.sqlite"
    if db_path.exists():
        db_path.unlink()
    app = build_demo_app(db_path)
    httpd = serve(app, host=host, port=port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    server = DemoServer(app=app, base_url=f"http://{host}:{port}", thread=thread, server=httpd)
    try:
        yield server
    finally:
        server.stop()

