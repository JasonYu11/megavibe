from __future__ import annotations

import argparse
import base64
import json
import os
import re
import signal
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_chat import SYSTEM_PROMPT
from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.attachments import AttachmentStore, attachment_context
from mini_agent_lab.config import load_config, load_dotenv
from mini_agent_lab.events import Event
from mini_agent_lab.memory import AutoMemoryStore, compose_system_prompt, load_memory
from mini_agent_lab.plan import build_approved_plan_message
from mini_agent_lab.provider import DeepSeekProvider, ProviderError
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.runtime_env import discover_runtime
from mini_agent_lab.safety import Approver, SafetyGate
from mini_agent_lab.session_store import SessionStore
from mini_agent_lab.tool import default_registry


class AutoAllowApprover(Approver):
    def approve(self, tool_name: str, arguments: dict, reason: str) -> bool:
        self.sink.emit(
            Event(
                "test_approval_auto_allowed",
                {"tool_name": tool_name, "arguments": arguments, "reason": reason},
            )
        )
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mcode UI benchmark cases.")
    parser.add_argument("--spec", default=str(ROOT / "benchmark_specs" / "agent_ui_v1.json"))
    parser.add_argument("--tier", default="p0", help="Benchmark tier to run, or 'all' for every non-external case")
    parser.add_argument("--case", default="", help="Run one case id")
    parser.add_argument("--root", default="", help="Benchmark output root")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--case-timeout", type=int, default=30, help="Maximum seconds per benchmark case")
    args = parser.parse_args()

    spec_path = Path(args.spec).expanduser().resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    selected_tier = (args.tier or "").lower()
    cases = [
        case
        for case in spec["cases"]
        if not case.get("external_runner")
        and (selected_tier in {"", "all"} or case.get("tier") == args.tier)
        and (not args.case or case.get("id") == args.case)
    ]
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    if not cases:
        raise SystemExit("No benchmark cases selected.")

    load_dotenv(ROOT / ".env")
    cfg = load_config()
    run_root = Path(args.root).expanduser().resolve() if args.root else _default_root(spec["name"], args.tier)
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[bench] root={run_root}")
    print(f"[bench] cases={len(cases)} tier={args.tier}")
    results = []
    for case in cases:
        print(f"\n[bench] running {case['id']}")
        try:
            case_result = run_case_with_timeout(case, run_root, cfg, args.case_timeout)
        except Exception as exc:
            case_result = record_case_crash(case, run_root, exc)
        results.append(case_result)
        print(json.dumps(_brief_case(case_result), ensure_ascii=False, indent=2))

    report = {
        "name": spec["name"],
        "tier": args.tier,
        "run_root": str(run_root),
        "started_at": run_root.name,
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "results": results,
    }
    report_path = run_root / "benchmark_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = run_root / "benchmark_report.md"
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(f"\n[bench] report={report_path}")
    print(f"[bench] markdown={markdown_path}")
    print(f"[bench] passed={report['passed']} failed={report['failed']}")
    return 0 if report["failed"] == 0 else 1


def run_case_with_timeout(case: dict[str, Any], run_root: Path, cfg, timeout_seconds: int) -> dict[str, Any]:
    def handle_timeout(signum, frame):
        raise TimeoutError(f"benchmark case exceeded {timeout_seconds}s")

    previous = signal.signal(signal.SIGALRM, handle_timeout)
    signal.alarm(max(1, timeout_seconds))
    try:
        return run_case(case, run_root, cfg)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def run_case(case: dict[str, Any], run_root: Path, cfg) -> dict[str, Any]:
    case_id = _safe_id(case["id"])
    project_root = run_root / case_id
    project_root.mkdir(parents=True, exist_ok=True)
    write_setup_files(project_root, case.get("setup_files", {}))
    old_cwd = Path.cwd()
    os.chdir(project_root)
    try:
        app_cfg = load_app_config(project_root / "mcode-config.json")
        memory_store = AutoMemoryStore(project_root / app_cfg.paths.memory_dir)
        memory = load_memory(project_root, auto_store=memory_store)
        session = Session(compose_system_prompt(SYSTEM_PROMPT, memory))
        session_id = time.strftime("%Y%m%d-%H%M%S") + f"-{case_id}"
        recorder = RunRecorder(project_root / app_cfg.paths.run_dir, run_id=session_id, session_id=session_id)
        runtime = discover_runtime(project_root, app_cfg)
        attachment_store = AttachmentStore(project_root / ".attachments")
        attachment_metas = write_attachments(attachment_store, session_id, case.get("attachments", []))
        prompt = case["prompt"] + attachment_context(attachment_metas)
        provider = DeepSeekProvider(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=cfg.model,
            temperature=cfg.temperature,
        )
        registry = default_registry(
            memory_store=memory_store,
            sink=recorder,
            job_log_dir=project_root / app_cfg.paths.job_dir,
            git_baseline_path=project_root / app_cfg.paths.gitstate_dir / f"{session_id}.baseline.json",
            runtime_selection=runtime,
            attachment_store=attachment_store,
            attachment_session_id=session_id,
        )
        agent = Agent(
            provider=provider,
            tools=registry,
            session=session,
            max_steps=min(cfg.max_steps, 60),
            safety_gate=SafetyGate(),
            approver=AutoAllowApprover(sink=recorder),
            context_config=app_cfg.context,
            archive_dir=str(project_root / app_cfg.paths.archive_dir),
            sink=recorder,
            git_baseline_path=project_root / app_cfg.paths.gitstate_dir / f"{session_id}.baseline.json",
        )

        started = time.time()
        plan_answer = ""
        if case.get("execution_mode") == "plan_then_execute":
            agent.set_plan_mode(True)
            plan_answer = agent.run(prompt)
            agent.set_plan_mode(False)
            answer = agent.run(build_approved_plan_message(plan_answer))
        else:
            answer = agent.run(prompt)
        elapsed = round(time.time() - started, 2)
        SessionStore(project_root / app_cfg.paths.session_dir).save(session_id, session)

        events = _read_jsonl(recorder.event_path)
        messages = _read_jsonl(project_root / app_cfg.paths.session_dir / f"{session_id}.jsonl")
        summary = _read_json(recorder.summary_path)
        debug = make_debug_report(events, messages, summary)
        debug_path = project_root / f"{session_id}.ui-debug-report.json"
        debug_path.write_text(json.dumps(debug, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        checks = evaluate_case(case.get("checks", {}), project_root, events, messages, summary, answer)
        acceptance = build_live_acceptance(case, events, messages, summary, answer, project_root)
        acceptance["success"] = not checks["errors"]
        return {
            "id": case["id"],
            "category": case.get("category", ""),
            "passed": not checks["errors"],
            "errors": checks["errors"],
            "warnings": debug["warnings"],
            "elapsed_seconds": elapsed,
            "project_root": str(project_root),
            "session_id": session_id,
            "event_path": str(recorder.event_path),
            "summary_path": str(recorder.summary_path),
            "debug_report_path": str(debug_path),
            "answer_preview": answer[:800],
            "plan_answer_preview": plan_answer[:800],
            "acceptance": acceptance,
            "debug": debug,
            "checks": checks,
        }
    finally:
        os.chdir(old_cwd)


def record_case_crash(case: dict[str, Any], run_root: Path, exc: Exception) -> dict[str, Any]:
    case_id = _safe_id(case["id"])
    project_root = run_root / case_id
    project_root.mkdir(parents=True, exist_ok=True)
    debug_path = project_root / "case_crash.json"
    error = f"{type(exc).__name__}: {exc}"
    provider_error = exc if isinstance(exc, ProviderError) else None
    payload = {
        "id": case["id"],
        "category": case.get("category", ""),
        "passed": False,
        "errors": [error],
        "warnings": ["benchmark case crashed before normal completion"],
        "elapsed_seconds": 0,
        "project_root": str(project_root),
        "session_id": "",
        "event_path": "",
        "summary_path": "",
        "debug_report_path": str(debug_path),
        "answer_preview": "",
        "plan_answer_preview": "",
        "acceptance": build_spec_acceptance(case, executed=False),
        "debug": {},
        "provider_error": {
            "kind": provider_error.kind,
            "status_code": provider_error.status_code,
            "retryable": provider_error.retryable,
            "attempt": provider_error.attempt,
            "request_id": provider_error.request_id,
        }
        if provider_error
        else None,
        "checks": {
            "errors": [error],
            "tool_counts": {},
            "command_output_event_count": 0,
            "summary_status": "crashed",
            "final_message_count": 0,
        },
    }
    debug_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def evaluate_case(
    checks: dict[str, Any],
    project_root: Path,
    events: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    summary: dict[str, Any],
    answer: str,
) -> dict[str, Any]:
    errors: list[str] = []
    tool_counts = Counter(
        str(event.get("data", {}).get("name", ""))
        for event in events
        if event.get("kind") == "tool_dispatch"
    )
    final_messages = [
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "assistant" and message.get("content")
    ]

    if checks.get("final_answer_required") and not (answer.strip() or final_messages or summary.get("final_answer")):
        errors.append("missing final assistant answer")
    max_tool_calls = checks.get("max_tool_calls")
    if max_tool_calls is not None and sum(tool_counts.values()) > int(max_tool_calls):
        errors.append(f"expected <= {max_tool_calls} tool calls, got {sum(tool_counts.values())}")
    for tool in checks.get("required_tools", []):
        if tool_counts.get(tool, 0) <= 0:
            errors.append(f"required tool not used: {tool}")
    for tool in checks.get("forbidden_tools", []):
        if tool_counts.get(tool, 0) > 0:
            errors.append(f"forbidden tool was used: {tool}")
    min_tool_calls = checks.get("min_tool_calls")
    if min_tool_calls is not None and sum(tool_counts.values()) < int(min_tool_calls):
        errors.append(f"expected >= {min_tool_calls} tool calls, got {sum(tool_counts.values())}")

    event_kinds = Counter(str(event.get("kind", "")) for event in events)
    for kind in checks.get("required_events", []):
        if event_kinds.get(str(kind), 0) <= 0:
            errors.append(f"required event not emitted: {kind}")

    if checks.get("ui_turn_answer_leaked") is False:
        leaked = [
            event
            for event in events
            if event.get("kind") == "notice"
            and str(event.get("data", {}).get("message", "")).startswith("UI turn answer:")
        ]
        if leaked:
            errors.append("UI turn answer leaked into events")

    command_outputs = [event for event in events if event.get("kind") == "command_output"]
    if "min_command_output_events" in checks and len(command_outputs) < int(checks["min_command_output_events"]):
        errors.append(f"expected noisy command output, got {len(command_outputs)} command_output events")
    if "max_command_output_events" in checks and len(command_outputs) > int(checks["max_command_output_events"]):
        errors.append(f"expected <= {checks['max_command_output_events']} command_output events, got {len(command_outputs)}")
    command_output_chars = sum(len(str(event.get("data", {}).get("text", ""))) for event in command_outputs)
    if "max_command_output_chars" in checks and command_output_chars > int(checks["max_command_output_chars"]):
        errors.append(f"expected <= {checks['max_command_output_chars']} command output chars, got {command_output_chars}")

    failed_tool_counts = Counter(
        str(event.get("data", {}).get("name", ""))
        for event in events
        if event.get("kind") == "tool_result" and event.get("data", {}).get("ok") is False
    )
    for tool in checks.get("required_failed_tools", []):
        if failed_tool_counts.get(tool, 0) <= 0:
            errors.append(f"required failed tool result missing: {tool}")

    result_data: dict[str, Any] = {}
    result_file = checks.get("result_file")
    if result_file:
        result_path = project_root / str(result_file)
        if not result_path.exists():
            errors.append(f"missing result file: {result_file}")
        else:
            try:
                result_data = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"invalid result json {result_file}: {exc}")
    for key, expected in checks.get("result_equals", {}).items():
        actual = result_data.get(key)
        if actual != expected:
            errors.append(f"result {key!r}: expected {expected!r}, got {actual!r}")

    for file_name in checks.get("required_files", []):
        if not _case_file(project_root, str(file_name)).exists():
            errors.append(f"missing required file: {file_name}")

    for file_name, needles in checks.get("file_contains", {}).items():
        path = _case_file(project_root, str(file_name))
        if not path.exists():
            errors.append(f"file_contains target missing: {file_name}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            if str(needle) not in text:
                errors.append(f"{file_name} does not contain {needle!r}")

    for file_name, needles in checks.get("file_not_contains", {}).items():
        path = _case_file(project_root, str(file_name))
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            if str(needle) in text:
                errors.append(f"{file_name} unexpectedly contains {needle!r}")

    answer_text = answer or (final_messages[-1] if final_messages else str(summary.get("final_answer", "")))
    max_lines = checks.get("answer_max_lines")
    if max_lines is not None and _visible_line_count(answer_text) > int(max_lines):
        errors.append(f"answer exceeds {max_lines} visible lines")
    for pattern in checks.get("answer_forbidden_patterns", []):
        if re.search(str(pattern), answer_text):
            errors.append(f"answer contains forbidden pattern: {pattern}")

    required_sources = set(str(item) for item in checks.get("required_change_sources", []))
    if required_sources:
        sources = change_sources(events, summary)
        missing = sorted(required_sources - sources)
        if missing:
            errors.append(f"missing change source(s): {', '.join(missing)}")

    return {
        "errors": errors,
        "tool_counts": dict(tool_counts),
        "command_output_event_count": len(command_outputs),
        "command_output_chars": command_output_chars,
        "failed_tool_counts": dict(failed_tool_counts),
        "summary_status": summary.get("status"),
        "final_message_count": len(final_messages),
    }


def write_setup_files(project_root: Path, setup_files: dict[str, str]) -> None:
    for relative, content in setup_files.items():
        path = _case_file(project_root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")


def write_attachments(store: AttachmentStore, session_id: str, attachments: list[dict[str, Any]]) -> list:
    metas = []
    for item in attachments:
        content = str(item.get("content", ""))
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        metas.append(
            store.add_base64(
                session_id,
                str(item.get("name") or "attachment.txt"),
                encoded,
                str(item.get("mime_type") or "text/plain"),
            )
        )
    return metas


def build_spec_acceptance(case: dict[str, Any], executed: bool = False) -> dict[str, Any]:
    checks = case.get("checks", {}) if isinstance(case.get("checks"), dict) else {}
    required_events = [str(item) for item in checks.get("required_events", [])]
    required_tools = [str(item) for item in checks.get("required_tools", [])]
    approval = "test_approval_auto_allowed" in required_events or "safety_approved" in required_events
    return {
        "executed": executed,
        "success": None if not executed else False,
        "tools_used": required_tools,
        "has_final_answer": bool(checks.get("final_answer_required")),
        "generated_target_files": _target_files_from_checks(checks),
        "approval_triggered": approval,
        "ui_key_events": required_events,
        "external_runner": bool(case.get("external_runner")),
    }


def build_live_acceptance(
    case: dict[str, Any],
    events: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    summary: dict[str, Any],
    answer: str,
    project_root: Path,
) -> dict[str, Any]:
    event_kinds = Counter(str(event.get("kind", "")) for event in events)
    tool_counts = Counter(
        str(event.get("data", {}).get("name", ""))
        for event in events
        if event.get("kind") == "tool_dispatch"
    )
    final_messages = [
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "assistant" and message.get("content")
    ]
    checks = case.get("checks", {}) if isinstance(case.get("checks"), dict) else {}
    target_files = _target_files_from_checks(checks)
    generated = [relative for relative in target_files if _case_file(project_root, relative).exists()]
    interesting_events = [
        "assistant_message",
        "tool_dispatch",
        "tool_result",
        "preview",
        "workspace_changes_detected",
        "checkpoint_saved",
        "plan_pending",
        "safety_ask",
        "safety_approved",
        "test_approval_auto_allowed",
        "turn_completed",
        "command_output",
    ]
    return {
        "executed": True,
        "success": None,
        "tools_used": dict(tool_counts.most_common()),
        "has_final_answer": bool(answer.strip() or final_messages or summary.get("final_answer")),
        "generated_target_files": generated,
        "approval_triggered": any(
            event_kinds.get(kind, 0) for kind in ("safety_ask", "safety_approved", "test_approval_auto_allowed")
        ),
        "ui_key_events": {kind: event_kinds.get(kind, 0) for kind in interesting_events if event_kinds.get(kind, 0)},
        "external_runner": bool(case.get("external_runner")),
    }


def _target_files_from_checks(checks: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for item in checks.get("required_files", []):
        if str(item) not in targets:
            targets.append(str(item))
    result_file = checks.get("result_file")
    if result_file and str(result_file) not in targets:
        targets.append(str(result_file))
    return targets


def change_sources(events: list[dict[str, Any]], summary: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    last_tool_name = ""
    for event in events:
        if event.get("kind") == "tool_dispatch":
            last_tool_name = str(event.get("data", {}).get("name", ""))
        if event.get("kind") == "preview":
            name = str(
                event.get("data", {}).get("source")
                or event.get("data", {}).get("tool_name")
                or last_tool_name
            )
            if name:
                sources.add(name)
        if event.get("kind") == "workspace_changes_detected":
            source = str(event.get("data", {}).get("source", ""))
            if source:
                sources.add(source)
    for item in summary.get("file_changes", []) if isinstance(summary.get("file_changes"), list) else []:
        if isinstance(item, dict):
            source = str(item.get("source", ""))
            if source:
                sources.add(source)
    return sources


def _case_file(project_root: Path, relative: str) -> Path:
    path = (project_root / relative).resolve()
    root = project_root.resolve()
    if not (path == root or root in path.parents):
        raise ValueError(f"benchmark file path escapes case root: {relative}")
    return path


def _visible_line_count(text: str) -> int:
    return len([line for line in text.strip().splitlines() if line.strip()])


def make_debug_report(events: list[dict[str, Any]], messages: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    kinds = Counter(str(event.get("kind", "")) for event in events)
    tool_counts = Counter(
        str(event.get("data", {}).get("name", ""))
        for event in events
        if event.get("kind") == "tool_dispatch"
    )
    command_output_chars = sum(
        len(str(event.get("data", {}).get("text", "")))
        for event in events
        if event.get("kind") == "command_output"
    )
    ui_turn_answer_notices = [
        event
        for event in events
        if event.get("kind") == "notice"
        and str(event.get("data", {}).get("message", "")).startswith("UI turn answer:")
    ]
    final_assistant_messages = [
        msg.get("content", "")
        for msg in messages
        if msg.get("role") == "assistant" and msg.get("content")
    ]
    warnings = []
    if ui_turn_answer_notices:
        warnings.append("UI turn answer notice leaked into event stream")
    if kinds.get("command_output", 0) > 5 or command_output_chars > 4000:
        warnings.append("command_output is noisy; UI should compact command output events")
    if summary.get("status") == "completed" and not final_assistant_messages:
        warnings.append("turn completed but no final assistant message was saved in session")
    return {
        "event_count": len(events),
        "message_count": len(messages),
        "event_kind_counts": dict(kinds.most_common()),
        "tool_counts": dict(tool_counts.most_common()),
        "command_output_event_count": kinds.get("command_output", 0),
        "command_output_chars": command_output_chars,
        "ui_turn_answer_notice_count": len(ui_turn_answer_notices),
        "summary_status": summary.get("status"),
        "summary_final_answer": summary.get("final_answer", ""),
        "last_assistant_message": final_assistant_messages[-1] if final_assistant_messages else "",
        "warnings": warnings,
    }


def _brief_case(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": result["id"],
        "passed": result["passed"],
        "errors": result["errors"],
        "warnings": result["warnings"],
        "tool_counts": result["checks"]["tool_counts"],
        "acceptance": result.get("acceptance", {}),
        "debug_report_path": result["debug_report_path"],
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# {report.get('name', 'agent benchmark')} Report",
        "",
        f"- Tier: {report.get('tier', '')}",
        f"- Total: {report.get('total', 0)}",
        f"- Passed: {report.get('passed', 0)}",
        f"- Failed: {report.get('failed', 0)}",
        f"- Run root: `{report.get('run_root', '')}`",
        "",
        "| Case | Status | Tools | Final Answer | Target Files | Approval | UI Events |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in report.get("results", []):
        acceptance = item.get("acceptance", {}) if isinstance(item, dict) else {}
        tools = acceptance.get("tools_used", {})
        if isinstance(tools, dict):
            tool_text = ", ".join(f"{name}:{count}" for name, count in tools.items()) or "-"
        else:
            tool_text = ", ".join(str(name) for name in tools) or "-"
        events = acceptance.get("ui_key_events", {})
        if isinstance(events, dict):
            event_text = ", ".join(f"{name}:{count}" for name, count in events.items()) or "-"
        else:
            event_text = ", ".join(str(name) for name in events) or "-"
        files = ", ".join(str(name) for name in acceptance.get("generated_target_files", [])) or "-"
        status = "PASS" if item.get("passed") else "FAIL"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("id", "")),
                    status,
                    tool_text,
                    "yes" if acceptance.get("has_final_answer") else "no",
                    files,
                    "yes" if acceptance.get("approval_triggered") else "no",
                    event_text,
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _default_root(name: str, tier: str) -> Path:
    return ROOT.parent / "benchmark_runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{_safe_id(name)}-{_safe_id(tier)}"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-") or "case"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"kind": "invalid_jsonl", "raw": line})
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "invalid_json"}


if __name__ == "__main__":
    raise SystemExit(main())
