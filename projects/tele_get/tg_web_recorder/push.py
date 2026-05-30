from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


def send_telegram_message(token: str, chat_id: str, text: str) -> dict:
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")
    if not chat_id:
        raise RuntimeError("TELEGRAM_PUSH_CHAT_ID is empty")
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text[:3900],
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {exc.code}: {body}") from exc

