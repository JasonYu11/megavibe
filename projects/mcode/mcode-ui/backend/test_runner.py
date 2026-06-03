from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class TestRun:
    id: str
    label: str
    command: list[str]
    status: str
    started_at: float
    finished_at: float = 0.0
    exit_code: int | None = None
    output: str = ""


class TestRunner:
    def __init__(self) -> None:
        self._runs: dict[str, TestRun] = {}
        self._lock = threading.Lock()

    def start(self, root: Path, label: str = "subagent") -> dict[str, Any]:
        safe_label = label if label in TEST_COMMANDS else "subagent"
        command = TEST_COMMANDS[safe_label]
        run_id = f"test-{int(time.time() * 1000)}"
        run = TestRun(id=run_id, label=safe_label, command=command, status="running", started_at=time.time())
        with self._lock:
            self._runs[run_id] = run
        threading.Thread(target=self._run, args=(run_id, root), daemon=True).start()
        return asdict(run)

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"unknown test run: {run_id}")
            return asdict(self._runs[run_id])

    def _run(self, run_id: str, root: Path) -> None:
        with self._lock:
            run = self._runs[run_id]
        try:
            proc = subprocess.run(
                run.command,
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
            )
            output = proc.stdout or ""
            status = "completed" if proc.returncode == 0 else "failed"
            exit_code = proc.returncode
        except Exception as exc:
            output = f"error: {exc}"
            status = "failed"
            exit_code = -1
        with self._lock:
            run = self._runs[run_id]
            run.status = status
            run.finished_at = time.time()
            run.exit_code = exit_code
            run.output = output


TEST_COMMANDS = {
    "subagent": ["python3", "tests/test_subagent.py"],
    "skills": ["python3", "tests/test_skills.py"],
    "recorder": ["python3", "tests/test_run_recorder.py"],
    "product": ["python3", "scripts/product_acceptance.py"],
    "benchmark-dry": ["python3", "scripts/run_product_benchmark_suite.py", "--dry-run"],
    "benchmark": ["python3", "scripts/run_product_benchmark_suite.py"],
}
