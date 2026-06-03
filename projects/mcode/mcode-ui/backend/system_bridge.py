from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Any


def pick_folder() -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"cancelled": True, "reason": "folder picker is only implemented for macOS"}
    script = 'POSIX path of (choose folder with prompt "选择 Mcode 项目文件夹")'
    result = subprocess.run(
        ["osascript", "-e", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        reason = result.stderr.strip() or "folder selection cancelled"
        return {"cancelled": True, "reason": reason}
    root = Path(result.stdout.strip()).expanduser().resolve(strict=False)
    if not root.exists() or not root.is_dir():
        return {"cancelled": True, "reason": f"selected path is not a directory: {root}"}
    return {"cancelled": False, "root_path": str(root), "name": root.name}


def open_file(path: Path, app_name: str = "cursor") -> dict[str, Any]:
    target = path.expanduser().resolve(strict=False)
    if not target.exists():
        return {"ok": False, "reason": f"file does not exist: {target}"}
    app = (app_name or "cursor").strip().lower()
    if platform.system() == "Darwin":
        if app == "cursor":
            command = ["open", "-a", "Cursor", str(target)]
        elif app in {"vscode", "vs code", "visual studio code"}:
            command = ["open", "-a", "Visual Studio Code", str(target)]
        elif app in {"finder", "reveal"}:
            command = ["open", "-R", str(target)]
        elif app in {"system", "default"}:
            command = ["open", str(target)]
        else:
            command = ["open", "-a", app_name, str(target)]
    else:
        command = ["xdg-open", str(target)]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    return {
        "ok": result.returncode == 0,
        "command": command,
        "reason": result.stderr.strip() or result.stdout.strip(),
    }
