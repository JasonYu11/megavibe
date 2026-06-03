from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_chat import SYSTEM_PROMPT
from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.app_config import load_app_config
from mini_agent_lab.config import load_config, load_dotenv
from mini_agent_lab.events import Event, PrintSink
from mini_agent_lab.memory import AutoMemoryStore, compose_system_prompt, load_memory
from mini_agent_lab.provider import DeepSeekProvider
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


TASKS = [
    {
        "name": "lfm_matched_filter",
        "script": "lfm_matched_filter.py",
        "result": "lfm_matched_filter_result.json",
        "image": "lfm_matched_filter_result.png",
        "prompt": """
真实执行一个 LFM 信号匹配滤波仿真。

要求：
1. 你自己设置合理参数，例如采样率、脉宽、带宽、延迟、信噪比。
2. 创建 Python 脚本 lfm_matched_filter.py。
3. 必须使用 python_run 运行脚本，不要用 bash 运行 Python。
4. 脚本必须保存 lfm_matched_filter_result.png 图像，不要弹出 GUI 图窗。
5. 脚本必须保存 lfm_matched_filter_result.json，包含至少这些字段：
   fs, pulse_width, bandwidth, delay_seconds, snr_db,
   peak_index, estimated_delay_seconds, delay_error_seconds,
   peak_snr_like, compressed_width_samples。
6. 最后用中文简要返回关键结果和文件名。
""".strip(),
    },
    {
        "name": "beamforming",
        "script": "beamforming_simulation.py",
        "result": "beamforming_result.json",
        "image": "beamforming_pattern.png",
        "prompt": """
真实执行一个波束形成仿真。

要求：
1. 你自己设置合理参数，例如均匀线阵阵元数、阵元间距、信号方向、干扰方向、快拍数、信噪比。
2. 创建 Python 脚本 beamforming_simulation.py。
3. 必须使用 python_run 运行脚本，不要用 bash 运行 Python。
4. 脚本必须保存 beamforming_pattern.png 方向图图像，不要弹出 GUI 图窗。
5. 脚本必须保存 beamforming_result.json，包含至少这些字段：
   array_elements, spacing_wavelength, target_angle_deg, interferer_angle_deg,
   snapshots, snr_db, estimated_peak_angle_deg, angle_error_deg,
   mainlobe_gain_db, interferer_response_db。
6. interferer_response_db 可以是绝对响应，也可以是相对主瓣的响应；最终回答里说清楚含义。
7. 最后用中文简要返回关键结果和文件名。
""".strip(),
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live Mcode simulation acceptance tasks.")
    parser.add_argument("--root", default="", help="Output project root. Defaults to a timestamped live_agent_tests folder.")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    cfg = load_config()
    project_root = Path(args.root).expanduser().resolve() if args.root else _default_root()
    project_root.mkdir(parents=True, exist_ok=True)
    os.chdir(project_root)

    app_cfg = load_app_config(project_root / "mcode-config.json")
    memory_store = AutoMemoryStore(project_root / app_cfg.paths.memory_dir)
    memory = load_memory(project_root, auto_store=memory_store)
    session = Session(compose_system_prompt(SYSTEM_PROMPT, memory))
    session_id = time.strftime("%Y%m%d-%H%M%S-live-sim")
    store = SessionStore(project_root / app_cfg.paths.session_dir)
    sink = RunRecorder(
        directory=project_root / app_cfg.paths.run_dir,
        run_id=session_id,
        session_id=session_id,
        downstream=PrintSink(),
    )
    runtime = discover_runtime(project_root, app_cfg)
    provider = DeepSeekProvider(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        temperature=cfg.temperature,
    )
    registry = default_registry(
        memory_store=memory_store,
        sink=sink,
        job_log_dir=project_root / app_cfg.paths.job_dir,
        git_baseline_path=project_root / app_cfg.paths.gitstate_dir / f"{session_id}.baseline.json",
        runtime_selection=runtime,
    )
    agent = Agent(
        provider=provider,
        tools=registry,
        session=session,
        max_steps=min(cfg.max_steps, 80),
        safety_gate=SafetyGate(),
        approver=AutoAllowApprover(sink=sink),
        context_config=app_cfg.context,
        archive_dir=str(project_root / app_cfg.paths.archive_dir),
        sink=sink,
        git_baseline_path=project_root / app_cfg.paths.gitstate_dir / f"{session_id}.baseline.json",
    )

    print(f"[live-test] project_root={project_root}")
    print(f"[live-test] session_id={session_id}")
    print(f"[live-test] python={runtime.python} source={runtime.python_source}")

    results: list[dict[str, Any]] = []
    for task in TASKS:
        print(f"\n[live-test] running {task['name']}")
        started = time.time()
        answer = agent.run(task["prompt"])
        store.save(session_id, session)
        elapsed = time.time() - started
        result_path = project_root / task["result"]
        script_path = project_root / task["script"]
        image_path = project_root / task["image"]
        result_data: dict[str, Any] = {}
        result_error = ""
        if result_path.exists():
            try:
                result_data = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                result_error = f"invalid json: {exc}"
        else:
            result_error = "missing result json"
        validation_errors = _validate_task_result(task["name"], result_data) if result_data else []
        if not answer.strip():
            validation_errors.append("missing final assistant answer")
        row = {
            "task": task["name"],
            "elapsed_seconds": round(elapsed, 2),
            "script_exists": script_path.exists(),
            "result_exists": result_path.exists(),
            "image_exists": image_path.exists(),
            "result_error": result_error,
            "validation_errors": validation_errors,
            "answer_preview": answer[:800],
            "result": result_data,
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False, indent=2))

    events = _read_jsonl(sink.event_path)
    tool_counts: dict[str, int] = {}
    for event in events:
        if event.get("kind") == "tool_dispatch":
            name = str(event.get("data", {}).get("name", ""))
            tool_counts[name] = tool_counts.get(name, 0) + 1

    report = {
        "project_root": str(project_root),
        "session_id": session_id,
        "event_path": str(sink.event_path),
        "summary_path": str(sink.summary_path),
        "python": runtime.python,
        "python_source": runtime.python_source,
        "tool_counts": tool_counts,
        "results": results,
    }
    report_path = project_root / "live_agent_simulation_test_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n[live-test] report={report_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    failed = [
        item
        for item in results
        if not item["script_exists"]
        or not item["result_exists"]
        or not item["image_exists"]
        or item["result_error"]
        or item["validation_errors"]
    ]
    if failed:
        print("[live-test] FAILED")
        return 1
    if tool_counts.get("python_run", 0) < len(TASKS):
        print("[live-test] FAILED: python_run was not used for every task")
        return 1
    print("[live-test] PASSED")
    return 0


def _default_root() -> Path:
    return ROOT.parent / "live_agent_tests" / time.strftime("%Y%m%d-%H%M%S")


def _validate_task_result(task_name: str, data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if task_name == "lfm_matched_filter":
        errors.extend(
            _missing(
                data,
                [
                    "fs",
                    "pulse_width",
                    "bandwidth",
                    "delay_seconds",
                    "snr_db",
                    "peak_index",
                    "estimated_delay_seconds",
                    "delay_error_seconds",
                    "peak_snr_like",
                    "compressed_width_samples",
                ],
            )
        )
        if abs(float(data.get("delay_error_seconds", 1))) > 2e-6:
            errors.append("lfm delay_error_seconds must be <= 2 us")
        if float(data.get("peak_snr_like", 0)) < 10:
            errors.append("lfm peak_snr_like must be >= 10")
        if int(data.get("compressed_width_samples", 10**9)) > 30:
            errors.append("lfm compressed_width_samples must be <= 30")
    elif task_name == "beamforming":
        errors.extend(
            _missing(
                data,
                [
                    "array_elements",
                    "spacing_wavelength",
                    "target_angle_deg",
                    "interferer_angle_deg",
                    "snapshots",
                    "snr_db",
                    "estimated_peak_angle_deg",
                    "angle_error_deg",
                    "mainlobe_gain_db",
                    "interferer_response_db",
                ],
            )
        )
        if abs(float(data.get("angle_error_deg", 999))) > 1.0:
            errors.append("beamforming angle_error_deg must be <= 1 degree")
        mainlobe_gain = float(data.get("mainlobe_gain_db", 0))
        interferer_response = float(data.get("interferer_response_db", 999))
        relative_suppression = mainlobe_gain - interferer_response
        if interferer_response > -6 and relative_suppression < 3:
            errors.append(
                "beamforming interferer response should be either <= -6 dB absolute "
                "or at least 3 dB below the mainlobe"
            )
        if int(data.get("array_elements", 0)) < 4:
            errors.append("beamforming array_elements must be >= 4")
    return errors


def _missing(data: dict[str, Any], required: list[str]) -> list[str]:
    return [f"missing required field: {name}" for name in required if name not in data]


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


if __name__ == "__main__":
    raise SystemExit(main())
