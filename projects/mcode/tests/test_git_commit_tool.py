"""Tests for the controlled git_commit tool."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.git_state import GitState, save_snapshot
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.safety import PolicyConfig, SafetyGate
from mini_agent_lab.tool import default_registry
from mini_agent_lab.tool.git_tools import GitCommitTool


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _repo() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    _git(root, "init")
    _git(root, "config", "user.email", "mini-agent@example.test")
    _git(root, "config", "user.name", "Mcode")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    (root / "other.txt").write_text("base other\n", encoding="utf-8")
    _git(root, "add", "tracked.txt", "other.txt")
    _git(root, "commit", "-m", "init")
    return tmp


def test_git_commit_tool_commits_explicit_file() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        baseline_path = root / ".gitstate" / "baseline.json"
        save_snapshot(GitState(root).snapshot(), baseline_path)
        (root / "tracked.txt").write_text("agent change\n", encoding="utf-8")
        recorder = RunRecorder(root / ".runs", run_id="commit-explicit")
        tool = GitCommitTool(GitState(root), baseline_path=baseline_path, sink=recorder)

        result = json.loads(tool.execute({"files": ["tracked.txt"], "message": "test: update tracked"}))
        log = _git(root, "log", "--oneline", "-1").stdout
        status = _git(root, "status", "--porcelain=v1").stdout
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))

        _assert(result["message"] == "test: update tracked", "result includes commit message")
        _assert("test: update tracked" in log, "commit is created")
        _assert("tracked.txt" not in status, "committed file is clean")
        _assert(summary["git"]["commit"]["status"] == "done", "summary records successful commit")
        _assert(summary["git"]["commit"]["files"] == ["tracked.txt"], "summary records committed files")


def test_git_commit_tool_does_not_commit_other_staged_files() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        baseline_path = root / ".gitstate" / "baseline.json"
        save_snapshot(GitState(root).snapshot(), baseline_path)
        (root / "tracked.txt").write_text("agent change\n", encoding="utf-8")
        (root / "other.txt").write_text("user staged change\n", encoding="utf-8")
        _git(root, "add", "other.txt")
        tool = GitCommitTool(GitState(root), baseline_path=baseline_path)

        tool.execute({"files": ["tracked.txt"], "message": "test: commit only tracked"})
        show = _git(root, "show", "--name-only", "--format=", "HEAD").stdout.splitlines()
        status = _git(root, "status", "--porcelain=v1").stdout

        _assert(show == ["tracked.txt"], "commit includes only explicit file")
        _assert("M  other.txt" in status, "previously staged other file remains staged")


def test_git_commit_tool_commits_untracked_file() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        baseline_path = root / ".gitstate" / "baseline.json"
        save_snapshot(GitState(root).snapshot(), baseline_path)
        (root / "new.txt").write_text("agent created\n", encoding="utf-8")
        tool = GitCommitTool(GitState(root), baseline_path=baseline_path)

        result = json.loads(tool.execute({"files": ["new.txt"], "message": "test: add new file"}))
        show = _git(root, "show", "--name-only", "--format=", "HEAD").stdout.splitlines()
        status = _git(root, "status", "--porcelain=v1").stdout

        _assert(show == ["new.txt"], "untracked file is committed")
        _assert("new.txt" not in status, "untracked file is clean after commit")
        _assert(result["risk"]["agent_files"] == ["new.txt"], "result classifies new file as agent file")


def test_git_commit_tool_rejects_invalid_inputs() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        tool = GitCommitTool(GitState(root), baseline_path=root / ".gitstate" / "baseline.json")
        for args, label in [
            ({"files": [], "message": "msg"}, "empty files"),
            ({"files": ["tracked.txt"], "message": "  "}, "empty message"),
            ({"files": ["."], "message": "msg"}, "dot path"),
            ({"files": [".runs/x.jsonl"], "message": "msg"}, "internal file"),
            ({"files": ["/tmp/outside.txt"], "message": "msg"}, "outside repo"),
        ]:
            try:
                tool.execute(args)
                raise AssertionError(f"{label} should fail")
            except ValueError:
                print(f"  OK: rejects {label}")


def test_git_commit_tool_rejects_unchanged_file() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        tool = GitCommitTool(GitState(root), baseline_path=root / ".gitstate" / "baseline.json")
        try:
            tool.execute({"files": ["tracked.txt"], "message": "test: unchanged"})
            raise AssertionError("unchanged file should fail")
        except ValueError as exc:
            _assert("unchanged" in str(exc) or "unknown" in str(exc), "unchanged file is rejected")


def test_git_commit_tool_rejects_non_git_repo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tool = GitCommitTool(GitState(root), baseline_path=root / ".gitstate" / "baseline.json")
        try:
            tool.execute({"files": ["file.txt"], "message": "test"})
            raise AssertionError("non-git repo should fail")
        except ValueError as exc:
            _assert("git" in str(exc).lower(), "non-git repo is rejected")


def test_registry_contains_git_commit_and_safety_asks() -> None:
    registry = default_registry()
    _assert("git_commit" in registry.names(), "default registry includes git_commit")
    result = SafetyGate(PolicyConfig({})).check(
        "git_commit",
        {"files": ["tracked.txt"], "message": "msg"},
        registry.get("git_commit").read_only,
    )
    _assert(result.decision == "ask", "git_commit requires approval")
    _assert("不会上传到远程仓库" in result.reason, "git_commit approval is human-readable")


if __name__ == "__main__":
    test_git_commit_tool_commits_explicit_file()
    test_git_commit_tool_does_not_commit_other_staged_files()
    test_git_commit_tool_commits_untracked_file()
    test_git_commit_tool_rejects_invalid_inputs()
    test_git_commit_tool_rejects_unchanged_file()
    test_git_commit_tool_rejects_non_git_repo()
    test_registry_contains_git_commit_and_safety_asks()
    print("All git commit tool tests passed.")
