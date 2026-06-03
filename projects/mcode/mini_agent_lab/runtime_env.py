from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from mini_agent_lab.app_config import AppConfig, load_app_config


@dataclass(frozen=True)
class RuntimeCandidate:
    path: str
    label: str
    source: str
    selected: bool = False


@dataclass(frozen=True)
class RuntimeSelection:
    shell: str
    python: str
    python_source: str
    candidates: tuple[RuntimeCandidate, ...]


def discover_runtime(root: str | Path, app_config: Optional[AppConfig] = None) -> RuntimeSelection:
    root_path = Path(root).resolve()
    app_config = app_config or load_app_config(root_path / "mcode-config.json")
    configured_python = app_config.runtime.python.strip()
    shell = app_config.runtime.shell.strip() or "/bin/zsh"

    candidates: list[RuntimeCandidate] = []
    if configured_python:
        candidates.append(_candidate(configured_python, "Configured Python", "configured"))

    candidates.extend(_project_candidates(root_path))
    if app_config.runtime.python_preference == "conda":
        candidates.extend(_conda_candidates())
    candidates.extend(_system_candidates())

    unique = _dedupe_existing(candidates)
    selected = _select_python(configured_python, unique)
    selected_path = selected.path if selected else sys.executable
    selected_source = selected.source if selected else "system"
    marked = tuple(
        RuntimeCandidate(item.path, item.label, item.source, selected=Path(item.path) == Path(selected_path))
        for item in unique
    )
    return RuntimeSelection(shell=shell, python=selected_path, python_source=selected_source, candidates=marked)


def runtime_to_dict(runtime: RuntimeSelection) -> dict[str, Any]:
    return {
        "shell": runtime.shell,
        "python": runtime.python,
        "python_source": runtime.python_source,
        "candidates": [
            {"path": item.path, "label": item.label, "source": item.source, "selected": item.selected}
            for item in runtime.candidates
        ],
    }


def save_runtime_override(root: str | Path, python: Optional[str] = None, shell: Optional[str] = None) -> RuntimeSelection:
    root_path = Path(root).resolve()
    config_path = root_path / "mcode-config.json"
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    runtime = dict(raw.get("runtime") or {})

    if python is not None:
        cleaned = python.strip()
        if cleaned:
            path = Path(cleaned).expanduser().resolve()
            if not path.exists() or not path.is_file():
                raise ValueError(f"python does not exist: {cleaned}")
            if not os.access(path, os.X_OK):
                raise ValueError(f"python is not executable: {cleaned}")
            runtime["python"] = str(path)
        else:
            runtime["python"] = ""
    if shell is not None:
        cleaned_shell = shell.strip()
        if cleaned_shell:
            runtime["shell"] = cleaned_shell

    raw["runtime"] = runtime
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(config_path, raw)
    return discover_runtime(root_path)


def _project_candidates(root: Path) -> list[RuntimeCandidate]:
    return [
        _candidate(root / ".venv" / "bin" / "python", "Project .venv", "project"),
        _candidate(root / "venv" / "bin" / "python", "Project venv", "project"),
        _candidate(root / "env" / "bin" / "python", "Project env", "project"),
    ]


def _conda_candidates() -> list[RuntimeCandidate]:
    rows: list[RuntimeCandidate] = []
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        rows.append(_candidate(Path(conda_prefix) / "bin" / "python", "Active Conda", "conda"))

    conda = shutil.which("conda") or "/Applications/anaconda3/bin/conda"
    if Path(conda).exists():
        rows.append(_candidate(Path(conda).parent / "python", "Conda on PATH", "conda"))
        try:
            proc = subprocess.run(
                [conda, "info", "--base"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
            base = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
            if base:
                rows.append(_candidate(Path(base) / "bin" / "python", "Conda base", "conda"))
        except (OSError, subprocess.SubprocessError):
            pass

    for path in (
        "/Applications/anaconda3/bin/python",
        "/Applications/miniconda3/bin/python",
        "/opt/homebrew/anaconda3/bin/python",
        "/opt/homebrew/miniconda3/bin/python",
        "/opt/homebrew/Caskroom/miniconda/base/bin/python",
        str(Path.home() / "anaconda3" / "bin" / "python"),
        str(Path.home() / "miniconda3" / "bin" / "python"),
    ):
        rows.append(_candidate(path, "Conda candidate", "conda"))
    return rows


def _system_candidates() -> list[RuntimeCandidate]:
    rows = [_candidate(sys.executable, "Current Python", "system")]
    path_python = shutil.which("python3")
    if path_python:
        rows.append(_candidate(path_python, "python3 on PATH", "system"))
    path_python = shutil.which("python")
    if path_python:
        rows.append(_candidate(path_python, "python on PATH", "system"))
    return rows


def _select_python(configured: str, candidates: list[RuntimeCandidate]) -> Optional[RuntimeCandidate]:
    if configured:
        configured_path = Path(configured).expanduser().resolve()
        for item in candidates:
            if Path(item.path) == configured_path:
                return item
    for source in ("project", "conda", "system"):
        for item in candidates:
            if item.source == source:
                return item
    return candidates[0] if candidates else None


def _candidate(path: str | Path, label: str, source: str) -> RuntimeCandidate:
    return RuntimeCandidate(str(Path(path).expanduser()), label, source)


def _dedupe_existing(candidates: list[RuntimeCandidate]) -> list[RuntimeCandidate]:
    seen: set[str] = set()
    rows: list[RuntimeCandidate] = []
    for item in candidates:
        path = Path(item.path).expanduser()
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path)
        if resolved in seen or not path.exists() or not path.is_file():
            continue
        seen.add(resolved)
        rows.append(RuntimeCandidate(resolved, item.label, item.source))
    return rows


def _atomic_write_json(path: Path, raw: dict[str, Any]) -> None:
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_name = f.name
            json.dump(raw, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()
