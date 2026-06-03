from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from mini_agent_lab.events import Event, EventSink, NullSink
from mini_agent_lab.plan import parse_plan_todos


MAX_PREVIEW_CHARS = 1200
MAX_RECENT_EVENTS = 50
MAX_FILE_CHANGES = 30


class RunRecorder(EventSink):
    """Persist agent events for replay and keep a compact status snapshot for UI previews."""

    def __init__(
        self,
        directory: str | Path = ".runs",
        run_id: str = "run",
        session_id: Optional[str] = None,
        downstream: Optional[EventSink] = None,
        record_downstream: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.directory = Path(directory)
        self.run_id = _safe_id(run_id)
        self.session_id = session_id or self.run_id
        self.downstream = downstream or NullSink()
        self.record_downstream = record_downstream
        self.event_path = self.directory / f"{self.run_id}.events.jsonl"
        self.summary_path = self.directory / f"{self.run_id}.summary.json"
        self._lock = threading.Lock()
        self._seq = self._load_next_seq()
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=MAX_RECENT_EVENTS)
        self._summary = self._load_or_create_summary()

    def emit(self, event: Event) -> None:
        with self._lock:
            now = time.time()
            record = {
                "seq": self._seq,
                "time": now,
                "time_text": _format_time(now),
                "kind": event.kind,
                "data": event.data,
            }
            self._seq += 1
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.event_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

            self._apply_event(record)
            self._write_summary()
            record_for_downstream = dict(record)
        self.downstream.emit(event)
        if self.record_downstream is not None:
            self.record_downstream(record_for_downstream)

    def _load_next_seq(self) -> int:
        if not self.event_path.exists():
            return 1
        seq = 0
        for line in self.event_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                seq = max(seq, int(json.loads(line).get("seq", 0)))
            except (ValueError, json.JSONDecodeError):
                continue
        return seq + 1

    def _load_or_create_summary(self) -> dict[str, Any]:
        if self.summary_path.exists():
            try:
                raw = json.loads(self.summary_path.read_text(encoding="utf-8"))
                for item in raw.get("recent_events", [])[-MAX_RECENT_EVENTS:]:
                    self._recent_events.append(item)
                return raw
            except json.JSONDecodeError:
                pass
        now = time.time()
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": "created",
            "started_at": now,
            "started_at_text": _format_time(now),
            "updated_at": now,
            "updated_at_text": _format_time(now),
            "event_path": str(self.event_path),
            "summary_path": str(self.summary_path),
            "turn_count": 0,
            "tool_calls": 0,
            "tool_results": 0,
            "todo": None,
            "git": None,
            "file_changes": [],
            "current_tool": None,
            "current_command": None,
            "jobs": {},
            "subagents": {},
            "last_notice": "",
            "last_error": "",
            "final_answer": "",
            "pending_plan": None,
            "plan_revision_count": 0,
            "recent_events": [],
            "ledger": {
                "objective": "",
                "task_type": "",
                "status": "running",
                "success_criteria": [],
                "completed": [],
                "current_focus": "",
                "changed_files": [],
                "validations": [],
                "artifacts": [],
                "local_services": [],
                "open_risks": [],
                "handoff_notes": [],
            },
        }

    def _apply_event(self, record: dict[str, Any]) -> None:
        kind = record["kind"]
        data = record["data"]
        self._summary["updated_at"] = record["time"]
        self._summary["updated_at_text"] = record["time_text"]
        self._remember_recent(record)

        if kind == "turn_started":
            pending_plan = self._summary.get("pending_plan")
            if isinstance(pending_plan, dict) and pending_plan.get("status") == "awaiting_approval":
                self._summary["last_pending_plan"] = pending_plan
            self._summary["status"] = "running"
            self._summary["turn_count"] = int(self._summary.get("turn_count", 0)) + 1
            self._summary["current_input"] = _preview(data.get("input", ""))
            self._summary["final_answer"] = ""
            self._summary["pending_plan"] = None
            self._summary["last_error"] = ""
            self._summary["current_tool"] = None
            self._summary["cancel_requested"] = False
            return

        if kind == "assistant_message":
            self._summary["last_assistant_message"] = _preview(data.get("content", ""))
            self._summary["pending_tool_calls"] = [
                call.get("name", "") for call in data.get("tool_calls", []) if isinstance(call, dict)
            ]
            return

        if kind == "notice":
            self._summary["last_notice"] = str(data.get("message", ""))
            return

        if kind == "turn_status":
            self._summary["status"] = data.get("status") or self._summary.get("status", "running")
            self._summary["phase"] = data.get("phase")
            self._summary["phase_message"] = data.get("message", "")
            return

        if kind in {"step_started", "step_progress", "step_completed", "step_failed"}:
            self._summary["current_step"] = {
                "step_id": data.get("step_id"),
                "title": data.get("title"),
                "message": data.get("message") or data.get("summary") or data.get("error") or "",
                "status": kind.replace("step_", ""),
            }
            if kind == "step_failed":
                self._summary["last_error"] = _preview(data.get("error", "step failed"))
            return

        if kind in {"action_started", "action_completed", "action_failed"}:
            self._summary["current_action"] = {
                "action_id": data.get("action_id"),
                "step_id": data.get("step_id"),
                "kind": data.get("kind"),
                "title": data.get("title"),
                "summary": data.get("summary") or data.get("error") or "",
                "status": kind.replace("action_", ""),
            }
            if kind == "action_failed":
                self._summary["last_error"] = _preview(data.get("error", "action failed"))
            return

        if kind == "assistant_message_completed":
            self._summary["last_assistant_message"] = _preview(data.get("content", ""))
            self._ledger_update("handoff_notes", _preview(data.get("content", "")))
            return

        if kind == "provider_error":
            self._summary["provider_error"] = _compact_value(data)
            self._summary["last_error"] = _preview(data.get("message") or data.get("kind") or "provider error")
            self._ledger_update("open_risks", f'Provider error: {data.get("kind")} — {_preview(data.get("message", ""))}')
            return

        if kind == "tool_dispatch":
            self._summary["status"] = "tool_running"
            self._summary["tool_calls"] = int(self._summary.get("tool_calls", 0)) + 1
            self._summary["current_tool"] = {
                "id": data.get("id"),
                "name": data.get("name"),
                "arguments": _compact_value(data.get("arguments", {})),
                "subagent_id": data.get("subagent_id"),
                "parent_tool_call_id": data.get("parent_tool_call_id"),
            }
            return

        if kind == "tool_result":
            result = str(data.get("output", data.get("result", "")))
            model_summary = str(data.get("model_summary", "")) or result
            ok = bool(data.get("ok", not result.startswith(("error:", "blocked:"))))
            error = str(data.get("error", ""))
            error_kind = str(data.get("error_kind", ""))
            self._summary["status"] = "running"
            self._summary["tool_results"] = int(self._summary.get("tool_results", 0)) + 1
            self._summary["current_tool"] = None
            self._summary["last_tool_result"] = {
                "id": data.get("id"),
                "name": data.get("name"),
                "result": _preview(result),
                "output": _preview(result),
                "model_summary": _preview(model_summary),
                "ok": ok,
                "error": _preview(error),
                "error_kind": error_kind,
                "blocked": bool(data.get("blocked", False)),
                "truncated": bool(data.get("truncated", False)),
                "subagent_id": data.get("subagent_id"),
                "parent_tool_call_id": data.get("parent_tool_call_id"),
            }
            if not ok:
                self._summary["last_error"] = _preview(error or result)
            return

        if kind == "subagent_started":
            self._summary["status"] = "subagent_running"
            subagents = dict(self._summary.get("subagents", {}))
            subagent_id = str(data.get("subagent_id", ""))
            subagents[subagent_id] = {
                "subagent_id": subagent_id,
                "parent_tool_call_id": data.get("parent_tool_call_id"),
                "task": _preview(data.get("task", "")),
                "tools": _compact_value(data.get("tools", [])),
                "max_steps": data.get("max_steps"),
                "status": "running",
            }
            self._summary["subagents"] = subagents
            return

        if kind == "subagent_completed":
            subagents = dict(self._summary.get("subagents", {}))
            subagent_id = str(data.get("subagent_id", ""))
            subagent = dict(subagents.get(subagent_id, {"subagent_id": subagent_id}))
            subagent.update(
                {
                    "status": "completed",
                    "answer": _preview(data.get("answer", "")),
                    "tools": _compact_value(data.get("tools", [])),
                    "max_steps": data.get("max_steps"),
                }
            )
            subagents[subagent_id] = subagent
            self._summary["subagents"] = subagents
            self._summary["status"] = "running"
            return

        if kind == "subagent_failed":
            subagents = dict(self._summary.get("subagents", {}))
            subagent_id = str(data.get("subagent_id", ""))
            subagent = dict(subagents.get(subagent_id, {"subagent_id": subagent_id}))
            subagent.update(
                {
                    "status": "failed",
                    "error": _preview(data.get("error", "")),
                    "tools": _compact_value(data.get("tools", [])),
                    "max_steps": data.get("max_steps"),
                }
            )
            subagents[subagent_id] = subagent
            self._summary["subagents"] = subagents
            self._summary["status"] = "running"
            self._summary["last_error"] = _preview(data.get("error", "subagent failed"))
            return

        if kind == "subagent_cancel_requested":
            subagents = dict(self._summary.get("subagents", {}))
            subagent_id = str(data.get("subagent_id", ""))
            subagent = dict(subagents.get(subagent_id, {"subagent_id": subagent_id}))
            subagent["status"] = "cancel_requested"
            subagent["parent_tool_call_id"] = data.get("parent_tool_call_id") or subagent.get("parent_tool_call_id")
            subagents[subagent_id] = subagent
            self._summary["subagents"] = subagents
            return

        if kind == "subagent_cancelled":
            subagents = dict(self._summary.get("subagents", {}))
            subagent_id = str(data.get("subagent_id", ""))
            subagent = dict(subagents.get(subagent_id, {"subagent_id": subagent_id}))
            subagent.update(
                {
                    "status": "cancelled",
                    "answer": _preview(data.get("answer", "")),
                    "parent_tool_call_id": data.get("parent_tool_call_id") or subagent.get("parent_tool_call_id"),
                }
            )
            subagents[subagent_id] = subagent
            self._summary["subagents"] = subagents
            self._summary["status"] = "running"
            return

        if data.get("subagent_id") and kind.startswith("git_"):
            self._apply_subagent_git_event(kind, data)
            return

        if kind == "todo_updated":
            self._summary["todo"] = {
                "completed": data.get("completed"),
                "total": data.get("total"),
                "pending": data.get("pending"),
                "in_progress": data.get("in_progress"),
                "progress_text": data.get("progress_text"),
                "done": data.get("done"),
                "current": _compact_value(data.get("current")),
                "todos": _compact_value(data.get("todos", [])),
            }
            return

        if kind == "preview":
            changes = list(self._summary.get("file_changes", []))
            changes.append(
                {
                    "kind": data.get("kind"),
                    "path": data.get("path"),
                    "diff": _preview(data.get("diff", "")),
                    "source": data.get("source") or data.get("tool_name"),
                }
            )
            self._summary["file_changes"] = changes[-MAX_FILE_CHANGES:]
            return

        if kind == "workspace_changes_detected":
            changes = list(self._summary.get("file_changes", []))
            for item in data.get("changes", []):
                if not isinstance(item, dict):
                    continue
                changes.append(
                    {
                        "kind": item.get("kind"),
                        "path": item.get("path"),
                        "diff": _preview(item.get("diff", "")),
                        "source": item.get("source") or data.get("source_kind"),
                        "recoverable": bool(item.get("recoverable", False)),
                        "note": _preview(item.get("note", "")),
                    }
                )
            self._summary["file_changes"] = changes[-MAX_FILE_CHANGES:]
            return

        if kind == "checkpoint_saved":
            self._summary["last_checkpoint"] = {
                "id": data.get("id"),
                "path": data.get("path"),
            }
            return

        if kind == "git_baseline_captured":
            self._summary["git"] = {
                "baseline_path": data.get("path"),
                "is_repo": data.get("is_repo"),
                "root": data.get("root"),
                "branch": data.get("branch"),
                "head": data.get("head"),
                "baseline_dirty": data.get("dirty_count"),
                "error": data.get("error"),
            }
            return

        if kind == "git_changes_classified":
            git = dict(self._summary.get("git") or {})
            git.update(_compact_value(data))
            self._summary["git"] = git
            if data.get("overlap"):
                self._summary["last_error"] = _preview(f"git overlap risk: {data.get('overlap')}")
            return

        if kind == "git_baseline_failed":
            git = dict(self._summary.get("git") or {})
            git["error"] = data.get("error")
            self._summary["git"] = git
            self._summary["last_error"] = _preview(data.get("error", "git baseline failed"))
            return

        if kind == "git_classify_failed":
            git = dict(self._summary.get("git") or {})
            git["classify_error"] = data.get("error")
            self._summary["git"] = git
            self._summary["last_error"] = _preview(data.get("error", "git classify failed"))
            return

        if kind == "git_baseline_missing":
            git = dict(self._summary.get("git") or {})
            git["baseline_missing"] = _compact_value(data)
            self._summary["git"] = git
            return

        if kind == "git_overlap_risk":
            git = dict(self._summary.get("git") or {})
            risks = list(git.get("overlap_risks", []))
            risks.append(_compact_value(data))
            git["overlap_risks"] = risks[-MAX_FILE_CHANGES:]
            self._summary["git"] = git
            self._summary["last_error"] = _preview(f"git overlap risk: {data.get('path')}")
            return

        if kind == "git_commit_started":
            git = dict(self._summary.get("git") or {})
            git["commit"] = {
                "status": "running",
                "files": _compact_value(data.get("files", [])),
                "message": data.get("message", ""),
                "risk": _compact_value(data.get("risk", {})),
            }
            self._summary["git"] = git
            return

        if kind == "git_commit_done":
            git = dict(self._summary.get("git") or {})
            git["commit"] = {
                "status": "done",
                "files": _compact_value(data.get("files", [])),
                "message": data.get("message", ""),
                "head": data.get("head"),
                "branch": data.get("branch"),
                "risk": _compact_value(data.get("risk", {})),
            }
            self._summary["git"] = git
            return

        if kind == "git_commit_failed":
            git = dict(self._summary.get("git") or {})
            git["commit"] = {
                "status": "failed",
                "files": _compact_value(data.get("files", [])),
                "error": data.get("error"),
            }
            self._summary["git"] = git
            self._summary["last_error"] = _preview(data.get("error", "git commit failed"))
            return

        if kind == "command_started":
            self._summary["status"] = "command_running"
            self._summary["current_command"] = {
                "command_id": data.get("command_id"),
                "command": data.get("command"),
                "pid": data.get("pid"),
                "timeout_seconds": data.get("timeout_seconds"),
                "output_preview": "",
            }
            return

        if kind == "command_output":
            self._summary["last_command_output"] = {
                "command_id": data.get("command_id"),
                "text": _preview(data.get("text", "")),
            }
            current = self._summary.get("current_command")
            if isinstance(current, dict) and current.get("command_id") == data.get("command_id"):
                current["output_preview"] = _preview(str(current.get("output_preview", "")) + str(data.get("text", "")))
            return

        if kind == "command_finished":
            self._summary["status"] = "running"
            self._summary["last_command"] = _compact_value(data)
            self._summary["current_command"] = None
            if data.get("exit_code") not in {0, None} or data.get("timed_out"):
                self._summary["last_error"] = _preview(
                    f"command failed exit={data.get('exit_code')} timed_out={data.get('timed_out')}"
                )
            return

        if kind == "job_started":
            self._summary["status"] = "job_running"
            jobs = dict(self._summary.get("jobs", {}))
            jobs[str(data.get("job_id"))] = {
                "job_id": data.get("job_id"),
                "kind": data.get("kind"),
                "command": _preview(data.get("command", "")),
                "label": data.get("label"),
                "pid": data.get("pid"),
                "log_path": data.get("log_path"),
                "status": "running",
                "output_preview": "",
            }
            self._summary["jobs"] = jobs
            return

        if kind == "job_output":
            self._summary["last_job_output"] = {
                "job_id": data.get("job_id"),
                "text": _preview(data.get("text", "")),
                "log_path": data.get("log_path"),
            }
            jobs = dict(self._summary.get("jobs", {}))
            job_id = str(data.get("job_id"))
            job = dict(jobs.get(job_id, {"job_id": job_id}))
            job["output_preview"] = _preview(str(job.get("output_preview", "")) + str(data.get("text", "")))
            job["log_path"] = data.get("log_path") or job.get("log_path")
            jobs[job_id] = job
            self._summary["jobs"] = jobs
            return

        if kind == "job_finished":
            jobs = dict(self._summary.get("jobs", {}))
            job_id = str(data.get("job_id"))
            job = dict(jobs.get(job_id, {"job_id": job_id}))
            job.update(
                {
                    "status": data.get("status"),
                    "exit_code": data.get("exit_code"),
                    "duration_ms": data.get("duration_ms"),
                    "log_path": data.get("log_path") or job.get("log_path"),
                }
            )
            jobs[job_id] = job
            self._summary["jobs"] = jobs
            self._summary["last_job"] = _compact_value(data)
            if not any(isinstance(item, dict) and item.get("status") == "running" for item in jobs.values()):
                self._summary["status"] = "running"
            if data.get("status") not in {"done", "killed"}:
                self._summary["last_error"] = _preview(f"job {job_id} {data.get('status')}")
            return

        if kind == "safety_ask":
            self._summary["status"] = "waiting_approval"
            self._summary["approval"] = _compact_value(data)
            return

        if kind == "safety_approved":
            self._summary["status"] = "running"
            self._summary["approval"] = _compact_value({**data, "status": "approved"})
            return

        if kind in {"safety_deny", "plan_blocked", "compact_failed"}:
            self._summary["last_error"] = _preview(data.get("reason") or data.get("error") or str(data))
            return

        if kind == "plan_pending":
            revision = _coerce_int(data.get("revision"))
            if revision <= 0:
                revision = int(self._summary.get("plan_revision_count", 0)) + 1
            plan_text = str(data.get("plan_text") or "")
            todos = data.get("todos")
            if not isinstance(todos, list):
                todos = parse_plan_todos(plan_text)
            self._summary["plan_revision_count"] = revision
            self._summary["status"] = "awaiting_plan_decision"
            self._summary["pending_plan"] = {
                "status": data.get("status") or "awaiting_approval",
                "plan_text": plan_text,
                "todos": _compact_value(todos),
                "todo_count": len(todos),
                "revision": revision,
                "created_at": record["time"],
                "created_at_text": record["time_text"],
            }
            return

        if kind == "plan_approved":
            plan_text = str(data.get("plan_text") or "")
            todos = data.get("todos")
            if not isinstance(todos, list):
                todos = parse_plan_todos(plan_text)
            revision = _coerce_int(data.get("revision")) or int(self._summary.get("plan_revision_count", 0))
            self._summary["status"] = "running"
            self._summary["pending_plan"] = {
                "status": "approved",
                "plan_text": plan_text,
                "todos": _compact_value(todos),
                "todo_count": len(todos),
                "revision": revision,
                "approved_at": record["time"],
                "approved_at_text": record["time_text"],
            }
            return

        if kind == "plan_cancelled":
            self._summary["status"] = "completed"
            self._summary["pending_plan"] = {
                "status": "cancelled",
                "plan_text": str(data.get("plan_text") or ""),
                "revision": _coerce_int(data.get("revision")) or int(self._summary.get("plan_revision_count", 0)),
                "cancelled_at": record["time"],
                "cancelled_at_text": record["time_text"],
            }
            return

        if kind == "turn_cancel_requested":
            self._summary["status"] = "cancelling" if data.get("running") else self._summary.get("status", "created")
            self._summary["cancel_requested"] = bool(data.get("running"))
            return

        if kind == "compact_started":
            self._summary["status"] = "compacting"
            self._summary["compact"] = _compact_value(data)
            return

        if kind == "compact_done":
            self._summary["status"] = "running"
            self._summary["compact"] = _compact_value(data)
            return

        if kind == "turn_completed":
            pending_plan = self._summary.get("pending_plan")
            self._summary["status"] = (
                "awaiting_plan_decision"
                if isinstance(pending_plan, dict) and pending_plan.get("status") == "awaiting_approval"
                else "completed"
            )
            self._summary["final_answer"] = _preview(data.get("answer", ""))
            self._summary["current_tool"] = None
            self._summary["completed_at"] = record["time"]
            self._summary["completed_at_text"] = record["time_text"]
            self._summary["cancel_requested"] = False
            return

        if kind == "turn_paused":
            self._summary["status"] = "paused"
            self._summary["last_error"] = _preview(data.get("message", ""))
            self._summary["current_tool"] = None
            self._summary["cancel_requested"] = False

        if kind == "turn_failed":
            self._summary["status"] = "failed"
            self._summary["last_error"] = _preview(data.get("error", "turn failed"))
            if data.get("provider_error"):
                self._summary["provider_error"] = _compact_value(data.get("provider_error"))
                provider_message = data.get("provider_error", {}).get("message")
                if provider_message:
                    self._summary["last_error"] = _preview(provider_message)
            self._summary["current_tool"] = None
            self._summary["current_command"] = None
            self._summary["pending_tool_calls"] = []
            self._summary["cancel_requested"] = False
            self._summary["recoverable"] = bool(data.get("recoverable", False))

        # ── Ledger auto-update events ──

        if kind == "turn_status":
            phase = data.get("phase", "")
            message = data.get("message", "")
            self._ledger_update("current_focus", f"{phase}: {message}" if phase else message)
            return

        if kind == "verification_completed":
            command = data.get("command", "")
            summary = data.get("summary", "")
            self._ledger_append("validations", {
                "command": command,
                "status": "passed",
                "summary": summary,
            })
            return

        if kind == "verification_failed":
            command = data.get("command", "")
            error = data.get("summary", data.get("error", ""))
            self._ledger_append("validations", {
                "command": command,
                "status": "failed",
                "summary": error,
            })
            self._ledger_update("open_risks", f"Validation failed: {command} — {error}")
            return

        if kind == "file_edited":
            path = data.get("path", "")
            if path and path not in self._summary["ledger"]["changed_files"]:
                self._ledger_append("changed_files", path)
            return

        if kind == "command_finished":
            command = data.get("command", "")
            exit_code = data.get("exit_code")
            if command and exit_code is not None:
                status = "passed" if exit_code == 0 else "failed"
                summary = data.get("output_preview", "")
                self._ledger_append("validations", {
                    "command": command,
                    "status": status,
                    "summary": _preview(summary) if summary else f"exit_code={exit_code}",
                })
            return

    def _ledger_update(self, field: str, value: str) -> None:
        """Update a single-value ledger field."""
        ledger = self._summary.setdefault("ledger", {})
        ledger[field] = value

    def _ledger_append(self, field: str, item: Any) -> None:
        """Append to a list ledger field, skipping duplicates."""
        ledger = self._summary.setdefault("ledger", {})
        items = ledger.setdefault(field, [])
        if item not in items:
            items.append(item)

    def _apply_subagent_git_event(self, kind: str, data: dict[str, Any]) -> None:
        subagents = dict(self._summary.get("subagents", {}))
        subagent_id = str(data.get("subagent_id", ""))
        subagent = dict(subagents.get(subagent_id, {"subagent_id": subagent_id}))
        git = dict(subagent.get("git") or {})

        if kind == "git_baseline_captured":
            git.update(
                {
                    "baseline_path": data.get("path"),
                    "is_repo": data.get("is_repo"),
                    "root": data.get("root"),
                    "branch": data.get("branch"),
                    "head": data.get("head"),
                    "baseline_dirty": data.get("dirty_count"),
                    "error": data.get("error"),
                }
            )
        elif kind == "git_changes_classified":
            git.update(_compact_value(data))
        else:
            git[kind] = _compact_value(data)
            if data.get("error"):
                git["error"] = data.get("error")

        subagent["git"] = git
        subagents[subagent_id] = subagent
        self._summary["subagents"] = subagents

    def _remember_recent(self, record: dict[str, Any]) -> None:
        self._recent_events.append(
            {
                "seq": record["seq"],
                "time_text": record["time_text"],
                "kind": record["kind"],
                "data": _compact_value(record["data"]),
            }
        )
        self._summary["recent_events"] = list(self._recent_events)

    def _write_summary(self) -> None:
        self.summary_path.write_text(
            json.dumps(self._summary, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return safe or "run"


def _format_time(value: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def _preview(value: Any, max_chars: int = MAX_PREVIEW_CHARS) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2
    omitted = len(text) - keep * 2
    return text[:keep] + f"\n...[{omitted} chars omitted]...\n" + text[-keep:]


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_value(item) for item in value[:MAX_RECENT_EVENTS]]
    if isinstance(value, str):
        return _preview(value)
    return value
