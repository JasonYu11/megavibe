from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Change:
    path: str
    before: Optional[str]
    after: str
    kind: str
    diff: str


class PreviewableTool:
    def preview(self, arguments: dict) -> Change:
        raise NotImplementedError


def make_change(path: str, before: Optional[str], after: str) -> Change:
    kind = "create" if before is None else "modify"
    diff = unified_diff(path, before, after)
    return Change(path=path, before=before, after=after, kind=kind, diff=diff)


def unified_diff(path: str, before: Optional[str], after: str) -> str:
    before_lines = [] if before is None else before.splitlines()
    after_lines = after.splitlines()

    fromfile = "/dev/null" if before is None else f"a/{path}"
    tofile = f"b/{path}"
    diff_lines = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    if not diff_lines:
        return "(no diff)"
    return "\n".join(diff_lines) + "\n"


def read_existing(path: str) -> Optional[str]:
    file_path = Path(path)
    if not file_path.exists():
        return None
    if file_path.is_dir():
        raise ValueError(f"{path} is a directory")
    return file_path.read_text(encoding="utf-8")
