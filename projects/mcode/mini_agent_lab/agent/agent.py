from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from mini_agent_lab.agent.session import Session
from mini_agent_lab.checkpoint import CheckpointStore
from mini_agent_lab.compact import compact_session, session_chars
from mini_agent_lab.app_config import ContextConfig
from mini_agent_lab.events import Event, EventSink, NullSink
from mini_agent_lab.git_state import GitState, classify_changes, load_snapshot, save_snapshot
from mini_agent_lab.plan import compose_plan_input
from mini_agent_lab.provider import DeepSeekProvider, Message, ProviderError, ProviderResponse
from mini_agent_lab.safety import Approver, SafetyGate
from mini_agent_lab.tool.todo import todo_event_data
from mini_agent_lab.tool.registry import ToolRegistry
from mini_agent_lab.trace import TraceEmitter, diff_stats, trace_action_kind, trace_action_title


MAX_TOOL_OUTPUT_CHARS = 12000
MAX_MODEL_TOOL_SUMMARY_CHARS = 4000
MODEL_SUMMARY_TAIL_LINES = 40
STORM_BREAK_THRESHOLD = 3
PLAN_MODE_HIDDEN_TOOLS = {"todo_write", "complete_step"}


@dataclass
class ToolOutcome:
    output: str
    ok: bool
    model_summary: str = ""
    error: str = ""
    error_kind: str = ""
    blocked: bool = False
    truncated: bool = False
    truncation_notice: str = ""


class Agent:
    """Minimal model-tool loop.

    This mirrors the core Reasonix idea:
    user message -> model -> tool calls -> tool results -> model -> final answer.
    """

    def __init__(
        self,
        provider: DeepSeekProvider,
        tools: ToolRegistry,
        session: Session,
        max_steps: int = 300,
        safety_gate: Optional[SafetyGate] = None,
        approver: Optional[Approver] = None,
        checkpoints: Optional[CheckpointStore] = None,
        context_config: Optional[ContextConfig] = None,
        archive_dir: str = ".archives",
        sink: Optional[EventSink] = None,
        git_baseline_path: Optional[str | Path] = None,
        git_state: Optional[GitState] = None,
        cancelled: Optional[Callable[[], bool]] = None,
        show_thought_summary: bool = True,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.session = session
        self.max_steps = max_steps
        self.safety_gate = safety_gate or SafetyGate()
        self.approver = approver or Approver()
        self.checkpoints = checkpoints or CheckpointStore()
        self.context_config = context_config or ContextConfig()
        self.archive_dir = archive_dir
        self.sink = sink or NullSink()
        self.plan_mode = False
        self.git_baseline_path = Path(git_baseline_path) if git_baseline_path else None
        self.git_state = git_state or GitState()
        self.cancelled = cancelled or (lambda: False)
        self._storm_signature = ""
        self._storm_count = 0
        self._last_user_message = ""   # For AutoReviewAgent context
        self.trace = TraceEmitter(self.sink, thought_summary_enabled=show_thought_summary)

    def set_plan_mode(self, enabled: bool) -> None:
        self.plan_mode = enabled

    def _model_tool_schemas(self) -> list[dict]:
        schemas = self.tools.schemas()
        if not self.plan_mode:
            return schemas
        return [
            schema
            for schema in schemas
            if self.tools.get(schema["name"]).read_only and schema["name"] not in PLAN_MODE_HIDDEN_TOOLS
        ]

    def _compose_user_input(self, user_input: str) -> str:
        if not self.plan_mode:
            return user_input
        return compose_plan_input(user_input)

    def run(self, user_input: str) -> str:
        self.sink.emit(Event("turn_started", {"input": user_input, "plan": self.plan_mode}))
        self.trace.turn_status("running", "understanding", "正在理解需求")
        self.trace.thought_started()
        self.trace.thought_delta("正在理解需求")
        self.trace.step_started("step-understand", "理解需求")
        self.trace.step_completed("step-understand", "已接收用户请求")
        self._last_user_message = user_input
        self._capture_git_baseline()
        self.session.add("user", self._compose_user_input(user_input))

        for step in range(self.max_steps):
            model_step_id = f"step-{step + 1}-model"
            tool_step_id = f"step-{step + 1}-tools"
            if self.cancelled():
                message = "cancelled before model call"
                self.trace.turn_status("cancelled", "cancelled", message)
                self.trace.thought_completed("已取消")
                self.sink.emit(Event("turn_paused", {"message": message, "cancelled": True}))
                return message
            try:
                self.trace.turn_status("running", "model_call", "正在生成下一步")
                self.trace.step_started(model_step_id, "生成下一步")
                assistant_message_id = f"assistant-{step + 1}"
                response, assistant_trace_emitted = self._complete_model_response(
                    tools=self._model_tool_schemas(),
                    message_id=assistant_message_id,
                    step_id=model_step_id,
                )
            except ProviderError as exc:
                self.trace.step_failed(model_step_id, str(exc))
                return self._recover_provider_failure(exc)
            except Exception as exc:
                self.trace.step_failed(model_step_id, str(exc))
                return self._recover_unexpected_model_failure(exc)

            tool_call_events = [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                for call in response.tool_calls or []
            ]
            if response.content and not assistant_trace_emitted:
                self._emit_assistant_trace(assistant_message_id, response.content, tool_call_events)
            self.session.messages.append(
                Message(
                    role="assistant",
                    content=response.content or "",
                    reasoning=response.reasoning or "",
                    tool_calls=response.tool_calls or None,
                )
            )
            self.sink.emit(
                Event(
                    "assistant_message",
                    {
                        "content": response.content or "",
                        "reasoning": response.reasoning or "",
                        "tool_calls": [
                            {
                                "id": call.id,
                                "name": call.name,
                                "arguments": call.arguments,
                            }
                            for call in response.tool_calls or []
                        ],
                    },
                )
            )

            if not response.tool_calls:
                self.trace.step_completed(model_step_id, "已生成最终回答")
                final_answer = response.content or ""
                if not final_answer.strip():
                    final_answer = self._recover_empty_final_answer()
                self._classify_git_changes_at_end()
                self.trace.turn_status("running", "finalizing", "正在完成交付")
                self.trace.step_started("step-final", "完成交付")
                self.trace.step_completed("step-final", "最终回答已生成")
                self.trace.thought_completed("已完成")
                if self.plan_mode and final_answer.strip():
                    self.sink.emit(
                        Event(
                            "plan_pending",
                            {
                                "plan_text": final_answer,
                                "status": "awaiting_approval",
                            },
                        )
                    )
                self.sink.emit(Event("turn_completed", {"answer": final_answer}))
                return final_answer

            self.trace.step_completed(model_step_id, f"模型请求 {len(response.tool_calls)} 个工具调用")
            self.trace.turn_status("running", "executing_tools", "正在执行工具调用")
            self.trace.step_started(tool_step_id, "执行工具调用")
            self.sink.emit(
                Event(
                    "notice",
                    {"message": f"step {step + 1}: model requested {len(response.tool_calls)} tool call(s)"},
                )
            )
            outcomes: list[ToolOutcome] = []
            for call in response.tool_calls:
                action_id = call.id or f"action-{step + 1}-{len(outcomes) + 1}"
                action_kind = trace_action_kind(call.name, call.arguments)
                action_title = trace_action_title(call.name, call.arguments)
                if self.cancelled():
                    outcomes.append(
                        ToolOutcome(
                            output="blocked: subagent was cancelled",
                            ok=False,
                            error="subagent was cancelled",
                            error_kind="cancelled",
                            blocked=True,
                        )
                    )
                    self.trace.action_failed(action_id, "subagent was cancelled")
                    continue
                self.trace.action_started(
                    action_id,
                    tool_step_id,
                    action_kind,
                    action_title,
                    tool_name=call.name,
                    arguments=call.arguments,
                )
                self.sink.emit(
                    Event(
                        "tool_dispatch",
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                            "arguments_json": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    )
                )
                outcome = self._execute_tool_call(call.name, call.arguments, call_id=call.id, trace_step_id=tool_step_id)
                outcomes.append(outcome)
                if outcome.ok:
                    self.trace.action_completed(action_id, _trace_outcome_summary(call.name, call.arguments, outcome))
                    self._emit_action_detail_trace(action_kind, tool_step_id, action_id, call.name, call.arguments, outcome)
                else:
                    if action_kind == "verification":
                        command = str(call.arguments.get("command") or call.arguments.get("path") or call.name)
                        self.trace.verification_completed(
                            command,
                            status="failed",
                            summary=outcome.error or outcome.output,
                            step_id=tool_step_id,
                            action_id=action_id,
                        )
                    self.trace.action_failed(action_id, outcome.error or outcome.output, blocked=outcome.blocked)

            self._apply_storm_breaker(response.tool_calls, outcomes)

            for call, outcome in zip(response.tool_calls, outcomes):
                self.sink.emit(Event("tool_result", _tool_result_event_data(call.id, call.name, outcome)))
                if outcome.truncated and outcome.truncation_notice:
                    self.sink.emit(Event("notice", {"message": outcome.truncation_notice}))
                self.session.messages.append(
                    Message(
                        role="tool",
                        content=outcome.model_summary or outcome.output,
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

            self._maybe_compact()
            self.trace.step_completed(tool_step_id, "工具调用已返回")

        message = f"paused after {self.max_steps} tool-call round(s)"
        self._classify_git_changes_at_end()
        self.trace.turn_status("paused", "max_steps", message)
        self.trace.thought_completed("已暂停")
        self.sink.emit(Event("turn_paused", {"message": message, "max_steps": self.max_steps}))
        return message

    def _complete_model_response(self, tools: list[dict], message_id: str, step_id: str = "") -> tuple[ProviderResponse, bool]:
        stream_complete = getattr(self.provider, "stream_complete", None)
        if not callable(stream_complete):
            return self.provider.complete(self.session.messages, tools=tools), False

        started = False
        reasoning_summary_emitted = False
        tool_call_states: dict[int, dict[str, object]] = {}
        completed: ProviderResponse | None = None
        try:
            for event in stream_complete(self.session.messages, tools=tools):
                if event.kind == "content_delta":
                    if not started:
                        self.trace.assistant_started(message_id)
                        started = True
                    self.trace.assistant_delta(message_id, event.delta)
                elif event.kind == "reasoning_delta":
                    if not reasoning_summary_emitted:
                        self.trace.thought_delta("正在分析上下文")
                        reasoning_summary_emitted = True
                elif event.kind == "tool_call_delta":
                    index = event.tool_call_index if event.tool_call_index is not None else 0
                    state = tool_call_states.setdefault(index, {"started": False, "received_chars": 0, "id": "", "name": ""})
                    if event.tool_call_id:
                        state["id"] = event.tool_call_id
                    if event.tool_call_name:
                        state["name"] = event.tool_call_name
                    if not state["started"]:
                        self.trace.tool_call_started(
                            message_id,
                            index,
                            tool_call_id=str(state["id"]),
                            tool_name=str(state["name"]),
                            step_id=step_id,
                        )
                        state["started"] = True
                    delta_chars = len(event.delta or "")
                    state["received_chars"] = int(state["received_chars"]) + delta_chars
                    self.trace.tool_call_delta(
                        message_id,
                        index,
                        delta_chars=delta_chars,
                        received_chars=int(state["received_chars"]),
                        tool_call_id=str(state["id"]),
                        tool_name=str(state["name"]),
                        step_id=step_id,
                    )
                elif event.kind == "message_completed":
                    completed = event.response
        except Exception as exc:
            if started:
                self.trace.assistant_failed(message_id, str(exc))
            raise

        if completed is None:
            error = ProviderError(kind="bad_response", message="stream ended without completed message", retryable=False)
            if started:
                self.trace.assistant_failed(message_id, error.message)
            raise error

        if started:
            self.trace.assistant_completed(message_id, completed.content, _tool_call_events(completed.tool_calls or []))
        for index, call in enumerate(completed.tool_calls or []):
            if index in tool_call_states:
                self.trace.tool_call_completed(
                    message_id,
                    index,
                    tool_call_id=call.id,
                    tool_name=call.name,
                    step_id=step_id,
                )
        return completed, started

    def _recover_provider_failure(self, exc: ProviderError) -> str:
        answer = _provider_failure_answer(exc)
        data = {
            "error": str(exc),
            "recoverable": True,
            "provider_error": {
                "kind": exc.kind,
                "message": exc.message,
                "status_code": exc.status_code,
                "retryable": exc.retryable,
                "attempt": exc.attempt,
                "request_id": exc.request_id,
            },
        }
        self.session.messages.append(Message(role="assistant", content=answer))
        self._classify_git_changes_at_end()
        self.sink.emit(Event("provider_error", data["provider_error"]))
        self._emit_assistant_trace("assistant-recovery-provider", answer, [])
        self.trace.turn_status("failed", "provider_error", exc.message)
        self.trace.thought_completed("模型请求失败")
        self.sink.emit(Event("assistant_message", {"content": answer, "tool_calls": []}))
        self.sink.emit(Event("turn_failed", data))
        return answer

    def _recover_unexpected_model_failure(self, exc: Exception) -> str:
        message = f"{type(exc).__name__}: {exc}"
        answer = "模型请求失败，本轮没有继续执行工具。你可以直接重试，或换一种更小的请求继续。"
        self.session.messages.append(Message(role="assistant", content=answer))
        self._classify_git_changes_at_end()
        self._emit_assistant_trace("assistant-recovery-unexpected", answer, [])
        self.trace.turn_status("failed", "provider_error", message)
        self.trace.thought_completed("模型请求失败")
        self.sink.emit(Event("assistant_message", {"content": answer, "tool_calls": []}))
        self.sink.emit(Event("turn_failed", {"error": message, "recoverable": True}))
        return answer

    def _recover_empty_final_answer(self) -> str:
        if self.plan_mode:
            prompt = "你刚才返回了空内容。请只输出简洁、可执行的计划，不要调用工具。"
        else:
            prompt = (
                "请基于刚才的工具结果直接给出最终回答，不要再调用工具。"
                "回答要简洁，只说明结果、关键文件和实际验证情况；"
                "不要输出完整工作回顾、长日志或逐步流水账。"
            )
        self.sink.emit(Event("notice", {"message": "empty final answer; requesting concise handoff"}))
        self.session.messages.append(Message(role="user", content=prompt))
        try:
            response = self.provider.complete(self.session.messages, tools=[])
        except Exception as exc:
            fallback = "任务已完成，但模型没有返回最终文本。请查看上方工具结果和生成文件。"
            self.sink.emit(Event("notice", {"message": f"empty final recovery failed: {exc}"}))
            self.session.messages.append(Message(role="assistant", content=fallback))
            self._emit_assistant_trace("assistant-empty-final-fallback", fallback, [])
            self.sink.emit(Event("assistant_message", {"content": fallback, "tool_calls": []}))
            return fallback
        final_answer = response.content.strip() or "任务已完成。请查看上方工具结果和生成文件。"
        self.session.messages.append(Message(role="assistant", content=final_answer))
        self._emit_assistant_trace("assistant-empty-final-recovered", final_answer, [])
        self.sink.emit(Event("assistant_message", {"content": final_answer, "tool_calls": []}))
        return final_answer

    def _capture_git_baseline(self) -> None:
        if self.git_baseline_path is None:
            return
        snapshot = self.git_state.snapshot()
        try:
            path = save_snapshot(snapshot, self.git_baseline_path)
        except Exception as exc:
            self.sink.emit(Event("git_baseline_failed", {"error": str(exc)}))
            return
        self.sink.emit(
            Event(
                "git_baseline_captured",
                {
                    "path": str(path),
                    "is_repo": snapshot.is_repo,
                    "root": snapshot.root,
                    "branch": snapshot.branch,
                    "head": snapshot.head,
                    "dirty_count": snapshot.dirty_count,
                    "error": snapshot.error,
                },
            )
        )

    def _session_summary(self) -> str:
        """Build a brief summary of the session for the auto-review agent."""
        lines = []
        for msg in self.session.messages[-8:]:  # Last 8 messages max
            role = msg.role
            content = msg.content or ""
            if role == "user":
                lines.append(f"[User] {content[:200]}")
            elif role == "assistant" and content:
                lines.append(f"[Assistant] {content[:200]}")
            elif role == "tool":
                lines.append(f"[Tool Result] {msg.name or 'unknown'}: {content[:100]}")
        return "\n".join(lines) if lines else "(no prior context)"

    def _execute_tool_call(self, name: str, arguments: dict, call_id: str = "", trace_step_id: str = "") -> ToolOutcome:
        try:
            tool = self.tools.get(name)
        except KeyError as exc:
            return ToolOutcome(
                output=f"error: {exc}",
                ok=False,
                error=str(exc),
                error_kind="unknown_tool",
            )

        if self.plan_mode and not tool.read_only:
            self.sink.emit(Event("plan_blocked", {"tool_name": name, "arguments": arguments}))
            output = (
                f"blocked: {name} is not available in plan mode. "
                "Plan mode is read-only; inspect with read-only tools, then write the plan as your reply."
            )
            return ToolOutcome(
                output=output,
                ok=False,
                error="plan mode is read-only",
                error_kind="blocked",
                blocked=True,
            )

        safety = self.safety_gate.check(name, arguments, tool.read_only)
        if safety.decision == "deny":
            self.sink.emit(Event("safety_deny", {"tool_name": name, "arguments": arguments, "reason": safety.reason}))
            return ToolOutcome(
                output=f"blocked: {safety.reason}",
                ok=False,
                error=safety.reason,
                error_kind="safety_deny",
                blocked=True,
            )
        self._print_preview_if_available(name, tool, arguments, call_id=call_id, trace_step_id=trace_step_id)
        git_ok, git_reason = self._check_git_write_overlap(name, arguments, tool.read_only)
        if not git_ok:
            return ToolOutcome(
                output=f"blocked: {git_reason}",
                ok=False,
                error=git_reason,
                error_kind="blocked",
                blocked=True,
            )
        if safety.decision == "ask":
            # Auto-review agent first, then escalate to human if needed
            auto_approved = False
            if getattr(self.safety_gate, "auto_review_agent", None) is not None:
                ar_decision, ar_reason = self.safety_gate.review_ask(
                    tool_name=name,
                    arguments=arguments,
                    safety_reason=safety.reason,
                    user_message=self._last_user_message,
                    session_summary=self._session_summary(),
                    plan_mode=self.plan_mode,
                )
                if ar_decision == "approve":
                    self.sink.emit(Event("auto_review_approved", {
                        "tool_name": name, "arguments": arguments,
                        "reason": ar_reason,
                    }))
                    auto_approved = True
                elif ar_decision == "reject":
                    self.sink.emit(Event("auto_review_rejected", {
                        "tool_name": name, "arguments": arguments,
                        "reason": ar_reason,
                    }))
                    return ToolOutcome(
                        output=f"blocked: auto-review rejected — {ar_reason}",
                        ok=False,
                        error=ar_reason,
                        error_kind="auto_review_rejected",
                        blocked=True,
                    )
                else:  # escalate — fall through to human Approver
                    self.sink.emit(Event("auto_review_escalated", {
                        "tool_name": name, "arguments": arguments,
                        "reason": ar_reason,
                    }))

            if not auto_approved:
                if not self.approver.approve(name, arguments, safety.reason):
                    reason = f"user denied {name}"
                    self.sink.emit(Event("safety_deny", {"tool_name": name, "arguments": arguments, "reason": reason}))
                    return ToolOutcome(
                        output=f"blocked: {reason}",
                        ok=False,
                        error=reason,
                        error_kind="blocked",
                        blocked=True,
                    )
                self.sink.emit(Event("safety_approved", {"tool_name": name, "arguments": arguments, "reason": safety.reason}))

        checkpoint_note = ""
        if not tool.read_only:
            checkpoint_note = self._save_checkpoint_if_available(name, tool, arguments)

        try:
            runtime_arguments = dict(arguments)
            if call_id:
                runtime_arguments["_tool_call_id"] = call_id
            result = tool.execute(runtime_arguments)
            if name == "todo_write":
                self._emit_todo_updated(arguments)
            if name == "git_classify_changes":
                self._emit_git_classified(result)
            if checkpoint_note:
                result = result + "\n" + checkpoint_note
            output, truncated, notice = _truncate_tool_output(result)
            model_summary = _summarize_tool_result(name, result, ok=True)
            return ToolOutcome(
                output=output,
                ok=True,
                model_summary=model_summary,
                truncated=truncated,
                truncation_notice=notice,
            )
        except Exception as exc:
            raw_error = f"error: {exc}"
            output, truncated, notice = _truncate_tool_output(raw_error)
            model_summary = _summarize_tool_result(name, raw_error, ok=False, error=str(exc))
            return ToolOutcome(
                output=output,
                ok=False,
                model_summary=model_summary,
                error=str(exc),
                error_kind=_classify_tool_exception(exc),
                truncated=truncated,
                truncation_notice=notice,
            )

    def _emit_assistant_trace(self, message_id: str, content: str, tool_calls: list[dict]) -> None:
        self.trace.assistant_started(message_id)
        self.trace.assistant_delta(message_id, content)
        self.trace.assistant_completed(message_id, content, tool_calls)

    def _emit_action_detail_trace(
        self,
        action_kind: str,
        step_id: str,
        action_id: str,
        tool_name: str,
        arguments: dict,
        outcome: ToolOutcome,
    ) -> None:
        path = str(arguments.get("path") or "").strip()
        if action_kind == "file_read" and path:
            self.trace.file_read(path, step_id=step_id, action_id=action_id)
        if action_kind == "verification":
            command = str(arguments.get("command") or arguments.get("path") or tool_name)
            status = "passed" if outcome.ok else "failed"
            self.trace.verification_completed(command, status=status, summary=_trace_outcome_summary(tool_name, arguments, outcome), step_id=step_id, action_id=action_id)

    def _apply_storm_breaker(self, calls, outcomes: list[ToolOutcome]) -> None:
        if len(calls) != 1 or not outcomes or outcomes[0].ok or outcomes[0].blocked:
            self._storm_signature = ""
            self._storm_count = 0
            return

        outcome = outcomes[0]
        signature = f"{calls[0].name}\x00{outcome.error_kind}\x00{outcome.error}"
        if signature != self._storm_signature:
            self._storm_signature = signature
            self._storm_count = 1
            return

        self._storm_count += 1
        if self._storm_count < STORM_BREAK_THRESHOLD:
            return

        guard = (
            f'\n\n[loop guard] "{calls[0].name}" has failed {self._storm_count} times in a row '
            "with the same error. Repeating the same tool call is unlikely to help. "
            "Change approach: fix the arguments, inspect with another tool, split the work into smaller calls, "
            "or explain the blocker in your final answer."
        )
        output, truncated, notice = _truncate_tool_output(outcome.output + guard)
        outcome.output = output
        outcome.model_summary = _summarize_tool_result(calls[0].name, output, ok=False, error=outcome.error)
        outcome.truncated = outcome.truncated or truncated
        outcome.truncation_notice = outcome.truncation_notice or notice
        self.sink.emit(
            Event(
                "notice",
                {
                    "message": (
                        f"loop guard: {calls[0].name} failed {self._storm_count} times "
                        "the same way; nudging the model to change approach"
                    )
                },
            )
        )

    def _emit_todo_updated(self, arguments: dict) -> None:
        self.sink.emit(Event("todo_updated", todo_event_data(arguments)))

    def _emit_git_classified(self, result: str) -> None:
        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            return
        current = data.get("current", {})
        self.sink.emit(
            Event(
                "git_changes_classified",
                {
                    "current_dirty": len(current.get("porcelain", [])),
                    "user_existing": data.get("user_existing", []),
                    "agent_created": data.get("agent_created", []),
                    "agent_modified": data.get("agent_modified", []),
                    "overlap": data.get("overlap", []),
                    "resolved_baseline_dirty": data.get("resolved_baseline_dirty", []),
                },
            )
        )

    def _classify_git_changes_at_end(self) -> None:
        if self.git_baseline_path is None or not self.git_baseline_path.exists():
            return
        try:
            baseline = load_snapshot(self.git_baseline_path)
            if not baseline.is_repo:
                return
            current = self.git_state.snapshot()
            if not current.is_repo:
                self.sink.emit(
                    Event(
                        "git_classify_failed",
                        {
                            "baseline_path": str(self.git_baseline_path),
                            "error": current.error or "current directory is not a git repository",
                        },
                    )
                )
                return
            classified = classify_changes(baseline, current)
        except Exception as exc:
            self.sink.emit(
                Event(
                    "git_classify_failed",
                    {
                        "baseline_path": str(self.git_baseline_path),
                        "error": str(exc),
                    },
                )
            )
            return
        self.sink.emit(
            Event(
                "git_changes_classified",
                {
                    "current_dirty": classified.current.dirty_count,
                    "user_existing": classified.user_existing,
                    "agent_created": classified.agent_created,
                    "agent_modified": classified.agent_modified,
                    "overlap": classified.overlap,
                    "resolved_baseline_dirty": classified.resolved_baseline_dirty,
                },
            )
        )

    def _check_git_write_overlap(self, tool_name: str, arguments: dict, read_only: bool) -> tuple[bool, str]:
        if read_only or self.git_baseline_path is None:
            return True, ""
        target = arguments.get("path")
        if not target:
            return True, ""
        if not self.git_baseline_path.exists():
            self.sink.emit(
                Event(
                    "git_baseline_missing",
                    {
                        "baseline_path": str(self.git_baseline_path),
                        "tool_name": tool_name,
                        "path": str(target),
                    },
                )
            )
            return True, ""

        try:
            baseline = load_snapshot(self.git_baseline_path)
        except Exception as exc:
            self.sink.emit(
                Event(
                    "git_baseline_failed",
                    {
                        "baseline_path": str(self.git_baseline_path),
                        "tool_name": tool_name,
                        "path": str(target),
                        "error": str(exc),
                    },
                )
            )
            return True, ""

        if not baseline.is_repo or not baseline.root:
            return True, ""

        rel_path = _repo_relative_path(str(target), baseline.root)
        if rel_path is None:
            return True, ""

        dirty_by_path = {entry.path: entry for entry in baseline.porcelain}
        entry = dirty_by_path.get(rel_path)
        if entry is None:
            return True, ""

        reason = (
            f"{rel_path} had uncommitted changes before this agent turn "
            f"({entry.raw}); modifying it may mix user and agent edits"
        )
        data = {
            "path": rel_path,
            "target": str(target),
            "baseline_path": str(self.git_baseline_path),
            "status_at_baseline": entry.raw,
            "tool_name": tool_name,
            "reason": reason,
        }
        self.sink.emit(Event("git_overlap_risk", data))
        if not self.approver.approve(tool_name, arguments, reason):
            return False, "user denied write to baseline-dirty file"
        return True, ""

    def _print_preview_if_available(self, tool_name: str, tool, arguments: dict, call_id: str = "", trace_step_id: str = "") -> None:
        if not _has_preview(tool):
            return
        try:
            change = tool.preview(arguments)
        except Exception as exc:
            print(f"[preview] unavailable: {exc}")
            return
            self.sink.emit(
                Event(
                    "preview",
                {
                    "kind": change.kind,
                    "path": change.path,
                    "diff": change.diff,
                    "tool_name": tool_name,
                    "tool_call_id": call_id,
                        "source": tool_name,
                    },
                )
            )
            additions, deletions = diff_stats(change.diff)
            self.trace.file_edited(
                change.path,
                step_id=trace_step_id or "step-preview",
                action_id=call_id,
                additions=additions,
                deletions=deletions,
                diff_preview=change.diff[:1200],
            )

    def _save_checkpoint_if_available(self, tool_name: str, tool, arguments: dict) -> str:
        if not _has_preview(tool):
            return ""
        try:
            change = tool.preview(arguments)
            cp = self.checkpoints.save(change, tool_name, arguments)
        except Exception as exc:
            return f"[checkpoint] skipped: {exc}"
        self.sink.emit(Event("checkpoint_saved", {"id": cp.id, "path": change.path, "tool_name": tool_name, "source": tool_name}))
        return f"[checkpoint] saved {cp.id}"

    def _maybe_compact(self) -> None:
        cfg = self.context_config
        before_chars = session_chars(self.session)
        self.sink.emit(
            Event(
                "compact_check",
                {
                    "chars": before_chars,
                    "trigger_chars": cfg.trigger_chars,
                    "auto_compact": cfg.auto_compact,
                },
            )
        )
        if not cfg.auto_compact:
            self.sink.emit(Event("compact_skipped", {"reason": "auto_compact_disabled"}))
            return
        if before_chars < cfg.trigger_chars:
            self.sink.emit(
                Event(
                    "compact_skipped",
                    {
                        "reason": "below_trigger",
                        "chars": before_chars,
                        "trigger_chars": cfg.trigger_chars,
                    },
                )
            )
            return

        self.sink.emit(
            Event(
                "compact_started",
                {
                    "chars": before_chars,
                    "trigger_chars": cfg.trigger_chars,
                    "recent_keep": cfg.recent_keep,
                    "summary_mode": cfg.summary_mode,
                },
            )
        )
        try:
            result = compact_session(
                self.session,
                recent_keep=cfg.recent_keep,
                archive_dir=self.archive_dir,
                provider=self.provider,
                context_config=cfg,
            )
        except Exception as exc:
            self.sink.emit(Event("compact_failed", {"error": str(exc), "chars": before_chars}))
            return

        if result.changed:
            after_chars = session_chars(self.session)
            self.sink.emit(
                Event(
                    "compact_done",
                    {
                        "archive_path": result.archive_path,
                        "archived_messages": result.original_messages - result.kept_messages + 1,
                        "original_messages": result.original_messages,
                        "kept_messages": result.kept_messages,
                        "before_chars": before_chars,
                        "after_chars": after_chars,
                        "trigger_chars": cfg.trigger_chars,
                        "summary_chars": len(result.summary),
                    },
                )
            )
            return

        self.sink.emit(
            Event(
                "compact_skipped",
                {
                    "reason": "no_compactable_region",
                    "chars": before_chars,
                    "messages": result.original_messages,
                },
            )
        )


def _has_preview(tool) -> bool:
    return callable(getattr(tool, "preview", None))


def _tool_result_event_data(call_id: str, name: str, outcome: ToolOutcome) -> dict:
    return {
        "id": call_id,
        "name": name,
        "result": outcome.output,
        "output": outcome.output,
        "model_summary": outcome.model_summary or outcome.output,
        "ok": outcome.ok,
        "error": outcome.error,
        "error_kind": outcome.error_kind,
        "blocked": outcome.blocked,
        "truncated": outcome.truncated,
    }


def _tool_call_events(tool_calls: list) -> list[dict]:
    return [
        {
            "id": call.id,
            "name": call.name,
            "arguments": call.arguments,
        }
        for call in tool_calls
    ]


def _trace_outcome_summary(tool_name: str, arguments: dict, outcome: ToolOutcome) -> str:
    if outcome.model_summary:
        return outcome.model_summary.splitlines()[0][:220]
    if outcome.output:
        return outcome.output.splitlines()[0][:220]
    path = str(arguments.get("path") or "").strip()
    if path:
        return f"{tool_name} {path}"
    return tool_name


def _classify_tool_exception(exc: Exception) -> str:
    if isinstance(exc, (TypeError, ValueError, json.JSONDecodeError)):
        return "invalid_args"
    return "tool_error"


def _provider_failure_answer(exc: ProviderError) -> str:
    if exc.kind == "network_timeout":
        return "模型请求超时，本轮没有继续执行工具。网络恢复后可以直接继续发送下一条消息。"
    if exc.kind == "network_reset":
        return "模型请求遇到网络连接问题，本轮已停止但对话记录已保留。你可以直接重试或继续下一步。"
    if exc.kind == "rate_limit":
        return "模型 API 当前限流，本轮已停止。稍后重试即可，对话记录和已完成步骤都已保留。"
    if exc.kind == "context_length":
        return "当前上下文过长，模型没有接受请求。请让我先压缩上下文，或用更小范围的问题继续。"
    if exc.kind == "auth_error":
        return "模型 API 鉴权失败，本轮已停止。请检查 API Key 或项目配置后继续。"
    if exc.kind == "server_error":
        return "模型服务暂时不可用，本轮没有继续执行工具。稍后可以直接重试。"
    if exc.kind == "bad_response":
        return "模型返回格式异常，本轮已停止但 transcript 已保留。可以直接重试或换一种问法继续。"
    return "模型请求失败，本轮已停止但对话记录已保留。你可以直接重试或继续下一步。"


def _truncate_tool_output(text: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> tuple[str, bool, str]:
    if len(text) <= max_chars:
        return text, False, ""
    keep = max_chars // 2
    omitted = len(text) - (keep * 2)
    notice = f"tool output truncated: {omitted} of {len(text)} characters omitted"
    output = (
        text[:keep]
        + f"\n\n[tool output truncated: {omitted} characters omitted]\n\n"
        + text[-keep:]
    )
    return output, True, notice


def _summarize_tool_result(name: str, text: str, ok: bool, error: str = "") -> str:
    if len(text) <= MAX_MODEL_TOOL_SUMMARY_CHARS and not _looks_like_command_result(text):
        return text

    lines: list[str] = [f"[tool summary] name={name} ok={str(ok).lower()}"]
    footer = _extract_command_footer(text)
    if footer:
        lines.append(footer)
    if error:
        lines.append(f"error={_one_line(error)}")

    traceback = _extract_python_traceback(text)
    if traceback:
        lines.append("")
        lines.append("[python traceback]")
        lines.append(traceback)

    important = _extract_important_error_lines(text)
    if important:
        lines.append("")
        lines.append("[important output]")
        lines.extend(important)

    tail = _tail_lines_without_footer(text, MODEL_SUMMARY_TAIL_LINES)
    if tail:
        lines.append("")
        lines.append(f"[last {min(MODEL_SUMMARY_TAIL_LINES, len(tail))} output lines]")
        lines.extend(tail)

    summary = "\n".join(lines).strip()
    if len(summary) <= MAX_MODEL_TOOL_SUMMARY_CHARS:
        return summary
    keep = MAX_MODEL_TOOL_SUMMARY_CHARS
    return summary[: keep // 2] + "\n\n[model summary truncated]\n\n" + summary[-keep // 2 :]


def _looks_like_command_result(text: str) -> bool:
    return bool(re.search(r"\[(?:python|command)\]\s+exit_code=", text))


def _extract_command_footer(text: str) -> str:
    matches = re.findall(r"\[(?:python|command)\]\s+exit_code=.*", text)
    return matches[-1].strip() if matches else ""


def _extract_python_traceback(text: str) -> str:
    match = re.search(r"Traceback \(most recent call last\):.*?(?=\n\[(?:python|command)\]|\Z)", text, re.S)
    if not match:
        return ""
    traceback_lines = [line.rstrip() for line in match.group(0).strip().splitlines()]
    if len(traceback_lines) <= 18:
        return "\n".join(traceback_lines)
    head = traceback_lines[:8]
    tail = traceback_lines[-10:]
    return "\n".join(head + [f"...[{len(traceback_lines) - len(head) - len(tail)} traceback lines omitted]..."] + tail)


def _extract_important_error_lines(text: str, limit: int = 12) -> list[str]:
    important: list[str] = []
    patterns = ("error", "failed", "failure", "exception", "traceback", "assertionerror", "pytest")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower()
        if any(pattern in lower for pattern in patterns) and line not in important:
            important.append(line)
        if len(important) >= limit:
            break
    return important


def _tail_lines_without_footer(text: str, limit: int) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if lines and re.match(r"\[(?:python|command)\]\s+exit_code=", lines[-1]):
        lines = lines[:-1]
    return lines[-limit:]


def _one_line(text: str, limit: int = 500) -> str:
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."


def _repo_relative_path(path: str, repo_root: str) -> Optional[str]:
    root = Path(repo_root).expanduser().resolve(strict=False)
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve(strict=False)
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return None
