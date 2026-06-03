from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.app_config import ContextConfig
from mini_agent_lab.events import Event, EventSink, NullSink
from mini_agent_lab.git_state import GitState
from mini_agent_lab.provider import DeepSeekProvider
from mini_agent_lab.safety import Approver, SafetyGate
from mini_agent_lab.tool.registry import ToolRegistry


DEFAULT_SUBAGENT_SYSTEM_PROMPT = """You are a focused Mcode subagent.
Work on only the delegated task. Use the available tools when useful, then return a concise final answer.
Do not ask the user directly; report blockers to the parent agent."""


SUBAGENT_META_TOOLS = {
    "task",
    "run_skill",
    "install_skill",
    "list_skills",
    "read_skill",
    "todo_write",
    "git_commit",
    "subagent_status",
    "subagent_output",
    "wait_subagent",
    "cancel_subagent",
}


_SUBAGENT_COUNTER = itertools.count(1)


@dataclass(frozen=True)
class SubagentResult:
    subagent_id: str
    answer: str
    max_steps: int
    tools: list[str]
    session_messages: list[dict]


class NestedSink(EventSink):
    """Forward useful child events with parent/subagent metadata attached."""

    def __init__(
        self,
        downstream: Optional[EventSink],
        parent_tool_call_id: str = "",
        subagent_id: str = "",
    ) -> None:
        self.downstream = downstream or NullSink()
        self.parent_tool_call_id = parent_tool_call_id
        self.subagent_id = subagent_id

    def emit(self, event: Event) -> None:
        if event.kind in {
            "turn_started",
            "assistant_message",
            "turn_completed",
            "turn_paused",
            "compact_check",
            "compact_skipped",
        }:
            return

        data = dict(event.data)
        if self.parent_tool_call_id:
            data["parent_tool_call_id"] = self.parent_tool_call_id
        if self.subagent_id:
            data["subagent_id"] = self.subagent_id
        if data.get("id") and self.parent_tool_call_id:
            data["id"] = f"{self.parent_tool_call_id}/{data['id']}"
        self.downstream.emit(Event(event.kind, data))


def filter_registry(
    parent: ToolRegistry,
    allowed: Optional[Iterable[str]] = None,
    exclude: Optional[set[str]] = None,
) -> ToolRegistry:
    child = ToolRegistry()
    allowed_set = {name for name in (allowed or []) if name}
    excluded = set(SUBAGENT_META_TOOLS)
    if exclude:
        excluded.update(exclude)

    for name, tool in parent.items():
        if name in excluded:
            continue
        if allowed_set and name not in allowed_set:
            continue
        child.add(tool)
    return child


def run_subagent(
    *,
    provider: DeepSeekProvider,
    parent_registry: ToolRegistry,
    task: str,
    parent_max_steps: int,
    allowed_tools: Optional[list[str]] = None,
    max_steps: int = 0,
    system_prompt: str = "",
    safety_gate: Optional[SafetyGate] = None,
    approver: Optional[Approver] = None,
    context_config: Optional[ContextConfig] = None,
    archive_dir: str = ".archives",
    sink: Optional[EventSink] = None,
    parent_tool_call_id: str = "",
    subagent_id: str = "",
    git_baseline_path: Optional[str | Path] = None,
    git_state: Optional[GitState] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> SubagentResult:
    if not task.strip():
        raise ValueError("subagent task is required")

    child_registry = filter_registry(parent_registry, allowed_tools)
    tools = child_registry.names()
    if not tools:
        raise ValueError("subagent has no tools available after filtering")

    child_id = subagent_id or f"subagent-{next(_SUBAGENT_COUNTER)}"
    steps = effective_subagent_max_steps(parent_max_steps, max_steps)
    downstream = sink or NullSink()
    downstream.emit(
        Event(
            "subagent_started",
            {
                "subagent_id": child_id,
                "parent_tool_call_id": parent_tool_call_id,
                "task": task,
                "tools": tools,
                "max_steps": steps,
            },
        )
    )
    child_sink = NestedSink(downstream, parent_tool_call_id=parent_tool_call_id, subagent_id=child_id)
    session = Session(system_prompt or DEFAULT_SUBAGENT_SYSTEM_PROMPT)
    child = Agent(
        provider=provider,
        tools=child_registry,
        session=session,
        max_steps=steps,
        safety_gate=safety_gate,
        approver=approver,
        context_config=context_config,
        archive_dir=archive_dir,
        sink=child_sink,
        git_baseline_path=git_baseline_path,
        git_state=git_state,
        cancelled=cancelled,
    )

    try:
        answer = child.run(task)
    except Exception as exc:
        downstream.emit(
            Event(
                "subagent_failed",
                {
                    "subagent_id": child_id,
                    "parent_tool_call_id": parent_tool_call_id,
                    "error": str(exc),
                    "max_steps": steps,
                    "tools": tools,
                },
            )
        )
        raise

    downstream.emit(
        Event(
            "subagent_completed",
            {
                "subagent_id": child_id,
                "parent_tool_call_id": parent_tool_call_id,
                "answer": answer,
                "max_steps": steps,
                "tools": tools,
            },
        )
    )
    return SubagentResult(
        subagent_id=child_id,
        answer=answer,
        max_steps=steps,
        tools=tools,
        session_messages=[message.to_dict() for message in session.messages],
    )


def effective_subagent_max_steps(parent_max_steps: int, requested: int = 0) -> int:
    parent = int(parent_max_steps or 0)
    req = int(requested or 0)
    if parent <= 0:
        return max(req, 5) if req > 0 else 5
    if req > 0:
        return max(1, min(req, parent))
    if parent < 10:
        return parent
    return max(5, parent // 2)
