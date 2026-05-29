from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from app.config.settings import load_app_config
from app.copy_trading import CopyTradeActionBuilder, CopyTradeClassifier, CopyTradeWatcher, DebankHistoryParser
from app.copy_trading.models import CopyTargetConfig, CopyTargetStatus
from app.core.order_info import TokenInfo
from app.core.order_state import OrderStatus
from app.execution.okx_client import OkxDexClient
from app.execution.receipt_tracker import OkxReceiptTracker
from app.orders.order_service import OrderService
from app.risk.context import SQLiteRiskContextProvider
from app.risk.risk_engine import RiskEngine
from app.secrets.provider import CompositeSecretProvider
from app.signing.local_signer import LocalSigner
from app.storage.sqlite_store import SQLiteStore


SOURCE_ADDRESS = "0x138ab382c889add23de09a78fd7a75b9b4fe5c25"
WALLET_ID = "base_main_test"
DEFAULT_WALLET_SECRET_REF = "KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1"
USDC = TokenInfo("USDC", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6)
VIRTUAL = TokenInfo("VIRTUAL", "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b", 18)
SAIRI = TokenInfo("SAIRI", "0xde61878b0b21ce395266c44d4d548d1c72a3eb07", 18)
CLAWBANK = TokenInfo("ClawBank", "0x16332535e2c27da578bc2e82beb09ce9d3c8eb07", 18)
TOKEN_PRICES = {
    USDC.address.lower(): "1",
    VIRTUAL.address.lower(): "0.718",
    SAIRI.address.lower(): "0.00000856",
    CLAWBANK.address.lower(): "0.000022",
}


@dataclass
class SimulatedDebankClient:
    history: dict[str, Any]

    def get_user_history(self, address: str, chain_id: str = "base", page_count: int = 20) -> dict[str, Any]:
        return self.history


@dataclass(frozen=True)
class RpcTokenBalanceProvider:
    rpc_url: str
    wallet_address: str

    def get_token_balance(self, token: TokenInfo) -> Decimal:
        if token.address.lower() == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            result = self._rpc("eth_getBalance", [self.wallet_address, "latest"])
        else:
            data = "0x70a08231" + self._address_arg(self.wallet_address)
            result = self._rpc("eth_call", [{"to": token.address, "data": data}, "latest"])
        if not isinstance(result, str) or not result.startswith("0x"):
            return Decimal("0")
        return Decimal(int(result, 16)) / (Decimal(10) ** token.decimals)

    def _rpc(self, method: str, params: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                response = requests.post(self.rpc_url, json=body, timeout=20)
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as exc:
                last_error = exc
                if attempt < 5:
                    time.sleep(2 + attempt * 2)
                    continue
                raise RuntimeError(f"RPC request failed during {method}: {exc}") from exc
        else:
            raise RuntimeError(f"RPC request failed during {method}: {last_error}")
        if "error" in payload:
            raise RuntimeError(f"RPC error during {method}: {payload['error']}")
        return payload.get("result")

    @staticmethod
    def _address_arg(address: str) -> str:
        return address.lower().removeprefix("0x").rjust(64, "0")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live copy-trade broadcasts from simulated DeBank history.")
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--db-path", default="var/live_copy_simulated_debank.sqlite")
    parser.add_argument("--source-address", default=SOURCE_ADDRESS)
    parser.add_argument("--copy-ratio", default="0.1")
    parser.add_argument("--max-copy-usd", default="0.01")
    parser.add_argument("--buy-usdc", default="0.01")
    parser.add_argument("--source-sell-claw", default="1000")
    parser.add_argument("--cycle-delay", default="8")
    parser.add_argument(
        "--scenario",
        choices=["clawbank_roundtrip", "multi_token_path"],
        default="clawbank_roundtrip",
    )
    args = parser.parse_args()

    load_dotenv(".env", override=False)
    _require_live_gates()
    config = load_app_config(
        runtime_path=os.environ.get("RUNTIME_CONFIG", "configs/runtime.local.yaml"),
        risk_policy_path=os.environ.get("RISK_CONFIG", "configs/risk_policy.example.yaml"),
        strategies_path=os.environ.get("STRATEGIES_CONFIG", "configs/strategies.example.yaml"),
    )
    secret_provider = CompositeSecretProvider()
    signer = LocalSigner(secret_provider, {WALLET_ID: os.environ.get("LIVE_WALLET_SECRET_REF", DEFAULT_WALLET_SECRET_REF)})
    wallet_address = signer.get_address(WALLET_ID)
    rpc_url = secret_provider.resolve(config.runtime["chains"]["base"]["rpc_url_ref"])
    okx_cfg = config.runtime["providers"]["okx"]
    okx = OkxDexClient(
        okx_cfg["api_key_ref"],
        okx_cfg["secret_key_ref"],
        okx_cfg["passphrase_ref"],
        okx_cfg["project_id_ref"],
        secret_provider,
        base_url=okx_cfg.get("base_url", "https://web3.okx.com"),
    )
    store = SQLiteStore(Path(args.db_path))
    balance_provider = RpcTokenBalanceProvider(rpc_url, wallet_address)
    service = OrderService(
        store=store,
        risk_engine=RiskEngine(config.risk_policy),
        quote_client=okx,
        execution_mode="live",
        execution_client=okx,
        signer=signer,
        risk_context_provider=SQLiteRiskContextProvider(store),
        balance_provider=balance_provider,
        live_enabled=True,
        rpc_url=rpc_url,
    )
    debank = SimulatedDebankClient(history={})
    watcher = CopyTradeWatcher(
        store=store,
        debank_client=debank,
        order_service=service,
        history_parser=DebankHistoryParser(),
        classifier=CopyTradeClassifier(),
        action_builder=CopyTradeActionBuilder(
            wallet_address=wallet_address,
            balance_provider=balance_provider,
        ),
        live_copy_enabled=True,
    )
    store.create_or_update_copy_target(
        CopyTargetConfig(
            address=args.source_address,
            status=CopyTargetStatus.ACTIVE,
            copy_ratio=Decimal(args.copy_ratio),
            max_copy_trade_usd=Decimal(args.max_copy_usd),
            max_age_seconds=300,
        )
    )

    print(f"wallet={wallet_address}")
    print(f"source={args.source_address}")
    print(f"db={args.db_path}")
    successes = 0
    failures: list[dict[str, Any]] = []
    for cycle in range(1, args.cycles + 1):
        if args.scenario == "multi_token_path":
            status = _run_multi_token_path(cycle, args, watcher, debank, store, okx, rpc_url, balance_provider)
            print(json.dumps(status, ensure_ascii=False, sort_keys=True))
            if not status["ok"]:
                failures.append({"cycle": cycle, "scenario": args.scenario, "result": status})
                break
        else:
            status = _run_clawbank_roundtrip(cycle, args, watcher, debank, store, okx, rpc_url, balance_provider)
            print(json.dumps(status, ensure_ascii=False, sort_keys=True))
            if not status["ok"]:
                failures.append({"cycle": cycle, "scenario": args.scenario, "result": status})
                break
        successes += 1
        if cycle < args.cycles:
            time.sleep(float(args.cycle_delay))

    print(
        json.dumps(
            {"scenario": args.scenario, "successful_cycles": successes, "requested_cycles": args.cycles, "failures": failures},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if successes != args.cycles:
        raise SystemExit(1)


def _run_clawbank_roundtrip(
    cycle: int,
    args: argparse.Namespace,
    watcher: CopyTradeWatcher,
    debank: SimulatedDebankClient,
    store: SQLiteStore,
    okx: OkxDexClient,
    rpc_url: str,
    balance_provider: RpcTokenBalanceProvider,
) -> dict[str, Any]:
    print(f"cycle {cycle}/{args.cycles}: simulated buy source {args.buy_usdc} USDC -> ClawBank")
    buy = _run_fixture(watcher, debank, _history("buy", cycle, args.source_address, Decimal(args.buy_usdc), Decimal("443")))
    buy_status = _settle_latest_group(store, okx, rpc_url, buy)
    print(json.dumps(buy_status, ensure_ascii=False, sort_keys=True))
    if not _group_success(buy_status):
        return {"ok": False, "failed_leg": "buy", "legs": [buy_status]}
    _wait_for_positive_balance(balance_provider, CLAWBANK)

    print(f"cycle {cycle}/{args.cycles}: simulated sell source {args.source_sell_claw} ClawBank -> USDC")
    sell = _run_fixture(watcher, debank, _history("sell", cycle, args.source_address, Decimal(args.source_sell_claw), Decimal("0.022")))
    sell_status = _settle_latest_group(store, okx, rpc_url, sell)
    print(json.dumps(sell_status, ensure_ascii=False, sort_keys=True))
    if not _group_success(sell_status):
        return {"ok": False, "failed_leg": "sell", "legs": [buy_status, sell_status]}
    return {"ok": True, "legs": [buy_status, sell_status]}


def _run_multi_token_path(
    cycle: int,
    args: argparse.Namespace,
    watcher: CopyTradeWatcher,
    debank: SimulatedDebankClient,
    store: SQLiteStore,
    okx: OkxDexClient,
    rpc_url: str,
    balance_provider: RpcTokenBalanceProvider,
) -> dict[str, Any]:
    routes = [
        ("usdc_virtual", USDC, VIRTUAL, Decimal("0.01"), Decimal("0.0139")),
        ("virtual_sairi", VIRTUAL, SAIRI, Decimal("0.0139"), Decimal("1168")),
        ("sairi_clawbank", SAIRI, CLAWBANK, Decimal("10000"), Decimal("3890")),
        ("clawbank_usdc", CLAWBANK, USDC, Decimal(args.source_sell_claw), Decimal("0.022")),
    ]
    legs: list[dict[str, Any]] = []
    for name, token_in, token_out, amount_in, amount_out in routes:
        print(f"cycle {cycle}/{args.cycles}: simulated {name} source {amount_in} {token_in.symbol} -> {amount_out} {token_out.symbol}")
        result = _run_fixture(
            watcher,
            debank,
            _history_route(name, cycle, args.source_address, token_in, token_out, amount_in, amount_out),
        )
        status = _settle_latest_group(store, okx, rpc_url, result)
        status["route"] = name
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        legs.append(status)
        if not _group_success(status):
            return {"ok": False, "failed_leg": name, "legs": legs}
        if token_out.address.lower() != USDC.address.lower():
            _wait_for_positive_balance(balance_provider, token_out)
    return {"ok": True, "legs": legs}


def _require_live_gates() -> None:
    required = {
        "RUN_LIVE_TRADE_TESTS": "1",
        "CONFIRM_LIVE_TRADE_BASE": "YES",
        "CONFIRM_LIVE_COPY_TRADE_BASE": "YES",
    }
    missing = [f"{key}={value}" for key, value in required.items() if os.environ.get(key) != value]
    if missing:
        raise SystemExit(f"Refusing live copy test. Set: {', '.join(missing)}")


def _history(kind: str, cycle: int, source_address: str, amount_in: Decimal, amount_out: Decimal) -> dict[str, Any]:
    now = int(time.time())
    if kind == "buy":
        sends = [{"token_id": USDC.address, "amount": str(amount_in)}]
        receives = [{"token_id": CLAWBANK.address, "amount": str(amount_out)}]
    else:
        sends = [{"token_id": CLAWBANK.address, "amount": str(amount_in)}]
        receives = [{"token_id": USDC.address, "amount": str(amount_out)}]
    return {
        "token_dict": _token_dict(),
        "history_list": [
            {
                "id": f"sim-{kind}-{cycle}-{now}",
                "chain": "base",
                "cate_id": "swap",
                "time_at": now,
                "tx": {"id": _fake_tx_hash(kind, cycle, now), "status": 1},
                "sends": sends,
                "receives": receives,
                "project_id": "simulated_debank_live_copy_test",
                "source_address": source_address,
            }
        ],
    }


def _history_route(
    route_name: str,
    cycle: int,
    source_address: str,
    token_in: TokenInfo,
    token_out: TokenInfo,
    amount_in: Decimal,
    amount_out: Decimal,
) -> dict[str, Any]:
    now = int(time.time())
    return {
        "token_dict": _token_dict(),
        "history_list": [
            {
                "id": f"sim-{route_name}-{cycle}-{now}",
                "chain": "base",
                "cate_id": "swap",
                "time_at": now,
                "tx": {"id": _fake_tx_hash(route_name, cycle, now), "status": 1},
                "sends": [{"token_id": token_in.address, "amount": str(amount_in)}],
                "receives": [{"token_id": token_out.address, "amount": str(amount_out)}],
                "project_id": "simulated_debank_live_copy_test",
                "source_address": source_address,
            }
        ],
    }


def _token_dict() -> dict[str, dict[str, Any]]:
    return {
        token.address: {
            "id": token.address,
            "symbol": token.symbol,
            "decimals": token.decimals,
            "price": TOKEN_PRICES[token.address.lower()],
        }
        for token in (USDC, VIRTUAL, SAIRI, CLAWBANK)
    }


def _fake_tx_hash(kind: str, cycle: int, now: int) -> str:
    seed = f"{kind}-{cycle}-{now}".encode("utf-8").hex()
    return "0x" + seed.ljust(64, "0")[:64]


def _run_fixture(watcher: CopyTradeWatcher, debank: SimulatedDebankClient, history: dict[str, Any]) -> Any:
    debank.history = history
    return watcher.process_once()


def _settle_latest_group(store: SQLiteStore, okx: OkxDexClient, rpc_url: str, result: Any) -> dict[str, Any]:
    tracker = OkxReceiptTracker(store, okx, rpc_url=rpc_url)
    statuses = []
    for group in result.action_groups:
        for action in group.actions:
            item: dict[str, Any] = {
                "side": action.side,
                "token_in": action.token_in.symbol if action.token_in else None,
                "token_out": action.token_out.symbol if action.token_out else None,
                "amount": str(action.amount),
                "action_status": action.status.value,
                "reason": action.reason,
                "order_id": action.order_id,
                "order_status": action.order_status,
            }
            if action.order_id and action.order_status == OrderStatus.BROADCASTED.value:
                item["final_status"] = _poll_receipt(tracker, action.order_id)
            statuses.append(item)
    return {"processed_events": result.processed_events, "submitted_orders": result.submitted_orders, "actions": statuses}


def _poll_receipt(tracker: OkxReceiptTracker, order_id: str, timeout_seconds: int = 90) -> str:
    deadline = time.monotonic() + timeout_seconds
    last = OrderStatus.BROADCASTED
    while time.monotonic() < deadline:
        last = tracker.refresh_order(order_id)
        if last in {OrderStatus.FILLED, OrderStatus.FAILED}:
            return last.value
        time.sleep(3)
    return last.value


def _group_success(status: dict[str, Any]) -> bool:
    actions = status.get("actions") or []
    return bool(actions) and all(item.get("final_status") == OrderStatus.FILLED.value for item in actions)


def _wait_for_positive_balance(provider: RpcTokenBalanceProvider, token: TokenInfo, timeout_seconds: int = 45) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if provider.get_token_balance(token) > 0:
            return
        time.sleep(2)
    raise RuntimeError(f"token balance did not become positive: {token.symbol}")


if __name__ == "__main__":
    main()
