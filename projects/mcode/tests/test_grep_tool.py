"""Tests for grep/glob path handling."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.tool import default_registry


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def test_grep_accepts_workspace_absolute_file_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "lfm_matched_filter.py"
        target.write_text("# 中文注释\nprint('ok')\n", encoding="utf-8")
        registry = default_registry(job_log_dir=root / "jobs")
        old_cwd = Path.cwd()
        try:
            os.chdir(root)
            result = registry.get("grep").execute({"pattern": "[\\u4e00-\\u9fff]", "path_glob": str(target)})
        finally:
            os.chdir(old_cwd)
        _assert("lfm_matched_filter.py" in result, "grep accepts absolute path inside workspace")
        _assert("中文注释" in result, "grep returns matching line from absolute file path")


def test_grep_rejects_absolute_path_outside_workspace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        registry = default_registry(job_log_dir=root / "jobs")
        old_cwd = Path.cwd()
        try:
            os.chdir(root)
            registry.get("grep").execute({"pattern": "x", "path_glob": "/tmp/outside.py"})
            raise AssertionError("absolute path outside workspace should fail")
        except ValueError:
            print("  OK: grep rejects absolute path outside workspace")
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    test_grep_accepts_workspace_absolute_file_path()
    test_grep_rejects_absolute_path_outside_workspace()
    print("All grep tool tests passed.")
