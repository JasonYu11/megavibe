from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mini_agent_lab.tool.base import JsonObject, Tool


TODO_STATUSES = {"pending", "in_progress", "completed"}
MAX_TODOS = 20


@dataclass(frozen=True)
class TodoItem:
    content: str
    status: str
    active_form: str = ""
    level: int = 0


@dataclass(frozen=True)
class TodoSummary:
    todos: list[TodoItem]
    completed: int
    in_progress: int
    pending: int
    current: TodoItem | None = None


class TodoWriteTool(Tool):
    @property
    def name(self) -> str:
        return "todo_write"

    @property
    def description(self) -> str:
        return (
            "Record and update the complete task list for the current work. "
            "Use it for multi-step tasks so progress is visible. Send the full list every call; "
            "it replaces the previous list. Keep at most one item in_progress, and mark an item "
            "completed as soon as it is done instead of batching completions. Skip this for trivial "
            "single-step tasks. Items may be flat or two-level: level 0 is a phase/milestone, "
            "level 1 is a concrete sub-step under the previous phase. A parent phase and child sub-step "
            "cannot both be in_progress; exactly one item total may be in_progress. "
            "Keep the list to 20 items or fewer."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The complete task list, in order. Replaces any previous list.",
                    "maxItems": MAX_TODOS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Imperative task description.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Task state. Keep at most one in_progress.",
                            },
                            "activeForm": {
                                "type": "string",
                                "description": "Present-continuous label shown while active, such as 'Running tests'.",
                            },
                            "level": {
                                "type": "integer",
                                "enum": [0, 1],
                                "description": "0 = phase/milestone, 1 = sub-step. Omit for a flat list.",
                            },
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["todos"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        summary = summarize_todos(arguments)
        return (
            f"Todos updated: {len(summary.todos)} total - "
            f"{summary.completed} completed, {summary.in_progress} in progress, {summary.pending} pending."
        )


def summarize_todos(arguments: JsonObject) -> TodoSummary:
    raw_todos = arguments.get("todos")
    if not isinstance(raw_todos, list):
        raise ValueError("todos must be an array")
    if len(raw_todos) > MAX_TODOS:
        raise ValueError(f"todos has {len(raw_todos)} items; keep it at {MAX_TODOS} or fewer")

    todos: list[TodoItem] = []
    completed = 0
    in_progress = 0
    pending = 0
    current: TodoItem | None = None
    seen_phase = False

    for index, raw in enumerate(raw_todos, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"todo {index}: item must be an object")
        item = _parse_todo(index, raw)
        if item.level == 0:
            seen_phase = True
        elif not seen_phase:
            raise ValueError(f"todo {index}: level 1 sub-step must follow a level 0 phase")
        todos.append(item)
        if item.status == "completed":
            completed += 1
        elif item.status == "in_progress":
            in_progress += 1
            current = item
        else:
            pending += 1

    if in_progress > 1:
        raise ValueError("todo list must have at most one in_progress item")

    return TodoSummary(
        todos=todos,
        completed=completed,
        in_progress=in_progress,
        pending=pending,
        current=current,
    )


def todo_event_data(arguments: JsonObject) -> JsonObject:
    summary = summarize_todos(arguments)
    total = len(summary.todos)
    done = total > 0 and summary.completed == total
    return {
        "todos": [
            {
                "content": item.content,
                "status": item.status,
                "activeForm": item.active_form,
                "level": item.level,
            }
            for item in summary.todos
        ],
        "total": total,
        "completed": summary.completed,
        "in_progress": summary.in_progress,
        "pending": summary.pending,
        "current": _todo_item_data(summary.current),
        "done": done,
        "progress_text": f"{summary.completed}/{total} done",
    }


def _parse_todo(index: int, raw: dict[str, Any]) -> TodoItem:
    content = str(raw.get("content") or "").strip()
    if not content:
        raise ValueError(f"todo {index}: content is required")

    status = str(raw.get("status") or "pending").strip()
    if status not in TODO_STATUSES:
        raise ValueError(f"todo {index}: invalid status {status!r}")

    try:
        level = int(raw.get("level", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"todo {index}: level must be 0 or 1") from exc
    if level not in {0, 1}:
        raise ValueError(f"todo {index}: level must be 0 or 1")

    active_form = str(raw.get("activeForm") or "").strip()
    return TodoItem(content=content, status=status, active_form=active_form, level=level)


def _todo_item_data(item: TodoItem | None) -> JsonObject | None:
    if item is None:
        return None
    return {
        "content": item.content,
        "status": item.status,
        "activeForm": item.active_form,
        "level": item.level,
    }
