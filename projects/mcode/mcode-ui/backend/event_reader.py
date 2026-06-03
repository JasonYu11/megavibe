from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_store import Project, ensure_inside_project, project_root


IGNORED_TREE_NAMES = {
    ".git",
    "__pycache__",
    ".pycache",
    "node_modules",
    "dist",
    "bin",
}


def list_sessions(project: Project) -> list[dict[str, Any]]:
    session_dir = project_root(project) / ".sessions"
    if not session_dir.exists():
        return []
    rows = []
    for path in sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        messages = read_jsonl(path)
        rows.append(
            {
                "id": path.stem,
                "path": str(path),
                "messages": len(messages),
                "updated_at": path.stat().st_mtime,
                "preview": _session_preview(messages),
            }
        )
    return rows


def read_session(project: Project, session_id: str) -> dict[str, Any]:
    path = project_root(project) / ".sessions" / f"{session_id}.jsonl"
    if not path.exists():
        return {"id": session_id, "path": str(path), "messages": [], "missing": True}
    messages = read_jsonl(path)
    return {"id": session_id, "path": str(path), "messages": messages}


def read_summary(project: Project, session_id: str) -> dict[str, Any]:
    path = project_root(project) / ".runs" / f"{session_id}.summary.json"
    if not path.exists():
        return {"run_id": session_id, "status": "missing", "path": str(path)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"run_id": session_id, "status": "invalid", "path": str(path), "error": str(exc)}


def read_events(project: Project, session_id: str, limit: int = 400) -> list[dict[str, Any]]:
    path = project_root(project) / ".runs" / f"{session_id}.events.jsonl"
    return read_jsonl(path, limit=limit)


def read_subagents(project: Project, session_id: str, event_limit: int = 20) -> list[dict[str, Any]]:
    base = project_root(project) / ".subagents" / session_id
    if not base.exists():
        return []
    rows = []
    for state_path in sorted(base.glob("*/state.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {"subagent_id": state_path.parent.name, "status": "invalid"}
        events_path = Path(str(state.get("events_path") or state_path.parent / "events.jsonl"))
        state["events"] = read_jsonl(events_path, limit=event_limit)
        rows.append(state)
    return rows


def read_jobs(project: Project) -> list[dict[str, Any]]:
    job_dir = project_root(project) / ".jobs"
    if not job_dir.exists():
        return []
    rows = []
    for path in sorted(job_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        text = _tail_text(path)
        rows.append(
            {
                "job_id": path.stem,
                "kind": path.stem.split("-", 1)[0],
                "path": str(path),
                "updated_at": path.stat().st_mtime,
                "tail": text,
            }
        )
    return rows


def file_tree(project: Project, rel_path: str = "", depth: int = 2) -> dict[str, Any]:
    path = ensure_inside_project(project, rel_path)
    root = project_root(project)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_dir():
        raise ValueError(f"not a directory: {rel_path}")
    return _tree_node(path, root, max(0, depth))


def read_file(project: Project, rel_path: str, max_chars: int = 120000) -> dict[str, Any]:
    path = ensure_inside_project(project, rel_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_file():
        raise ValueError(f"not a file: {rel_path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    return {
        "path": str(path),
        "rel_path": str(path.relative_to(project_root(project))),
        "content": text[:max_chars],
        "truncated": truncated,
        "size": path.stat().st_size,
    }


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit is not None and limit > 0:
        lines = lines[-limit:]
    rows = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"kind": "invalid_jsonl", "raw": line})
    return rows


def _tree_node(path: Path, root: Path, depth: int) -> dict[str, Any]:
    children = []
    if depth > 0:
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name in IGNORED_TREE_NAMES:
                continue
            if child.name.startswith(".") and child.name not in {".sessions", ".runs", ".subagents", ".jobs"}:
                continue
            node = {
                "name": child.name,
                "path": str(child.relative_to(root)),
                "is_dir": child.is_dir(),
                "children": [],
            }
            if child.is_dir():
                node = _tree_node(child, root, depth - 1)
            children.append(node)
    return {"name": path.name, "path": str(path.relative_to(root)) if path != root else "", "is_dir": True, "children": children}


def _session_preview(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user" and message.get("content"):
            text = str(message["content"]).strip().replace("\n", " ")
            return text[:120]
    return "(empty session)"


def _tail_text(path: Path, max_chars: int = 12000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
