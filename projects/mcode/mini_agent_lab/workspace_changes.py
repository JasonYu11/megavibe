from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mini_agent_lab.change import unified_diff


IGNORED_DIRS = {
    ".archives",
    ".checkpoints",
    ".git",
    ".gitstate",
    ".jobs",
    ".memory",
    ".mcode-ui",
    ".mypy_cache",
    ".pytest_cache",
    ".runs",
    ".sessions",
    ".subagents",
    ".swift-module-cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
MAX_FILE_BYTES = 512_000
MAX_DIFF_CHARS = 20_000


@dataclass(frozen=True)
class FileSnapshot:
    sha256: str
    size: int
    text: Optional[str]


WorkspaceSnapshot = dict[str, FileSnapshot]


def snapshot_workspace(root: str | Path = ".") -> WorkspaceSnapshot:
    base = Path(root).resolve()
    snapshot: WorkspaceSnapshot = {}
    if not base.exists():
        return snapshot
    for path in sorted(base.rglob("*")):
        if _ignored(path, base) or not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        rel = path.relative_to(base).as_posix()
        text = _decode_text(data) if len(data) <= MAX_FILE_BYTES else None
        snapshot[rel] = FileSnapshot(sha256=hashlib.sha256(data).hexdigest(), size=len(data), text=text)
    return snapshot


def diff_workspace(before: WorkspaceSnapshot, after: WorkspaceSnapshot) -> list[dict]:
    changes: list[dict] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old and new and old.sha256 == new.sha256:
            continue
        kind = "create" if old is None else "delete" if new is None else "modify"
        before_text = old.text if old else None
        after_text = "" if new is None else new.text
        diff = ""
        if after_text is not None and (before_text is not None or old is None):
            diff = unified_diff(path, before_text, after_text)
            if len(diff) > MAX_DIFF_CHARS:
                diff = diff[:MAX_DIFF_CHARS] + f"\n...[diff truncated at {MAX_DIFF_CHARS} chars]...\n"
        additions, deletions = _diff_stats(diff)
        changes.append(
            {
                "path": path,
                "kind": kind,
                "additions": additions,
                "deletions": deletions,
                "diff": diff,
                "recoverable": False,
                "source": "command",
                "note": "由命令产生，当前只能检测变更；撤销需要使用 checkpoint 或手动处理。",
            }
        )
    return changes


def _ignored(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in IGNORED_DIRS for part in rel.parts)


def _decode_text(data: bytes) -> Optional[str]:
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _count_lines(text: Optional[str]) -> int:
    if text is None or text == "":
        return 0
    return len(text.splitlines())


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
