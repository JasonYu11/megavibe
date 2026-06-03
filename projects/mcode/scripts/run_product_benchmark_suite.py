from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_agent_ui_benchmarks import build_spec_acceptance, render_markdown_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the product-level 8 task benchmark suite.")
    parser.add_argument("--spec", default=str(ROOT / "benchmark_specs" / "agent_ui_v1.json"))
    parser.add_argument("--root", default="", help="Output root for benchmark artifacts")
    parser.add_argument("--case-timeout", type=int, default=30, help="Timeout seconds per agent case")
    parser.add_argument("--dry-run", action="store_true", help="Only validate the benchmark suite definition")
    parser.add_argument("--skip-live", action="store_true", help="Skip external live simulation runner")
    args = parser.parse_args()

    started = time.time()
    run_root = Path(args.root).expanduser().resolve() if args.root else _default_root()
    run_root.mkdir(parents=True, exist_ok=True)
    spec_path = Path(args.spec).expanduser().resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    checks = [
        {
            "id": "benchmark_spec",
            "command": ["python3", "scripts/validate_product_benchmarks.py", "--spec", str(spec_path)],
        },
    ]
    if not args.dry_run:
        checks.append(
            {
                "id": "agent_core_cases",
                "command": [
                    "python3",
                    "scripts/run_agent_ui_benchmarks.py",
                    "--spec",
                    args.spec,
                    "--tier",
                    "all",
                    "--root",
                    str(run_root / "agent_cases"),
                    "--case-timeout",
                    str(args.case_timeout),
                ],
            }
        )
    if not args.skip_live and not args.dry_run:
        checks.append(
            {
                "id": "live_simulation_cases",
                "command": [
                    "python3",
                    "scripts/live_agent_simulation_test.py",
                    "--root",
                    str(run_root / "live_simulation"),
                ],
            }
        )

    results = [run_check(check) for check in checks]
    case_reports = build_dry_case_reports(spec) if args.dry_run else []
    report = {
        "name": "mcode-product-benchmarks",
        "run_root": str(run_root),
        "spec": str(spec_path),
        "started_at": started,
        "elapsed_seconds": round(time.time() - started, 2),
        "dry_run": args.dry_run,
        "skip_live": args.skip_live,
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "results": results,
        "case_reports": case_reports,
    }
    report_path = run_root / "product_benchmark_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = run_root / "product_benchmark_report.md"
    markdown_path.write_text(render_product_markdown(report), encoding="utf-8")
    print(json.dumps(_brief(report, report_path), ensure_ascii=False, indent=2))
    return 0 if report["failed"] == 0 else 1


def build_dry_case_reports(spec: dict[str, Any]) -> list[dict[str, Any]]:
    reports = []
    for case in spec.get("cases", []):
        acceptance = build_spec_acceptance(case, executed=False)
        reports.append(
            {
                "id": case.get("id", ""),
                "tier": case.get("tier", ""),
                "category": case.get("category", ""),
                "product_requirement": case.get("product_requirement", ""),
                "passed": True,
                "dry_run": True,
                "external_runner": bool(case.get("external_runner")),
                "prompt_preview": str(case.get("prompt", ""))[:500],
                "acceptance": acceptance,
            }
        )
    return reports


def render_product_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report.get('name', 'product benchmarks')} Report",
        "",
        f"- Dry run: {report.get('dry_run')}",
        f"- Skip live: {report.get('skip_live')}",
        f"- Checks passed: {report.get('passed', 0)}/{report.get('total', 0)}",
        f"- Run root: `{report.get('run_root', '')}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Exit |",
        "| --- | --- | --- |",
    ]
    for item in report.get("results", []):
        lines.append(f"| {item.get('id', '')} | {'PASS' if item.get('passed') else 'FAIL'} | {item.get('exit_code', '')} |")
    case_reports = report.get("case_reports", [])
    if case_reports:
        lines.extend(["", "## Dry-Run Case Matrix", ""])
        lines.append(
            render_markdown_report(
                {
                    "name": "agent_ui_v1",
                    "tier": "dry-run",
                    "total": len(case_reports),
                    "passed": sum(1 for item in case_reports if item.get("passed")),
                    "failed": sum(1 for item in case_reports if not item.get("passed")),
                    "run_root": report.get("run_root", ""),
                    "results": case_reports,
                }
            ).strip()
        )
    lines.append("")
    return "\n".join(lines)


def run_check(check: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            check["command"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output = proc.stdout or ""
        exit_code = proc.returncode
    except Exception as exc:
        output = f"error: {type(exc).__name__}: {exc}"
        exit_code = -1
    return {
        "id": check["id"],
        "command": check["command"],
        "passed": exit_code == 0,
        "exit_code": exit_code,
        "elapsed_seconds": round(time.time() - started, 2),
        "output_tail": output[-5000:],
    }


def _brief(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    return {
        "name": report["name"],
        "report": str(report_path),
        "markdown": str(report_path.with_suffix(".md")),
        "skip_live": report["skip_live"],
        "dry_run": report["dry_run"],
        "total": report["total"],
        "passed": report["passed"],
        "failed": report["failed"],
        "failed_checks": [item["id"] for item in report["results"] if not item["passed"]],
    }


def _default_root() -> Path:
    return ROOT.parent / "product_benchmark_runs" / time.strftime("%Y%m%d-%H%M%S")


if __name__ == "__main__":
    raise SystemExit(main())
