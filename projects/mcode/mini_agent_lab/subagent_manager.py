from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from mini_agent_lab.app_config import ContextConfig
from mini_agent_lab.events import Event, EventSink, NullSink
from mini_agent_lab.provider import DeepSeekProvider
from mini_agent_lab.safety import Approver, SafetyGate
from mini_agent_lab.subagent import DEFAULT_SUBAGENT_SYSTEM_PROMPT, run_subagent
from mini_agent_lab.tool.registry import ToolRegistry


MAX_EVENT_OUTPUT_CHARS = 12000


@dataclass
class SubagentRecord:
    subagent_id: str
    parent_session_id: str
    parent_tool_call_id: str
    description: str
    task: str
    status: str
    tools: list[str]
    max_steps: int
    run_in_background: bool
    created_at: float
    started_at: float = 0.0
    finished_at: float = 0.0
    answer: str = ""
    error: str = ""
    state_path: str = ""
    events_path: str = ""
    session_path: str = ""
    git_baseline_path: str = ""


class SubagentManager:
    def __init__(
        self,
        *,
        root_dir: str | Path = ".subagents",
        parent_session_id: str = "default",
        provider: DeepSeekProvider,
        registry_getter: Callable[[], ToolRegistry],
        parent_max_steps: int,
        safety_gate: Optional[SafetyGate] = None,
        approver: Optional[Approver] = None,
        context_config: Optional[ContextConfig] = None,
        archive_dir: str = ".archives",
        gitstate_dir: str | Path = ".gitstate",
        sink: Optional[EventSink] = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.parent_session_id = _safe_id(parent_session_id)
        self.run_dir = self.root_dir / self.parent_session_id
        self.provider = provider
        self.registry_getter = registry_getter
        self.parent_max_steps = parent_max_steps
        self.safety_gate = safety_gate
        self.approver = approver
        self.context_config = context_config
        self.archive_dir = archive_dir
        self.gitstate_dir = Path(gitstate_dir)
        self.sink = sink or NullSink()
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._mark_stale_running_records()

    def run_task(self, arguments: dict[str, Any], system_prompt: str = "") -> dict[str, Any]:
        prompt = str(arguments.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("prompt is required")
        tools = [str(name) for name in arguments.get("tools", []) if str(name).strip()]
        requested_steps = int(arguments.get("max_steps", 0) or 0)
        description = str(arguments.get("description", "") or "").strip() or "task"
        parent_tool_call_id = str(arguments.get("_tool_call_id", "") or "")
        background = bool(arguments.get("run_in_background", False))

        record = self._new_record(
            description=description,
            task=prompt,
            tools=tools,
            max_steps=requested_steps,
            run_in_background=background,
            parent_tool_call_id=parent_tool_call_id,
        )
        self._save_record(record)
        if background:
            self._start_background(record, system_prompt=system_prompt)
            return {
                "subagent": "started",
                "subagent_id": record.subagent_id,
                "status": "running",
                "description": record.description,
                "events_path": record.events_path,
                "state_path": record.state_path,
                "note": "Use subagent_status, subagent_output, wait_subagent, or cancel_subagent to manage it.",
            }

        return self._run_foreground(record, system_prompt=system_prompt)

    def status(self, subagent_id: str = "") -> dict[str, Any]:
        if subagent_id:
            record = self._load_record(subagent_id)
            self._refresh_running_status(record)
            return {"subagents": [asdict(record)]}
        records = [self._load_record(path.parent.name) for path in sorted(self.run_dir.glob("*/state.json"))]
        for record in records:
            self._refresh_running_status(record)
        return {"subagents": [asdict(record) for record in records]}

    def output(self, subagent_id: str, limit: int = 20) -> dict[str, Any]:
        record = self._load_record(subagent_id)
        events = _read_jsonl_output_window(Path(record.events_path), max(1, int(limit or 20)))
        return {
            "subagent_id": record.subagent_id,
            "status": record.status,
            "answer": record.answer,
            "error": record.error,
            "events": events,
        }

    def wait(self, subagent_id: str, timeout_seconds: int = 0) -> dict[str, Any]:
        record = self._load_record(subagent_id)
        thread = self._threads.get(record.subagent_id)
        if thread and thread.is_alive():
            timeout = None if timeout_seconds <= 0 else timeout_seconds
            thread.join(timeout=timeout)
        record = self._load_record(subagent_id)
        self._refresh_running_status(record)
        return asdict(record)

    def cancel(self, subagent_id: str) -> dict[str, Any]:
        record = self._load_record(subagent_id)
        cancel_event = self._cancel.get(record.subagent_id)
        if record.status not in {"running", "queued", "cancel_requested"}:
            return {"subagent_id": record.subagent_id, "status": record.status, "note": "subagent is not running"}
        if cancel_event is not None:
            cancel_event.set()
        record.status = "cancel_requested"
        record.error = "cancel requested"
        self._save_record(record)
        self.sink.emit(
            Event(
                "subagent_cancel_requested",
                {
                    "subagent_id": record.subagent_id,
                    "parent_tool_call_id": record.parent_tool_call_id,
                },
            )
        )
        return {
            "subagent_id": record.subagent_id,
            "status": record.status,
            "note": "Cancellation is cooperative; a running model/tool call may finish before stopping.",
        }

    def _run_foreground(self, record: SubagentRecord, system_prompt: str = "") -> dict[str, Any]:
        cancel_event = threading.Event()
        self._cancel[record.subagent_id] = cancel_event
        self._run_record(record, cancel_event, system_prompt=system_prompt)
        record = self._load_record(record.subagent_id)
        return {
            "subagent": record.status,
            "subagent_id": record.subagent_id,
            "description": record.description,
            "answer": record.answer,
            "error": record.error,
            "events_path": record.events_path,
            "state_path": record.state_path,
        }

    def _start_background(self, record: SubagentRecord, system_prompt: str = "") -> None:
        cancel_event = threading.Event()
        self._cancel[record.subagent_id] = cancel_event
        thread = threading.Thread(
            target=self._run_record,
            args=(record, cancel_event),
            kwargs={"system_prompt": system_prompt},
            daemon=True,
        )
        with self._lock:
            self._threads[record.subagent_id] = thread
        thread.start()

    def _run_record(self, record: SubagentRecord, cancel_event: threading.Event, system_prompt: str = "") -> None:
        record.status = "running"
        record.started_at = time.time()
        self._save_record(record)
        sink = _SubagentFileSink(Path(record.events_path), downstream=self.sink)
        try:
            result = run_subagent(
                provider=self.provider,
                parent_registry=self.registry_getter(),
                task=record.task,
                parent_max_steps=self.parent_max_steps,
                allowed_tools=record.tools,
                max_steps=record.max_steps,
                system_prompt=system_prompt or DEFAULT_SUBAGENT_SYSTEM_PROMPT,
                safety_gate=self.safety_gate,
                approver=self.approver,
                context_config=self.context_config,
                archive_dir=self.archive_dir,
                sink=sink,
                parent_tool_call_id=record.parent_tool_call_id,
                subagent_id=record.subagent_id,
                git_baseline_path=record.git_baseline_path,
                cancelled=cancel_event.is_set,
            )
            record.answer = result.answer
            record.max_steps = result.max_steps
            record.tools = result.tools
            record.status = "cancelled" if cancel_event.is_set() else "completed"
            _write_jsonl(Path(record.session_path), result.session_messages)
            if cancel_event.is_set():
                sink.emit(
                    Event(
                        "subagent_cancelled",
                        {
                            "subagent_id": record.subagent_id,
                            "parent_tool_call_id": record.parent_tool_call_id,
                            "answer": result.answer,
                        },
                    )
                )
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            self.sink.emit(
                Event(
                    "subagent_failed",
                    {
                        "subagent_id": record.subagent_id,
                        "parent_tool_call_id": record.parent_tool_call_id,
                        "error": str(exc),
                    },
                )
            )
        finally:
            record.finished_at = time.time()
            self._save_record(record)
            with self._lock:
                self._threads.pop(record.subagent_id, None)
                self._cancel.pop(record.subagent_id, None)

    def _new_record(
        self,
        *,
        description: str,
        task: str,
        tools: list[str],
        max_steps: int,
        run_in_background: bool,
        parent_tool_call_id: str,
    ) -> SubagentRecord:
        now = time.time()
        subagent_id = self._new_id(description)
        run_path = self.run_dir / subagent_id
        run_path.mkdir(parents=True, exist_ok=False)
        return SubagentRecord(
            subagent_id=subagent_id,
            parent_session_id=self.parent_session_id,
            parent_tool_call_id=parent_tool_call_id,
            description=description,
            task=task,
            status="queued",
            tools=tools,
            max_steps=max_steps,
            run_in_background=run_in_background,
            created_at=now,
            state_path=str(run_path / "state.json"),
            events_path=str(run_path / "events.jsonl"),
            session_path=str(run_path / "session.jsonl"),
            git_baseline_path=str(self.gitstate_dir / f"{self.parent_session_id}.{subagent_id}.baseline.json"),
        )

    def _new_id(self, description: str) -> str:
        stem = _safe_id(description)[:48] or "task"
        for index in range(1, 10000):
            candidate = f"{stem}-{int(time.time() * 1000)}-{index}"
            if not (self.run_dir / candidate).exists():
                return candidate
        raise RuntimeError("unable to allocate subagent id")

    def _load_record(self, subagent_id: str) -> SubagentRecord:
        path = self.run_dir / _safe_id(subagent_id) / "state.json"
        if not path.exists():
            raise KeyError(f"unknown subagent: {subagent_id}")
        return SubagentRecord(**json.loads(path.read_text(encoding="utf-8")))

    def _save_record(self, record: SubagentRecord) -> None:
        path = Path(record.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, json.dumps(asdict(record), ensure_ascii=False, indent=2) + "\n")

    def _refresh_running_status(self, record: SubagentRecord) -> None:
        if record.status not in {"running", "queued", "cancel_requested"}:
            return
        thread = self._threads.get(record.subagent_id)
        if thread and thread.is_alive():
            return
        record.status = "interrupted"
        record.error = record.error or "subagent process is not running; inspect events and start a new task if needed"
        record.finished_at = record.finished_at or time.time()
        self._save_record(record)

    def _mark_stale_running_records(self) -> None:
        for path in self.run_dir.glob("*/state.json"):
            try:
                record = SubagentRecord(**json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            self._refresh_running_status(record)


class _SubagentFileSink(EventSink):
    def __init__(self, events_path: Path, downstream: Optional[EventSink] = None) -> None:
        self.events_path = events_path
        self.downstream = downstream or NullSink()
        self._lock = threading.Lock()
        self._seq = 1

    def emit(self, event: Event) -> None:
        with self._lock:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "seq": self._seq,
                "time": time.time(),
                "kind": event.kind,
                "data": event.data,
            }
            self._seq += 1
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self.downstream.emit(event)


def _read_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"kind": "invalid_event", "data": {"text": line[:MAX_EVENT_OUTPUT_CHARS]}})
    return rows


def _read_jsonl_output_window(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = _read_jsonl_tail(path, max(limit * 5, 80))
    if len(rows) <= limit:
        return rows
    tail = rows[-limit:]
    if any(_is_tool_dispatch_event(event) for event in tail):
        return tail
    key_event = next((event for event in reversed(rows) if _is_tool_dispatch_event(event)), None)
    if key_event is None:
        if any(_is_output_anchor_event(event) for event in tail):
            return tail
        key_event = next((event for event in reversed(rows) if _is_output_anchor_event(event)), None)
    if key_event is None:
        if any(_is_key_subagent_event(event) for event in tail):
            return tail
        key_event = next((event for event in reversed(rows) if _is_key_subagent_event(event)), None)
        if key_event is None:
            return tail
    selected = tail[1:] if len(tail) >= limit else tail
    keyed = {_event_key(event): event for event in selected}
    keyed[_event_key(key_event)] = key_event
    return sorted(keyed.values(), key=lambda event: int(event.get("seq") or 0))


def _is_tool_dispatch_event(event: dict[str, Any]) -> bool:
    return str(event.get("kind") or "") == "tool_dispatch"


def _is_output_anchor_event(event: dict[str, Any]) -> bool:
    return str(event.get("kind") or "") in {"tool_dispatch", "tool_result"}


def _is_key_subagent_event(event: dict[str, Any]) -> bool:
    return str(event.get("kind") or "") in {
        "tool_dispatch",
        "tool_result",
        "assistant_message",
        "turn_completed",
        "turn_failed",
        "turn_paused",
    }


def _event_key(event: dict[str, Any]) -> str:
    if event.get("seq") is not None:
        return f"seq-{event.get('seq')}"
    return json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_name = f.name
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_name = f.name
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return safe or "subagent"
