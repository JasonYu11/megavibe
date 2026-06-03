"""Tests for git baseline snapshots and change classification."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.git_state import (
    GitSnapshot,
    GitState,
    classify_changes,
    load_snapshot,
    parse_porcelain,
    save_snapshot,
)
from mini_agent_lab.provider import Message, ProviderResponse
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.safety import SafetyResult
from mini_agent_lab.tool import ToolRegistry
from mini_agent_lab.tool.builtin import WriteFileTool
from mini_agent_lab.tool.git_tools import GitBaselineTool, GitClassifyChangesTool, GitDiffTool, GitStatusTool


class FakeProvider:
    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(content="done")


class AlwaysAllowSafetyGate:
    def check(self, tool_name: str, arguments: dict, read_only: bool) -> SafetyResult:
        return SafetyResult("allow", "test allow")


class RecordingApprover:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, dict, str]] = []

    def approve(self, tool_name: str, arguments: dict, reason: str) -> bool:
        self.calls.append((tool_name, arguments, reason))
        return self.allow


class SequenceGitState:
    def __init__(self, snapshots: list[GitSnapshot]) -> None:
        self.snapshots = list(snapshots)

    def snapshot(self) -> GitSnapshot:
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _completed(stdout: str = "", stderr: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], code, stdout, stderr)


def test_parse_porcelain() -> None:
    entries = parse_porcelain(" M README.md\nM  src/app.py\n?? notes/new.md\nR  old.txt -> new.txt\n")
    _assert(entries[0].path == "README.md", "unstaged path parsed")
    _assert(entries[0].index == " " and entries[0].worktree == "M", "unstaged status parsed")
    _assert(entries[1].staged, "staged status parsed")
    _assert(entries[2].untracked, "untracked status parsed")
    _assert(entries[3].path == "new.txt", "rename target path parsed")


def test_snapshot_and_diff_with_fake_runner() -> None:
    def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        key = " ".join(args)
        responses = {
            "rev-parse --show-toplevel": _completed("/repo\n"),
            "rev-parse --abbrev-ref HEAD": _completed("main\n"),
            "rev-parse --short HEAD": _completed("abc123\n"),
            "status --porcelain=v1": _completed(" M README.md\n?? notes/new.md\n"),
            "diff -- README.md": _completed("diff --git a/README.md b/README.md\n"),
        }
        return responses.get(key, _completed(stderr=f"unexpected {key}", code=1))

    git = GitState(runner=runner)
    snapshot = git.snapshot()
    diff = git.diff(path="README.md")

    _assert(snapshot.is_repo, "snapshot detects repo")
    _assert(snapshot.root == "/repo", "snapshot captures root")
    _assert(snapshot.branch == "main", "snapshot captures branch")
    _assert(snapshot.head == "abc123", "snapshot captures head")
    _assert(snapshot.dirty_count == 2, "snapshot captures dirty count")
    _assert("diff --git" in diff, "git diff returns output")


def test_non_git_snapshot_with_fake_runner() -> None:
    def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return _completed(stderr="fatal: not a git repository", code=128)

    snapshot = GitState(runner=runner).snapshot()
    _assert(not snapshot.is_repo, "non-git directory is represented safely")
    _assert("not a git repository" in snapshot.error, "non-git error is captured")


def test_classify_changes() -> None:
    baseline = GitSnapshot(
        is_repo=True,
        root="/repo",
        branch="main",
        head="abc123",
        porcelain=parse_porcelain(" M user.txt\n"),
        captured_at=1,
    )
    current = GitSnapshot(
        is_repo=True,
        root="/repo",
        branch="main",
        head="abc123",
        porcelain=parse_porcelain(" M user.txt\n?? new.txt\n M clean-now-dirty.py\n?? .runs/demo.events.jsonl\n?? .gitstate/demo.json\n"),
        captured_at=2,
    )
    classified = classify_changes(baseline, current)
    _assert(classified.user_existing == ["user.txt"], "baseline dirty file is user_existing")
    _assert(classified.agent_created == ["new.txt"], "new untracked file is agent_created")
    _assert(classified.agent_modified == ["clean-now-dirty.py"], "new dirty tracked file is agent_modified")
    _assert(classified.overlap == ["user.txt"], "still-dirty baseline file is overlap risk")
    _assert(classified.resolved_baseline_dirty == [], "no baseline dirty file resolved")
    _assert(".runs/demo.events.jsonl" not in classified.agent_created, "agent internal run files are ignored")


def test_snapshot_save_load_and_tools() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        baseline_path = Path(tmp) / "baseline.json"

        def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            key = " ".join(args)
            responses = {
                "rev-parse --show-toplevel": _completed("/repo\n"),
                "rev-parse --abbrev-ref HEAD": _completed("main\n"),
                "rev-parse --short HEAD": _completed("abc123\n"),
                "status --porcelain=v1": _completed(" M README.md\n"),
                "diff": _completed("diff body\n"),
            }
            return responses.get(key, _completed(stderr=f"unexpected {key}", code=1))

        git = GitState(runner=runner)
        saved = save_snapshot(git.snapshot(), baseline_path)
        loaded = load_snapshot(saved)
        _assert(loaded.dirty_count == 1, "snapshot save/load preserves porcelain")

        status = GitStatusTool(git).execute({})
        diff = GitDiffTool(git).execute({})
        baseline = GitBaselineTool(git, baseline_path).execute({"action": "show"})
        classified = GitClassifyChangesTool(git, baseline_path).execute({})
        _assert('"branch": "main"' in status, "git_status tool returns json")
        _assert("diff body" in diff, "git_diff tool returns diff")
        _assert('"baseline_path"' in baseline, "git_baseline show returns baseline path")
        _assert('"overlap"' in classified, "git_classify_changes returns classification")


def test_agent_captures_git_baseline_event() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        baseline_path = Path(tmp) / "baseline.json"
        recorder = RunRecorder(Path(tmp) / "runs", run_id="git-agent")

        def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            key = " ".join(args)
            responses = {
                "rev-parse --show-toplevel": _completed("/repo\n"),
                "rev-parse --abbrev-ref HEAD": _completed("main\n"),
                "rev-parse --short HEAD": _completed("abc123\n"),
                "status --porcelain=v1": _completed(" M README.md\n"),
            }
            return responses.get(key, _completed(stderr=f"unexpected {key}", code=1))

        agent = Agent(
            provider=FakeProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            sink=recorder,
            git_baseline_path=baseline_path,
            git_state=GitState(runner=runner),
        )
        answer = agent.run("hello")
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = [event["kind"] for event in events]

        _assert(answer == "done", "agent returns final answer")
        _assert(baseline_path.exists(), "agent writes git baseline")
        _assert("git_baseline_captured" in kinds, "agent emits git baseline event")
        _assert(summary["git"]["baseline_dirty"] == 1, "summary captures baseline dirty count")


def test_agent_auto_classifies_git_changes_on_completion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = GitSnapshot(
            is_repo=True,
            root=str(root),
            branch="main",
            head="abc123",
            porcelain=parse_porcelain(" M user.txt\n"),
            captured_at=1,
        )
        current = GitSnapshot(
            is_repo=True,
            root=str(root),
            branch="main",
            head="abc123",
            porcelain=parse_porcelain(" M user.txt\n?? new.txt\n M agent.py\n"),
            captured_at=2,
        )
        baseline_path = root / "baseline.json"
        recorder = RunRecorder(root / "runs", run_id="git-auto-classify")
        agent = Agent(
            provider=FakeProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            sink=recorder,
            git_baseline_path=baseline_path,
            git_state=SequenceGitState([baseline, current]),
        )

        answer = agent.run("hello")
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = [event["kind"] for event in events]

        _assert(answer == "done", "agent final answer is preserved")
        _assert("git_changes_classified" in kinds, "agent emits final git classification")
        _assert(summary["git"]["current_dirty"] == 3, "summary records current dirty count")
        _assert(summary["git"]["agent_created"] == ["new.txt"], "summary records agent-created files")
        _assert(summary["git"]["agent_modified"] == ["agent.py"], "summary records agent-modified files")
        _assert(summary["git"]["overlap"] == ["user.txt"], "summary records overlap")


def test_agent_auto_classify_skips_non_git_baseline() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        non_git = GitSnapshot(
            is_repo=False,
            root=None,
            branch=None,
            head=None,
            porcelain=[],
            captured_at=1,
            error="not a git repo",
        )
        baseline_path = root / "baseline.json"
        recorder = RunRecorder(root / "runs", run_id="git-auto-non-git")
        agent = Agent(
            provider=FakeProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            sink=recorder,
            git_baseline_path=baseline_path,
            git_state=SequenceGitState([non_git]),
        )

        answer = agent.run("hello")
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = [event["kind"] for event in events]
        _assert(answer == "done", "non-git final answer is preserved")
        _assert("git_changes_classified" not in kinds, "non-git baseline skips final classification")
        _assert("git_classify_failed" not in kinds, "non-git baseline is not a failure")


def test_agent_auto_classify_failure_does_not_block_answer() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = GitSnapshot(
            is_repo=True,
            root=str(root),
            branch="main",
            head="abc123",
            porcelain=[],
            captured_at=1,
        )
        current = GitSnapshot(
            is_repo=False,
            root=None,
            branch=None,
            head=None,
            porcelain=[],
            captured_at=2,
            error="current repo disappeared",
        )
        baseline_path = root / "baseline.json"
        recorder = RunRecorder(root / "runs", run_id="git-auto-fail")
        agent = Agent(
            provider=FakeProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            sink=recorder,
            git_baseline_path=baseline_path,
            git_state=SequenceGitState([baseline, current]),
        )

        answer = agent.run("hello")
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = [event["kind"] for event in events]
        _assert(answer == "done", "classification failure does not block answer")
        _assert("git_classify_failed" in kinds, "classification failure emits event")
        _assert(summary["git"]["classify_error"] == "current repo disappeared", "summary records classify error")


def test_git_overlap_guard_allows_clean_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline_path = root / "baseline.json"
        save_snapshot(
            GitSnapshot(
                is_repo=True,
                root=str(root),
                branch="main",
                head="abc123",
                porcelain=parse_porcelain(" M user.txt\n"),
                captured_at=1,
            ),
            baseline_path,
        )
        recorder = RunRecorder(root / "runs", run_id="git-clean-write")
        approver = RecordingApprover()
        registry = ToolRegistry()
        registry.add(WriteFileTool())
        target = root / "agent.txt"
        agent = Agent(
            provider=FakeProvider(),
            tools=registry,
            session=Session("system"),
            sink=recorder,
            safety_gate=AlwaysAllowSafetyGate(),
            approver=approver,
            git_baseline_path=baseline_path,
        )

        result = agent._execute_tool_call("write_file", {"path": str(target), "content": "agent\n"})
        _assert(result.ok is True, "clean target write is allowed")
        _assert("wrote" in result.output, "clean target output is preserved")
        _assert(target.read_text(encoding="utf-8") == "agent\n", "clean target is written")
        _assert(len(approver.calls) == 0, "clean target does not ask for overlap approval")


def test_git_overlap_guard_asks_and_allows_dirty_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline_path = root / "baseline.json"
        target = root / "user.txt"
        target.write_text("before\n", encoding="utf-8")
        save_snapshot(
            GitSnapshot(
                is_repo=True,
                root=str(root),
                branch="main",
                head="abc123",
                porcelain=parse_porcelain(" M user.txt\n"),
                captured_at=1,
            ),
            baseline_path,
        )
        recorder = RunRecorder(root / "runs", run_id="git-overlap-allow")
        approver = RecordingApprover(allow=True)
        registry = ToolRegistry()
        registry.add(WriteFileTool())
        agent = Agent(
            provider=FakeProvider(),
            tools=registry,
            session=Session("system"),
            sink=recorder,
            safety_gate=AlwaysAllowSafetyGate(),
            approver=approver,
            git_baseline_path=baseline_path,
        )

        result = agent._execute_tool_call("write_file", {"path": str(target), "content": "after\n"})
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        _assert(result.ok is True, "dirty target write proceeds when approved")
        _assert("wrote" in result.output, "dirty target output is preserved")
        _assert(target.read_text(encoding="utf-8") == "after\n", "dirty target is written after approval")
        _assert(len(approver.calls) == 1, "dirty target asks for overlap approval")
        _assert("user.txt" in approver.calls[0][2], "approval reason names dirty file")
        _assert(summary["git"]["overlap_risks"][0]["path"] == "user.txt", "summary records overlap risk")


def test_git_overlap_guard_denies_dirty_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline_path = root / "baseline.json"
        target = root / "user.txt"
        target.write_text("before\n", encoding="utf-8")
        save_snapshot(
            GitSnapshot(
                is_repo=True,
                root=str(root),
                branch="main",
                head="abc123",
                porcelain=parse_porcelain(" M user.txt\n"),
                captured_at=1,
            ),
            baseline_path,
        )
        recorder = RunRecorder(root / "runs", run_id="git-overlap-deny")
        approver = RecordingApprover(allow=False)
        registry = ToolRegistry()
        registry.add(WriteFileTool())
        agent = Agent(
            provider=FakeProvider(),
            tools=registry,
            session=Session("system"),
            sink=recorder,
            safety_gate=AlwaysAllowSafetyGate(),
            approver=approver,
            git_baseline_path=baseline_path,
        )

        result = agent._execute_tool_call("write_file", {"path": str(target), "content": "after\n"})
        _assert(result.ok is False, "dirty target write is blocked when denied")
        _assert(result.output.startswith("blocked:"), "blocked output is preserved")
        _assert(result.blocked is True, "denied dirty target is marked blocked")
        _assert(target.read_text(encoding="utf-8") == "before\n", "denied write leaves file unchanged")
        _assert(len(approver.calls) == 1, "denied dirty target still asks once")


def test_git_overlap_guard_missing_baseline_warns_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline_path = root / "missing.json"
        target = root / "agent.txt"
        recorder = RunRecorder(root / "runs", run_id="git-missing-baseline")
        registry = ToolRegistry()
        registry.add(WriteFileTool())
        agent = Agent(
            provider=FakeProvider(),
            tools=registry,
            session=Session("system"),
            sink=recorder,
            safety_gate=AlwaysAllowSafetyGate(),
            approver=RecordingApprover(),
            git_baseline_path=baseline_path,
        )

        result = agent._execute_tool_call("write_file", {"path": str(target), "content": "agent\n"})
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        _assert(result.ok is True, "missing baseline does not block writes")
        _assert("wrote" in result.output, "missing baseline output is preserved")
        _assert(target.exists(), "missing baseline write succeeds")
        _assert(summary["git"]["baseline_missing"]["path"] == str(target), "summary records missing baseline warning")


if __name__ == "__main__":
    test_parse_porcelain()
    test_snapshot_and_diff_with_fake_runner()
    test_non_git_snapshot_with_fake_runner()
    test_classify_changes()
    test_snapshot_save_load_and_tools()
    test_agent_captures_git_baseline_event()
    test_agent_auto_classifies_git_changes_on_completion()
    test_agent_auto_classify_skips_non_git_baseline()
    test_agent_auto_classify_failure_does_not_block_answer()
    test_git_overlap_guard_allows_clean_target()
    test_git_overlap_guard_asks_and_allows_dirty_target()
    test_git_overlap_guard_denies_dirty_target()
    test_git_overlap_guard_missing_baseline_warns_only()
    print("All git state tests passed.")
