from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.checkpoint import CheckpointStore


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/checkpoint_restore.py <checkpoint-id>")
        return 2
    cp = CheckpointStore().restore(sys.argv[1])
    action = "deleted created file" if cp.before is None else "restored previous content"
    print(f"{action}: {cp.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

