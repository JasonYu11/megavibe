from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.tool.builtin import default_registry, pretty_schemas


USAGE = """Usage:
  python3 scripts/tool_demo.py --schemas
  python3 scripts/tool_demo.py '<tool-call-json>'
  python3 scripts/tool_demo.py read_file '{"path":"README.md"}'

Tool call JSON format:
  {"name":"read_file","arguments":{"path":"README.md","offset":0,"limit":20}}
"""


def main() -> int:
    registry = default_registry()

    if len(sys.argv) == 2 and sys.argv[1] == "--schemas":
        print(pretty_schemas(registry))
        return 0

    if len(sys.argv) == 2:
        raw = json.loads(sys.argv[1])
        name = raw["name"]
        arguments = raw.get("arguments", {})
    elif len(sys.argv) == 3:
        name = sys.argv[1]
        arguments = json.loads(sys.argv[2])
    else:
        print(USAGE)
        return 2

    tool = registry.get(name)
    try:
        result = tool.execute(arguments)
    except Exception as exc:
        print(f"error: {exc}")
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
