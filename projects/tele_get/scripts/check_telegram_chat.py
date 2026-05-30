#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def tg_get(token: str, method: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    env = {**load_env(ROOT / ".env"), **os.environ}
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print(json.dumps({"ok": False, "error": "TELEGRAM_BOT_TOKEN is empty"}, ensure_ascii=False))
        return 2

    try:
        me = tg_get(token, "getMe")
        updates = tg_get(token, "getUpdates")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"ok": False, "status": exc.code, "error": body}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    chats: dict[str, dict] = {}
    for update in updates.get("result", []):
        message = update.get("message") or update.get("channel_post") or update.get("edited_message") or {}
        chat = message.get("chat")
        if chat and "id" in chat:
            chats[str(chat["id"])] = {
                "id": chat["id"],
                "type": chat.get("type"),
                "title": chat.get("title"),
                "username": chat.get("username"),
                "first_name": chat.get("first_name"),
                "last_name": chat.get("last_name"),
            }

    output = {
        "ok": True,
        "bot": {
            "id": me.get("result", {}).get("id"),
            "username": me.get("result", {}).get("username"),
            "first_name": me.get("result", {}).get("first_name"),
        },
        "chat_count": len(chats),
        "chats": list(chats.values()),
        "hint": "If chat_count is 0, send any message to the bot first, then run this script again.",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
