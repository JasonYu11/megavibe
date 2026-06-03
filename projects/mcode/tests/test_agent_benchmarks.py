"""Tests for the product-level agent benchmark suite."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_product_benchmark_suite import build_dry_case_reports
from scripts.validate_product_benchmarks import validate_spec


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def test_benchmark_spec_covers_required_regressions() -> None:
    spec = json.loads((ROOT / "benchmark_specs" / "agent_ui_v1.json").read_text(encoding="utf-8"))
    reports = build_dry_case_reports(spec)
    by_requirement = {item["product_requirement"]: item for item in reports}

    _assert(validate_spec(spec) == [], "benchmark spec validates")
    _assert(len(reports) == spec["required_case_count"], "dry case reports match required count")
    _assert(by_requirement["创建并运行 Python 脚本"]["acceptance"]["tools_used"].count("python_run") == 1, "python script case requires python_run")
    _assert(by_requirement["附件处理"]["acceptance"]["tools_used"].count("read_attachment") == 1, "attachment case requires read_attachment")
    _assert("plan_pending" in by_requirement["Plan 执行"]["acceptance"]["ui_key_events"], "plan case requires plan_pending")
    _assert(by_requirement["权限审批"]["acceptance"]["approval_triggered"], "approval case is marked as approval-triggering")
    _assert("read_file" in by_requirement["失败恢复"]["acceptance"]["tools_used"], "recovery case records expected tools")


def test_product_benchmark_dry_run_writes_reports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "bench"
        proc = subprocess.run(
            ["python3", "scripts/run_product_benchmark_suite.py", "--dry-run", "--root", str(root)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        _assert(proc.returncode == 0, "dry-run exits successfully")

        json_path = root / "product_benchmark_report.json"
        markdown_path = root / "product_benchmark_report.md"
        report = json.loads(json_path.read_text(encoding="utf-8"))
        markdown = markdown_path.read_text(encoding="utf-8")

        _assert(report["dry_run"] is True, "report marks dry-run")
        _assert(report["case_reports"], "report includes per-case dry-run matrix")
        _assert("acceptance" in report["case_reports"][0], "case report includes acceptance fields")
        _assert("Dry-Run Case Matrix" in markdown, "markdown includes dry-run case matrix")
        _assert("Final Answer" in markdown and "UI Events" in markdown, "markdown exposes acceptance columns")


if __name__ == "__main__":
    test_benchmark_spec_covers_required_regressions()
    test_product_benchmark_dry_run_writes_reports()
    print("All agent benchmark tests passed.")
