from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


CHECKS = [
    {
        "id": "backend_ui_helpers",
        "description": "Project/session/event/change-review backend helpers",
        "command": ["python3", "tests/test_ui_backend.py"],
        "cwd": ROOT,
    },
    {
        "id": "settings_api",
        "description": "Settings and app-local API key storage endpoints",
        "command": ["python3", "mcode-ui/backend/test_settings_api.py"],
        "cwd": ROOT,
    },
    {
        "id": "python_tool_events",
        "description": "python_run execution, headless env, and workspace change detection",
        "command": ["python3", "tests/test_python_run_tool.py"],
        "cwd": ROOT,
    },
    {
        "id": "bash_tool_events",
        "description": "bash foreground/background events and workspace change detection",
        "command": ["python3", "tests/test_bash_events.py"],
        "cwd": ROOT,
    },
    {
        "id": "run_recorder",
        "description": "RunRecorder event and summary persistence",
        "command": ["python3", "tests/test_run_recorder.py"],
        "cwd": ROOT,
    },
    {
        "id": "tool_outcomes",
        "description": "Tool success/error/block/truncation outcomes",
        "command": ["python3", "tests/test_tool_outcomes.py"],
        "cwd": ROOT,
    },
    {
        "id": "product_benchmark_spec",
        "description": "Product benchmark suite has the required agent regression cases",
        "command": ["python3", "scripts/validate_product_benchmarks.py"],
        "cwd": ROOT,
    },
    {
        "id": "product_benchmark_dry_run",
        "description": "Benchmark dry-run produces a JSON/Markdown case matrix without model API calls",
        "command": ["python3", "scripts/run_product_benchmark_suite.py", "--dry-run"],
        "cwd": ROOT,
    },
    {
        "id": "frontend_layout_dock_tests",
        "description": "Workbench layout computation and dock pane interaction tests",
        "command": ["npm", "run", "test", "--", "layoutState.test.ts", "WorkspaceDock.test.tsx"],
        "cwd": ROOT / "mcode-ui" / "frontend",
    },
    {
        "id": "frontend_tests",
        "description": "React UI component and event mapping tests",
        "command": ["npm", "run", "test", "--", "--run"],
        "cwd": ROOT / "mcode-ui" / "frontend",
    },
    {
        "id": "frontend_build",
        "description": "TypeScript typecheck and Vite production build",
        "command": ["npm", "run", "build"],
        "cwd": ROOT / "mcode-ui" / "frontend",
    },
    {
        "id": "macos_app_build",
        "description": "Build Mcode.app with bundled frontend/backend resources",
        "command": ["mcode-ui/macos/build_app.sh"],
        "cwd": ROOT,
    },
    {
        "id": "macos_plist_lint",
        "description": "Validate Mcode.app Info.plist",
        "command": ["plutil", "-lint", "mcode-ui/dist/Mcode.app/Contents/Info.plist"],
        "cwd": ROOT,
    },
    {
        "id": "macos_codesign_verify",
        "description": "Verify ad-hoc signed Mcode.app bundle",
        "command": ["codesign", "--verify", "--deep", "--strict", "mcode-ui/dist/Mcode.app"],
        "cwd": ROOT,
    },
    {
        "id": "python_compile",
        "description": "Python syntax check for backend and core agent modules",
        "command": [
            "python3",
            "-m",
            "compileall",
            "mini_agent_lab",
            "mcode-ui/backend",
            "scripts/agent_chat.py",
            "scripts/run_agent_ui_benchmarks.py",
            "scripts/validate_product_benchmarks.py",
            "scripts/run_product_benchmark_suite.py",
            "scripts/live_agent_simulation_test.py",
        ],
        "cwd": ROOT,
        "env": {"PYTHONPYCACHEPREFIX": "/private/tmp/mcode-pyc"},
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run product-level Mcode App acceptance gates.")
    parser.add_argument("--report", default="", help="Optional report JSON path")
    parser.add_argument("--timeout", type=int, default=180, help="Timeout seconds per check")
    args = parser.parse_args()

    started = time.time()
    results = [run_check(check, timeout=args.timeout) for check in CHECKS]
    report = {
        "name": "mcode-product-acceptance",
        "root": str(ROOT),
        "started_at": started,
        "elapsed_seconds": round(time.time() - started, 2),
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "results": results,
    }
    report_path = Path(args.report).expanduser().resolve() if args.report else ROOT / "notes" / "product_acceptance_latest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(_brief(report, report_path), ensure_ascii=False, indent=2))
    return 0 if report["failed"] == 0 else 1


def run_check(check: dict[str, Any], timeout: int) -> dict[str, Any]:
    started = time.time()
    env = None
    if check.get("env"):
        import os

        env = os.environ.copy()
        env.update(check["env"])
    try:
        proc = subprocess.run(
            check["command"],
            cwd=check["cwd"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        output = proc.stdout or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        output += f"\nerror: timed out after {timeout}s"
        exit_code = -1
    except Exception as exc:
        output = f"error: {type(exc).__name__}: {exc}"
        exit_code = -1
    return {
        "id": check["id"],
        "description": check["description"],
        "command": check["command"],
        "cwd": str(check["cwd"]),
        "passed": exit_code == 0,
        "exit_code": exit_code,
        "elapsed_seconds": round(time.time() - started, 2),
        "output_tail": output[-3000:],
    }


def _brief(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    return {
        "name": report["name"],
        "report": str(report_path),
        "total": report["total"],
        "passed": report["passed"],
        "failed": report["failed"],
        "failed_checks": [item["id"] for item in report["results"] if not item["passed"]],
    }


if __name__ == "__main__":
    raise SystemExit(main())
