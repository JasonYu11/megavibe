from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.safety import SafetyGate
from mini_agent_lab.tool import default_registry


def main() -> int:
    registry = default_registry()
    gate = SafetyGate()
    examples = [
        ("read_file", {"path": "README.md"}),
        ("write_file", {"path": "notes.txt", "content": "hello"}),
        ("edit_file", {"path": "notes.txt", "old_string": "a", "new_string": "b"}),
        ("write_file", {"path": "/private/tmp/mcode-outside.txt", "content": "hello"}),
        ("write_file", {"path": "/etc/mcode-denied.txt", "content": "hello"}),
        ("bash", {"command": "printf ok"}),
        ("bash", {"command": "sleep 10", "run_in_background": True}),
        ("bash_output", {"job_id": "bash-1"}),
        ("wait", {"job_ids": ["bash-1"], "timeout_seconds": 1}),
        ("kill_shell", {"job_id": "bash-1"}),
        ("bash", {"command": "git push origin main"}),
        ("bash", {"command": "sudo reboot"}),
        ("bash", {"command": "rm -rf /"}),
    ]

    for name, args in examples:
        tool = registry.get(name)
        result = gate.check(name, args, tool.read_only)
        print(f"{name:10} {args!r}")
        print(f"  -> {result.decision}: {result.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
