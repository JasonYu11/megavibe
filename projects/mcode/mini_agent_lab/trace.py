from __future__ import annotations

import time
from typing import Any

from mini_agent_lab.events import Event, EventSink


class TraceEmitter:
    """Product-level trace events layered on top of the raw agent event log."""

    def __init__(self, sink: EventSink, thought_summary_enabled: bool = True) -> None:
        self.sink = sink
        self.thought_summary_enabled = thought_summary_enabled

    def turn_status(self, status: str, phase: str, message: str = "") -> None:
        self._emit("turn_status", {"status": status, "phase": phase, "message": message})

    def thought_started(self, text: str = "") -> None:
        if not self.thought_summary_enabled:
            return
        self._emit("thought_summary_started", {"text": text})

    def thought_delta(self, text: str) -> None:
        if self.thought_summary_enabled and text:
            self._emit("thought_summary_delta", {"text": text})

    def thought_completed(self, text: str = "") -> None:
        if not self.thought_summary_enabled:
            return
        self._emit("thought_summary_completed", {"text": text})

    def step_started(self, step_id: str, title: str, source: str = "agent", **data: Any) -> None:
        self._emit("step_started", {"step_id": step_id, "title": title, "source": source, **data})

    def step_progress(self, step_id: str, message: str, **data: Any) -> None:
        self._emit("step_progress", {"step_id": step_id, "message": message, **data})

    def step_completed(self, step_id: str, summary: str = "", **data: Any) -> None:
        self._emit("step_completed", {"step_id": step_id, "summary": summary, **data})

    def step_failed(self, step_id: str, error: str, **data: Any) -> None:
        self._emit("step_failed", {"step_id": step_id, "error": error, **data})

    def action_started(
        self,
        action_id: str,
        step_id: str,
        kind: str,
        title: str,
        summary: str = "",
        **data: Any,
    ) -> None:
        self._emit(
            "action_started",
            {
                "action_id": action_id,
                "step_id": step_id,
                "kind": kind,
                "title": title,
                "summary": summary,
                "started_at": time.time(),
                **data,
            },
        )

    def action_completed(self, action_id: str, summary: str = "", **data: Any) -> None:
        self._emit("action_completed", {"action_id": action_id, "summary": summary, "completed_at": time.time(), **data})

    def action_failed(self, action_id: str, error: str, **data: Any) -> None:
        self._emit("action_failed", {"action_id": action_id, "error": error, "completed_at": time.time(), **data})

    def file_read(self, path: str, step_id: str, action_id: str = "", line_range: str = "") -> None:
        self._emit("file_read", {"path": path, "step_id": step_id, "action_id": action_id, "line_range": line_range})

    def file_edited(
        self,
        path: str,
        step_id: str,
        action_id: str = "",
        additions: int = 0,
        deletions: int = 0,
        diff_preview: str = "",
    ) -> None:
        self._emit(
            "file_edited",
            {
                "path": path,
                "step_id": step_id,
                "action_id": action_id,
                "additions": additions,
                "deletions": deletions,
                "diff_preview": diff_preview,
            },
        )

    def assistant_started(self, message_id: str) -> None:
        self._emit("assistant_message_started", {"message_id": message_id})

    def assistant_delta(self, message_id: str, delta: str) -> None:
        if delta:
            self._emit("assistant_delta", {"message_id": message_id, "delta": delta})

    def assistant_completed(self, message_id: str, content: str, tool_calls: list[dict[str, Any]] | None = None) -> None:
        self._emit("assistant_message_completed", {"message_id": message_id, "content": content, "tool_calls": tool_calls or []})

    def assistant_failed(self, message_id: str, error: str) -> None:
        self._emit("assistant_message_failed", {"message_id": message_id, "error": error, "completed_at": time.time()})

    def tool_call_started(
        self,
        message_id: str,
        tool_call_index: int,
        tool_call_id: str = "",
        tool_name: str = "",
        step_id: str = "",
    ) -> None:
        self._emit(
            "tool_call_started",
            {
                "message_id": message_id,
                "tool_call_index": tool_call_index,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "step_id": step_id,
            },
        )

    def tool_call_delta(
        self,
        message_id: str,
        tool_call_index: int,
        delta_chars: int = 0,
        received_chars: int = 0,
        tool_call_id: str = "",
        tool_name: str = "",
        step_id: str = "",
    ) -> None:
        self._emit(
            "tool_call_delta",
            {
                "message_id": message_id,
                "tool_call_index": tool_call_index,
                "delta_chars": delta_chars,
                "received_chars": received_chars,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "step_id": step_id,
            },
        )

    def tool_call_completed(
        self,
        message_id: str,
        tool_call_index: int,
        tool_call_id: str = "",
        tool_name: str = "",
        step_id: str = "",
    ) -> None:
        self._emit(
            "tool_call_completed",
            {
                "message_id": message_id,
                "tool_call_index": tool_call_index,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "step_id": step_id,
                "completed_at": time.time(),
            },
        )

    def verification_completed(
        self,
        command: str,
        status: str,
        exit_code: int | None = None,
        duration_ms: int | None = None,
        summary: str = "",
        step_id: str = "",
        action_id: str = "",
    ) -> None:
        self._emit(
            "verification_completed" if status == "passed" else "verification_failed",
            {
                "command": command,
                "status": status,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "summary": summary,
                "step_id": step_id,
                "action_id": action_id,
            },
        )

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        self.sink.emit(Event(kind, data))


def trace_action_kind(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name in {"read_file", "list_dir", "glob", "grep", "git_status", "git_diff"}:
        return "file_read"
    if tool_name in {"edit_file", "write_file"}:
        return "file_edit"
    if tool_name in {"bash", "python_run", "bash_output", "wait", "kill_shell"}:
        command = str(arguments.get("command") or arguments.get("path") or "")
        return "verification" if _looks_like_verification(command) else "command"
    if tool_name in {"todo_write", "complete_step"}:
        return "todo"
    if tool_name in {"task", "run_skill"}:
        return "subagent"
    return "tool"


def trace_action_title(tool_name: str, arguments: dict[str, Any]) -> str:
    path = str(arguments.get("path") or arguments.get("pattern") or "").strip()
    if tool_name == "read_file" and path:
        return f"读取 {path}"
    if tool_name == "list_dir":
        return f"列出 {path or '.'}"
    if tool_name == "grep":
        return f"搜索 {path or arguments.get('query') or arguments.get('pattern') or 'workspace'}"
    if tool_name == "edit_file" and path:
        return f"编辑 {path}"
    if tool_name == "write_file" and path:
        return f"写入 {path}"
    if tool_name in {"bash", "python_run"}:
        command = str(arguments.get("command") or arguments.get("path") or tool_name)
        return f"运行 {command[:80]}"
    if tool_name == "todo_write":
        return "更新任务列表"
    return tool_name


def diff_stats(diff: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _looks_like_verification(command: str) -> bool:
    lowered = command.lower()
    return any(token in lowered for token in ("test", "pytest", "vitest", "npm run build", "tsc", "mypy", "ruff"))
