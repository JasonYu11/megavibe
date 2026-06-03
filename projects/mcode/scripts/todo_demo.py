from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.tool.todo import TodoWriteTool, todo_event_data


def main() -> int:
    tool = TodoWriteTool()
    cases = [
        (
            "flat list",
            {
                "todos": [
                    {"content": "Read design", "status": "completed"},
                    {"content": "Implement tool", "status": "in_progress", "activeForm": "Implementing tool"},
                    {"content": "Run tests", "status": "pending"},
                ]
            },
        ),
        (
            "two-level list",
            {
                "todos": [
                    {"content": "Build todo feature", "status": "in_progress", "level": 0},
                    {"content": "Add validation", "status": "pending", "level": 1},
                    {"content": "Add events", "status": "pending", "level": 1},
                ]
            },
        ),
        (
            "all done",
            {
                "todos": [
                    {"content": "Read design", "status": "completed"},
                    {"content": "Run demo", "status": "completed"},
                ]
            },
        ),
        (
            "invalid: multiple in_progress",
            {
                "todos": [
                    {"content": "One", "status": "in_progress"},
                    {"content": "Two", "status": "in_progress"},
                ]
            },
        ),
        (
            "invalid: orphan sub-step",
            {"todos": [{"content": "Sub-step first", "status": "pending", "level": 1}]},
        ),
        (
            "invalid: too many items",
            {"todos": [{"content": f"Task {i}", "status": "pending"} for i in range(21)]},
        ),
    ]

    for name, args in cases:
        print(f"== {name} ==")
        try:
            print(tool.execute(args))
            print(todo_event_data(args))
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
