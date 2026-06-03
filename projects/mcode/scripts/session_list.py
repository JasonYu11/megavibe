from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.session_store import SessionStore


def main() -> int:
    sessions = SessionStore().list()
    if not sessions:
        print("(no sessions)")
        return 0
    for info in sessions:
        print(f"{info.id}  messages={info.messages}  path={info.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
