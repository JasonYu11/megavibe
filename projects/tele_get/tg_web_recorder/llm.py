from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.2
    timeout_seconds: int = 60


def load_llm_config(env: dict[str, str]) -> LLMConfig:
    return LLMConfig(
        base_url=env.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        api_key=env.get("LLM_API_KEY", ""),
        model=env.get("LLM_MODEL", "gpt-4.1-mini"),
        temperature=float(env.get("LLM_TEMPERATURE", "0.2") or 0.2),
        timeout_seconds=int(env.get("LLM_TIMEOUT_SECONDS", "60") or 60),
    )


def chat_completion(config: LLMConfig, messages: list[dict[str, str]]) -> str:
    if not config.api_key:
        raise RuntimeError("LLM_API_KEY is empty")
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{config.base_url}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {exc.code}: {error_body}") from exc
    return body["choices"][0]["message"]["content"].strip()

