from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.copy_trading.models import CopyTargetConfig, CopyTargetStatus
from app.core.order_info import ConditionalOrder, MarketOrder
from app.core.order_state import ConditionalOrderStatus, OrderStatus


@dataclass
class SQLiteStore:
    db_path: str | Path

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    order_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conditional_orders (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quotes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS risk_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tx_hash TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    actor TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_states (
                    scope_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS copy_targets (
                    address TEXT PRIMARY KEY,
                    chain TEXT NOT NULL,
                    status TEXT NOT NULL,
                    copy_ratio TEXT NOT NULL,
                    max_copy_trade_usd TEXT NOT NULL,
                    max_age_seconds INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS copy_seen_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_address TEXT NOT NULL,
                    history_id TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(target_address, history_id),
                    UNIQUE(target_address, tx_hash)
                );

                CREATE TABLE IF NOT EXISTS copy_trade_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_address TEXT NOT NULL,
                    history_id TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def create_order(self, order: MarketOrder, status: OrderStatus = OrderStatus.DRAFT) -> None:
        now = self._now()
        payload = json.dumps(order.to_dict(), ensure_ascii=False, sort_keys=True)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO orders (id, order_type, source, status, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (order.id, order.order_type, order.source, status.value, payload, now, now),
            )
            self._insert_event(conn, order.id, "order_created", None, status.value, {"order_id": order.id})

    def create_conditional_order(
        self,
        order: ConditionalOrder,
        status: ConditionalOrderStatus = ConditionalOrderStatus.ACTIVE,
    ) -> None:
        now = self._now()
        payload = json.dumps(order.to_dict(), ensure_ascii=False, sort_keys=True)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO conditional_orders (id, status, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (order.id, status.value, payload, now, now),
            )
            self._insert_event(conn, order.id, "conditional_order_created", None, status.value, {"order_id": order.id})

    def update_order_status(self, order_id: str, status: OrderStatus, payload: dict[str, Any] | None = None) -> None:
        now = self._now()
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown order_id: {order_id}")
            old = row["status"]
            conn.execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (status.value, now, order_id))
            self._insert_event(conn, order_id, "order_status_changed", old, status.value, payload or {})

    def update_conditional_status(
        self,
        order_id: str,
        status: ConditionalOrderStatus,
        payload: dict[str, Any] | None = None,
    ) -> None:
        now = self._now()
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM conditional_orders WHERE id = ?", (order_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown conditional order_id: {order_id}")
            old = row["status"]
            conn.execute(
                "UPDATE conditional_orders SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, order_id),
            )
            self._insert_event(conn, order_id, "conditional_status_changed", old, status.value, payload or {})

    def get_order(self, order_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    def get_conditional_order(self, order_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM conditional_orders WHERE id = ?", (order_id,)).fetchone()

    def get_events(self, entity_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM events WHERE entity_id = ? ORDER BY id", (entity_id,)))

    def list_active_conditional_orders(self) -> list[sqlite3.Row]:
        active = (
            ConditionalOrderStatus.ACTIVE.value,
            ConditionalOrderStatus.TRIGGERED.value,
            ConditionalOrderStatus.PENDING_CONFIRMATION.value,
            ConditionalOrderStatus.PAUSED.value,
        )
        placeholders = ",".join("?" for _ in active)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"SELECT * FROM conditional_orders WHERE status IN ({placeholders}) ORDER BY created_at",
                    active,
                )
            )

    def insert_quote(self, order_id: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO quotes (order_id, payload_json, created_at) VALUES (?, ?, ?)",
                (order_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), self._now()),
            )

    def get_quotes(self, order_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM quotes WHERE order_id = ? ORDER BY id", (order_id,)))

    def insert_risk_decision(self, order_id: str, decision: str, reason: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO risk_decisions (order_id, decision, reason, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (order_id, decision, reason, json.dumps(payload, ensure_ascii=False, sort_keys=True), self._now()),
            )

    def get_risk_decisions(self, order_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM risk_decisions WHERE order_id = ? ORDER BY id", (order_id,)))

    def insert_execution(self, order_id: str, status: str, tx_hash: str | None, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO executions (order_id, status, tx_hash, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (order_id, status, tx_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), self._now()),
            )

    def get_executions(self, order_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM executions WHERE order_id = ? ORDER BY id", (order_id,)))

    def insert_approval(self, order_id: str, decision: str, actor: str | None, payload: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (order_id, decision, actor, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (order_id, decision, actor, json.dumps(payload or {}, ensure_ascii=False, sort_keys=True), self._now()),
            )

    def get_approvals(self, order_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM approvals WHERE order_id = ? ORDER BY id", (order_id,)))

    def list_orders(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)))

    def list_conditional_orders(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM conditional_orders ORDER BY created_at DESC LIMIT ?", (limit,)))

    def list_current_orders(self, limit: int = 20) -> list[sqlite3.Row]:
        current = (
            OrderStatus.PENDING_CONFIRMATION.value,
            OrderStatus.SIGNING.value,
            OrderStatus.BROADCASTED.value,
        )
        placeholders = ",".join("?" for _ in current)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
                    (*current, limit),
                )
            )

    def list_history_orders(self, limit: int = 20) -> list[sqlite3.Row]:
        current = (
            OrderStatus.PENDING_CONFIRMATION.value,
            OrderStatus.SIGNING.value,
            OrderStatus.BROADCASTED.value,
        )
        placeholders = ",".join("?" for _ in current)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"SELECT * FROM orders WHERE status NOT IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
                    (*current, limit),
                )
            )

    def list_current_conditional_orders(self, limit: int = 20) -> list[sqlite3.Row]:
        current = (
            ConditionalOrderStatus.PENDING_CONFIRMATION.value,
            ConditionalOrderStatus.ACTIVE.value,
            ConditionalOrderStatus.TRIGGERED.value,
            ConditionalOrderStatus.EXECUTING.value,
            ConditionalOrderStatus.PAUSED.value,
        )
        placeholders = ",".join("?" for _ in current)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"SELECT * FROM conditional_orders WHERE status IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
                    (*current, limit),
                )
            )

    def list_history_conditional_orders(self, limit: int = 20) -> list[sqlite3.Row]:
        current = (
            ConditionalOrderStatus.PENDING_CONFIRMATION.value,
            ConditionalOrderStatus.ACTIVE.value,
            ConditionalOrderStatus.TRIGGERED.value,
            ConditionalOrderStatus.EXECUTING.value,
            ConditionalOrderStatus.PAUSED.value,
        )
        placeholders = ",".join("?" for _ in current)
        with self.connect() as conn:
            return list(
                conn.execute(
                    f"SELECT * FROM conditional_orders WHERE status NOT IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
                    (*current, limit),
                )
            )

    def save_conversation_state(self, scope_id: str, payload: dict[str, Any]) -> None:
        now = self._now()
        with self.connect() as conn:
            existing = conn.execute("SELECT created_at FROM conversation_states WHERE scope_id = ?", (scope_id,)).fetchone()
            created_at = existing["created_at"] if existing is not None else now
            conn.execute(
                """
                INSERT INTO conversation_states (scope_id, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
                """,
                (scope_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), created_at, now),
            )

    def get_conversation_state(self, scope_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload_json FROM conversation_states WHERE scope_id = ?", (scope_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def clear_conversation_state(self, scope_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM conversation_states WHERE scope_id = ?", (scope_id,))

    def set_runtime_value(self, key: str, value: str) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def get_runtime_value(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM runtime_state WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def create_or_update_copy_target(self, target: CopyTargetConfig) -> None:
        now = self._now()
        address = target.address.lower()
        with self.connect() as conn:
            row = conn.execute("SELECT created_at FROM copy_targets WHERE address = ?", (address,)).fetchone()
            created_at = row["created_at"] if row is not None else now
            conn.execute(
                """
                INSERT INTO copy_targets (
                    address, chain, status, copy_ratio, max_copy_trade_usd, max_age_seconds, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    chain = excluded.chain,
                    status = excluded.status,
                    copy_ratio = excluded.copy_ratio,
                    max_copy_trade_usd = excluded.max_copy_trade_usd,
                    max_age_seconds = excluded.max_age_seconds,
                    updated_at = excluded.updated_at
                """,
                (
                    address,
                    target.chain,
                    target.status.value,
                    str(target.copy_ratio),
                    str(target.max_copy_trade_usd),
                    target.max_age_seconds,
                    created_at,
                    now,
                ),
            )

    def update_copy_target(
        self,
        address: str,
        *,
        status: CopyTargetStatus | None = None,
        copy_ratio: Any | None = None,
        max_copy_trade_usd: Any | None = None,
        max_age_seconds: int | None = None,
    ) -> None:
        current = self.get_copy_target(address)
        if current is None:
            raise KeyError(f"unknown copy target: {address}")
        self.create_or_update_copy_target(
            CopyTargetConfig(
                address=current.address,
                chain=current.chain,
                status=status or current.status,
                copy_ratio=current.copy_ratio if copy_ratio is None else current.copy_ratio.__class__(str(copy_ratio)),
                max_copy_trade_usd=current.max_copy_trade_usd
                if max_copy_trade_usd is None
                else current.max_copy_trade_usd.__class__(str(max_copy_trade_usd)),
                max_age_seconds=max_age_seconds if max_age_seconds is not None else current.max_age_seconds,
            )
        )

    def get_copy_target(self, address: str) -> CopyTargetConfig | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM copy_targets WHERE address = ?", (address.lower(),)).fetchone()
        return self._copy_target_from_row(row) if row is not None else None

    def list_copy_targets(self, status: CopyTargetStatus | None = None) -> list[CopyTargetConfig]:
        with self.connect() as conn:
            if status is None:
                rows = conn.execute("SELECT * FROM copy_targets WHERE status != ? ORDER BY created_at", (CopyTargetStatus.REMOVED.value,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM copy_targets WHERE status = ? ORDER BY created_at", (status.value,)).fetchall()
        return [self._copy_target_from_row(row) for row in rows]

    def is_copy_seen(self, target_address: str, history_id: str, tx_hash: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM copy_seen_transactions
                WHERE target_address = ? AND (history_id = ? OR tx_hash = ?)
                LIMIT 1
                """,
                (target_address.lower(), history_id, tx_hash),
            ).fetchone()
        return row is not None

    def mark_copy_seen(self, target_address: str, history_id: str, tx_hash: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO copy_seen_transactions (target_address, history_id, tx_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (target_address.lower(), history_id, tx_hash, self._now()),
            )

    def insert_copy_trade_event(
        self,
        target_address: str,
        history_id: str,
        tx_hash: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO copy_trade_events (target_address, history_id, tx_hash, status, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    target_address.lower(),
                    history_id,
                    tx_hash,
                    status,
                    json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                    self._now(),
                ),
            )

    def list_copy_trade_events(self, target_address: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if target_address is None:
                return list(conn.execute("SELECT * FROM copy_trade_events ORDER BY id DESC LIMIT ?", (limit,)))
            return list(
                conn.execute(
                    "SELECT * FROM copy_trade_events WHERE target_address = ? ORDER BY id DESC LIMIT ?",
                    (target_address.lower(), limit),
                )
            )

    def insert_event(self, entity_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            self._insert_event(conn, entity_id, event_type, None, None, payload or {})

    @staticmethod
    def _copy_target_from_row(row: sqlite3.Row) -> CopyTargetConfig:
        from decimal import Decimal

        return CopyTargetConfig(
            address=str(row["address"]),
            chain=str(row["chain"]),
            status=CopyTargetStatus(str(row["status"])),
            copy_ratio=Decimal(str(row["copy_ratio"])),
            max_copy_trade_usd=Decimal(str(row["max_copy_trade_usd"])),
            max_age_seconds=int(row["max_age_seconds"]),
        )

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        entity_id: str,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO events (entity_id, event_type, from_status, to_status, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                event_type,
                from_status,
                to_status,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                self._now(),
            ),
        )
