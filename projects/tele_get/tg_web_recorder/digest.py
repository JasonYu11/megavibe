from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import load_config, resolve_path
from .env import load_env
from .llm import chat_completion, load_llm_config
from .push import send_telegram_message
from .storage import MessageStore


ROOT = Path(__file__).resolve().parents[1]


SYSTEM_PROMPT = """你是 Telegram 群聊日报助手。请用中文总结给定时间窗口内的群聊分析结果。

要求：
- 输出 Markdown，不要输出 JSON。
- 分 alpha 和 degenchannel 两个部分总结。
- 保留代币名、ticker、合约地址、链、市值/FDV/涨幅等关键事实。
- 明确标注这是群聊信息/传闻/观点，不要给投资建议。
- 末尾列出“值得后续关注”的项目或合约。
"""


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def load_recent_analysis(conn: sqlite3.Connection, since: str) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute(
            """
            SELECT id, target_name, message_count, summary_markdown, detected_contracts_json, created_at
            FROM analysis_runs
            WHERE datetime(created_at) >= datetime(?)
            ORDER BY target_name, id
            """,
            (since,),
        )
    )


def build_digest_input(rows: list[sqlite3.Row], since: str) -> str:
    lines = [f"摘要窗口开始: {since}", f"分析记录数: {len(rows)}", ""]
    for row in rows:
        lines.extend(
            [
                f"## target={row['target_name']} analysis_run={row['id']} created_at={row['created_at']}",
                f"message_count={row['message_count']}",
                f"contracts={row['detected_contracts_json']}",
                row["summary_markdown"],
                "",
            ]
        )
    return "\n".join(lines)


def mock_digest(rows: list[sqlite3.Row], since: str) -> str:
    targets = sorted({row["target_name"] for row in rows})
    return "\n".join(
        [
            f"### Telegram 摘要 Mock",
            f"窗口开始：{since}",
            f"分析记录数：{len(rows)}",
            f"目标：{', '.join(targets) if targets else '无'}",
            "",
            "这是本地 mock 摘要，用于验证日报推送链路。",
        ]
    )


def run_digest(config: dict[str, Any], env: dict[str, str], *, hours: int, use_mock: bool, push: bool) -> dict[str, Any]:
    return run_digest_with_key(config, env, hours=hours, use_mock=use_mock, push=push, dedup_key=None)


def run_digest_with_key(
    config: dict[str, Any],
    env: dict[str, str],
    *,
    hours: int,
    use_mock: bool,
    push: bool,
    dedup_key: str | None,
) -> dict[str, Any]:
    db_path = resolve_path(config, config["database_path"])
    store = MessageStore(db_path)
    try:
        since = since_iso(hours)
        rows = load_recent_analysis(store.conn, since)
        output: dict[str, Any] = {
            "database_path": str(db_path),
            "since": since,
            "analysis_count": len(rows),
        }
        if not rows:
            output["skipped"] = "no analysis runs in window"
            return output
        input_text = build_digest_input(rows, since)
        if use_mock:
            summary = mock_digest(rows, since)
            model = "mock"
        else:
            llm_config = load_llm_config(env)
            model = llm_config.model
            summary = chat_completion(
                llm_config,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": input_text},
                ],
            )
        output["model"] = model
        output["summary_preview"] = summary[:800]
        if push:
            if dedup_key and store.sent_push_exists(dedup_key):
                output["push"] = {"status": "skipped", "reason": "duplicate_digest", "dedup_key": dedup_key}
                return output
            content = f"[定时摘要] 最近 {hours} 小时\n\n{summary}"
            response = send_telegram_message(env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_PUSH_CHAT_ID", ""), content)
            sent_at = datetime.now(timezone.utc).isoformat()
            store.record_push_event(
                analysis_run_id=None,
                push_type="digest",
                target_name="all",
                dedup_key=dedup_key,
                content=content,
                status="sent",
                sent_at=sent_at,
            )
            output["push"] = {
                "status": "sent",
                "telegram_message_id": response.get("result", {}).get("message_id"),
                "dedup_key": dedup_key,
            }
        else:
            output["push"] = {"status": "skipped"}
        return output
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and optionally push a digest from analysis runs.")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--env", default=str(ROOT / ".env"))
    parser.add_argument("--hours", type=int, default=12)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    env = load_env(args.env)
    print(json.dumps(run_digest(config, env, hours=args.hours, use_mock=args.mock, push=args.push), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
