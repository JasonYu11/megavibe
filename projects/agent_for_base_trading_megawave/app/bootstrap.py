from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.bot.command_parser import TelegramCommandParser
from app.bot.guided_flow import GuidedTradeFlow
from app.bot.orchestrator import RuntimeOrchestrator
from app.bot.runtime import TelegramHttpTransport, TelegramRuntime
from app.bot.telegram_handlers import TelegramCommandHandler
from app.config.settings import AppConfig
from app.copy_trading import CopyTradeActionBuilder, CopyTradeClassifier, CopyTradeWatcher, DebankHistoryParser, DebankTokenBalanceProvider
from app.data.balance_service import DebankBalanceService
from app.data.debank_client import DebankClient
from app.data.price_provider import DebankPriceProvider
from app.data.token_resolver import TokenResolver
from app.execution.okx_client import OkxDexClient
from app.execution.receipt_tracker import OkxReceiptTracker
from app.orders.conditional_watcher import ConditionalOrderWatcher
from app.orders.order_service import OrderService
from app.risk.context import SQLiteRiskContextProvider
from app.risk.risk_engine import RiskEngine
from app.secrets.provider import CompositeSecretProvider, SecretProvider
from app.signing.local_signer import LocalSigner
from app.storage.sqlite_store import SQLiteStore


@dataclass(frozen=True)
class TradingRuntimeApp:
    store: SQLiteStore
    debank_client: DebankClient
    okx_client: OkxDexClient
    token_resolver: TokenResolver
    parser: TelegramCommandParser
    handler: TelegramCommandHandler
    orchestrator: RuntimeOrchestrator


def build_trading_runtime_app(
    config: AppConfig,
    db_path: str | Path | None = None,
    secret_provider: SecretProvider | None = None,
) -> TradingRuntimeApp:
    runtime = config.runtime
    secret_provider = secret_provider or CompositeSecretProvider()
    store = SQLiteStore(db_path or runtime.get("storage", {}).get("sqlite_path", "var/orders.sqlite"))

    debank_cfg = runtime["providers"]["debank"]
    debank_client = DebankClient(
        access_key_ref=debank_cfg["access_key_ref"],
        secret_provider=secret_provider,
        base_url=debank_cfg.get("base_url", "https://pro-openapi.debank.com/v1"),
    )
    okx_cfg = runtime["providers"]["okx"]
    okx_client = OkxDexClient(
        api_key_ref=okx_cfg["api_key_ref"],
        secret_key_ref=okx_cfg["secret_key_ref"],
        passphrase_ref=okx_cfg["passphrase_ref"],
        project_id_ref=okx_cfg["project_id_ref"],
        secret_provider=secret_provider,
        base_url=okx_cfg.get("base_url", "https://web3.okx.com"),
    )

    signer = LocalSigner(
        secret_provider,
        {"base_main_test": runtime["wallets"]["base_main_test"]["signer_ref"]},
    )
    wallet_address = _wallet_address(runtime, signer)
    token_resolver = TokenResolver(debank_client)
    parser = TelegramCommandParser(token_resolver=token_resolver, wallet_address=wallet_address)
    rpc_url = _optional_secret(secret_provider, runtime["chains"]["base"].get("rpc_url_ref"))
    balance_service = DebankBalanceService(debank_client, wallet_address=wallet_address)
    token_balance_provider = DebankTokenBalanceProvider(debank_client, wallet_address=wallet_address)
    order_service = OrderService(
        store=store,
        risk_engine=RiskEngine(config.risk_policy),
        quote_client=okx_client,
        execution_mode=config.execution_mode,
        execution_client=okx_client,
        signer=signer,
        risk_context_provider=SQLiteRiskContextProvider(store, balance_service=balance_service),
        balance_provider=token_balance_provider,
        live_enabled=_live_enabled(config.execution_mode),
        rpc_url=rpc_url,
    )
    price_provider = DebankPriceProvider(debank_client)
    guided_flow = GuidedTradeFlow(store, parser)
    handler = TelegramCommandHandler(
        parser=parser,
        order_service=order_service,
        store=store,
        balance_service=balance_service,
        price_provider=price_provider,
        guided_flow=guided_flow,
        allowed_user_ids=_csv_env("TELEGRAM_ALLOWED_USER_IDS"),
        allowed_chat_ids=_allowed_chat_ids(runtime),
    )
    watcher = ConditionalOrderWatcher(store, price_provider, order_service)
    conditional_interval = _strategy_interval(config.strategies, "conditional_order", default=30)
    copy_interval = _strategy_interval(config.strategies, "copy_trade", default=30)
    _seed_runtime_interval(store, "conditional_watcher_interval_seconds", conditional_interval)
    _seed_runtime_interval(store, "copy_watcher_interval_seconds", copy_interval)
    copy_watcher = CopyTradeWatcher(
        store=store,
        debank_client=debank_client,
        order_service=order_service,
        history_parser=DebankHistoryParser(),
        classifier=CopyTradeClassifier(),
        action_builder=CopyTradeActionBuilder(
            wallet_address=wallet_address,
            balance_provider=token_balance_provider,
        ),
        live_copy_enabled=_live_copy_enabled(config.execution_mode),
    )
    receipt_tracker = OkxReceiptTracker(store, okx_client, rpc_url=rpc_url)
    telegram_runtime = _build_telegram_runtime(runtime, secret_provider, handler)
    orchestrator = RuntimeOrchestrator(
        store=store,
        telegram_runtime=telegram_runtime,
        conditional_watcher=watcher,
        copy_trade_watcher=copy_watcher,
        receipt_tracker=receipt_tracker,
        poll_interval_seconds=float(runtime.get("telegram", {}).get("poll_interval_seconds", 5)),
        conditional_watcher_interval_seconds=float(conditional_interval),
        copy_watcher_interval_seconds=float(copy_interval),
    )
    return TradingRuntimeApp(
        store=store,
        debank_client=debank_client,
        okx_client=okx_client,
        token_resolver=token_resolver,
        parser=parser,
        handler=handler,
        orchestrator=orchestrator,
    )


def _optional_secret(secret_provider: SecretProvider, secret_ref: str | None) -> str | None:
    if not secret_ref:
        return None
    try:
        return secret_provider.resolve(secret_ref)
    except Exception:
        return None


def _strategy_interval(strategies: dict, section: str, default: int) -> int:
    try:
        value = int(strategies.get(section, {}).get("poll_interval_seconds", default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _seed_runtime_interval(store: SQLiteStore, key: str, value: int) -> None:
    if store.get_runtime_value(key) is None:
        store.set_runtime_value(key, str(value))


def _wallet_address(runtime: dict, signer: LocalSigner) -> str:
    configured = str(runtime["wallets"]["base_main_test"].get("address") or "")
    if configured and configured.lower() != "0x0000000000000000000000000000000000000000":
        return configured
    try:
        return signer.get_address("base_main_test")
    except Exception:
        return configured


def _live_enabled(execution_mode: str) -> bool:
    if execution_mode != "live":
        return False
    return os.environ.get("RUN_LIVE_TRADE_TESTS") == "1" and os.environ.get("CONFIRM_LIVE_TRADE_BASE") == "YES"


def _live_copy_enabled(execution_mode: str) -> bool:
    return _live_enabled(execution_mode) and os.environ.get("CONFIRM_LIVE_COPY_TRADE_BASE") == "YES"


def _csv_env(name: str) -> set[str] | None:
    raw = os.environ.get(name, "")
    values = {part.strip() for part in raw.split(",") if part.strip()}
    return values or None


def _allowed_chat_ids(runtime: dict) -> set[str] | None:
    ids = _csv_env("TELEGRAM_ALLOWED_CHAT_IDS") or set()
    chat_id = str(runtime.get("telegram", {}).get("default_chat_id") or os.environ.get("TELEGRAM_DEFAULT_CHAT_ID") or "")
    if chat_id:
        ids.add(chat_id)
    return ids or None


def _build_telegram_runtime(
    runtime: dict,
    secret_provider: SecretProvider,
    handler: TelegramCommandHandler,
) -> TelegramRuntime | None:
    telegram = runtime.get("telegram", {})
    chat_id = str(telegram.get("default_chat_id") or os.environ.get("TELEGRAM_DEFAULT_CHAT_ID") or "")
    token_ref = telegram.get("bot_token_ref")
    if not chat_id or not token_ref:
        return None
    transport = TelegramHttpTransport(token_ref, secret_provider)
    return TelegramRuntime(handler, transport, chat_id=chat_id)
