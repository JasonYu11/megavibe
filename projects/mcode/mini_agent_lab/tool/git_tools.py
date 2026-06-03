from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from mini_agent_lab.events import Event, EventSink, NullSink
from mini_agent_lab.git_state import (
    GitState,
    classify_changes,
    is_agent_internal_path,
    load_snapshot,
    save_snapshot,
)
from mini_agent_lab.tool.base import JsonObject, Tool


class GitStatusTool(Tool):
    def __init__(self, git: Optional[GitState] = None) -> None:
        self.git = git or GitState()

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return "Read git branch, head, and porcelain status for the current workspace."

    @property
    def schema(self) -> JsonObject:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        snapshot = self.git.snapshot()
        return json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2)


class GitDiffTool(Tool):
    def __init__(self, git: Optional[GitState] = None) -> None:
        self.git = git or GitState()

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def description(self) -> str:
        return "Read git diff. Use staged=true for staged diff, or path for one file."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "staged": {"type": "boolean", "description": "Show staged diff instead of unstaged diff"},
                "path": {"type": "string", "description": "Optional file path to limit the diff"},
            },
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        return self.git.diff(
            staged=bool(arguments.get("staged", False)),
            path=arguments.get("path"),
        )


class GitBaselineTool(Tool):
    def __init__(
        self,
        git: Optional[GitState] = None,
        baseline_path: str | Path = ".gitstate/baseline.json",
    ) -> None:
        self.git = git or GitState()
        self.baseline_path = Path(baseline_path)

    @property
    def name(self) -> str:
        return "git_baseline"

    @property
    def description(self) -> str:
        return "Capture or show the git baseline snapshot used to compare agent changes."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["capture", "show"],
                    "description": "capture a new baseline or show the saved one",
                }
            },
            "required": ["action"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        action = arguments.get("action")
        if action == "capture":
            snapshot = self.git.snapshot()
            save_snapshot(snapshot, self.baseline_path)
            return json.dumps(
                {
                    "baseline_path": str(self.baseline_path),
                    "snapshot": snapshot.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        if action == "show":
            if not self.baseline_path.exists():
                return f"(no git baseline at {self.baseline_path})"
            return json.dumps(
                {
                    "baseline_path": str(self.baseline_path),
                    "snapshot": load_snapshot(self.baseline_path).to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        raise ValueError("action must be capture or show")


class GitClassifyChangesTool(Tool):
    def __init__(
        self,
        git: Optional[GitState] = None,
        baseline_path: str | Path = ".gitstate/baseline.json",
    ) -> None:
        self.git = git or GitState()
        self.baseline_path = Path(baseline_path)

    @property
    def name(self) -> str:
        return "git_classify_changes"

    @property
    def description(self) -> str:
        return "Compare saved git baseline to current status and classify user-existing, agent-created, agent-modified, and overlap files."

    @property
    def schema(self) -> JsonObject:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        if not self.baseline_path.exists():
            raise ValueError(f"no git baseline at {self.baseline_path}; capture one first")
        baseline = load_snapshot(self.baseline_path)
        current = self.git.snapshot()
        classification = classify_changes(baseline, current)
        return json.dumps(classification.to_dict(), ensure_ascii=False, indent=2)


class GitCommitTool(Tool):
    def __init__(
        self,
        git: Optional[GitState] = None,
        baseline_path: str | Path = ".gitstate/baseline.json",
        sink: Optional[EventSink] = None,
    ) -> None:
        self.git = git or GitState()
        self.baseline_path = Path(baseline_path)
        self.sink = sink or NullSink()

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return (
            "Create a local git commit from an explicit file list only. "
            "Never uses git add . and refuses Mcode internal files."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit files to include in the commit. Do not pass '.' or directories.",
                },
                "message": {
                    "type": "string",
                    "description": "Non-empty commit message.",
                },
            },
            "required": ["files", "message"],
        }

    def execute(self, arguments: JsonObject) -> str:
        message = str(arguments.get("message", "")).strip()
        if not message:
            raise ValueError("message is required")
        raw_files = arguments.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("files must be a non-empty array")

        snapshot = self.git.snapshot()
        if not snapshot.is_repo or not snapshot.root:
            raise ValueError(snapshot.error or "current directory is not a git repository")
        root = Path(snapshot.root).resolve(strict=False)
        files = _normalize_commit_files(raw_files, root)
        changed = {entry.path for entry in snapshot.porcelain}
        unchanged = [path for path in files if path not in changed]
        if unchanged:
            raise ValueError(f"cannot commit unchanged or unknown files: {', '.join(unchanged)}")

        risk = _commit_risk(files, self.baseline_path, snapshot)
        self.sink.emit(
            Event(
                "git_commit_started",
                {
                    "files": files,
                    "message": message,
                    "risk": risk,
                },
            )
        )
        add = self.git.run(["add", "--", *files])
        if add.returncode != 0:
            self.sink.emit(Event("git_commit_failed", {"files": files, "error": _git_error(add)}))
            raise RuntimeError(_git_error(add))

        commit = self.git.run(["commit", "--only", "-m", message, "--", *files])
        if commit.returncode != 0:
            self.sink.emit(Event("git_commit_failed", {"files": files, "error": _git_error(commit)}))
            raise RuntimeError(_git_error(commit))

        after = self.git.snapshot()
        data = {
            "files": files,
            "message": message,
            "output": (commit.stdout or commit.stderr).strip(),
            "head": after.head,
            "branch": after.branch,
            "risk": risk,
        }
        self.sink.emit(Event("git_commit_done", data))
        return json.dumps(data, ensure_ascii=False, indent=2)


def _normalize_commit_files(raw_files: list, root: Path) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("files must contain non-empty strings")
        raw_path = raw.strip()
        if raw_path in {".", "./"}:
            raise ValueError("refusing to commit '.'; pass explicit files")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = root / path
        resolved = path.resolve(strict=False)
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"file is outside git repo: {raw_path}") from exc
        if rel == "." or rel.endswith("/"):
            raise ValueError(f"refusing directory-like commit target: {raw_path}")
        if is_agent_internal_path(rel):
            raise ValueError(f"refusing to commit Mcode internal file: {rel}")
        if rel not in seen:
            out.append(rel)
            seen.add(rel)
    return out


def _commit_risk(files: list[str], baseline_path: Path, current_snapshot) -> dict:
    if not baseline_path.exists():
        return {"baseline_available": False, "user_existing": [], "overlap": [], "agent_files": files}
    try:
        baseline = load_snapshot(baseline_path)
        if not baseline.is_repo:
            return {"baseline_available": False, "user_existing": [], "overlap": [], "agent_files": files}
        classified = classify_changes(baseline, current_snapshot)
    except Exception as exc:
        return {"baseline_available": False, "error": str(exc), "user_existing": [], "overlap": [], "agent_files": files}
    user_existing = [path for path in files if path in classified.user_existing]
    overlap = [path for path in files if path in classified.overlap]
    agent_files = [
        path
        for path in files
        if path in set(classified.agent_created) | set(classified.agent_modified)
    ]
    unknown = [path for path in files if path not in set(user_existing) | set(overlap) | set(agent_files)]
    return {
        "baseline_available": True,
        "user_existing": user_existing,
        "overlap": overlap,
        "agent_files": agent_files,
        "unknown": unknown,
    }


def _git_error(result) -> str:
    return (result.stderr or result.stdout or f"git exited with {result.returncode}").strip()
