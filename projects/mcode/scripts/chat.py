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
    cfg = load_config()
    provider = DeepSeekProvider(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        temperature=cfg.temperature,
    )
    session = Session(
        "You are a concise Chinese learning assistant for agent engineering. "
        "Remember the conversation context and answer based on it."
    )

    print("Mcode chat")
    print("Type /exit to quit, /history to inspect the current session.\n")

    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not user:
            continue
        if user in {"/exit", "/quit"}:
            return 0
        if user == "/history":
            for i, msg in enumerate(session.messages):
                print(f"{i:02d} {msg.role}: {msg.content}")
            continue

        session.add("user", user)
        try:
            response = provider.complete(session.messages)
        except Exception as exc:
            print(f"error: {exc}")
            continue

        session.add("assistant", response.content)
        print(f"assistant> {response.content}\n")


if __name__ == "__main__":
    raise SystemExit(main())
