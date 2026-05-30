from __future__ import annotations

import hashlib
import re
from typing import Any


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def make_fingerprint(message: dict[str, Any]) -> str:
    text = normalize_text(message.get("text") or message.get("raw_text") or "")
    parts = [
        message.get("target_name", ""),
        message.get("chat_title", ""),
        message.get("topic_title", ""),
        message.get("sender_hint", ""),
        message.get("message_time", ""),
        message.get("media_hint", ""),
        text,
    ]
    payload = "\x1f".join(normalize_text(str(part)) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

