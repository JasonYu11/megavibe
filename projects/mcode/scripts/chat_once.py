from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent import Session
from mini_agent_lab.config import load_config
from mini_agent_lab.provider import DeepSeekProvider


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/chat_once.py 'your message'")
        return 2

    cfg = load_config()
    provider = DeepSeekProvider(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        temperature=cfg.temperature,
    )
    session = Session("You are a concise Chinese learning assistant for agent engineering.")
    session.add("user", " ".join(sys.argv[1:]))

    response = provider.complete(session.messages)
    session.add("assistant", response.content)

    print(response.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
