from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from mini_agent_lab.events import Event, EventSink, NullSink
from mini_agent_lab.workspace_changes import WorkspaceSnapshot, diff_workspace, snapshot_workspace


@dataclass
class Job:
    id: str
    kind: str
    label: str
    process: subprocess.Popen
    command: str
    log_path: Path
    started_at: float
    output: list[str] = field(default_factory=list)
    cursor: int = 0
    status: str = "running"
    error: str = ""
    exit_code: Optional[int] = None
    finished_at: Optional[float] = None
    workspace_before: WorkspaceSnapshot = field(default_factory=dict)
    workspace_root: Path = field(default_factory=Path.cwd)


class JobManager:
    def __init__(
        self,
        log_dir: str | Path = ".jobs",
        sink: Optional[EventSink] = None,
    ) -> None:
        self._jobs: dict[str, Job] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self.log_dir = Path(log_dir)
        self.sink = sink or NullSink()

    def start_bash(self, command: str) -> Job:
        return self.start_process(
            kind="bash",
            command=command,
            shell=True,
            label=_preview(command),
        )

    def start_process(
        self,
        kind: str,
        command: str | Sequence[str],
        shell: bool = False,
        label: str = "",
        env: Optional[dict[str, str]] = None,
    ) -> Job:
        with self._lock:
            safe_kind = "".join(ch for ch in kind if ch.isalnum() or ch in {"_", "-"}).strip("-_") or "job"
            job_id = f"{safe_kind}-{self._next_id}"
            self._next_id += 1

        workspace_root = Path.cwd()
        workspace_before = snapshot_workspace(workspace_root)
        proc = subprocess.Popen(
            command,
            shell=shell,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=env,
        )
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{job_id}.log"
        job = Job(
            id=job_id,
            kind=safe_kind,
            label=label or _preview(_command_text(command)),
            process=proc,
            command=_command_text(command),
            log_path=log_path,
            started_at=time.time(),
            workspace_before=workspace_before,
            workspace_root=workspace_root,
        )
        with self._lock:
            self._jobs[job_id] = job

        self.sink.emit(
            Event(
                "job_started",
                {
                    "job_id": job.id,
                    "kind": job.kind,
                    "command": job.command,
                    "label": job.label,
                    "pid": proc.pid,
                    "log_path": str(log_path),
                },
            )
        )
        threading.Thread(target=self._pump_output, args=(job,), daemon=True).start()
        threading.Thread(target=self._watch_process, args=(job,), daemon=True).start()
        return job

    def output(self, job_id: str) -> tuple[str, str]:
        job = self._get(job_id)
        with self._lock:
            new = "".join(job.output[job.cursor :])
            job.cursor = len(job.output)
            return new, job.status

    def wait(self, job_ids: Optional[list[str]] = None, timeout_seconds: Optional[int] = None) -> str:
        deadline = None
        if timeout_seconds and timeout_seconds > 0:
            deadline = time.time() + timeout_seconds

        jobs = self._select(job_ids)
        if not jobs:
            return "No background jobs to wait for."

        while True:
            if all(job.process.poll() is not None for job in jobs):
                break
            if deadline is not None and time.time() >= deadline:
                break
            time.sleep(0.1)

        parts = []
        for job in jobs:
            text, status = self.output(job.id)
            label = f"{job.id} ({job.label})" if job.label else job.id
            if text.strip():
                parts.append(f"[{label}] {status}\n{text.rstrip()}")
            else:
                parts.append(f"[{label}] {status}\n(no new output)")
        return "\n\n".join(parts)

    def kill(self, job_id: str) -> str:
        job = self._get(job_id)
        if job.process.poll() is not None:
            return f"Background job {job_id} is already {job.status}."
        job.process.terminate()
        try:
            job.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=3)
        with self._lock:
            job.status = "killed"
            job.exit_code = job.process.returncode
            job.finished_at = time.time()
        self.sink.emit(
            Event(
                "job_finished",
                {
                    "job_id": job.id,
                    "status": job.status,
                    "exit_code": job.exit_code,
                    "duration_ms": _duration_ms(job.started_at, job.finished_at),
                    "log_path": str(job.log_path),
                },
            )
        )
        self._emit_workspace_changes(job)
        return f"Killed background job {job_id}."

    def _pump_output(self, job: Job) -> None:
        assert job.process.stdout is not None
        for line in job.process.stdout:
            with self._lock:
                job.output.append(line)
            with job.log_path.open("a", encoding="utf-8") as f:
                f.write(line)
            self.sink.emit(
                Event(
                    "job_output",
                    {
                        "job_id": job.id,
                        "text": line,
                        "log_path": str(job.log_path),
                    },
                )
            )

    def _watch_process(self, job: Job) -> None:
        code = job.process.wait()
        with self._lock:
            if job.status == "killed":
                return
            job.exit_code = code
            job.finished_at = time.time()
            job.status = "done" if code == 0 else f"failed({code})"
        self.sink.emit(
            Event(
                "job_finished",
                {
                    "job_id": job.id,
                    "status": job.status,
                    "exit_code": code,
                    "duration_ms": _duration_ms(job.started_at, job.finished_at),
                    "log_path": str(job.log_path),
                },
            )
        )
        self._emit_workspace_changes(job)

    def _get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"unknown background job: {job_id}")
            return self._jobs[job_id]

    def _select(self, job_ids: Optional[list[str]]) -> list[Job]:
        with self._lock:
            if job_ids:
                return [self._jobs[jid] for jid in job_ids if jid in self._jobs]
            return [job for job in self._jobs.values() if job.status == "running"]

    def _emit_workspace_changes(self, job: Job) -> None:
        changes = diff_workspace(job.workspace_before, snapshot_workspace(job.workspace_root))
        if not changes:
            return
        self.sink.emit(
            Event(
                "workspace_changes_detected",
                {
                    "source_kind": job.kind,
                    "job_id": job.id,
                    "changes": changes,
                },
            )
        )


def _preview(command: str) -> str:
    command = " ".join(command.strip().split())
    return command if len(command) <= 48 else command[:48] + "..."


def _command_text(command: str | Sequence[str]) -> str:
    if isinstance(command, str):
        return command
    return " ".join(str(part) for part in command)


def _duration_ms(started_at: float, finished_at: Optional[float]) -> int:
    end = finished_at if finished_at is not None else time.time()
    return int((end - started_at) * 1000)
