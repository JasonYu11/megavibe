from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from event_reader import read_events
from project_store import Project, project_root

from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.checkpoint import CheckpointStore
from mini_agent_lab.events import Event
from mini_agent_lab.run_recorder import RunRecorder


def confirm_latest_changes(project: Project, session_id: str) -> dict[str, Any]:
    root = project_root(project)
    review = latest_change_review(project, session_id)
    if review["status"] != "pending":
        return review
    _emit_review_event(root, session_id, "change_review_confirmed", review)
    return {**review, "status": "confirmed"}


def undo_latest_changes(project: Project, session_id: str) -> dict[str, Any]:
    root = project_root(project)
    review = latest_change_review(project, session_id)
    if review["status"] != "pending":
        return review
    checkpoint_ids = [item["checkpoint_id"] for item in review["changes"] if item.get("checkpoint_id")]
    if not checkpoint_ids:
        raise ValueError("no checkpoints available for latest turn")

    checkpoints = CheckpointStore(root / _checkpoint_dir(root))
    restored: list[dict[str, str]] = []
    for checkpoint_id in reversed(checkpoint_ids):
        checkpoint = checkpoints.restore(str(checkpoint_id))
        restored.append({"id": checkpoint.id, "path": checkpoint.path})

    payload = {**review, "restored": restored}
    _emit_review_event(root, session_id, "change_review_reverted", payload)
    return {**payload, "status": "reverted"}


def undo_latest_change_file(project: Project, session_id: str, file_path: str) -> dict[str, Any]:
    root = project_root(project)
    review = latest_change_review(project, session_id)
    if review["status"] != "pending":
        return review
    target = str(file_path)
    change = next(
        (
            item
            for item in reversed(review["changes"])
            if item.get("path") == target and item.get("checkpoint_id") and item.get("status") != "reverted"
        ),
        None,
    )
    if not change:
        raise ValueError(f"no restorable checkpoint for file: {target}")

    checkpoints = CheckpointStore(root / _checkpoint_dir(root))
    checkpoint = checkpoints.restore(str(change["checkpoint_id"]))
    payload = {
        "session_id": session_id,
        "path": target,
        "checkpoint_id": checkpoint.id,
        "restored": [{"id": checkpoint.id, "path": checkpoint.path}],
    }
    _emit_review_event(root, session_id, "change_review_file_reverted", payload)
    return {**payload, "status": "file_reverted"}


def latest_change_review(project: Project, session_id: str) -> dict[str, Any]:
    events = read_events(project, session_id, limit=2000)
    turn_start = 0
    for index, event in enumerate(events):
        if event.get("kind") == "turn_started":
            turn_start = index
    turn_events = events[turn_start:]

    changes: list[dict[str, Any]] = []
    status = "pending"
    for event in turn_events:
        data = event.get("data") or {}
        kind = event.get("kind")
        if kind == "preview":
            additions, deletions = _diff_stats(str(data.get("diff") or ""))
            changes.append(
                {
                    "path": str(data.get("path") or ""),
                    "kind": str(data.get("kind") or "modify"),
                    "additions": additions,
                    "deletions": deletions,
                    "diff": str(data.get("diff") or ""),
                    "checkpoint_id": "",
                    "recoverable": True,
                    "source": str(data.get("source") or data.get("tool_name") or "tool"),
                }
            )
        elif kind == "workspace_changes_detected":
            for item in data.get("changes", []):
                if not isinstance(item, dict):
                    continue
                changes.append(
                    {
                        "path": str(item.get("path") or ""),
                        "kind": str(item.get("kind") or "modify"),
                        "additions": int(item.get("additions") or 0),
                        "deletions": int(item.get("deletions") or 0),
                        "diff": str(item.get("diff") or ""),
                        "checkpoint_id": "",
                        "recoverable": bool(item.get("recoverable", False)),
                        "source": str(item.get("source") or data.get("source_kind") or "command"),
                        "note": str(item.get("note") or ""),
                    }
                )
        elif kind == "checkpoint_saved":
            path = str(data.get("path") or "")
            for change in reversed(changes):
                if not change.get("checkpoint_id") and (not path or change.get("path") == path):
                    change["checkpoint_id"] = str(data.get("id") or "")
                    break
        elif kind == "change_review_file_reverted":
            path = str(data.get("path") or "")
            checkpoint_id = str(data.get("checkpoint_id") or "")
            for change in reversed(changes):
                if change.get("path") == path and (
                    not checkpoint_id or change.get("checkpoint_id") == checkpoint_id
                ):
                    change["status"] = "reverted"
                    break
        elif kind == "change_review_confirmed":
            status = "confirmed"
        elif kind == "change_review_reverted":
            status = "reverted"

    return {
        "session_id": session_id,
        "status": status,
        "changes": changes,
        "files": len({item["path"] for item in changes if item.get("path")}),
        "additions": sum(int(item.get("additions") or 0) for item in changes),
        "deletions": sum(int(item.get("deletions") or 0) for item in changes),
    }


def _emit_review_event(root: Path, session_id: str, kind: str, data: dict[str, Any]) -> None:
    app_cfg = load_app_config(root / "mcode-config.json")
    sink = RunRecorder(directory=root / app_cfg.paths.run_dir, run_id=session_id, session_id=session_id)
    sink.emit(Event(kind, data))


def _checkpoint_dir(root: Path) -> str:
    return load_app_config(root / "mcode-config.json").paths.checkpoint_dir


def _diff_stats(diff: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions
