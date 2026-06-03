from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.jobs import JobManager
from mini_agent_lab.tool import default_registry


def main() -> int:
    jobs = JobManager()
    registry = default_registry(jobs)

    bash = registry.get("bash")
    bash_output = registry.get("bash_output")
    wait = registry.get("wait")

    started = bash.execute(
        {
            "command": "for i in 1 2 3; do echo tick-$i; sleep 1; done",
            "run_in_background": True,
        }
    )
    print(started)
    match = re.search(r"bash-\d+", started)
    if not match:
        print("failed to parse job id")
        return 1
    job_id = match.group(0)

    time.sleep(1.2)
    print("\n--- bash_output ---")
    print(bash_output.execute({"job_id": job_id}))

    print("\n--- wait ---")
    print(wait.execute({"job_ids": [job_id], "timeout_seconds": 5}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
