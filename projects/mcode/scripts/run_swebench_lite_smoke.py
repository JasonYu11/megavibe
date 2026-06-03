from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from datasets import load_dataset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_chat import SYSTEM_PROMPT
from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.config import load_config, load_dotenv
from mini_agent_lab.events import Event
from mini_agent_lab.memory import AutoMemoryStore, compose_system_prompt, load_memory
from mini_agent_lab.provider import DeepSeekProvider, ProviderError
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.runtime_env import discover_runtime
from mini_agent_lab.safety import Approver, SafetyGate
from mini_agent_lab.session_store import SessionStore
from mini_agent_lab.tool import default_registry


DEFAULT_INSTANCES = [
    "pytest-dev__pytest-11143",
    "pytest-dev__pytest-6116",
    "psf__requests-863",
]


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
    parser = argparse.ArgumentParser(description="Run a 3-task SWE-bench Lite smoke test with Mcode.")
    parser.add_argument("--instances", nargs="*", default=DEFAULT_INSTANCES)
    parser.add_argument("--root", default=str(ROOT.parent / "swebench_smoke_runs"))
    parser.add_argument("--case-timeout", type=int, default=300)
    parser.add_argument("--max-steps", type=int, default=35)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    cfg = load_config()
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    by_id = {row["instance_id"]: row for row in ds}
    missing = [instance_id for instance_id in args.instances if instance_id not in by_id]
    if missing:
        raise SystemExit(f"Unknown instance id(s): {missing}")

    run_root = Path(args.root).expanduser().resolve() / f"{time.strftime('%Y%m%d-%H%M%S')}-swebench-lite-smoke"
    run_root.mkdir(parents=True, exist_ok=True)
    print(f"[swe-smoke] root={run_root}")
    print(f"[swe-smoke] instances={len(args.instances)} timeout={args.case_timeout}s max_steps={args.max_steps}")

    results = []
    for instance_id in args.instances:
        row = by_id[instance_id]
        print(f"\n[swe-smoke] running {instance_id} {row['repo']}")
        try:
            result = run_case_with_timeout(row, run_root, cfg, args.case_timeout, args.max_steps)
        except Exception as exc:
            result = record_crash(row, run_root, exc)
        results.append(result)
        print(json.dumps(brief(result), ensure_ascii=False, indent=2))

    report = {
        "kind": "swebench_lite_smoke",
        "note": "Smoke test only: generates patches and records agent traces. Official SWE-bench resolved scoring requires Docker harness.",
        "run_root": str(run_root),
        "total": len(results),
        "patch_generated": sum(1 for item in results if item["patch_generated"]),
        "failed": sum(1 for item in results if item["status"] == "failed"),
        "results": results,
    }
    report_path = run_root / "swebench_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n[swe-smoke] report={report_path}")
    print(f"[swe-smoke] patch_generated={report['patch_generated']}/{report['total']} failed={report['failed']}")
    return 0 if report["failed"] == 0 else 1


def run_case_with_timeout(row: dict[str, Any], run_root: Path, cfg, timeout_seconds: int, max_steps: int) -> dict[str, Any]:
    def handle_timeout(signum, frame):
        raise TimeoutError(f"SWE-bench smoke case exceeded {timeout_seconds}s")

    previous = signal.signal(signal.SIGALRM, handle_timeout)
    signal.alarm(max(1, timeout_seconds))
    try:
        return run_case(row, run_root, cfg, max_steps)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def run_case(row: dict[str, Any], run_root: Path, cfg, max_steps: int) -> dict[str, Any]:
    case_root = run_root / safe_id(row["instance_id"])
    repo_root = case_root / "repo"
    case_root.mkdir(parents=True, exist_ok=True)
    save_task_files(row, case_root)
    clone_and_checkout(row["repo"], row["base_commit"], repo_root)

    old_cwd = Path.cwd()
    os.chdir(repo_root)
    try:
        app_cfg = load_app_config(repo_root / "mcode-config.json")
        memory_store = AutoMemoryStore(repo_root / app_cfg.paths.memory_dir)
        memory = load_memory(repo_root, auto_store=memory_store)
        session = Session(compose_system_prompt(SYSTEM_PROMPT, memory))
        session_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_id(row['instance_id'])}"
        recorder = RunRecorder(repo_root / app_cfg.paths.run_dir, run_id=session_id, session_id=session_id)
        runtime = discover_runtime(repo_root, app_cfg)
        provider = DeepSeekProvider(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=cfg.model,
            temperature=cfg.temperature,
        )
        registry = default_registry(
            memory_store=memory_store,
            sink=recorder,
            job_log_dir=repo_root / app_cfg.paths.job_dir,
            git_baseline_path=repo_root / app_cfg.paths.gitstate_dir / f"{session_id}.baseline.json",
            runtime_selection=runtime,
        )
        agent = Agent(
            provider=provider,
            tools=registry,
            session=session,
            max_steps=max_steps,
            safety_gate=SafetyGate(),
            approver=AutoAllowApprover(sink=recorder),
            context_config=app_cfg.context,
            archive_dir=str(repo_root / app_cfg.paths.archive_dir),
            sink=recorder,
            git_baseline_path=repo_root / app_cfg.paths.gitstate_dir / f"{session_id}.baseline.json",
        )
        started = time.time()
        answer = agent.run(make_prompt(row))
        elapsed = round(time.time() - started, 2)
        SessionStore(repo_root / app_cfg.paths.session_dir).save(session_id, session)
        patch_text = run(["git", "diff", "--", "."], cwd=repo_root, check=False).stdout
        patch_path = case_root / "agent.patch"
        patch_path.write_text(patch_text, encoding="utf-8")
        summary = read_json(recorder.summary_path)
        return {
            "instance_id": row["instance_id"],
            "repo": row["repo"],
            "status": "completed",
            "elapsed_seconds": elapsed,
            "patch_generated": bool(patch_text.strip()),
            "patch_lines": len(patch_text.splitlines()),
            "answer_preview": answer[:1000],
            "case_root": str(case_root),
            "repo_root": str(repo_root),
            "patch_path": str(patch_path),
            "event_path": str(recorder.event_path),
            "summary_path": str(recorder.summary_path),
            "summary_status": summary.get("status", ""),
        }
    finally:
        os.chdir(old_cwd)


def clone_and_checkout(repo: str, base_commit: str, repo_root: Path) -> None:
    if repo_root.exists() and (repo_root / ".git").exists():
        run(["git", "fetch", "--all", "--tags"], cwd=repo_root)
    else:
        repo_root.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", f"https://github.com/{repo}.git", str(repo_root)], cwd=repo_root.parent)
    run(["git", "checkout", "--force", base_commit], cwd=repo_root)
    run(["git", "clean", "-fdx"], cwd=repo_root)


def save_task_files(row: dict[str, Any], case_root: Path) -> None:
    payload = {key: row[key] for key in row.keys()}
    (case_root / "task.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (case_root / "gold.patch").write_text(row["patch"], encoding="utf-8")
    (case_root / "test.patch").write_text(row["test_patch"], encoding="utf-8")
    (case_root / "problem.md").write_text(row["problem_statement"], encoding="utf-8")


def make_prompt(row: dict[str, Any]) -> str:
    tests = row.get("FAIL_TO_PASS") or []
    return f"""You are solving a SWE-bench Lite smoke-test task.

Repository: {row['repo']}
Instance: {row['instance_id']}
Base commit: {row['base_commit']}

Problem statement:
{row['problem_statement']}

Hints:
{row.get('hints_text') or '(none)'}

FAIL_TO_PASS tests from the benchmark metadata:
{json.dumps(tests, ensure_ascii=False)}

Instructions:
- Inspect the repository and identify the smallest source change that addresses the issue.
- Edit files directly in this repository.
- Run a lightweight targeted test or import check if practical, but do not spend time installing large dependencies.
- Do not apply the official gold patch or test patch files.
- Finish with a short summary of files changed and how you validated the change.
"""


def record_crash(row: dict[str, Any], run_root: Path, exc: Exception) -> dict[str, Any]:
    case_root = run_root / safe_id(row["instance_id"])
    case_root.mkdir(parents=True, exist_ok=True)
    provider_error = exc if isinstance(exc, ProviderError) else None
    payload = {
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "status": "failed",
        "error": f"{type(exc).__name__}: {exc}",
        "provider_error": {
            "kind": provider_error.kind,
            "status_code": provider_error.status_code,
            "retryable": provider_error.retryable,
            "attempt": provider_error.attempt,
            "request_id": provider_error.request_id,
        }
        if provider_error
        else None,
        "patch_generated": False,
        "patch_lines": 0,
        "case_root": str(case_root),
    }
    (case_root / "case_crash.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=str(cwd), text=True, capture_output=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\nstdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
        )
    return result


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)


def brief(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": result["instance_id"],
        "repo": result["repo"],
        "status": result["status"],
        "patch_generated": result["patch_generated"],
        "patch_lines": result.get("patch_lines", 0),
        "error": result.get("error", ""),
        "case_root": result.get("case_root", ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
