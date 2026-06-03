from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent.agent import _truncate_tool_output


def main() -> int:
    text = "A" * 7000 + "MIDDLE" + "Z" * 7000
    out = _truncate_tool_output(text, max_chars=100)
    print(out)
    print(f"\nlength={len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

