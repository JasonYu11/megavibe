from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.run_view import find_latest_run_file, render_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Mcode .summary.json status snapshot.")
    parser.add_argument("path", nargs="?", help="Path to a .summary.json file. Defaults to the latest file in .runs.")
    parser.add_argument("--runs-dir", default=".runs", help="Run directory used when path is omitted.")
    args = parser.parse_args()

    try:
        path = Path(args.path) if args.path else find_latest_run_file(args.runs_dir, ".summary.json")
        print(render_summary(path))
    except (FileNotFoundError, ValueError, OSError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
