from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.order_state import OrderStatus
from app.storage.sqlite_store import SQLiteStore


def row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def json_payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def summarize_order(store: SQLiteStore, row: Any) -> dict[str, Any]:
    payload = json_payload(row)
    executions = [row_to_dict(item) for item in store.get_executions(row["id"])]
    quotes = [row_to_dict(item) for item in store.get_quotes(row["id"])]
    risk = [row_to_dict(item) for item in store.get_risk_decisions(row["id"])]
    latest_execution = executions[-1] if executions else None
    latest_quote = _parse_payload(quotes[-1]) if quotes else None
    token_in = payload.get("token_in") if isinstance(payload.get("token_in"), dict) else {}
    token_out = payload.get("token_out") if isinstance(payload.get("token_out"), dict) else {}
    amount = payload.get("amount") if isinstance(payload.get("amount"), dict) else {}
    trade = payload.get("trade") if isinstance(payload.get("trade"), dict) else {}
    return {
        "id": row["id"],
        "status": row["status"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "side": trade.get("side", "swap"),
        "token_in": token_in,
        "token_out": token_out,
        "amount": amount.get("value"),
        "route": _route_text(amount.get("value"), token_in, token_out),
        "last_tx_hash": latest_execution.get("tx_hash") if latest_execution else None,
        "latest_execution": latest_execution,
        "latest_quote": latest_quote,
        "risk": [_parse_payload(item) | {"decision": item["decision"], "reason": item["reason"]} for item in risk],
        "payload": payload,
    }


def summarize_conditional(row: Any) -> dict[str, Any]:
    payload = json_payload(row)
    trigger = payload.get("trigger") if isinstance(payload.get("trigger"), dict) else {}
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    return {
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "trigger": trigger,
        "action": action,
        "payload": payload,
    }


def summarize_copy_target(target: Any, events: list[Any]) -> dict[str, Any]:
    if target is None:
        return {}
    target_events = [row_to_dict(row) for row in events if str(row["target_address"]).lower() == target.address.lower()]
    latest_reason = ""
    if target_events:
        payload = _parse_payload(target_events[0])
        actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
        for action in actions:
            if isinstance(action, dict) and action.get("reason"):
                latest_reason = str(action["reason"])
                break
    return {
        "address": target.address,
        "chain": target.chain,
        "status": target.status.value,
        "copy_ratio": str(target.copy_ratio),
        "max_copy_trade_usd": str(target.max_copy_trade_usd),
        "max_age_seconds": target.max_age_seconds,
        "recent_events": len(target_events),
        "latest_reason": latest_reason,
    }


def summarize_copy_event(row: Any) -> dict[str, Any]:
    payload = json_payload(row)
    return {
        "id": row["id"],
        "target_address": row["target_address"],
        "history_id": row["history_id"],
        "tx_hash": row["tx_hash"],
        "status": row["status"],
        "created_at": row["created_at"],
        "payload": payload,
        "actions": payload.get("actions") if isinstance(payload.get("actions"), list) else [],
        "kind": payload.get("kind"),
        "estimated_usd_value": payload.get("estimated_usd_value"),
    }


def compute_copy_positions(store: SQLiteStore, limit: int = 1000) -> list[dict[str, Any]]:
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    for row in store.list_orders(limit=limit):
        if row["source"] != "copy_trade" or row["status"] not in {OrderStatus.FILLED.value, OrderStatus.BROADCASTED.value}:
            continue
        payload = json_payload(row)
        trade = payload.get("trade") if isinstance(payload.get("trade"), dict) else {}
        side = str(trade.get("side") or "").lower()
        token_in = payload.get("token_in") if isinstance(payload.get("token_in"), dict) else {}
        token_out = payload.get("token_out") if isinstance(payload.get("token_out"), dict) else {}
        amount = _decimal((payload.get("amount") or {}).get("value"))
        target = _target_for_order(store, row["id"])
        if side == "buy":
            bought = _quote_to_amount(store, row["id"], token_out) or Decimal("0")
            _position(positions, target, token_out)["bought"] += bought
        elif side == "sell":
            _position(positions, target, token_in)["sold"] += amount
    results = []
    for (target, token_address), item in positions.items():
        net = item["bought"] - item["sold"]
        results.append(
            {
                "target_address": target,
                "token_address": token_address,
                "token_symbol": item["symbol"],
                "total_bought_amount": _fmt(item["bought"]),
                "total_sold_amount": _fmt(item["sold"]),
                "net_amount": _fmt(net),
            }
        )
    return sorted(results, key=lambda item: (item["target_address"], item["token_symbol"]))


def _route_text(amount: Any, token_in: dict[str, Any], token_out: dict[str, Any]) -> str:
    return f"{amount or '?'} {token_in.get('symbol', '?')} -> {token_out.get('symbol', '?')}"


def _parse_payload(row: Any) -> dict[str, Any]:
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return result if result.is_finite() else Decimal("0")


def _fmt(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _target_for_order(store: SQLiteStore, order_id: str) -> str:
    for row in store.list_copy_trade_events(limit=1000):
        payload = json_payload(row)
        actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
        if any(isinstance(action, dict) and action.get("order_id") == order_id for action in actions):
            return str(row["target_address"])
    return "unknown"


def _position(positions: dict[tuple[str, str], dict[str, Any]], target: str, token: dict[str, Any]) -> dict[str, Any]:
    key = (target, str(token.get("address", "")).lower())
    if key not in positions:
        positions[key] = {
            "symbol": token.get("symbol", token.get("address", "?")),
            "bought": Decimal("0"),
            "sold": Decimal("0"),
        }
    return positions[key]


def _quote_to_amount(store: SQLiteStore, order_id: str, token_out: dict[str, Any]) -> Decimal | None:
    quotes = store.get_quotes(order_id)
    if not quotes:
        return None
    quote = _parse_payload(quotes[-1])
    item = quote.get("data", [{}])[0] if isinstance(quote.get("data"), list) and quote.get("data") else quote
    amount = item.get("toTokenAmount")
    if amount is None:
        return None
    decimals = int(token_out.get("decimals") or 18)
    return _decimal(amount) / (Decimal(10) ** decimals)
