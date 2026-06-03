from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.checkpoint import CheckpointStore


def main() -> int:
    store = CheckpointStore()
    checkpoints = store.list()
    if not checkpoints:
        print("(no checkpoints)")
        return 0
    for cp in checkpoints:
        print(f"{cp.id}  {cp.kind:6}  {cp.path}  via {cp.tool_name}  at {cp.created_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

