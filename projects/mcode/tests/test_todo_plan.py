"""Tests for todo_write tool and plan markdown parsing."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.tool.todo import (
    MAX_TODOS,
    TodoWriteTool,
    summarize_todos,
    TodoSummary,
)
from mini_agent_lab.tool.complete_step import CompleteStepTool
from mini_agent_lab.plan import build_approved_plan_message, parse_plan_todos


# ── helpers ──────────────────────────────────────────────────────────

_tool = TodoWriteTool()
_complete_step = CompleteStepTool()
_failures: list[str] = []


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        _failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  OK:   {msg}")


def _assert_raises(exc_type: type, msg: str, func, *args, **kwargs) -> None:
    try:
        func(*args, **kwargs)
        _failures.append(msg)
        print(f"  FAIL: {msg} (no exception raised)")
    except exc_type:
        print(f"  OK:   {msg}")
    except Exception as e:
        _failures.append(msg)
        print(f"  FAIL: {msg} (expected {exc_type.__name__}, got {type(e).__name__}: {e})")


def _summary(todos_list: list[dict]) -> TodoSummary:
    return summarize_todos({"todos": todos_list})


# ── Group 1: Normal list cases ──────────────────────────────────────

def test_flat_list() -> None:
    print("\n── Flat list ──")
    todos = [
        {"content": "Read design", "status": "completed"},
        {"content": "Implement tool", "status": "in_progress", "activeForm": "Implementing"},
        {"content": "Run tests", "status": "pending"},
    ]
    s = _summary(todos)
    _assert(s.completed == 1, "completed == 1")
    _assert(s.in_progress == 1, "in_progress == 1")
    _assert(s.pending == 1, "pending == 1")
    _assert(len(s.todos) == 3, "total == 3")
    _assert(s.current is not None and s.current.content == "Implement tool", "current == 'Implement tool'")

    result = _tool.execute({"todos": todos})
    _assert("3 total" in result, "execute() reports 3 total")
    _assert("1 completed" in result, "execute() reports 1 completed")
    _assert("1 pending" in result, "execute() reports 1 pending")


def test_two_level_list() -> None:
    print("\n── Two-level list ──")
    todos = [
        {"content": "Build todo feature", "status": "in_progress", "level": 0},
        {"content": "Add validation", "status": "pending", "level": 1},
        {"content": "Add events", "status": "pending", "level": 1},
    ]
    s = _summary(todos)
    _assert(s.completed == 0, "completed == 0")
    _assert(s.in_progress == 1, "in_progress == 1")
    _assert(s.pending == 2, "pending == 2")
    _assert(len(s.todos) == 3, "total == 3")
    _assert(s.todos[0].level == 0, "phase level == 0")
    _assert(s.todos[1].level == 1, "sub-step level == 1")


def test_all_done() -> None:
    print("\n── All done ──")
    todos = [
        {"content": "Step A", "status": "completed"},
        {"content": "Step B", "status": "completed"},
    ]
    s = _summary(todos)
    _assert(s.completed == 2, "completed == 2")
    _assert(s.in_progress == 0, "in_progress == 0")
    _assert(s.pending == 0, "pending == 0")
    _assert(s.current is None, "current is None")


def test_complete_step_requires_evidence() -> None:
    print("\n── complete_step evidence ──")
    _assert(_complete_step.read_only is True, "complete_step is read-only")
    _assert_raises(
        ValueError,
        "complete_step without evidence raises ValueError",
        _complete_step.execute,
        {"step": "Run tests", "result": "Tests pass", "evidence": []},
    )
    result = _complete_step.execute(
        {
            "step": "Run tests",
            "result": "Tests pass",
            "evidence": [
                {
                    "kind": "verification",
                    "summary": "python3 tests/test_todo_plan.py passed",
                    "command": "python3 tests/test_todo_plan.py",
                }
            ],
        }
    )
    _assert("Run tests" in result, "complete_step reports completed step")
    _assert("verification" in result, "complete_step reports evidence kind")


# ── Group 2: Error cases ────────────────────────────────────────────

def test_multiple_in_progress() -> None:
    print("\n── Multiple in_progress error ──")
    _assert_raises(
        ValueError,
        "two flat items both in_progress raises ValueError",
        _summary,
        [
            {"content": "One", "status": "in_progress"},
            {"content": "Two", "status": "in_progress"},
        ],
    )


def test_phase_and_substep_both_in_progress() -> None:
    print("\n── Phase + sub-step both in_progress ──")
    _assert_raises(
        ValueError,
        "phase and sub-step both in_progress raises ValueError",
        _summary,
        [
            {"content": "Phase", "status": "in_progress", "level": 0},
            {"content": "Sub-step", "status": "in_progress", "level": 1},
        ],
    )


def test_orphan_substep() -> None:
    print("\n── Orphan sub-step ──")
    _assert_raises(
        ValueError,
        "orphan sub-step (level=1 before level=0) raises ValueError",
        _summary,
        [{"content": "Sub-step first", "status": "pending", "level": 1}],
    )


def test_too_many_items() -> None:
    print("\n── Too many items ──")
    lots = [{"content": f"Task {i}", "status": "pending"} for i in range(MAX_TODOS + 1)]
    _assert_raises(
        ValueError,
        f"> {MAX_TODOS} items raises ValueError",
        _summary,
        lots,
    )


def test_empty_content() -> None:
    print("\n── Empty content ──")
    _assert_raises(
        ValueError,
        "empty content raises ValueError",
        _summary,
        [{"content": "", "status": "pending"}],
    )


def test_invalid_status() -> None:
    print("\n── Invalid status ──")
    _assert_raises(
        ValueError,
        "invalid status raises ValueError",
        _summary,
        [{"content": "Task", "status": "unknown"}],
    )


# ── Group 3: Plan markdown parsing ──────────────────────────────────

def test_plan_numbered_headings() -> None:
    print("\n── Plan: numbered headings ──")
    plan = """## Test Plan

### 1. Prepare tests
- create tests directory
- import todo helpers

### 2. Cover behavior
- test valid flat list
- test invalid duplicate in_progress
"""
    todos = parse_plan_todos(plan)
    _assert(len(todos) >= 4, f"got {len(todos)} todos, expected >= 4")
    # First phase should be in_progress
    _assert(todos[0]["status"] == "in_progress", "first item is in_progress")
    _assert(todos[0]["level"] == 0, "first item level == 0")
    _assert(todos[0]["content"] == "Prepare tests", f"phase content: {todos[0]['content']!r}")
    # Rest pending
    for todo in todos[1:]:
        _assert(todo["status"] == "pending", f"'{todo['content']}' is pending")


def test_plan_unordered_indented() -> None:
    print("\n── Plan: unordered indented list ──")
    plan = """Plan:

1. Add plan mode core
   - add the marker
   - block writer tools
2. Wire the CLI
   - add /plan command
"""
    todos = parse_plan_todos(plan)
    _assert(len(todos) >= 4, f"got {len(todos)} todos, expected >= 4")
    _assert(todos[0]["level"] == 0, "phase level == 0")
    _assert(todos[1]["level"] == 1, "indented item level == 1")
    _assert(todos[0]["status"] == "in_progress", "first item in_progress")


def test_plan_empty_string() -> None:
    print("\n── Plan: empty string ──")
    todos = parse_plan_todos("")
    _assert(isinstance(todos, list), "returns list")
    _assert(len(todos) == 0, "empty list")


def test_approved_plan_message_contains_plan_todos_and_rules() -> None:
    print("\n── Approved plan message ──")
    plan = "1. Inspect\n2. Implement\n3. Test"
    message = build_approved_plan_message(plan)
    _assert("Approved plan:\n1. Inspect" in message, "approved message includes plan text")
    _assert("Initial todo_write arguments" in message, "approved message includes todo seed")
    _assert("complete_step" in message, "approved message instructs evidence sign-off")


# ── Runner ───────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 54)
    print("  test_todo_plan.py")
    print("=" * 54)

    # Group 1
    test_flat_list()
    test_two_level_list()
    test_all_done()
    test_complete_step_requires_evidence()

    # Group 2
    test_multiple_in_progress()
    test_phase_and_substep_both_in_progress()
    test_orphan_substep()
    test_too_many_items()
    test_empty_content()
    test_invalid_status()

    # Group 3
    test_plan_numbered_headings()
    test_plan_unordered_indented()
    test_plan_empty_string()
    test_approved_plan_message_contains_plan_todos_and_rules()

    print()
    print(f"Results: {len(_failures)} failure(s) out of "
          f"{len([f for f in dir() if f.startswith('test_')])} test groups")
    if _failures:
        print("Failures:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
