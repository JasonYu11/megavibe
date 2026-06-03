from __future__ import annotations

import os
import pty
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TerminalSession:
    id: str
    project_root: str
    shell: str
    kind: str
    cwd: str
    master_fd: int
    process: subprocess.Popen
    created_at: float
    updated_at: float
    output: str = ""
    exit_code: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class TerminalManager:
    def __init__(self, max_buffer_chars: int = 200_000) -> None:
        self.max_buffer_chars = max_buffer_chars
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def create(self, project_root: Path, shell: str = "", kind: str = "python", python: str = "") -> dict[str, Any]:
        root = project_root.resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"invalid project root: {root}")
        terminal_kind = kind.strip().lower() or "python"
        shell_path = shell.strip() or os.environ.get("SHELL") or "/bin/zsh"
        python_path = python.strip()
        if terminal_kind == "python":
            executable = python_path or "python3"
            argv = [executable, "-i"]
        elif terminal_kind == "shell":
            if not Path(shell_path).exists():
                raise ValueError(f"shell does not exist: {shell_path}")
            executable = shell_path
            argv = [shell_path, "-l"]
        else:
            raise ValueError(f"unsupported terminal kind: {kind}")

        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")
        env["PWD"] = str(root)
        state_dir = root / ".mcode-ui"
        state_dir.mkdir(parents=True, exist_ok=True)
        env["HISTFILE"] = str(state_dir / "terminal_history")
        process = subprocess.Popen(
            argv,
            cwd=str(root),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave_fd)
        session = TerminalSession(
            id=f"term-{uuid.uuid4().hex[:10]}",
            project_root=str(root),
            shell=shell_path,
            kind=terminal_kind,
            cwd=str(root),
            master_fd=master_fd,
            process=process,
            created_at=time.time(),
            updated_at=time.time(),
        )
        with self._lock:
            self._sessions[session.id] = session
        thread = threading.Thread(target=self._reader, args=(session,), daemon=True)
        thread.start()
        return self.snapshot(session)

    def list(self, project_root: Path) -> list[dict[str, Any]]:
        root = str(project_root.resolve())
        with self._lock:
            sessions = [session for session in self._sessions.values() if session.project_root == root]
        return [self.snapshot(session, include_output=False) for session in sessions]

    def read(self, terminal_id: str, cursor: int = 0) -> dict[str, Any]:
        session = self._get(terminal_id)
        with session.lock:
            output = session.output
            safe_cursor = max(0, min(cursor, len(output)))
            chunk = output[safe_cursor:]
            next_cursor = len(output)
        snap = self.snapshot(session, include_output=False)
        return {**snap, "chunk": chunk, "cursor": next_cursor}

    def write(self, terminal_id: str, data: str) -> dict[str, Any]:
        session = self._get(terminal_id)
        if session.process.poll() is not None:
            raise RuntimeError("terminal is not running")
        os.write(session.master_fd, data.encode("utf-8", errors="replace"))
        session.updated_at = time.time()
        return self.snapshot(session, include_output=False)

    def close(self, terminal_id: str) -> dict[str, Any]:
        session = self._get(terminal_id)
        if session.process.poll() is None:
            try:
                os.killpg(session.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        session.exit_code = session.process.poll()
        session.updated_at = time.time()
        return self.snapshot(session, include_output=False)

    def snapshot(self, session: TerminalSession, include_output: bool = True) -> dict[str, Any]:
        exit_code = session.process.poll()
        if exit_code is not None:
            session.exit_code = exit_code
        with session.lock:
            output_len = len(session.output)
            tail = session.output[-4000:]
        data = {
            "id": session.id,
            "project_root": session.project_root,
            "shell": session.shell,
            "kind": session.kind,
            "cwd": session.cwd,
            "pid": session.process.pid,
            "running": exit_code is None,
            "exit_code": exit_code,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "cursor": output_len,
        }
        if include_output:
            data["output"] = tail
        return data

    def _reader(self, session: TerminalSession) -> None:
        while True:
            try:
                data = os.read(session.master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            text = data.decode("utf-8", errors="replace")
            with session.lock:
                session.output = (session.output + text)[-self.max_buffer_chars :]
                session.updated_at = time.time()
        session.exit_code = session.process.poll()
        session.updated_at = time.time()
        try:
            os.close(session.master_fd)
        except OSError:
            pass

    def _get(self, terminal_id: str) -> TerminalSession:
        with self._lock:
            session = self._sessions.get(terminal_id)
        if session is None:
            raise KeyError(terminal_id)
        return session
