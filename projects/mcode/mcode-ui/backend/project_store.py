from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("MCODE_RUNTIME_ROOT", "")).expanduser() if os.environ.get("MCODE_RUNTIME_ROOT") else BACKEND_ROOT.parents[1]
APP_DATA_DIR = Path(os.environ.get("MCODE_APP_DATA_DIR", "")).expanduser() if os.environ.get("MCODE_APP_DATA_DIR") else REPO_ROOT / ".mcode-ui"
STORE_PATH = APP_DATA_DIR / "projects.json"
DEFAULT_PROJECT_ID = "mcode"
LEGACY_DEFAULT_PROJECT_ID = "mini-agent-lab"


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    root_path: str
    created_at: float


def default_project() -> Project:
    return Project(
        id=DEFAULT_PROJECT_ID,
        name="Mcode",
        root_path=str(REPO_ROOT),
        created_at=REPO_ROOT.stat().st_ctime,
    )


class ProjectStore:
    def __init__(self, path: str | Path = STORE_PATH) -> None:
        self.path = Path(path)

    def list(self) -> list[Project]:
        projects = self._read()
        if not projects:
            projects = [default_project()]
            self._write(projects)
        return projects

    def get(self, project_id: str) -> Project:
        for project in self.list():
            if project.id == project_id:
                return project
            if project_id == LEGACY_DEFAULT_PROJECT_ID and project.id == DEFAULT_PROJECT_ID:
                return project
        raise KeyError(f"unknown project: {project_id}")

    def create(self, *, name: str, root_path: str) -> tuple[Project, bool]:
        root = Path(root_path).expanduser().resolve(strict=False)
        if not root.exists() or not root.is_dir():
            raise ValueError(f"project path does not exist or is not a directory: {root}")
        projects = self.list()
        for project in projects:
            if project_root(project) == root:
                return project, False
        project_id = _safe_id(name or root.name)
        existing = {project.id for project in projects}
        base = project_id
        index = 2
        while project_id in existing:
            project_id = f"{base}-{index}"
            index += 1
        project = Project(id=project_id, name=name or root.name, root_path=str(root), created_at=time.time())
        projects.append(project)
        self._write(projects)
        return project, True

    def _read(self) -> list[Project]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        out = []
        for item in raw.get("projects", []):
            if isinstance(item, dict) and item.get("id") and item.get("root_path"):
                project = Project(
                    id=str(item["id"]),
                    name=str(item.get("name") or item["id"]),
                    root_path=str(item["root_path"]),
                    created_at=float(item.get("created_at", 0.0) or 0.0),
                )
                if project.id == LEGACY_DEFAULT_PROJECT_ID and project_root(project) == REPO_ROOT:
                    project = Project(
                        id=DEFAULT_PROJECT_ID,
                        name="Mcode",
                        root_path=project.root_path,
                        created_at=project.created_at,
                    )
                out.append(project)
        return out

    def _write(self, projects: list[Project]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"projects": [asdict(project) for project in projects]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def project_root(project: Project) -> Path:
    return Path(project.root_path).expanduser().resolve(strict=False)


def ensure_inside_project(project: Project, rel_path: str = "") -> Path:
    root = project_root(project)
    target = root / rel_path if rel_path else root
    target = target.expanduser().resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"path escapes project root: {rel_path}") from exc
    return target


def project_to_dict(project: Project) -> dict[str, Any]:
    return asdict(project)


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return safe or "project"
