"""Tests for persisted run event logs and summary snapshots."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.events import Event
from mini_agent_lab.run_recorder import RunRecorder


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def test_run_recorder_writes_events_and_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(tmp, run_id="demo/run 1", session_id="session-1")
        recorder.emit(Event("turn_started", {"input": "create a file"}))
        recorder.emit(
            Event(
                "tool_dispatch",
                {
                    "name": "write_file",
                    "arguments": {"path": "notes/demo.md", "content": "hello"},
                },
            )
        )
        recorder.emit(
            Event(
                "preview",
                {
                    "kind": "write",
                    "path": "notes/demo.md",
                    "diff": "--- before\n+++ after\n+hello\n",
                    "source": "write_file",
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
                    "todos": [
                        {"content": "Plan", "status": "completed"},
                        {"content": "Write", "status": "pending"},
                    ],
                },
            )
        )
        recorder.emit(Event("tool_result", {"name": "write_file", "result": "wrote notes/demo.md"}))
        recorder.emit(Event("turn_completed", {"answer": "done"}))

        _assert(recorder.event_path.exists(), "events jsonl exists")
        _assert(recorder.summary_path.exists(), "summary json exists")

        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))

        _assert(len(events) == 6, "six events persisted")
        _assert(events[0]["seq"] == 1, "first event seq is 1")
        _assert(events[-1]["kind"] == "turn_completed", "last event is turn_completed")
        _assert(summary["run_id"] == "demo-run-1", "run id is sanitized")
        _assert(summary["session_id"] == "session-1", "session id is preserved")
        _assert(summary["status"] == "completed", "summary status is completed")
        _assert(summary["tool_calls"] == 1, "tool call count is tracked")
        _assert(summary["tool_results"] == 1, "tool result count is tracked")
        _assert(summary["todo"]["completed"] == 1, "todo progress is tracked")
        _assert(summary["file_changes"][0]["path"] == "notes/demo.md", "file preview is tracked")
        _assert(summary["file_changes"][0]["source"] == "write_file", "file preview source is tracked")
        _assert(summary["final_answer"] == "done", "final answer is tracked")
        _assert(len(summary["recent_events"]) == 6, "recent events are included")


def test_run_recorder_tracks_pending_and_cancelled_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(tmp, run_id="plan", session_id="s1")
        recorder.emit(Event("turn_started", {"input": "make a plan"}))
        recorder.emit(Event("assistant_message", {"content": "1. Inspect\n2. Implement", "tool_calls": []}))
        recorder.emit(Event("plan_pending", {"plan_text": "1. Inspect\n2. Implement", "status": "awaiting_approval"}))
        recorder.emit(Event("turn_completed", {"answer": "1. Inspect\n2. Implement"}))

        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        _assert(summary["status"] == "awaiting_plan_decision", "pending plan keeps summary awaiting decision")
        _assert(summary["pending_plan"]["plan_text"].startswith("1. Inspect"), "pending plan text is stored")
        _assert(summary["pending_plan"]["revision"] == 1, "first pending plan is revision 1")
        _assert(summary["pending_plan"]["todo_count"] == 2, "pending plan stores parsed todo count")
        _assert(summary["pending_plan"]["todos"][0]["status"] == "in_progress", "pending plan seeds first todo")

        recorder.emit(Event("turn_started", {"input": "refine plan", "plan": True}))
        recorder.emit(Event("plan_pending", {"plan_text": "1. Inspect\n2. Test\n3. Ship", "status": "awaiting_approval"}))
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        _assert(summary["pending_plan"]["revision"] == 2, "refined pending plan increments revision")

        recorder.emit(Event("plan_cancelled", {"plan_text": "1. Inspect\n2. Implement"}))
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        _assert(summary["status"] == "completed", "cancelled plan returns summary to completed")
        _assert(summary["pending_plan"]["status"] == "cancelled", "cancelled plan status is stored")
        _assert(summary["pending_plan"]["revision"] == 2, "cancelled plan keeps latest revision")


def test_run_recorder_publishes_persisted_records() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        published = []
        recorder = RunRecorder(tmp, run_id="stream", session_id="s1", record_downstream=published.append)
        recorder.emit(Event("turn_started", {"input": "hello"}))
        recorder.emit(Event("turn_status", {"status": "running", "phase": "model_call", "message": "生成中"}))

        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        _assert([item["seq"] for item in published] == [1, 2], "record downstream receives persisted seq records")
        _assert(published[1]["kind"] == "turn_status", "record downstream keeps event kind")
        _assert(summary["phase"] == "model_call", "trace status updates summary phase")


if __name__ == "__main__":
    test_run_recorder_writes_events_and_summary()
    test_run_recorder_tracks_pending_and_cancelled_plan()
    test_run_recorder_publishes_persisted_records()
    print("All run recorder tests passed.")
