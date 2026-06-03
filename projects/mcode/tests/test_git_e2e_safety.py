"""End-to-end safety checks for git-aware agent runs."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.app_config import ContextConfig
from mini_agent_lab.checkpoint import CheckpointStore
from mini_agent_lab.git_state import GitState, save_snapshot
from mini_agent_lab.provider import ProviderResponse, ToolCall
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.safety import PolicyConfig, SafetyGate
from mini_agent_lab.tool import ToolRegistry
from mini_agent_lab.tool.builtin import WriteFileTool
from mini_agent_lab.tool.git_tools import GitCommitTool


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _repo() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    _git(root, "init")
    _git(root, "config", "user.email", "mini-agent@example.test")
    _git(root, "config", "user.name", "Mcode")
    (root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    (root / "user.txt").write_text("user base\n", encoding="utf-8")
    _git(root, "add", "agent.py", "user.txt")
    _git(root, "commit", "-m", "init")
    return tmp


class ScriptedProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self.responses = list(responses)

    def complete(self, messages: list[Any], tools: list[dict]) -> ProviderResponse:
        if not self.responses:
            raise AssertionError("provider was called more times than expected")
        return self.responses.pop(0)


class AllowSafetyGate:
    def check(self, tool_name: str, arguments: dict, read_only: bool):
        return type("SafetyResult", (), {"decision": "allow", "reason": "test allow"})()


class RecordingApprover:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[dict[str, Any]] = []

    def approve(self, tool_name: str, arguments: dict, reason: str) -> bool:
        self.calls.append({"tool_name": tool_name, "arguments": arguments, "reason": reason})
        return self.allow


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(WriteFileTool())
    return registry


def _run_agent_write(
    root: Path,
    path: Path,
    content: str,
    run_id: str,
    approver: RecordingApprover | None = None,
) -> RunRecorder:
    recorder = RunRecorder(root / ".runs", run_id=run_id)
    baseline_path = root / ".gitstate" / f"{run_id}.baseline.json"
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="write_file",
                        arguments={"path": str(path), "content": content},
                    )
                ],
            ),
            ProviderResponse(content="done"),
        ]
    )
    agent = Agent(
        provider=provider,  # type: ignore[arg-type]
        tools=_registry(),
        session=Session("You are a test agent."),
        safety_gate=AllowSafetyGate(),  # type: ignore[arg-type]
        approver=approver or RecordingApprover(True),  # type: ignore[arg-type]
        checkpoints=CheckpointStore(root / ".checkpoints"),
        context_config=ContextConfig(auto_compact=False),
        sink=recorder,
        git_baseline_path=baseline_path,
        git_state=GitState(root),
    )
    answer = agent.run("write the file")
    _assert(answer == "done", f"{run_id} agent run completes")
    return recorder


def _summary(recorder: RunRecorder) -> dict[str, Any]:
    return json.loads(recorder.summary_path.read_text(encoding="utf-8"))


def test_agent_write_classifies_tracked_file() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        recorder = _run_agent_write(root, root / "agent.py", "print('agent')\n", "tracked")
        git = _summary(recorder)["git"]

        _assert(git["agent_modified"] == ["agent.py"], "tracked agent edit is classified")
        _assert(git["agent_created"] == [], "tracked edit is not classified as created")
        _assert(git["user_existing"] == [], "clean baseline has no user-existing files")


def test_agent_write_classifies_created_file_and_ignores_internal_dirs() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        recorder = _run_agent_write(root, root / "new.txt", "new file\n", "created")
        git = _summary(recorder)["git"]
        dirty = _git(root, "status", "--porcelain=v1").stdout

        _assert(git["agent_created"] == ["new.txt"], "untracked agent file is classified as created")
        _assert(".runs/" in dirty and ".gitstate/" in dirty, "recorder/gitstate are visible to raw git")
        classified = (
            git.get("agent_created", [])
            + git.get("agent_modified", [])
            + git.get("user_existing", [])
            + git.get("overlap", [])
        )
        _assert(not any(path.startswith(".runs/") for path in classified), "agent run files are filtered from classification")
        _assert(
            not any(path.startswith(".gitstate/") for path in classified),
            "agent baseline files are filtered from classification",
        )


def test_agent_write_does_not_hide_user_dirty_file() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        (root / "user.txt").write_text("user dirty\n", encoding="utf-8")
        recorder = _run_agent_write(root, root / "agent.py", "print('agent')\n", "mixed")
        git = _summary(recorder)["git"]

        _assert(git["user_existing"] == ["user.txt"], "baseline user dirty file is recorded")
        _assert(git["agent_modified"] == ["agent.py"], "agent edit is still classified separately")
        _assert(git["overlap"] == ["user.txt"], "still-dirty baseline file remains visible as overlap risk")


def test_overlap_write_denied_preserves_user_file() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        (root / "user.txt").write_text("user dirty\n", encoding="utf-8")
        approver = RecordingApprover(False)
        recorder = _run_agent_write(root, root / "user.txt", "agent overwrite\n", "overlap-denied", approver)
        summary = _summary(recorder)

        _assert((root / "user.txt").read_text(encoding="utf-8") == "user dirty\n", "denied overlap keeps user content")
        _assert(len(approver.calls) == 1, "overlap risk asks exactly once")
        _assert(summary["last_error"].startswith("git overlap risk"), "summary shows overlap risk")
        _assert(summary["last_tool_result"]["result"].startswith("blocked:"), "tool result is blocked")
        _assert(summary["git"]["overlap_risks"][0]["path"] == "user.txt", "overlap risk path is recorded")


def test_overlap_write_approved_records_risk() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        (root / "user.txt").write_text("user dirty\n", encoding="utf-8")
        approver = RecordingApprover(True)
        recorder = _run_agent_write(root, root / "user.txt", "agent overwrite\n", "overlap-approved", approver)
        summary = _summary(recorder)

        _assert((root / "user.txt").read_text(encoding="utf-8") == "agent overwrite\n", "approved overlap writes content")
        _assert(len(approver.calls) == 1, "approved overlap asks once")
        _assert(summary["git"]["overlap_risks"][0]["path"] == "user.txt", "approved overlap remains auditable")


def test_git_commit_only_commits_agent_file_with_user_staged_file_present() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        baseline_path = root / ".gitstate" / "baseline.json"
        save_snapshot(GitState(root).snapshot(), baseline_path)
        (root / "agent.py").write_text("print('agent')\n", encoding="utf-8")
        (root / "user.txt").write_text("user staged\n", encoding="utf-8")
        _git(root, "add", "user.txt")
        recorder = RunRecorder(root / ".runs", run_id="commit-staged")
        tool = GitCommitTool(GitState(root), baseline_path=baseline_path, sink=recorder)

        result = json.loads(tool.execute({"files": ["agent.py"], "message": "test: commit agent only"}))
        committed_files = _git(root, "show", "--name-only", "--format=", "HEAD").stdout.splitlines()
        status = _git(root, "status", "--porcelain=v1").stdout
        summary = _summary(recorder)

        _assert(committed_files == ["agent.py"], "commit contains only explicit agent file")
        _assert("M  user.txt" in status, "pre-staged user file remains staged after commit")
        _assert(result["risk"]["agent_files"] == ["agent.py"], "commit result identifies agent file")
        _assert(summary["git"]["commit"]["status"] == "done", "summary records completed commit")


def test_git_commit_refuses_internal_file() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        baseline_path = root / ".gitstate" / "baseline.json"
        save_snapshot(GitState(root).snapshot(), baseline_path)
        (root / ".runs").mkdir()
        (root / ".runs" / "x.jsonl").write_text("internal\n", encoding="utf-8")
        tool = GitCommitTool(GitState(root), baseline_path=baseline_path)

        try:
            tool.execute({"files": [".runs/x.jsonl"], "message": "test: internal"})
            raise AssertionError("internal file commit should fail")
        except ValueError as exc:
            _assert("internal" in str(exc), "git_commit refuses agent internal files")


def test_git_command_safety_matrix() -> None:
    gate = SafetyGate(PolicyConfig({}))
    cases = [
        ("git status --porcelain", "allow"),
        ("git diff -- agent.py", "allow"),
        ("git diff --output=patch.txt", "ask"),
        ("git commit -m test", "ask"),
        ("git stash push", "ask"),
        ("git reset --hard", "ask"),
        ("git clean -fd", "ask"),
        ("git push --force", "ask"),
    ]

    for command, expected in cases:
        result = gate.check("bash", {"command": command}, read_only=False)
        _assert(result.decision == expected, f"{command!r} -> {expected}")


def test_agent_run_in_non_git_directory_does_not_crash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        recorder = _run_agent_write(root, root / "plain.txt", "plain\n", "non-git")
        summary = _summary(recorder)

        _assert((root / "plain.txt").exists(), "agent can write in a non-git directory")
        _assert(summary["git"]["is_repo"] is False, "summary records non-git baseline")


def test_git_commit_hook_failure_is_recorded() -> None:
    with _repo() as tmp:
        root = Path(tmp)
        baseline_path = root / ".gitstate" / "baseline.json"
        save_snapshot(GitState(root).snapshot(), baseline_path)
        (root / "agent.py").write_text("print('agent')\n", encoding="utf-8")
        recorder = RunRecorder(root / ".runs", run_id="commit-failed")
        hook = root / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho hook failed >&2\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        tool = GitCommitTool(GitState(root), baseline_path=baseline_path, sink=recorder)

        try:
            tool.execute({"files": ["agent.py"], "message": "test: should fail"})
            raise AssertionError("commit rejected by hook should fail")
        except RuntimeError:
            summary = _summary(recorder)
            _assert(summary["git"]["commit"]["status"] == "failed", "failed commit is recorded")
            _assert(summary["git"]["commit"]["files"] == ["agent.py"], "failed commit records file list")


if __name__ == "__main__":
    test_agent_write_classifies_tracked_file()
    test_agent_write_classifies_created_file_and_ignores_internal_dirs()
    test_agent_write_does_not_hide_user_dirty_file()
    test_overlap_write_denied_preserves_user_file()
    test_overlap_write_approved_records_risk()
    test_git_commit_only_commits_agent_file_with_user_staged_file_present()
    test_git_commit_refuses_internal_file()
    test_git_command_safety_matrix()
    test_agent_run_in_non_git_directory_does_not_crash()
    test_git_commit_hook_failure_is_recorded()
    print("All git e2e safety tests passed.")
