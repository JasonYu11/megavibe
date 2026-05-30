from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config, resolve_path
from .env import load_env
from .llm import chat_completion, load_llm_config
from .push import send_telegram_message
from .storage import MessageStore


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_RE = re.compile(r"0x[a-fA-F0-9]{40}")


SYSTEM_PROMPT = """你是 Telegram 群聊信息整理助手。你的任务是阅读一批新消息，用中文做简洁但不丢关键信息的总结。

要求：
- 输出 Markdown，不要输出 JSON。
- 重点保留代币名、ticker、项目名、合约地址、链、MC/FDV/涨幅/时间等信息。
- 明确区分事实、传闻、群友观点，不要给投资建议。
- 如果消息里出现新的代币、合约地址、明显交易关注点，最后写一行：推送判断：建议推送。
- 如果只是闲聊或没有值得提醒的信息，最后写一行：推送判断：不建议推送。
- 不要编造消息里没有的信息。
"""


def compact_message(row: Any) -> str:
    text = row["text"] or row["raw_text"] or ""
    return (
        f"- id={row['id']} time={row['message_time']} sender={row['sender_hint']} "
        f"media={row['media_hint']} reply={bool(row['has_reply'])}: {text}"
    )


def build_input_text(target_name: str, rows: list[Any]) -> str:
    lines = [
        f"目标: {target_name}",
        f"消息数量: {len(rows)}",
        "新消息:",
    ]
    lines.extend(compact_message(row) for row in rows)
    return "\n".join(lines)


def detect_contracts(*texts: str) -> list[str]:
    seen: dict[str, str] = {}
    for text in texts:
        for match in CONTRACT_RE.findall(text or ""):
            seen.setdefault(match.lower(), match)
    return list(seen.values())


def should_push(summary: str, contracts: list[str]) -> bool:
    if contracts:
        return True
    lowered = summary.lower()
    positive = [
        "推送判断：建议推送",
        "推送判断:建议推送",
        "建议推送",
        "should push",
    ]
    negative = [
        "推送判断：不建议推送",
        "推送判断:不建议推送",
        "不建议推送",
    ]
    if any(item in summary for item in negative):
        return False
    return any(item in summary for item in positive) or "$" in summary or "0x" in lowered


def make_push_dedup_key(push_type: str, target_name: str, rows: list[Any]) -> str:
    if not rows:
        return f"{push_type}:{target_name}:empty"
    message_ids = [str(int(row["id"])) for row in rows]
    digest = hashlib.sha256(",".join(message_ids).encode("utf-8")).hexdigest()[:16]
    return f"{push_type}:{target_name}:{message_ids[0]}-{message_ids[-1]}:{digest}"


def format_contracts(contracts: list[str]) -> str:
    if not contracts:
        return "未识别到合约地址"
    return "\n".join(f"• `{contract}`" for contract in contracts[:8])


def strip_push_decision(summary: str) -> str:
    lines = []
    for line in summary.splitlines():
        if "推送判断" in line:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def format_immediate_card(
    *,
    target_name: str,
    topic_title: str,
    rows: list[Any],
    summary: str,
    contracts: list[str],
) -> str:
    cleaned_summary = strip_push_decision(summary)
    first_id = int(rows[0]["id"]) if rows else 0
    last_id = int(rows[-1]["id"]) if rows else 0
    message_count = len(rows)
    return "\n".join(
        [
            "🚨 即时群聊更新",
            "━━━━━━━━━━━━━━",
            f"📌 来源：{target_name} / {topic_title}",
            f"🧾 消息：{message_count} 条 · id {first_id}-{last_id}",
            "",
            "🔎 识别到的合约",
            format_contracts(contracts),
            "",
            "🧠 LLM 总结",
            cleaned_summary[:3000],
            "",
            "⚠️ 仅为群聊信息整理，不构成投资建议。",
        ]
    )


def mock_summary(input_text: str) -> str:
    contracts = detect_contracts(input_text)
    ticker_matches = sorted(set(re.findall(r"\$[A-Za-z0-9_]{2,12}", input_text)))
    parts = [
        "### 总结",
        "这是本地 mock 分析结果，用于验证 LLM 分析与推送管线。消息中出现了可用于后续处理的交易线索。",
        "",
        "### 关键信息",
    ]
    if ticker_matches:
        parts.append(f"- 代币/ticker: {', '.join(ticker_matches[:8])}")
    if contracts:
        parts.append(f"- 合约地址: {', '.join(contracts[:5])}")
    if not ticker_matches and not contracts:
        parts.append("- 未发现明确 ticker 或合约地址。")
    parts.extend(["", "推送判断：建议推送" if contracts or ticker_matches else "推送判断：不建议推送"])
    return "\n".join(parts)


def analyze_target(
    *,
    store: MessageStore,
    target: dict[str, Any],
    config: dict[str, Any],
    env: dict[str, str],
    use_mock: bool,
    push: bool,
    recent: int,
) -> dict[str, Any]:
    target_name = target["name"]
    limit = int(config.get("analysis_max_messages_per_target", 40))
    rows = store.fetch_recent_messages(target_name, recent) if recent > 0 else store.fetch_unanalyzed_messages(target_name, limit)
    result: dict[str, Any] = {"target": target_name, "message_count": len(rows)}
    if not rows:
        result["skipped"] = "no new messages"
        return result

    input_text = build_input_text(target_name, rows)
    if use_mock:
        summary = mock_summary(input_text)
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

    contracts = detect_contracts(input_text, summary)
    push_flag = should_push(summary, contracts)
    run_id = store.insert_analysis_run(
        target_name=target_name,
        rows=rows,
        input_text=input_text,
        summary_markdown=summary,
        detected_contracts=contracts,
        should_push=push_flag,
    )
    result.update(
        {
            "analysis_run_id": run_id,
            "model": model,
            "message_from_id": int(rows[0]["id"]),
            "message_to_id": int(rows[-1]["id"]),
            "detected_contracts": contracts,
            "should_push": push_flag,
            "summary_preview": summary[:500],
        }
    )

    if push and push_flag:
        dedup_key = make_push_dedup_key("immediate", target_name, rows)
        content = format_immediate_card(
            target_name=target_name,
            topic_title=target.get("topic_title", ""),
            rows=rows,
            summary=summary,
            contracts=contracts,
        )
        if store.sent_push_exists(dedup_key):
            result["push"] = {"status": "skipped", "reason": "duplicate", "dedup_key": dedup_key}
            return result
        if store.sent_push_covers_message_to_id(
            push_type="immediate",
            target_name=target_name,
            message_to_id=int(rows[-1]["id"]),
        ):
            result["push"] = {
                "status": "skipped",
                "reason": "latest_message_already_pushed",
                "dedup_key": dedup_key,
            }
            return result
        if store.sent_push_exists_for_message_range(
            push_type="immediate",
            target_name=target_name,
            message_from_id=int(rows[0]["id"]),
            message_to_id=int(rows[-1]["id"]),
        ):
            result["push"] = {
                "status": "skipped",
                "reason": "duplicate_message_range",
                "dedup_key": dedup_key,
            }
            return result
        try:
            response = send_telegram_message(
                env.get("TELEGRAM_BOT_TOKEN", ""),
                env.get("TELEGRAM_PUSH_CHAT_ID", ""),
                content,
            )
            sent_at = datetime.now(timezone.utc).isoformat()
            store.record_push_event(
                analysis_run_id=run_id,
                push_type="immediate",
                target_name=target_name,
                content=content,
                status="sent",
                dedup_key=dedup_key,
                sent_at=sent_at,
            )
            result["push"] = {
                "status": "sent",
                "telegram_message_id": response.get("result", {}).get("message_id"),
                "dedup_key": dedup_key,
            }
        except Exception as exc:  # Keep analysis successful even if push fails.
            store.record_push_event(
                analysis_run_id=run_id,
                push_type="immediate",
                target_name=target_name,
                content=content,
                status="failed",
                dedup_key=None,
                error=str(exc),
            )
            result["push"] = {"status": "failed", "error": str(exc)}
    else:
        result["push"] = {"status": "skipped", "reason": "disabled or should_push=false"}
    return result


def run_once(config: dict[str, Any], env: dict[str, str], use_mock: bool, push: bool) -> dict[str, Any]:
    db_path = resolve_path(config, config["database_path"])
    store = MessageStore(db_path)
    try:
        output = {"database_path": str(db_path), "targets": []}
        for target in config["targets"]:
            output["targets"].append(
                analyze_target(
                    store=store,
                    target=target,
                    config=config,
                    env=env,
                    use_mock=use_mock,
                    push=push,
                    recent=int(config.get("_analysis_recent", 0) or 0),
                )
            )
        return output
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze collected Telegram messages with an LLM and optionally push.")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--env", default=str(ROOT / ".env"))
    parser.add_argument("--mock", action="store_true", help="Use local mock summary instead of calling LLM API.")
    parser.add_argument("--push", action="store_true", help="Send immediate Telegram push when analysis says it should push.")
    parser.add_argument("--recent", type=int, default=0, help="Test mode: re-analyze the latest N messages per target.")
    args = parser.parse_args()

    config = load_config(args.config)
    config["_analysis_recent"] = args.recent
    env = load_env(args.env)
    print(json.dumps(run_once(config, env, args.mock, args.push), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
