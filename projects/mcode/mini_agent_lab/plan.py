from __future__ import annotations

import json
import re
from typing import Optional

from mini_agent_lab.tool.todo import MAX_TODOS, todo_event_data


PLAN_MODE_MARKER = """[Plan mode - read-only.
Explore the codebase first using read-only tools such as read_file, ls, grep, and glob.
Do not write files, edit files, or run side-effecting commands.
When you understand the task, present a concise two-level markdown plan as your reply and stop.
Use top-level numbered items as phases and indented bullets as concrete sub-steps.
Keep the plan small, concrete, and verifiable. The user will approve before changes are made.]"""


PLAN_APPROVED_MESSAGE = """Plan approved - plan mode is off.
Implement the approved plan now.
Keep the task list current with todo_write: preserve the two-level shape, keep one item in_progress, and mark each step completed as you finish it.
If using phases and sub-steps, do not mark a parent phase and its child sub-step in_progress at the same time; exactly one todo total may be in_progress.
When a concrete step is finished, call complete_step with evidence from verification, files, diff, or manual inspection.
Do not ask for another approval unless a new consequential decision appears.
When finished, give a concise final answer: what changed, key files, and what was verified. Do not include long logs or a complete work review."""


def compose_plan_input(task: str) -> str:
    task = task.strip()
    if task.startswith(PLAN_MODE_MARKER):
        return task
    return PLAN_MODE_MARKER + "\n\n" + task


def build_approved_plan_message(plan_text: str, todos: list[dict] | None = None) -> str:
    """Build the execution turn sent after the user approves a plan."""
    plan_text = plan_text.strip()
    if todos is None:
        todos = parse_plan_todos(plan_text)
    todos_json = json.dumps({"todos": todos}, ensure_ascii=False) if todos else ""
    parts = [
        PLAN_APPROVED_MESSAGE,
        "Approved plan:\n" + plan_text,
    ]
    if todos_json:
        parts.append("Initial todo_write arguments parsed from the approved plan:\n" + todos_json)
    parts.append(
        "Rules:\n"
        "- Use todo_write before starting execution.\n"
        "- Preserve the approved plan structure where practical.\n"
        "- Keep exactly one todo item in_progress.\n"
        "- Mark items completed as they are finished.\n"
        "- Use complete_step for finished concrete steps and cite actual evidence.\n"
        "- Report only verification that actually happened."
    )
    return "\n\n".join(parts)


def parse_plan_todos(plan_text: str) -> list[dict]:
    """Parse a markdown list plan into todo_write-shaped items."""
    todos: list[dict] = []
    in_heading_phase = False
    for raw in plan_text.splitlines():
        heading = _parse_numbered_heading(raw)
        if heading:
            status = "in_progress" if not todos else "pending"
            todos.append({"content": heading, "status": status, "level": 0})
            in_heading_phase = True
            if len(todos) >= MAX_TODOS:
                break
            continue

        parsed = _parse_list_item(raw)
        if parsed is None:
            continue
        content, level, is_ordered = parsed
        if in_heading_phase and not is_ordered:
            level = 1
        if is_ordered:
            in_heading_phase = False
        status = "in_progress" if not todos else "pending"
        todos.append({"content": content, "status": status, "level": level})
        if len(todos) >= MAX_TODOS:
            break
    return _normalize_levels(todos)


def plan_todo_arguments(plan_text: str) -> Optional[dict]:
    todos = parse_plan_todos(plan_text)
    if not todos:
        return None
    return {"todos": todos}


def plan_todo_event_data(plan_text: str) -> Optional[dict]:
    arguments = plan_todo_arguments(plan_text)
    if not arguments:
        return None
    return todo_event_data(arguments)


def plan_todos_json(plan_text: str) -> str:
    arguments = plan_todo_arguments(plan_text)
    return json.dumps(arguments, ensure_ascii=False) if arguments else ""


_LIST_RE = re.compile(r"^(?P<indent>[ \t]*)(?:[-*+]\s+|\d+[\.)]\s+)(?P<body>.+?)\s*$")
_ORDERED_LIST_RE = re.compile(r"^[ \t]*\d+[\.)]\s+")
_NUMBERED_HEADING_RE = re.compile(r"^#{2,6}\s+\d+[\.)]?\s+(?P<body>.+?)\s*$")


def _parse_numbered_heading(line: str) -> str:
    match = _NUMBERED_HEADING_RE.match(line.strip())
    if not match:
        return ""
    return _clean_item_text(match.group("body"))


def _parse_list_item(line: str) -> Optional[tuple[str, int, bool]]:
    match = _LIST_RE.match(line)
    if not match:
        return None
    indent_text = match.group("indent")
    body = _clean_item_text(match.group("body"))
    if not body:
        return None
    level = 1 if _indent_width(indent_text) > 0 else 0
    return body, level, bool(_ORDERED_LIST_RE.match(line))


def _indent_width(text: str) -> int:
    width = 0
    for char in text:
        width += 4 if char == "\t" else 1
    return width


def _clean_item_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\[[ xX]\]\s+", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return " ".join(text.split())


def _normalize_levels(todos: list[dict]) -> list[dict]:
    """Ensure parser output is legal for todo_write."""
    normalized: list[dict] = []
    seen_phase = False
    for todo in todos:
        item = dict(todo)
        if item.get("level") == 1 and not seen_phase:
            item["level"] = 0
        if item.get("level", 0) == 0:
            seen_phase = True
        normalized.append(item)
    return normalized
