from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    temperature: float
    max_steps: int


def load_dotenv(path: Union[str, Path] = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config() -> Config:
    load_dotenv()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key or api_key == "sk-your-key-here":
        raise RuntimeError("Please set DEEPSEEK_API_KEY in .env")
    return Config(
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        temperature=float(_env("MCODE_TEMPERATURE", "MINI_AGENT_TEMPERATURE", "0.2")),
        max_steps=int(_env("MCODE_MAX_STEPS", "MINI_AGENT_MAX_STEPS", "300")),
    )


def _env(primary: str, legacy: str, default: str) -> str:
    return os.environ.get(primary, os.environ.get(legacy, default))
