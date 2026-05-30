from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from .config import load_config, resolve_path
from .storage import MessageStore
from .telegram_page import (
    collect_recent_messages,
    current_chat,
    is_logged_in,
    open_target,
    wait_for_telegram,
)


ROOT = Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def run_once(config: dict[str, Any], profile: str, headless: bool) -> dict[str, Any]:
    db_path = resolve_path(config, config["database_path"])
    jsonl_path = resolve_path(config, config.get("jsonl_path", "data/telegram.jsonl"))
    store = MessageStore(db_path, jsonl_path)
    output: dict[str, Any] = {
        "telegram_url": config["telegram_url"],
        "database_path": str(db_path),
        "targets": [],
    }

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile,
            executable_path=CHROME,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(config["telegram_url"], wait_until="domcontentloaded")
            wait_for_telegram(page)
            output["logged_in"] = is_logged_in(page)
            if not output["logged_in"]:
                output["error"] = "Telegram login is required in the configured Chrome profile."
                return output

            for target in config["targets"]:
                target_result: dict[str, Any] = {
                    "target": target["name"],
                    "topic_title": target.get("topic_title", ""),
                }
                opened = open_target(page, target)
                target_result["open"] = opened
                if not opened.get("opened"):
                    target_result["parsed"] = 0
                    target_result["inserted"] = 0
                    target_result["duplicate"] = 0
                    output["targets"].append(target_result)
                    continue

                chat_title = current_chat(page)
                messages, scroll_result = collect_recent_messages(page, target, int(config.get("scroll_pages", 0)))
                max_messages = int(config.get("max_messages_per_sync", 0) or 0)
                if max_messages > 0:
                    messages = messages[-max_messages:]
                inserted, duplicate = store.insert_many(messages)
                target_result.update(
                    {
                        "current_chat": chat_title,
                        "scroll": scroll_result,
                        "parsed": len(messages),
                        "inserted": inserted,
                        "duplicate": duplicate,
                        "sample": [
                            {
                                "time": msg.get("message_time"),
                                "sender_hint": msg.get("sender_hint"),
                                "media_hint": msg.get("media_hint"),
                                "text": (msg.get("text") or msg.get("raw_text") or "")[:140],
                            }
                            for msg in messages[:3]
                        ],
                    }
                )
                output["targets"].append(target_result)
        finally:
            context.close()
            store.close()
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram Web recorder.")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--profile", default=str(ROOT / "profiles" / "telegram-web"))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    if not args.watch:
        print(json.dumps(run_once(config, args.profile, args.headless), ensure_ascii=False, indent=2))
        return

    while True:
        print(json.dumps(run_once(config, args.profile, args.headless), ensure_ascii=False))
        time.sleep(int(config.get("interval_seconds", 300)))


if __name__ == "__main__":
    main()
