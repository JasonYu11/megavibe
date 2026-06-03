from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "benchmark_specs" / "agent_ui_v1.json"

REQUIRED_REQUIREMENTS = {
    "普通对话",
    "读文件",
    "创建并运行 Python 脚本",
    "写文件",
    "修改文件",
    "LFM 匹配滤波仿真",
    "波束形成仿真",
    "Bug 修复",
    "权限审批",
    "附件处理",
    "Plan 执行",
    "长输出",
    "失败恢复",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Mcode product benchmark spec.")
    parser.add_argument("--spec", default=str(SPEC_PATH))
    args = parser.parse_args()
    spec_path = Path(args.spec).expanduser().resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    errors = validate_spec(spec)
    if errors:
        print("Product benchmark spec validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"Product benchmark spec OK: {len(spec.get('cases', []))} cases")
    return 0


def validate_spec(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cases = spec.get("cases", [])
    if not isinstance(cases, list):
        return ["cases must be a list"]
    required_count = int(spec.get("required_case_count", 8))
    if len(cases) != required_count:
        errors.append(f"expected {required_count} cases, got {len(cases)}")

    ids = [str(case.get("id", "")) for case in cases]
    if len(ids) != len(set(ids)):
        errors.append("case ids must be unique")
    requirements = {str(case.get("product_requirement", "")) for case in cases}
    missing_requirements = sorted(REQUIRED_REQUIREMENTS - requirements)
    if missing_requirements:
        errors.append(f"missing product requirement(s): {', '.join(missing_requirements)}")

    for case in cases:
        case_id = str(case.get("id", ""))
        prefix = case_id or "(missing id)"
        if not case_id:
            errors.append("case missing id")
        if not case.get("tier"):
            errors.append(f"{prefix}: missing tier")
        if not case.get("category"):
            errors.append(f"{prefix}: missing category")
        if not str(case.get("prompt", "")).strip():
            errors.append(f"{prefix}: missing prompt")
        if not case.get("external_runner") and not isinstance(case.get("checks"), dict):
            errors.append(f"{prefix}: non-external case requires checks")
        if case.get("external_runner") and not Path(ROOT / str(case["external_runner"])).exists():
            errors.append(f"{prefix}: external runner not found: {case['external_runner']}")

    by_requirement = {str(case.get("product_requirement", "")): case for case in cases}
    _require_check(errors, by_requirement, "普通对话", "max_tool_calls")
    _require_check(errors, by_requirement, "读文件", "required_tools", "read_file")
    _require_check(errors, by_requirement, "创建并运行 Python 脚本", "required_tools", "python_run")
    _require_check(errors, by_requirement, "写文件", "required_change_sources", "write_file")
    _require_check(errors, by_requirement, "修改文件", "required_change_sources", "edit_file")
    _require_check(errors, by_requirement, "Bug 修复", "required_tools", "python_run")
    _require_check(errors, by_requirement, "权限审批", "required_events", "test_approval_auto_allowed")
    _require_check(errors, by_requirement, "附件处理", "required_tools", "read_attachment")
    _require_check(errors, by_requirement, "Plan 执行", "required_events", "plan_pending")
    _require_check(errors, by_requirement, "长输出", "required_events", "command_output")
    _require_check(errors, by_requirement, "失败恢复", "required_failed_tools", "read_file")
    for requirement in ("LFM 匹配滤波仿真", "波束形成仿真"):
        case = by_requirement.get(requirement, {})
        if not case.get("external_runner"):
            errors.append(f"{requirement}: simulation case must declare external_runner")
    plan_case = by_requirement.get("Plan 执行", {})
    if plan_case.get("execution_mode") != "plan_then_execute":
        errors.append("Plan 执行: execution_mode must be plan_then_execute")
    attachment_case = by_requirement.get("附件处理", {})
    if not attachment_case.get("attachments"):
        errors.append("附件处理: case must include at least one attachment")
    return errors


def _require_check(
    errors: list[str],
    by_requirement: dict[str, dict[str, Any]],
    requirement: str,
    key: str,
    value: str | None = None,
) -> None:
    checks = by_requirement.get(requirement, {}).get("checks", {})
    if key not in checks:
        errors.append(f"{requirement}: missing check {key}")
        return
    if value is not None and value not in checks.get(key, []):
        errors.append(f"{requirement}: check {key} must include {value}")


if __name__ == "__main__":
    raise SystemExit(main())
