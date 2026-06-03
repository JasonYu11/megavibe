from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.plan import plan_todo_arguments, plan_todo_event_data


def main() -> int:
    plan = """Plan:

1. Add plan mode core
   - add the marker
   - block writer tools
2. Wire the CLI
   - add /plan command
   - ask for approval
3. Verify
   - run parser demo
   - run syntax checks
"""
    heading_plan = """## Test Plan

### 1. Prepare tests
- create tests directory
- import todo helpers

### 2. Cover behavior
- test valid flat list
- test invalid duplicate in_progress
"""
    print("== plan ==")
    print(plan)
    print("== todo arguments ==")
    print(plan_todo_arguments(plan))
    print("== event data ==")
    print(plan_todo_event_data(plan))
    print("== numbered headings ==")
    print(plan_todo_arguments(heading_plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
