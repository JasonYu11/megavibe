"""Tests for python_run tool execution and job events."""

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
from mini_agent_lab.runtime_env import RuntimeSelection
from mini_agent_lab.tool import default_registry


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _runtime() -> RuntimeSelection:
    return RuntimeSelection(shell="/bin/zsh", python=sys.executable, python_source="test", candidates=())


def test_python_code_events() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(Path(tmp) / "runs", run_id="python-code")
        registry = default_registry(
            sink=recorder,
            job_log_dir=Path(tmp) / "jobs",
            runtime_selection=_runtime(),
        )
        result = registry.get("python_run").execute({"mode": "code", "code": "print('PY_OK')", "timeout_seconds": 3})
        events = _events(recorder.event_path)
        kinds = [event["kind"] for event in events]
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        _assert("PY_OK" in result, "python_run returns stdout")
        _assert("[python] exit_code=0" in result, "python_run returns structured footer")
        _assert("command_started" in kinds, "python_run records command_started")
        _assert("command_output" in kinds, "python_run records command_output")
        _assert(summary["last_command"]["kind"] == "python", "summary tracks python command kind")
        env_result = registry.get("python_run").execute(
            {
                "mode": "code",
                "code": "import os; print(os.environ.get('MPLBACKEND')); print(os.environ.get('QT_QPA_PLATFORM'))",
                "timeout_seconds": 3,
            }
        )
        _assert("Agg" in env_result, "python_run forces matplotlib headless backend")
        _assert("offscreen" in env_result, "python_run forces Qt offscreen mode")


def test_python_code_detects_workspace_changes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        recorder = RunRecorder(root / "runs", run_id="python-change")
        registry = default_registry(
            sink=recorder,
            job_log_dir=root / "jobs",
            runtime_selection=_runtime(),
        )
        old_cwd = Path.cwd()
        try:
            import os

            os.chdir(root)
            result = registry.get("python_run").execute(
                {
                    "mode": "code",
                    "code": "from pathlib import Path; Path('generated.py').write_text(\"print('ok')\\n\", encoding='utf-8')",
                    "timeout_seconds": 3,
                }
            )
        finally:
            os.chdir(old_cwd)

        events = _events(recorder.event_path)
        change_event = next(event for event in events if event["kind"] == "workspace_changes_detected")
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        change = change_event["data"]["changes"][0]
        _assert("[python] exit_code=0" in result, "python_run succeeds while creating a file")
        _assert(change["path"] == "generated.py", "python_run detects generated file path")
        _assert(change["kind"] == "create", "python_run marks generated file as create")
        _assert(change["recoverable"] is False, "command-generated change is marked non-recoverable")
        _assert(summary["file_changes"][0]["path"] == "generated.py", "summary tracks command-generated file change")


def test_python_file_execution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script = root / "hello.py"
        script.write_text("print('FILE_OK')\n", encoding="utf-8")
        recorder = RunRecorder(root / "runs", run_id="python-file")
        registry = default_registry(sink=recorder, job_log_dir=root / "jobs", runtime_selection=_runtime())
        old_cwd = Path.cwd()
        try:
            import os

            os.chdir(root)
            result = registry.get("python_run").execute({"mode": "file", "path": "hello.py", "timeout_seconds": 3})
        finally:
            os.chdir(old_cwd)
        _assert("FILE_OK" in result, "python_run executes project-relative files")
        try:
            old_cwd = Path.cwd()
            import os

            os.chdir(root)
            registry.get("python_run").execute({"mode": "file", "path": "../escape.py", "timeout_seconds": 3})
            raise AssertionError("escaped python file should fail")
        except ValueError:
            print("  OK: python_run rejects escaped file paths")
        finally:
            os.chdir(old_cwd)


def test_python_background_job() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(Path(tmp) / "runs", run_id="python-background")
        registry = default_registry(sink=recorder, job_log_dir=Path(tmp) / "jobs", runtime_selection=_runtime())
        started = registry.get("python_run").execute(
            {
                "mode": "code",
                "code": "print('BG_START')",
                "run_in_background": True,
            }
        )
        _assert("python-1" in started, "background python returns python job id")
        waited = registry.get("wait").execute({"job_ids": ["python-1"], "timeout_seconds": 3})
        time.sleep(0.1)
        _assert("BG_START" in waited, "wait returns python job output")
        _assert((Path(tmp) / "jobs" / "python-1.log").exists(), "python background log exists")


if __name__ == "__main__":
    test_python_code_events()
    test_python_code_detects_workspace_changes()
    test_python_file_execution()
    test_python_background_job()
    print("All python_run tests passed.")
