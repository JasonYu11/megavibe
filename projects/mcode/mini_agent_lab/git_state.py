from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional


GitRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]

AGENT_INTERNAL_PREFIXES = (
    ".archives/",
    ".checkpoints/",
    ".gitstate/",
    ".jobs/",
    ".memory/",
    ".runs/",
    ".sessions/",
)


@dataclass(frozen=True)
class GitStatusEntry:
    path: str
    index: str
    worktree: str
    raw: str

    @property
    def staged(self) -> bool:
        return self.index not in {" ", "?"}

    @property
    def unstaged(self) -> bool:
        return self.worktree not in {" ", "?"}

    @property
    def untracked(self) -> bool:
        return self.index == "?" and self.worktree == "?"


@dataclass(frozen=True)
class GitSnapshot:
    is_repo: bool
    root: Optional[str]
    branch: Optional[str]
    head: Optional[str]
    porcelain: list[GitStatusEntry]
    captured_at: float
    error: str = ""

    @property
    def dirty_count(self) -> int:
        return len(self.porcelain)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["porcelain"] = [asdict(entry) for entry in self.porcelain]
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> "GitSnapshot":
        return cls(
            is_repo=bool(raw.get("is_repo")),
            root=raw.get("root"),
            branch=raw.get("branch"),
            head=raw.get("head"),
            porcelain=[GitStatusEntry(**entry) for entry in raw.get("porcelain", [])],
            captured_at=float(raw.get("captured_at", 0)),
            error=str(raw.get("error", "")),
        )


@dataclass(frozen=True)
class GitChangeClassification:
    baseline: GitSnapshot
    current: GitSnapshot
    user_existing: list[str]
    agent_created: list[str]
    agent_modified: list[str]
    overlap: list[str]
    resolved_baseline_dirty: list[str]

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "current": self.current.to_dict(),
            "user_existing": self.user_existing,
            "agent_created": self.agent_created,
            "agent_modified": self.agent_modified,
            "overlap": self.overlap,
            "resolved_baseline_dirty": self.resolved_baseline_dirty,
        }


class GitState:
    def __init__(
        self,
        cwd: str | Path = ".",
        runner: Optional[GitRunner] = None,
    ) -> None:
        self.cwd = Path(cwd)
        self.runner = runner or _run_git

    def snapshot(self) -> GitSnapshot:
        root_result = self._run(["rev-parse", "--show-toplevel"])
        if root_result.returncode != 0:
            return GitSnapshot(
                is_repo=False,
                root=None,
                branch=None,
                head=None,
                porcelain=[],
                captured_at=time.time(),
                error=_clean_error(root_result),
            )

        root = root_result.stdout.strip()
        branch = self._run(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or None
        head = self._run(["rev-parse", "--short", "HEAD"]).stdout.strip() or None
        status = self._run(["status", "--porcelain=v1"])
        if status.returncode != 0:
            return GitSnapshot(
                is_repo=True,
                root=root,
                branch=branch,
                head=head,
                porcelain=[],
                captured_at=time.time(),
                error=_clean_error(status),
            )
        return GitSnapshot(
            is_repo=True,
            root=root,
            branch=branch,
            head=head,
            porcelain=parse_porcelain(status.stdout),
            captured_at=time.time(),
        )

    def diff(self, staged: bool = False, path: Optional[str] = None) -> str:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.extend(["--", path])
        result = self._run(args)
        if result.returncode != 0:
            raise RuntimeError(_clean_error(result))
        return result.stdout or "(no diff)"

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return self._run(args)

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return self.runner(args, self.cwd)


def parse_porcelain(text: str) -> list[GitStatusEntry]:
    entries: list[GitStatusEntry] = []
    for raw in text.splitlines():
        if not raw:
            continue
        if raw.startswith("?? "):
            path = raw[3:]
            entries.append(GitStatusEntry(path=path, index="?", worktree="?", raw=raw))
            continue
        if len(raw) < 4:
            continue
        index = raw[0]
        worktree = raw[1]
        path = raw[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append(GitStatusEntry(path=path, index=index, worktree=worktree, raw=raw))
    return entries


def save_snapshot(snapshot: GitSnapshot, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_snapshot(path: str | Path) -> GitSnapshot:
    return GitSnapshot.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def classify_changes(baseline: GitSnapshot, current: GitSnapshot) -> GitChangeClassification:
    baseline_by_path = {entry.path: entry for entry in baseline.porcelain if not _is_agent_internal_path(entry.path)}
    current_by_path = {entry.path: entry for entry in current.porcelain if not _is_agent_internal_path(entry.path)}
    baseline_paths = set(baseline_by_path)
    current_paths = set(current_by_path)

    agent_created = sorted(
        path
        for path in current_paths - baseline_paths
        if current_by_path[path].untracked or current_by_path[path].index == "A"
    )
    agent_modified = sorted((current_paths - baseline_paths) - set(agent_created))
    overlap = sorted(baseline_paths & current_paths)
    resolved = sorted(baseline_paths - current_paths)

    return GitChangeClassification(
        baseline=baseline,
        current=current,
        user_existing=sorted(baseline_paths),
        agent_created=agent_created,
        agent_modified=agent_modified,
        overlap=overlap,
        resolved_baseline_dirty=resolved,
    )


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command, 124, exc.stdout or "", exc.stderr or "git timed out")


def _clean_error(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or result.stdout or "").strip()
    return text or f"git exited with {result.returncode}"


def _is_agent_internal_path(path: str) -> bool:
    normalized = path.strip("/")
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in AGENT_INTERNAL_PREFIXES)


def is_agent_internal_path(path: str) -> bool:
    return _is_agent_internal_path(path)
