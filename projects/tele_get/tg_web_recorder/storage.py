from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_name TEXT NOT NULL,
  chat_title TEXT,
  topic_title TEXT,
  peer_id TEXT,
  sender_hint TEXT,
  message_time TEXT,
  text TEXT,
  raw_text TEXT,
  media_hint TEXT,
  has_reply INTEGER NOT NULL DEFAULT 0,
  fingerprint TEXT NOT NULL UNIQUE,
  scraped_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_target_time
ON messages(target_name, message_time);

CREATE TABLE IF NOT EXISTS analysis_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_name TEXT NOT NULL,
  message_from_id INTEGER,
  message_to_id INTEGER,
  message_count INTEGER NOT NULL,
  input_text TEXT NOT NULL,
  summary_markdown TEXT NOT NULL,
  detected_contracts_json TEXT NOT NULL DEFAULT '[]',
  should_push INTEGER NOT NULL DEFAULT 0,
  pushed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_target_created
ON analysis_runs(target_name, created_at);

CREATE TABLE IF NOT EXISTS push_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_run_id INTEGER,
  push_type TEXT NOT NULL,
  target_name TEXT,
  dedup_key TEXT,
  content TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  sent_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(analysis_run_id, push_type)
);

"""


class MessageStore:
    def __init__(self, db_path: Path, jsonl_path: Path | None = None) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(push_events)").fetchall()
        }
        if "dedup_key" not in columns:
            self.conn.execute("ALTER TABLE push_events ADD COLUMN dedup_key TEXT")
        self.conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_push_events_dedup_key
            ON push_events(dedup_key)
            WHERE dedup_key IS NOT NULL AND status = 'sent'
            """
        )

    def insert_message(self, message: dict[str, Any]) -> bool:
        values = {
            "target_name": message.get("target_name", ""),
            "chat_title": message.get("chat_title", ""),
            "topic_title": message.get("topic_title", ""),
            "peer_id": message.get("peer_id", ""),
            "sender_hint": message.get("sender_hint", ""),
            "message_time": message.get("message_time", ""),
            "text": message.get("text", ""),
            "raw_text": message.get("raw_text", ""),
            "media_hint": message.get("media_hint", ""),
            "has_reply": 1 if message.get("has_reply") else 0,
            "fingerprint": message["fingerprint"],
            "scraped_at": message["scraped_at"],
        }
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO messages (
              target_name, chat_title, topic_title, peer_id, sender_hint,
              message_time, text, raw_text, media_hint, has_reply,
              fingerprint, scraped_at
            ) VALUES (
              :target_name, :chat_title, :topic_title, :peer_id, :sender_hint,
              :message_time, :text, :raw_text, :media_hint, :has_reply,
              :fingerprint, :scraped_at
            )
            """,
            values,
        )
        inserted = cur.rowcount == 1
        if inserted and self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        return inserted

    def insert_many(self, messages: list[dict[str, Any]]) -> tuple[int, int]:
        inserted = 0
        duplicate = 0
        for message in messages:
            if self.insert_message(message):
                inserted += 1
            else:
                duplicate += 1
        self.conn.commit()
        return inserted, duplicate

    def fetch_unanalyzed_messages(self, target_name: str, limit: int) -> list[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        max_analyzed_id = self.conn.execute(
            "SELECT COALESCE(MAX(message_to_id), 0) FROM analysis_runs WHERE target_name = ?",
            (target_name,),
        ).fetchone()[0]
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM messages
                WHERE target_name = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (target_name, max_analyzed_id, limit),
            )
        )

    def fetch_recent_messages(self, target_name: str, limit: int) -> list[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        rows = list(
            self.conn.execute(
                """
                SELECT *
                FROM messages
                WHERE target_name = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (target_name, limit),
            )
        )
        return list(reversed(rows))

    def insert_analysis_run(
        self,
        *,
        target_name: str,
        rows: list[sqlite3.Row],
        input_text: str,
        summary_markdown: str,
        detected_contracts: list[str],
        should_push: bool,
    ) -> int:
        message_ids = [int(row["id"]) for row in rows]
        cur = self.conn.execute(
            """
            INSERT INTO analysis_runs (
              target_name, message_from_id, message_to_id, message_count,
              input_text, summary_markdown, detected_contracts_json, should_push
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_name,
                min(message_ids) if message_ids else None,
                max(message_ids) if message_ids else None,
                len(rows),
                input_text,
                summary_markdown,
                json.dumps(detected_contracts, ensure_ascii=False),
                1 if should_push else 0,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def record_push_event(
        self,
        *,
        analysis_run_id: int | None,
        push_type: str,
        target_name: str,
        content: str,
        status: str,
        dedup_key: str | None = None,
        error: str = "",
        sent_at: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO push_events (
              analysis_run_id, push_type, target_name, dedup_key, content, status, error, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (analysis_run_id, push_type, target_name, dedup_key, content, status, error, sent_at),
        )
        if status == "sent" and analysis_run_id is not None:
            self.conn.execute("UPDATE analysis_runs SET pushed_at = ? WHERE id = ?", (sent_at, analysis_run_id))
        self.conn.commit()

    def sent_push_exists(self, dedup_key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM push_events WHERE dedup_key = ? AND status = 'sent' LIMIT 1",
            (dedup_key,),
        ).fetchone()
        return row is not None

    def sent_push_exists_for_message_range(
        self,
        *,
        push_type: str,
        target_name: str,
        message_from_id: int,
        message_to_id: int,
    ) -> bool:
        row = self.conn.execute(
            """
            SELECT 1
            FROM push_events p
            JOIN analysis_runs a ON a.id = p.analysis_run_id
            WHERE p.push_type = ?
              AND p.target_name = ?
              AND p.status = 'sent'
              AND a.message_from_id = ?
              AND a.message_to_id = ?
            LIMIT 1
            """,
            (push_type, target_name, message_from_id, message_to_id),
        ).fetchone()
        return row is not None

    def sent_push_covers_message_to_id(self, *, push_type: str, target_name: str, message_to_id: int) -> bool:
        row = self.conn.execute(
            """
            SELECT MAX(a.message_to_id)
            FROM push_events p
            JOIN analysis_runs a ON a.id = p.analysis_run_id
            WHERE p.push_type = ?
              AND p.target_name = ?
              AND p.status = 'sent'
            """,
            (push_type, target_name),
        ).fetchone()
        max_pushed_to_id = row[0] if row else None
        return max_pushed_to_id is not None and int(max_pushed_to_id) >= int(message_to_id)
