"""Tests for bash command and background job event recording."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.tool import default_registry


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_foreground_bash_events() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(Path(tmp) / "runs", run_id="bash-foreground")
        registry = default_registry(sink=recorder, job_log_dir=Path(tmp) / "jobs")
        result = registry.get("bash").execute({"command": "printf 'hello\\n'", "timeout_seconds": 3})
        events = _events(recorder.event_path)
        kinds = [event["kind"] for event in events]
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))

        _assert("hello" in result, "foreground bash returns command output")
        _assert("[command] exit_code=0" in result, "foreground bash returns structured footer")
        _assert("command_started" in kinds, "command_started event is recorded")
        _assert("command_output" in kinds, "command_output event is recorded")
        _assert("command_finished" in kinds, "command_finished event is recorded")
        _assert(summary["last_command"]["exit_code"] == 0, "summary tracks command exit code")
        _assert(summary["current_command"] is None, "summary clears current command")


def test_foreground_bash_detects_workspace_changes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        recorder = RunRecorder(root / "runs", run_id="bash-change")
        registry = default_registry(sink=recorder, job_log_dir=root / "jobs")
        old_cwd = Path.cwd()
        try:
            import os

            os.chdir(root)
            registry.get("bash").execute({"command": "printf 'hello\\n' > generated.txt", "timeout_seconds": 3})
        finally:
            os.chdir(old_cwd)

        events = _events(recorder.event_path)
        change_event = next(event for event in events if event["kind"] == "workspace_changes_detected")
        change = change_event["data"]["changes"][0]
        _assert(change["path"] == "generated.txt", "bash detects generated file path")
        _assert(change["kind"] == "create", "bash marks generated file as create")
        _assert("+hello" in change["diff"], "bash change includes diff preview")


def test_background_bash_job_events_and_log() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        job_dir = Path(tmp) / "jobs"
        recorder = RunRecorder(Path(tmp) / "runs", run_id="bash-background")
        registry = default_registry(sink=recorder, job_log_dir=job_dir)
        old_cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp)
            started = registry.get("bash").execute(
                {
                    "command": "printf 'start\\n'; sleep 0.1; printf 'done\\n'; printf 'bg\\n' > bg.txt",
                    "run_in_background": True,
                }
            )
        finally:
            os.chdir(old_cwd)
        _assert("Started background job bash-1" in started, "background bash returns job id")

        waited = registry.get("wait").execute({"job_ids": ["bash-1"], "timeout_seconds": 3})
        time.sleep(0.2)
        events = _events(recorder.event_path)
        kinds = [event["kind"] for event in events]
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        log_path = job_dir / "bash-1.log"

        _assert("start" in waited and "done" in waited, "wait returns background output")
        _assert(log_path.exists(), "background job log file exists")
        _assert("start" in log_path.read_text(encoding="utf-8"), "background job log contains output")
        _assert("job_started" in kinds, "job_started event is recorded")
        _assert("job_output" in kinds, "job_output event is recorded")
        _assert("job_finished" in kinds, "job_finished event is recorded")
        _assert("workspace_changes_detected" in kinds, "background job records workspace changes")
        change_event = next(event for event in events if event["kind"] == "workspace_changes_detected")
        _assert(change_event["data"]["changes"][0]["path"] == "bg.txt", "background job detects generated file")
        _assert(summary["jobs"]["bash-1"]["status"] == "done", "summary tracks completed job")
        _assert(summary["jobs"]["bash-1"]["exit_code"] == 0, "summary tracks job exit code")


if __name__ == "__main__":
    test_foreground_bash_events()
    test_foreground_bash_detects_workspace_changes()
    test_background_bash_job_events_and_log()
    print("All bash event tests passed.")
