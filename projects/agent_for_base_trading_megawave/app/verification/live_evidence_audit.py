from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_TABLES = {
    "orders",
    "conditional_orders",
    "quotes",
    "risk_decisions",
    "executions",
    "approvals",
    "events",
}

LIVE_FINAL_STATUSES = {"BROADCASTED", "FILLED", "FAILED"}
FORBIDDEN_PAYLOAD_MARKERS = {
    "private_key",
    "signer_ref",
    "secret_ref",
    "debank_access_key",
    "okx_secret",
    "okx_secret_key",
    "telegram_bot_token",
    "agent_wallet_private_key",
    "live_wallet_secret_ref",
    "KEYCHAIN:",
    "ENV:DEBANK_ACCESS_KEY",
    "ENV:OKX_SECRET_KEY",
    "ENV:TELEGRAM_BOT_TOKEN",
}


@dataclass
class LiveEvidenceAudit:
    db_path: Path
    ok: bool
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        status = "OK" if self.ok else "FAILED"
        lines = [f"phase2 live evidence audit: {status}", f"db_path: {self.db_path}"]
        for key in sorted(self.counts):
            lines.append(f"{key}: {self.counts[key]}")
        if self.errors:
            lines.append("errors:")
            lines.extend(f"- {error}" for error in self.errors)
        if self.warnings:
            lines.append("warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)


def audit_live_evidence(db_path: str | Path, require_limit: bool = True) -> LiveEvidenceAudit:
    path = Path(db_path)
    errors: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}

    if not path.exists():
        return LiveEvidenceAudit(path, False, errors=[f"evidence DB does not exist: {path}"])

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = _table_names(conn)
        missing_tables = sorted(REQUIRED_TABLES - tables)
        if missing_tables:
            errors.append(f"missing required tables: {', '.join(missing_tables)}")
            return LiveEvidenceAudit(path, False, counts=counts, errors=errors, warnings=warnings)

        for table in REQUIRED_TABLES:
            counts[f"table.{table}"] = _count(conn, table)

        secret_hits = _scan_secret_markers(conn)
        if secret_hits:
            errors.extend(secret_hits)

        live_orders = _live_orders(conn)
        counts["orders.live_complete"] = len(live_orders)
        if not live_orders:
            errors.append("no live broadcast order with tx hash was found")

        direct_orders = [order for order in live_orders if _trade_execution_mode(order) != "watcher_triggered"]
        watcher_orders = [order for order in live_orders if _trade_execution_mode(order) == "watcher_triggered"]
        counts["orders.live_direct_market"] = len(direct_orders)
        counts["orders.live_watcher_triggered"] = len(watcher_orders)

        if not direct_orders:
            errors.append("no direct market live broadcast evidence was found")
        if require_limit and not watcher_orders:
            errors.append("no watcher-triggered limit live broadcast evidence was found")

        triggered_conditionals = _triggered_conditionals(conn)
        counts["conditional_orders.triggered"] = len(triggered_conditionals)
        if require_limit and not triggered_conditionals:
            errors.append("no triggered conditional order evidence was found")

        for order in live_orders:
            _audit_live_order(conn, order, errors)

        if require_limit:
            for row in triggered_conditionals:
                if not _has_event_payload(conn, row["id"], "current_price"):
                    errors.append(f"conditional order {row['id']} is triggered but has no current_price event payload")

    return LiveEvidenceAudit(path, not errors, counts=counts, errors=errors, warnings=warnings)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row["name"]) for row in rows}


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


def _scan_secret_markers(conn: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    for table, column in [
        ("orders", "payload_json"),
        ("conditional_orders", "payload_json"),
        ("quotes", "payload_json"),
        ("risk_decisions", "payload_json"),
        ("executions", "payload_json"),
        ("approvals", "payload_json"),
        ("events", "payload_json"),
    ]:
        for row in conn.execute(f"SELECT id, {column} FROM {table}"):
            payload = str(row[column])
            lowered = payload.lower()
            for marker in FORBIDDEN_PAYLOAD_MARKERS:
                if marker.lower() in lowered:
                    errors.append(f"secret marker {marker!r} found in {table}.{column} row {row['id']}")
    return errors


def _live_orders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in LIVE_FINAL_STATUSES)
    rows = conn.execute(
        f"""
        SELECT DISTINCT o.*
        FROM orders o
        JOIN executions e ON e.order_id = o.id
        WHERE o.status IN ({placeholders})
          AND e.status IN ({placeholders})
          AND e.tx_hash IS NOT NULL
          AND e.tx_hash != ''
          AND e.payload_json LIKE '%"mode": "live"%'
        ORDER BY o.created_at
        """,
        tuple(LIVE_FINAL_STATUSES) + tuple(LIVE_FINAL_STATUSES),
    ).fetchall()
    return list(rows)


def _triggered_conditionals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT *
            FROM conditional_orders
            WHERE status IN ('TRIGGERED', 'EXECUTING', 'FILLED', 'FAILED')
            ORDER BY created_at
            """
        )
    )


def _trade_execution_mode(order_row: sqlite3.Row) -> str:
    payload = json.loads(order_row["payload_json"])
    return str((payload.get("trade") or {}).get("execution_mode", "immediate"))


def _audit_live_order(conn: sqlite3.Connection, order: sqlite3.Row, errors: list[str]) -> None:
    order_id = order["id"]
    if not _has_rows(conn, "quotes", order_id):
        errors.append(f"order {order_id} has no quote evidence")
    if not _has_rows(conn, "risk_decisions", order_id):
        errors.append(f"order {order_id} has no risk decision evidence")
    if not _has_approval(conn, order_id):
        errors.append(f"order {order_id} has no confirmed approval evidence")
    if not _has_live_broadcast_execution(conn, order_id):
        errors.append(f"order {order_id} has no live broadcast execution with tx hash")
    if not _has_execution_payload(conn, order_id, "receipt"):
        errors.append(f"order {order_id} has no receipt payload evidence")
    if not _has_event_payload(conn, order_id, "post_trade_observation"):
        errors.append(f"order {order_id} has no post-trade observation event")


def _has_rows(conn: sqlite3.Connection, table: str, order_id: str) -> bool:
    row = conn.execute(f"SELECT 1 FROM {table} WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
    return row is not None


def _has_approval(conn: sqlite3.Connection, order_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM approvals WHERE order_id = ? AND decision = 'CONFIRMED' LIMIT 1",
        (order_id,),
    ).fetchone()
    return row is not None


def _has_live_broadcast_execution(conn: sqlite3.Connection, order_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM executions
        WHERE order_id = ?
          AND status IN ('BROADCASTED', 'FILLED', 'FAILED')
          AND tx_hash IS NOT NULL
          AND tx_hash != ''
          AND payload_json LIKE '%"mode": "live"%'
        LIMIT 1
        """,
        (order_id,),
    ).fetchone()
    return row is not None


def _has_execution_payload(conn: sqlite3.Connection, order_id: str, marker: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM executions WHERE order_id = ? AND payload_json LIKE ? LIMIT 1",
        (order_id, f"%{marker}%"),
    ).fetchone()
    return row is not None


def _has_event_payload(conn: sqlite3.Connection, entity_id: str, marker: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM events WHERE entity_id = ? AND payload_json LIKE ? LIMIT 1",
        (entity_id, f"%{marker}%"),
    ).fetchone()
    return row is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Phase 2 live broadcast evidence SQLite DB.")
    parser.add_argument("--db-path", default="var/phase2_live_evidence.sqlite")
    parser.add_argument("--allow-missing-limit", action="store_true")
    args = parser.parse_args(argv)

    result = audit_live_evidence(args.db_path, require_limit=not args.allow_missing_limit)
    print(result.to_text())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

