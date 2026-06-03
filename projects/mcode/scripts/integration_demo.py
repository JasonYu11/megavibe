from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.jobs import JobManager
from mini_agent_lab.safety import SafetyGate
from mini_agent_lab.tool import default_registry


def call(registry, name: str, arguments: dict) -> str:
    tool = registry.get(name)
    return tool.execute(arguments)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    jobs = JobManager()
    registry = default_registry(jobs)
    gate = SafetyGate()

    section("1. Explore project: ls -> glob -> grep -> read_file")
    print(call(registry, "ls", {"path": "."}))
    print("\n-- python files --")
    print(call(registry, "glob", {"pattern": "mini_agent_lab/**/*.py", "limit": 8}))
    print("\n-- find Agent class --")
    print(call(registry, "grep", {"pattern": "class Agent", "path_glob": "mini_agent_lab/**/*.py", "limit": 5}))
    print("\n-- read agent.py --")
    print(call(registry, "read_file", {"path": "mini_agent_lab/agent/agent.py", "limit": 18}))

    section("2. File workflow: write_file -> read_file -> edit_file -> read_file")
    test_path = Path("notes/integration-demo.txt")
    print(call(registry, "write_file", {"path": str(test_path), "content": "alpha\nbeta\ngamma\n"}))
    print(call(registry, "read_file", {"path": str(test_path)}))
    print(call(registry, "edit_file", {"path": str(test_path), "old_string": "beta", "new_string": "BETA"}))
    print(call(registry, "read_file", {"path": str(test_path)}))

    section("3. Background bash: bash -> bash_output -> wait")
    started = call(
        registry,
        "bash",
        {
            "command": "for i in 1 2 3; do echo combo-$i; sleep 1; done",
            "run_in_background": True,
        },
    )
    print(started)
    match = re.search(r"bash-\d+", started)
    if not match:
        raise RuntimeError("could not parse job id")
    job_id = match.group(0)
    time.sleep(1.2)
    print(call(registry, "bash_output", {"job_id": job_id}))
    print(call(registry, "wait", {"job_ids": [job_id], "timeout_seconds": 5}))

    section("4. Safety decisions")
    examples = [
        ("read_file", {"path": "README.md"}),
        ("write_file", {"path": "notes/inside.txt", "content": "ok"}),
        ("write_file", {"path": "/private/tmp/outside.txt", "content": "ok"}),
        ("write_file", {"path": "/etc/denied.txt", "content": "no"}),
        ("bash", {"command": "printf ok"}),
        ("bash", {"command": "git push origin main"}),
    ]
    for name, args in examples:
        tool = registry.get(name)
        result = gate.check(name, args, tool.read_only)
        print(f"{name:10} -> {result.decision:5} | {result.reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
