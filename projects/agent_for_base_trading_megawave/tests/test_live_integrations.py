from __future__ import annotations

import os
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pytest
import requests

from app.bot.message_format import format_execution_result
from app.bot.runtime import TelegramHttpTransport
from app.core.order_info import ConditionalOrder, MarketOrder, TokenInfo
from app.core.order_state import OrderStatus
from app.data.debank_client import DebankClient
from app.data.price_provider import DebankPriceProvider
from app.execution.okx_client import OkxDexClient
from app.execution.receipt_tracker import OkxReceiptTracker
from app.orders.conditional_watcher import ConditionalOrderWatcher
from app.orders.order_service import OrderService
from app.risk.risk_engine import RiskEngine
from app.secrets.provider import CompositeSecretProvider, SecretError
from app.signing.local_signer import LocalSigner
from app.storage.sqlite_store import SQLiteStore
from app.strategies.copy_trade import CopyTradeConfig, CopyTradeStrategy
from tests.test_risk_engine import policy


ETH_NATIVE_BASE = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
WETH_BASE = "0x4200000000000000000000000000000000000006"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
VIRTUAL_BASE = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
WALLET_ID = "base_main_test"
DEFAULT_WALLET_SECRET_REF = "KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1"
LIVE_WALLET_SECRET_REF_ENV = "LIVE_WALLET_SECRET_REF"

TOKENS = {
    "ETH": {"symbol": "ETH", "address": ETH_NATIVE_BASE, "decimals": 18},
    "USDC": {"symbol": "USDC", "address": USDC_BASE, "decimals": 6},
    "VIRTUAL": {"symbol": "VIRTUAL", "address": VIRTUAL_BASE, "decimals": 18},
}

SIGN_ONLY_ROUTES = [("ETH", "USDC"), ("USDC", "VIRTUAL")]
LIVE_ROUTE_ENV = "LIVE_TRADE_ROUTE"
LIVE_EVIDENCE_DB_ENV = "LIVE_EVIDENCE_DB_PATH"
DEFAULT_LIVE_EVIDENCE_DB = "var/phase2_live_evidence.sqlite"


@pytest.mark.integration
def test_live_debank_token_info_when_enabled() -> None:
    if os.environ.get("RUN_LIVE_DEBANK_TESTS") != "1":
        pytest.skip("set RUN_LIVE_DEBANK_TESTS=1 to run live DeBank test")

    info = _debank_client().get_token_info(USDC_BASE, chain_id="base")

    assert info["symbol"].upper() == "USDC"
    assert int(info["decimals"]) == 6


def _debank_client() -> DebankClient:
    return DebankClient("ENV:DEBANK_ACCESS_KEY", CompositeSecretProvider())


def _debank_test_address() -> str:
    configured = os.environ.get("DEBANK_TEST_ADDRESS")
    if configured:
        return configured
    try:
        return _signer_and_address(CompositeSecretProvider())[1]
    except BaseException as exc:
        pytest.skip(f"set DEBANK_TEST_ADDRESS or configure local signer for DeBank live tests: {exc}")


def _trade_usd_value() -> Decimal:
    value = Decimal(os.environ.get("LIVE_TRADE_USD_VALUE", "0.01"))
    if value <= 0:
        pytest.fail("LIVE_TRADE_USD_VALUE must be positive")
    if value > Decimal("0.05"):
        pytest.fail("LIVE_TRADE_USD_VALUE must be <= 0.05 for Phase 1 live tests")
    return value


def _token_price_usd(symbol: str) -> Decimal:
    if symbol == "USDC":
        return Decimal("1")
    token_address = WETH_BASE if symbol == "ETH" else TOKENS[symbol]["address"]
    price = _debank_client().get_token_price(token_address, chain_id="base")
    if price is None:
        pytest.skip(f"DeBank price unavailable for {symbol}")
    return Decimal(str(price))


def _amount_for_usd(symbol: str, usd_value: Decimal) -> Decimal:
    token = TOKENS[symbol]
    price = _token_price_usd(symbol)
    scale = Decimal(10) ** int(token["decimals"])
    base_units = int(((usd_value / price) * scale).to_integral_value(rounding=ROUND_DOWN))
    if base_units <= 0:
        pytest.fail(f"{usd_value} USD converts to zero base units for {symbol}")
    return Decimal(base_units) / scale


def _native_eth_balance(address: str) -> Decimal:
    rpc_url = os.environ.get("BASE_RPC_URL")
    if not rpc_url:
        pytest.skip("set BASE_RPC_URL to check native ETH balance")
    response = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [address, "latest"]},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    result = data.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        pytest.fail("Base RPC eth_getBalance returned no result")
    return Decimal(int(result, 16)) / (Decimal(10) ** 18)


def _token_balance(address: str, symbol: str) -> Decimal:
    if symbol == "ETH":
        return _native_eth_balance(address)
    target = TOKENS[symbol]
    tokens = _debank_client().get_user_token_list(address, chain_id="base", is_all=True)
    balance = Decimal("0")
    for token in tokens:
        token_id = str(token.get("id") or "").lower()
        token_symbol = str(token.get("symbol") or "").upper()
        if token_id == str(target["address"]).lower() or token_symbol == symbol:
            balance += Decimal(str(token.get("amount") or "0"))
    return balance


def _require_token_balance(address: str, symbol: str, required_amount: Decimal) -> None:
    balance = _token_balance(address, symbol)
    if balance < required_amount:
        pytest.fail(f"test wallet {symbol} balance {balance} is below required live amount {required_amount}")


@pytest.mark.integration
def test_live_debank_wallet_balance_when_enabled() -> None:
    if os.environ.get("RUN_LIVE_DEBANK_TESTS") != "1":
        pytest.skip("set RUN_LIVE_DEBANK_TESTS=1 to run live DeBank test")

    balance = _debank_client().get_user_chain_balance(_debank_test_address(), chain_id="base")

    assert isinstance(balance, dict)


@pytest.mark.integration
def test_live_debank_user_history_when_enabled() -> None:
    if os.environ.get("RUN_LIVE_DEBANK_TESTS") != "1":
        pytest.skip("set RUN_LIVE_DEBANK_TESTS=1 to run live DeBank test")

    history = _debank_client().get_user_history(_debank_test_address(), chain_id="base", page_count=5)

    assert "history_list" in history
    assert "token_dict" in history


@pytest.mark.integration
def test_live_debank_follow_trade_fixture_when_enabled() -> None:
    if os.environ.get("RUN_LIVE_DEBANK_TESTS") != "1":
        pytest.skip("set RUN_LIVE_DEBANK_TESTS=1 to run live DeBank follow-trade fixture test")

    history = _debank_client().get_user_history(_debank_test_address(), chain_id="base", page_count=10)
    strategy = CopyTradeStrategy(
        CopyTradeConfig(buy_ratio=Decimal("0.1"), sell_ratio=Decimal("0.25"), max_copy_trade_usd=Decimal("0.01")),
        pay_token=TokenInfo.from_dict(TOKENS["USDC"]),
    )

    orders = strategy.generate_orders(history)

    assert orders
    assert all(order.source == "copy_trade" for order in orders)
    assert all(order.approval.require_confirmation for order in orders)


@pytest.mark.integration
@pytest.mark.parametrize(("token_in", "token_out"), SIGN_ONLY_ROUTES)
def test_live_okx_quote_when_enabled(token_in: str, token_out: str) -> None:
    if os.environ.get("RUN_LIVE_OKX_TESTS") != "1":
        pytest.skip("set RUN_LIVE_OKX_TESTS=1 to run live OKX quote test")
    client = _okx_client(CompositeSecretProvider())
    amount = _amount_for_usd(token_in, _trade_usd_value())

    quote = client.quote(
        8453,
        TOKENS[token_in]["address"],
        TOKENS[token_out]["address"],
        _to_base_units(amount, TOKENS[token_in]["decimals"]),
        "1.0",
    )

    assert quote.get("code") == "0"
    assert quote.get("data")


def _require_okx_env() -> None:
    missing = [
        name
        for name in ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_API_PASSPHRASE", "OKX_PROJECT_ID", "BASE_RPC_URL"]
        if not os.environ.get(name)
    ]
    if missing:
        pytest.skip(f"set {', '.join(missing)} to run OKX live/signing test")


def _okx_client(secret_provider: CompositeSecretProvider) -> OkxDexClient:
    return OkxDexClient(
        "ENV:OKX_API_KEY",
        "ENV:OKX_SECRET_KEY",
        "ENV:OKX_API_PASSPHRASE",
        "ENV:OKX_PROJECT_ID",
        secret_provider,
    )


def _live_policy() -> dict:
    risk_policy = policy()
    risk_policy["tokens"]["allowed_tokens"] = [
        {"symbol": "ETH", "address": ETH_NATIVE_BASE},
        {"symbol": "USDC", "address": USDC_BASE},
        {"symbol": "VIRTUAL", "address": VIRTUAL_BASE},
    ]
    return risk_policy


def _to_base_units(amount: Decimal, decimals: int) -> int:
    return int((amount * (Decimal(10) ** decimals)).to_integral_exact())


def _live_market_order(wallet_address: str, token_in: str, token_out: str, amount: Decimal) -> MarketOrder:
    return MarketOrder.from_dict(
        {
            "order_type": "market",
            "source": "cli",
            "chain": {"namespace": "evm", "chain_id": 8453, "chain_name": "base"},
            "wallet": {"wallet_id": WALLET_ID, "address": wallet_address},
            "token_in": TOKENS[token_in],
            "token_out": TOKENS[token_out],
            "amount": {"type": "exact_in", "value": str(amount), "unit": "token"},
            "trade": {"side": "swap", "route_provider": "okx", "execution_mode": "immediate"},
            "approval": {"require_confirmation": True, "confirmation_channel": "cli"},
        }
    )


def _live_order_service(
    okx: OkxDexClient,
    signer: LocalSigner,
    mode: str,
    live_enabled: bool = False,
    db_path: str | Path | None = None,
) -> OrderService:
    return OrderService(
        SQLiteStore(db_path or Path("var") / "tmp_live_test.sqlite"),
        RiskEngine(_live_policy()),
        okx,
        execution_mode=mode,
        execution_client=okx,
        signer=signer,
        live_enabled=live_enabled,
        rpc_url=os.environ["BASE_RPC_URL"],
    )


def _tmp_db_path(tmp_path) -> Path:  # type: ignore[no-untyped-def]
    return tmp_path / "orders.sqlite"


def _live_evidence_db_path() -> Path:
    return Path(os.environ.get(LIVE_EVIDENCE_DB_ENV, DEFAULT_LIVE_EVIDENCE_DB))


def _record_post_trade_observation(service: OrderService, order_id: str, address: str, receipt_status: OrderStatus) -> None:
    history = _debank_client().get_user_history(address, chain_id="base", page_count=5)
    assert "history_list" in history
    service.store.update_order_status(
        order_id,
        receipt_status,
        {
            "post_trade_observation": {
                "source": "debank.user_history",
                "history_count": len(history.get("history_list") or []),
            }
        },
    )


def _notify_live_result(result, label: str) -> None:  # type: ignore[no-untyped-def]
    chat_id = os.environ.get("TELEGRAM_DEFAULT_CHAT_ID")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not chat_id or not token:
        return
    text = format_execution_result(result)
    transport = TelegramHttpTransport("ENV:TELEGRAM_BOT_TOKEN", CompositeSecretProvider())
    try:
        transport.send_message(chat_id, f"{label}: {text}")
    except Exception:
        return


def _signer_and_address(secret_provider: CompositeSecretProvider) -> tuple[LocalSigner, str]:
    secret_ref = os.environ.get(LIVE_WALLET_SECRET_REF_ENV, DEFAULT_WALLET_SECRET_REF)
    signer = LocalSigner(secret_provider, {WALLET_ID: secret_ref})
    try:
        address = signer.get_address(WALLET_ID)
    except SecretError as exc:
        pytest.skip(f"local signer secret not available through {LIVE_WALLET_SECRET_REF_ENV or 'default ref'}: {exc}")
    return signer, address


@pytest.mark.integration
@pytest.mark.parametrize(("token_in", "token_out"), SIGN_ONLY_ROUTES)
def test_live_okx_swap_sign_only_when_enabled(tmp_path, token_in: str, token_out: str) -> None:  # type: ignore[no-untyped-def]
    if os.environ.get("RUN_LIVE_OKX_SIGN_ONLY_TESTS") != "1":
        pytest.skip("set RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 to run live OKX sign_only test")
    _require_okx_env()
    secret_provider = CompositeSecretProvider()
    signer, address = _signer_and_address(secret_provider)
    amount = _amount_for_usd(token_in, _trade_usd_value())
    _require_token_balance(address, token_in, amount)
    okx = _okx_client(secret_provider)
    service = _live_order_service(okx, signer, mode="sign_only", db_path=_tmp_db_path(tmp_path))
    order = _live_market_order(address, token_in, token_out, amount)

    submitted = service.submit_market_order(order)
    result = service.confirm_order(submitted.order_id, actor="manual_live_sign_only_test")

    assert result.status == "SIGNED_NOT_BROADCASTED"
    executions = service.store.get_executions(order.id)
    assert executions[0]["tx_hash"]


def _live_trade_route() -> tuple[str, str]:
    route = os.environ.get(LIVE_ROUTE_ENV, "USDC_TO_VIRTUAL").upper()
    routes = {
        "ETH_TO_USDC": ("ETH", "USDC"),
        "USDC_TO_VIRTUAL": ("USDC", "VIRTUAL"),
    }
    if route not in routes:
        pytest.fail(f"{LIVE_ROUTE_ENV} must be one of: {', '.join(sorted(routes))}")
    return routes[route]


@pytest.mark.integration
def test_live_small_trade_when_explicitly_enabled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    if os.environ.get("RUN_LIVE_TRADE_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TRADE_TESTS=1 to run small live trade test")
    if os.environ.get("CONFIRM_LIVE_TRADE_BASE") != "YES":
        pytest.skip("set CONFIRM_LIVE_TRADE_BASE=YES to explicitly allow live broadcast")
    _require_okx_env()
    token_in, token_out = _live_trade_route()
    amount = _amount_for_usd(token_in, _trade_usd_value())

    secret_provider = CompositeSecretProvider()
    signer, address = _signer_and_address(secret_provider)
    _require_token_balance(address, token_in, amount)
    okx = _okx_client(secret_provider)
    service = _live_order_service(okx, signer, mode="live", live_enabled=True, db_path=_live_evidence_db_path())
    order = _live_market_order(address, token_in, token_out, amount)

    submitted = service.submit_market_order(order)
    result = service.confirm_order(submitted.order_id, actor="manual_live_trade_test")

    assert result.status == "BROADCASTED"
    executions = service.store.get_executions(order.id)
    assert executions[0]["tx_hash"]
    receipt_status = OkxReceiptTracker(service.store, okx).refresh_order(order.id)
    assert receipt_status in {OrderStatus.BROADCASTED, OrderStatus.FILLED, OrderStatus.FAILED}
    row = service.store.get_order(order.id)
    assert row is not None
    assert service.store.get_quotes(order.id)
    assert service.store.get_risk_decisions(order.id)
    assert service.store.get_approvals(order.id)

    if os.environ.get("DEBANK_ACCESS_KEY"):
        _record_post_trade_observation(service, order.id, address, receipt_status)
    _notify_live_result(result, f"phase2 live {token_in}->{token_out}")


@pytest.mark.integration
def test_live_conditional_limit_sign_only_when_enabled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    if os.environ.get("RUN_LIVE_OKX_SIGN_ONLY_TESTS") != "1":
        pytest.skip("set RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 to run live limit sign_only test")
    _require_okx_env()
    secret_provider = CompositeSecretProvider()
    signer, address = _signer_and_address(secret_provider)
    amount = _amount_for_usd("USDC", _trade_usd_value())
    _require_token_balance(address, "USDC", amount)
    current_price = DebankPriceProvider(_debank_client()).get_price_usd(VIRTUAL_BASE)
    okx = _okx_client(secret_provider)
    service = _live_order_service(okx, signer, mode="sign_only", db_path=_tmp_db_path(tmp_path))
    order = ConditionalOrder.from_dict(
        {
            "order_type": "conditional",
            "source": "live_limit_test",
            "chain": {"namespace": "evm", "chain_id": 8453, "chain_name": "base"},
            "wallet": {"wallet_id": WALLET_ID, "address": address},
            "trigger": {
                "type": "price",
                "source": "debank",
                "token": TOKENS["VIRTUAL"],
                "operator": "<=",
                "target_price_usd": str(current_price * Decimal("1.01")),
                "poll_interval_seconds": 30,
            },
            "action": {
                "order_type": "market",
                "token_in": TOKENS["USDC"],
                "token_out": TOKENS["VIRTUAL"],
                "amount": {"type": "exact_in", "value": str(amount), "unit": "token"},
                "trade": {"side": "swap", "route_provider": "okx"},
            },
            "approval": {"require_confirmation_on_trigger": True, "confirmation_channel": "cli"},
            "lifecycle": {"status": "active"},
        }
    )
    service.store.create_conditional_order(order)
    watcher = ConditionalOrderWatcher(service.store, DebankPriceProvider(_debank_client()), service)

    tick = watcher.process_once()
    result = service.confirm_order(tick.executions[0].order_id, actor="manual_live_limit_sign_only_test")

    assert tick.triggered == 1
    assert result.status == "SIGNED_NOT_BROADCASTED"


@pytest.mark.integration
def test_live_conditional_limit_trade_when_explicitly_enabled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    if os.environ.get("RUN_LIVE_TRADE_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TRADE_TESTS=1 to run live limit trade test")
    if os.environ.get("CONFIRM_LIVE_TRADE_BASE") != "YES":
        pytest.skip("set CONFIRM_LIVE_TRADE_BASE=YES to explicitly allow live broadcast")
    if os.environ.get("CONFIRM_LIVE_LIMIT_TRADE_BASE") != "YES":
        pytest.skip("set CONFIRM_LIVE_LIMIT_TRADE_BASE=YES to explicitly allow live limit broadcast")
    _require_okx_env()
    secret_provider = CompositeSecretProvider()
    signer, address = _signer_and_address(secret_provider)
    amount = _amount_for_usd("USDC", _trade_usd_value())
    _require_token_balance(address, "USDC", amount)
    current_price = DebankPriceProvider(_debank_client()).get_price_usd(VIRTUAL_BASE)
    okx = _okx_client(secret_provider)
    service = _live_order_service(okx, signer, mode="live", live_enabled=True, db_path=_live_evidence_db_path())
    order = ConditionalOrder.from_dict(
        {
            "order_type": "conditional",
            "source": "live_limit_broadcast_test",
            "chain": {"namespace": "evm", "chain_id": 8453, "chain_name": "base"},
            "wallet": {"wallet_id": WALLET_ID, "address": address},
            "trigger": {
                "type": "price",
                "source": "debank",
                "token": TOKENS["VIRTUAL"],
                "operator": "<=",
                "target_price_usd": str(current_price * Decimal("1.01")),
                "poll_interval_seconds": 30,
            },
            "action": {
                "order_type": "market",
                "token_in": TOKENS["USDC"],
                "token_out": TOKENS["VIRTUAL"],
                "amount": {"type": "exact_in", "value": str(amount), "unit": "token"},
                "trade": {"side": "swap", "route_provider": "okx"},
            },
            "approval": {"require_confirmation_on_trigger": True, "confirmation_channel": "cli"},
            "lifecycle": {"status": "active"},
        }
    )
    service.store.create_conditional_order(order)
    watcher = ConditionalOrderWatcher(service.store, DebankPriceProvider(_debank_client()), service)

    tick = watcher.process_once()
    result = service.confirm_order(tick.executions[0].order_id, actor="manual_live_limit_trade_test")

    assert tick.triggered == 1
    assert result.status == "BROADCASTED"
    receipt_status = OkxReceiptTracker(service.store, okx).refresh_order(result.order_id)
    assert receipt_status in {OrderStatus.BROADCASTED, OrderStatus.FILLED, OrderStatus.FAILED}
    _record_post_trade_observation(service, result.order_id, address, receipt_status)
    assert service.store.get_events(order.id)
    assert service.store.get_quotes(result.order_id)
    assert service.store.get_risk_decisions(result.order_id)
    assert service.store.get_approvals(result.order_id)
    assert service.store.get_executions(result.order_id)
    _notify_live_result(result, "phase2 live limit USDC->VIRTUAL")


@pytest.mark.integration
def test_live_telegram_send_message_when_enabled() -> None:
    if os.environ.get("RUN_LIVE_TELEGRAM_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TELEGRAM_TESTS=1 to run live Telegram test")
    chat_id = os.environ.get("TELEGRAM_DEFAULT_CHAT_ID")
    if not chat_id:
        pytest.skip("set TELEGRAM_DEFAULT_CHAT_ID to run live Telegram test")

    transport = TelegramHttpTransport("ENV:TELEGRAM_BOT_TOKEN", CompositeSecretProvider())

    transport.send_message(chat_id, "agent_for_base_trading_megawave live Telegram test")
    updates = transport.get_updates(timeout=0, limit=5)
    assert isinstance(updates, list)
