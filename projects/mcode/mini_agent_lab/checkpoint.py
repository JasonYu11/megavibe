from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Union

from mini_agent_lab.change import Change


@dataclass(frozen=True)
class Checkpoint:
    id: str
    path: str
    before: Optional[str]
    after: str
    kind: str
    tool_name: str
    arguments: dict
    created_at: str


class CheckpointStore:
    def __init__(self, directory: Union[str, Path] = ".checkpoints") -> None:
        self.directory = Path(directory)

    def save(self, change: Change, tool_name: str, arguments: dict) -> Checkpoint:
        self.directory.mkdir(parents=True, exist_ok=True)
        checkpoint_id = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        cp = Checkpoint(
            id=checkpoint_id,
            path=change.path,
            before=change.before,
            after=change.after,
            kind=change.kind,
            tool_name=tool_name,
            arguments=arguments,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        path = self.directory / f"{checkpoint_id}.json"
        path.write_text(json.dumps(asdict(cp), ensure_ascii=False, indent=2), encoding="utf-8")
        return cp

    def list(self) -> list[Checkpoint]:
        if not self.directory.exists():
            return []
        checkpoints = []
        for path in sorted(self.directory.glob("*.json")):
            checkpoints.append(self._load(path))
        return checkpoints

    def restore(self, checkpoint_id: str) -> Checkpoint:
        cp_path = self.directory / f"{checkpoint_id}.json"
        cp = self._load(cp_path)
        target = Path(cp.path)
        if not target.is_absolute():
            target = self.directory.parent / target
        if cp.before is None:
            if target.exists() and target.is_file():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(cp.before, encoding="utf-8")
        return cp

    @staticmethod
    def _load(path: Path) -> Checkpoint:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Checkpoint(**raw)
