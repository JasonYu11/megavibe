from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def load_events(path: str | Path) -> list[dict[str, Any]]:
    event_path = Path(path)
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(event_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{event_path}:{line_no}: invalid json: {exc}") from exc
        if isinstance(event, dict):
            events.append(event)
    return events


def load_summary(path: str | Path) -> dict[str, Any]:
    summary = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError(f"{path} is not a summary object")
    return summary


def find_latest_run_file(directory: str | Path = ".runs", suffix: str = ".events.jsonl") -> Path:
    root = Path(directory)
    matches = sorted(root.glob(f"*{suffix}"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"no *{suffix} files under {root}")
    return matches[0]


def render_timeline(path: str | Path) -> str:
    lines = [format_event(event) for event in load_events(path)]
    return "\n".join(line for line in lines if line)


def format_event(event: dict[str, Any]) -> str:
    seq = event.get("seq", "?")
    time_text = event.get("time_text", "")
    kind = str(event.get("kind", "unknown"))
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    prefix = f"{seq:>4} {time_text} [{kind}]"

    if kind == "turn_started":
        return f"{prefix} input={_quote(data.get('input', ''))}"
    if kind == "assistant_message":
        calls = data.get("tool_calls") or []
        if calls:
            names = ", ".join(str(call.get("name", "")) for call in calls if isinstance(call, dict))
            return f"{prefix} tool_calls={names}"
        return f"{prefix} content={_quote(data.get('content', ''))}"
    if kind == "tool_dispatch":
        name = data.get("name", "")
        subject = _subject_from_args(data.get("arguments", {}))
        return f"{prefix} {name}{(' ' + subject) if subject else ''}"
    if kind == "tool_result":
        name = data.get("name", "")
        status = "ok" if data.get("ok", _legacy_ok(data)) else "error"
        extras = []
        if data.get("error_kind"):
            extras.append(f"kind={data.get('error_kind')}")
        if data.get("blocked"):
            extras.append("blocked")
        if data.get("truncated"):
            extras.append("truncated")
        if data.get("error"):
            extras.append(f"error={_quote(data.get('error'))}")
        suffix = f" ({', '.join(extras)})" if extras else ""
        return f"{prefix} {name} {status}{suffix}"
    if kind == "preview":
        return f"{prefix} {data.get('kind', 'change')} {data.get('path', '')}"
    if kind == "checkpoint_saved":
        return f"{prefix} id={data.get('id')} path={data.get('path')}"
    if kind == "todo_updated":
        return f"{prefix} {data.get('progress_text') or _todo_progress(data)}"
    if kind == "git_baseline_captured":
        if data.get("is_repo"):
            return (
                f"{prefix} branch={data.get('branch')} head={data.get('head')} "
                f"dirty={data.get('dirty_count')}"
            )
        return f"{prefix} no_repo error={_quote(data.get('error', ''))}"
    if kind == "git_changes_classified":
        return (
            f"{prefix} dirty={data.get('current_dirty')} "
            f"created={_list(data.get('agent_created'))} "
            f"modified={_list(data.get('agent_modified'))} "
            f"overlap={_list(data.get('overlap'))}"
        )
    if kind == "git_overlap_risk":
        return f"{prefix} path={data.get('path')} baseline={data.get('status_at_baseline')}"
    if kind in {"git_baseline_failed", "git_classify_failed", "git_commit_failed"}:
        return f"{prefix} error={_quote(data.get('error', ''))}"
    if kind == "git_commit_started":
        return f"{prefix} files={_list(data.get('files'))} message={_quote(data.get('message', ''))}"
    if kind == "git_commit_done":
        return f"{prefix} head={data.get('head')} files={_list(data.get('files'))}"
    if kind == "command_started":
        return f"{prefix} pid={data.get('pid')} command={_quote(data.get('command', ''))}"
    if kind == "command_output":
        return f"{prefix} {_quote(data.get('text', ''))}"
    if kind == "command_finished":
        return (
            f"{prefix} exit={data.get('exit_code')} timed_out={data.get('timed_out')} "
            f"duration_ms={data.get('duration_ms')}"
        )
    if kind == "job_started":
        return f"{prefix} id={data.get('job_id')} pid={data.get('pid')} log={data.get('log_path')}"
    if kind == "job_output":
        return f"{prefix} id={data.get('job_id')} {_quote(data.get('text', ''))}"
    if kind == "job_finished":
        return (
            f"{prefix} id={data.get('job_id')} status={data.get('status')} "
            f"exit={data.get('exit_code')}"
        )
    if kind == "safety_ask":
        return f"{prefix} tool={data.get('tool_name')} reason={_quote(data.get('reason', ''))}"
    if kind == "safety_deny":
        return f"{prefix} tool={data.get('tool_name')} reason={_quote(data.get('reason', ''))}"
    if kind == "plan_blocked":
        return f"{prefix} tool={data.get('tool_name')}"
    if kind.startswith("compact_"):
        return f"{prefix} {_compact_kv(data)}"
    if kind in {"turn_completed", "turn_paused"}:
        return f"{prefix} {_quote(data.get('answer') or data.get('message') or '')}"
    if kind == "notice":
        return f"{prefix} {_quote(data.get('message', ''))}"
    return f"{prefix} {_compact_kv(data)}"


def render_summary(path: str | Path) -> str:
    summary = load_summary(path)
    lines = [
        f"Run: {summary.get('run_id', '')}",
        f"Session: {summary.get('session_id', '')}",
        f"Status: {summary.get('status', '')}",
        f"Updated: {summary.get('updated_at_text', '')}",
    ]
    _append(lines, "Input", summary.get("current_input"))
    _append(lines, "Current tool", _format_current_tool(summary.get("current_tool")))
    _append(lines, "Current command", _format_command(summary.get("current_command")))
    _append(lines, "Last tool", _format_last_tool(summary.get("last_tool_result")))
    _append(lines, "Todo", _format_todo(summary.get("todo")))
    _append(lines, "Git", _format_git(summary.get("git")))
    _append(lines, "Jobs", _format_jobs(summary.get("jobs")))
    _append(lines, "Last notice", summary.get("last_notice"))
    _append(lines, "Last error", summary.get("last_error"))
    _append(lines, "Final", summary.get("final_answer"))
    return "\n".join(lines)


def _append(lines: list[str], label: str, value: Any) -> None:
    if value is None or value == "" or value == {} or value == []:
        return
    lines.append(f"{label}: {value}")


def _format_current_tool(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    name = value.get("name", "")
    subject = _subject_from_args(value.get("arguments", {}))
    return f"{name}{(' ' + subject) if subject else ''}"


def _format_last_tool(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    status = "ok" if value.get("ok", _legacy_ok(value)) else "error"
    parts = [str(value.get("name", "")), status]
    if value.get("error_kind"):
        parts.append(f"kind={value.get('error_kind')}")
    if value.get("blocked"):
        parts.append("blocked")
    if value.get("truncated"):
        parts.append("truncated")
    if value.get("error"):
        parts.append(f"error={_quote(value.get('error'))}")
    return " ".join(part for part in parts if part)


def _format_todo(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    progress = value.get("progress_text") or _todo_progress(value)
    current = value.get("current")
    return f"{progress}{'; current=' + _quote(current) if current else ''}"


def _format_git(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts = []
    if value.get("is_repo") is False:
        parts.append("not a git repo")
    if value.get("branch") or value.get("head"):
        parts.append(f"{value.get('branch')}@{value.get('head')}")
    for key in ("agent_created", "agent_modified", "overlap", "resolved_baseline_dirty"):
        if value.get(key):
            parts.append(f"{key}={_list(value.get(key))}")
    if value.get("overlap_risks"):
        risks = value.get("overlap_risks") or []
        parts.append(f"overlap_risks={len(risks)}")
    commit = value.get("commit")
    if isinstance(commit, dict):
        parts.append(f"commit={commit.get('status')} files={_list(commit.get('files'))}")
    if value.get("error"):
        parts.append(f"error={_quote(value.get('error'))}")
    return "; ".join(parts)


def _format_command(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return f"pid={value.get('pid')} command={_quote(value.get('command', ''))}"


def _format_jobs(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    counts: dict[str, int] = {}
    for item in value.values():
        if isinstance(item, dict):
            status = str(item.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
    return ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))


def _subject_from_args(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    for key in ("path", "command", "pattern", "url", "message", "label"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return _quote(value, max_chars=120)
    return ""


def _legacy_ok(data: dict[str, Any]) -> bool:
    result = str(data.get("result", data.get("output", "")))
    return not result.startswith(("error:", "blocked:"))


def _todo_progress(data: dict[str, Any]) -> str:
    completed = data.get("completed", 0)
    total = data.get("total", 0)
    return f"{completed}/{total} done"


def _compact_kv(data: dict[str, Any]) -> str:
    parts = []
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            parts.append(f"{key}={_list(value) if isinstance(value, list) else '{...}'}")
        else:
            parts.append(f"{key}={_quote(value)}")
    return " ".join(parts)


def _list(value: Any) -> str:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return "[]"
    items = [str(item) for item in value]
    if len(items) > 6:
        return "[" + ", ".join(items[:6]) + f", ... +{len(items) - 6}" + "]"
    return "[" + ", ".join(items) + "]"


def _quote(value: Any, max_chars: int = 180) -> str:
    text = str(value).replace("\n", "\\n")
    if len(text) > max_chars:
        keep = max_chars - 15
        text = text[:keep] + "...[truncated]"
    return text
