from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from mini_agent_lab.agent import Session
from mini_agent_lab.provider import Message


@dataclass(frozen=True)
class SessionInfo:
    id: str
    path: Path
    messages: int
    updated_at: float


class SessionStore:
    def __init__(self, directory: str | Path = ".sessions") -> None:
        self.directory = Path(directory)

    def new_id(self, label: str = "session") -> str:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", label.strip()).strip("-") or "session"
        return time.strftime("%Y%m%d-%H%M%S") + "-" + safe

    def path_for(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.jsonl"

    def save(self, session_id: str, session: Session) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(session_id)
        tmp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.directory,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as f:
                tmp_name = f.name
                for message in session.messages:
                    f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            if tmp_name and Path(tmp_name).exists():
                Path(tmp_name).unlink()
        return path

    def load(self, session_id: str) -> Session:
        path = self.path_for(session_id)
        if not path.exists():
            raise FileNotFoundError(f"no session {session_id!r} at {path}")
        session = Session()
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                session.messages.append(Message.from_dict(json.loads(line)))
        return session

    def list(self) -> list[SessionInfo]:
        if not self.directory.exists():
            return []
        infos = []
        for path in sorted(self.directory.glob("*.jsonl")):
            messages = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            infos.append(
                SessionInfo(
                    id=path.stem,
                    path=path,
                    messages=messages,
                    updated_at=path.stat().st_mtime,
                )
            )
        return sorted(infos, key=lambda item: item.updated_at, reverse=True)

    def delete(self, session_id: str) -> None:
        path = self.path_for(session_id)
        if path.exists():
            path.unlink()

    def rename(self, session_id: str, label: str) -> str:
        path = self.path_for(session_id)
        if not path.exists():
            raise FileNotFoundError(f"no session {session_id!r}")
        new_id = self.new_id(label)
        new_path = self.path_for(new_id)
        path.rename(new_path)
        return new_id
