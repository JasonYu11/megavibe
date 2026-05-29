from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the complete Megawave dashboard promo video package.")
    parser.add_argument("--record-only", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if not args.compose_only and not args.verify_only:
        run(["python", "-m", "promo.record"], "record")
    if not args.record_only and not args.verify_only:
        run(["python", "-m", "promo.compose"], "compose")
    if not args.record_only and not args.compose_only:
        run(["python", "-m", "promo.verify_outputs"], "verify")


def run(cmd: list[str], label: str) -> None:
    try:
        subprocess.run(cmd, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"{label} stage failed with exit code {exc.returncode}") from exc


if __name__ == "__main__":
    main()
