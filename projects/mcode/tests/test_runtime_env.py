"""Tests for project runtime discovery and overrides."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.runtime_env import discover_runtime, save_runtime_override


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _touch_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_project_venv_preferred() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        python = root / ".venv" / "bin" / "python"
        _touch_executable(python)
        runtime = discover_runtime(root)
        _assert(runtime.python == str(python.resolve()), "project .venv python is selected first")
        _assert(runtime.python_source == "project", "project runtime source is reported")


def test_runtime_override_is_persisted() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        custom = root / "custom-python"
        _touch_executable(custom)
        runtime = save_runtime_override(root, python=str(custom), shell="/bin/bash")
        raw = json.loads((root / "mcode-config.json").read_text(encoding="utf-8"))
        _assert(runtime.python == str(custom.resolve()), "configured python is selected")
        _assert(raw["runtime"]["python"] == str(custom.resolve()), "configured python is written")
        _assert(raw["runtime"]["shell"] == "/bin/bash", "configured shell is written")


def test_anaconda_candidate_detected_when_available() -> None:
    runtime = discover_runtime(Path.cwd())
    candidates = [item.path for item in runtime.candidates]
    anaconda = Path("/Applications/anaconda3/bin/python")
    if anaconda.exists():
        _assert(str(anaconda.resolve()) in candidates, "Anaconda python is discovered")
    else:
        _assert(bool(runtime.python), "runtime falls back when Anaconda is absent")


if __name__ == "__main__":
    os.chdir(ROOT)
    test_project_venv_preferred()
    test_runtime_override_is_persisted()
    test_anaconda_candidate_detected_when_available()
    print("All runtime env tests passed.")
