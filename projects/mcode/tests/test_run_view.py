"""Tests for run timeline and status renderers."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.events import Event
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.run_view import find_latest_run_file, render_summary, render_timeline


PYTHON = "/Users/macbot/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _sample_run(tmp: str) -> RunRecorder:
    recorder = RunRecorder(tmp, run_id="view-demo", session_id="session-1")
    recorder.emit(Event("turn_started", {"input": "write and test"}))
    recorder.emit(
        Event(
            "assistant_message",
            {
                "content": "",
                "tool_calls": [{"id": "call-1", "name": "write_file", "arguments": {"path": "notes/a.md"}}],
            },
        )
    )
    recorder.emit(Event("tool_dispatch", {"name": "write_file", "arguments": {"path": "notes/a.md"}}))
    recorder.emit(Event("preview", {"kind": "write", "path": "notes/a.md", "diff": "+hello\n"}))
    recorder.emit(
        Event(
            "tool_result",
            {
                "name": "write_file",
                "result": "wrote notes/a.md",
                "output": "wrote notes/a.md",
                "ok": True,
                "error": "",
                "error_kind": "",
                "blocked": False,
                "truncated": False,
            },
        )
    )
    recorder.emit(
        Event(
            "todo_updated",
            {
                "completed": 1,
                "total": 2,
                "pending": 1,
                "in_progress": 0,
                "progress_text": "1/2 done",
                "done": False,
                "current": None,
                "todos": [],
            },
        )
    )
    recorder.emit(
        Event(
            "git_changes_classified",
            {
                "current_dirty": 1,
                "user_existing": [],
                "agent_created": ["notes/a.md"],
                "agent_modified": [],
                "overlap": [],
                "resolved_baseline_dirty": [],
            },
        )
    )
    recorder.emit(Event("turn_completed", {"answer": "done"}))
    return recorder


def test_render_timeline_and_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = _sample_run(tmp)
        timeline = render_timeline(recorder.event_path)
        summary = render_summary(recorder.summary_path)

        _assert("[turn_started] input=write and test" in timeline, "timeline shows turn start")
        _assert("[assistant_message] tool_calls=write_file" in timeline, "timeline shows model tool call")
        _assert("[tool_dispatch] write_file notes/a.md" in timeline, "timeline shows tool dispatch subject")
        _assert("[tool_result] write_file ok" in timeline, "timeline shows structured tool result")
        _assert("created=[notes/a.md]" in timeline, "timeline shows git classification")
        _assert("Run: view-demo" in summary, "summary shows run id")
        _assert("Status: completed" in summary, "summary shows status")
        _assert("Last tool: write_file ok" in summary, "summary shows latest tool")
        _assert("Todo: 1/2 done" in summary, "summary shows todo progress")
        _assert("Final: done" in summary, "summary shows final answer")


def test_latest_run_file_and_scripts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = _sample_run(tmp)
        latest_events = find_latest_run_file(tmp, ".events.jsonl")
        latest_summary = find_latest_run_file(tmp, ".summary.json")

        replay = subprocess.run(
            [PYTHON, str(ROOT / "scripts" / "run_replay.py"), str(recorder.event_path)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        status = subprocess.run(
            [PYTHON, str(ROOT / "scripts" / "run_status.py"), str(recorder.summary_path)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        _assert(latest_events == recorder.event_path, "latest events file is found")
        _assert(latest_summary == recorder.summary_path, "latest summary file is found")
        _assert("[tool_result] write_file ok" in replay.stdout, "run_replay prints timeline")
        _assert("Status: completed" in status.stdout, "run_status prints summary")


def test_render_legacy_tool_result() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy.events.jsonl"
        path.write_text(
            json.dumps(
                {
                    "seq": 1,
                    "time": 1,
                    "time_text": "now",
                    "kind": "tool_result",
                    "data": {"name": "old_tool", "result": "error: old failure"},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        timeline = render_timeline(path)
        _assert("[tool_result] old_tool error" in timeline, "legacy result prefix still classifies errors")


if __name__ == "__main__":
    test_render_timeline_and_summary()
    test_latest_run_file_and_scripts()
    test_render_legacy_tool_result()
    print("All run view tests passed.")
