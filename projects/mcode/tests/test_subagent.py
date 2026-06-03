"""Tests for task/subagent delegation."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.events import Event, EventSink
from mini_agent_lab.provider import ProviderResponse, ToolCall
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.subagent import effective_subagent_max_steps, run_subagent
from mini_agent_lab.subagent_manager import SubagentManager
from mini_agent_lab.tool import default_registry
from mini_agent_lab.tool.builtin import EchoTool
from mini_agent_lab.tool.registry import ToolRegistry
from mini_agent_lab.tool.task import TaskTool


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


class CaptureSink(EventSink):
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


class ScriptedProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self.responses = list(responses)
        self.tool_schemas: list[list[dict]] = []

    def complete(self, messages: list[Any], tools: list[dict]) -> ProviderResponse:
        self.tool_schemas.append(tools)
        if not self.responses:
            raise AssertionError("provider exhausted")
        return self.responses.pop(0)


def test_effective_steps_are_bounded() -> None:
    _assert(effective_subagent_max_steps(300, 0) == 150, "default child steps are half of parent")
    _assert(effective_subagent_max_steps(8, 0) == 8, "small parent step limit is preserved")
    _assert(effective_subagent_max_steps(300, 500) == 300, "requested child steps are capped by parent")
    _assert(effective_subagent_max_steps(300, 4) == 4, "explicit smaller child step limit is honored")


def test_run_subagent_filters_tools_and_nests_events() -> None:
    registry = ToolRegistry()
    registry.add(EchoTool())
    registry.add(TaskTool(lambda args: "should not be reachable"))
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="",
                tool_calls=[ToolCall(id="child-call", name="echo", arguments={"text": "child saw it"})],
            ),
            ProviderResponse(content="child done"),
        ]
    )
    sink = CaptureSink()

    result = run_subagent(
        provider=provider,
        parent_registry=registry,
        task="echo something",
        parent_max_steps=20,
        allowed_tools=[],
        sink=sink,
        parent_tool_call_id="parent-call",
        subagent_id="sub-1",
    )
    schema_names = {tool["name"] for tool in provider.tool_schemas[0]}
    dispatch = next(event for event in sink.events if event.kind == "tool_dispatch")

    _assert(result.answer == "child done", "subagent returns the child final answer")
    _assert("echo" in schema_names and "task" not in schema_names, "subagent tool schema excludes meta tools")
    _assert(dispatch.data["subagent_id"] == "sub-1", "nested tool dispatch includes subagent id")
    _assert(dispatch.data["parent_tool_call_id"] == "parent-call", "nested event points to parent tool call")
    _assert(dispatch.data["id"] == "parent-call/child-call", "nested tool call id is namespaced")
    _assert(any(event.kind == "subagent_completed" for event in sink.events), "subagent completion event is emitted")


def test_task_tool_passes_parent_call_id_inside_agent_loop() -> None:
    seen: dict[str, Any] = {}

    def runner(arguments: dict) -> str:
        seen.update(arguments)
        return "delegated answer"

    registry = ToolRegistry()
    registry.add(TaskTool(runner))
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="task-call",
                        name="task",
                        arguments={"prompt": "inspect x", "description": "inspect", "tools": ["echo"]},
                    )
                ],
            ),
            ProviderResponse(content="parent done"),
        ]
    )
    agent = Agent(provider=provider, tools=registry, session=Session("system"))
    answer = agent.run("delegate")
    tool_message = next(message for message in agent.session.messages if message.role == "tool")
    payload = json.loads(tool_message.content)

    _assert(answer == "parent done", "parent loop continues after task result")
    _assert(seen["_tool_call_id"] == "task-call", "task runner receives parent tool call id")
    _assert(payload["answer"] == "delegated answer", "task tool returns subagent answer as JSON")


def test_subagent_git_events_do_not_replace_parent_git_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(directory=tmp, run_id="subagent-git")
        recorder.emit(
            Event(
                "git_baseline_captured",
                {
                    "path": "parent.json",
                    "is_repo": True,
                    "root": "/repo",
                    "branch": "main",
                    "head": "abc",
                    "dirty_count": 1,
                    "error": "",
                },
            )
        )
        recorder.emit(
            Event(
                "subagent_started",
                {
                    "subagent_id": "sub-1",
                    "parent_tool_call_id": "call-1",
                    "task": "inspect",
                    "tools": ["git_status"],
                    "max_steps": 5,
                },
            )
        )
        recorder.emit(
            Event(
                "git_baseline_captured",
                {
                    "subagent_id": "sub-1",
                    "parent_tool_call_id": "call-1",
                    "path": "child.json",
                    "is_repo": True,
                    "root": "/repo",
                    "branch": "main",
                    "head": "def",
                    "dirty_count": 2,
                    "error": "",
                },
            )
        )
        summary = json.loads(Path(tmp, "subagent-git.summary.json").read_text(encoding="utf-8"))

    _assert(summary["git"]["baseline_path"] == "parent.json", "parent git summary is preserved")
    _assert(
        summary["subagents"]["sub-1"]["git"]["baseline_path"] == "child.json",
        "subagent git summary is nested under subagents",
    )


def test_subagent_manager_foreground_persists_state_events_and_session() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        registry.add(EchoTool())
        provider = ScriptedProvider(
            [
                ProviderResponse(
                    content="",
                    tool_calls=[ToolCall(id="echo-1", name="echo", arguments={"text": "hello"})],
                ),
                ProviderResponse(content="done"),
            ]
        )
        manager = SubagentManager(
            root_dir=Path(tmp) / "subagents",
            parent_session_id="parent",
            provider=provider,
            registry_getter=lambda: registry,
            parent_max_steps=20,
            gitstate_dir=Path(tmp) / "gitstate",
        )
        result = manager.run_task({"prompt": "echo hello", "description": "demo"})
        record = manager.status(result["subagent_id"])["subagents"][0]
        output = manager.output(result["subagent_id"], limit=10)

        _assert(result["subagent"] == "completed", "manager foreground run completes")
        _assert(record["status"] == "completed", "manager persists completed status")
        _assert(Path(record["events_path"]).exists(), "manager persists subagent events")
        _assert(Path(record["session_path"]).exists(), "manager persists child session")
        _assert(any(event["kind"] == "tool_dispatch" for event in output["events"]), "subagent output returns recent events")


def test_subagent_manager_background_wait_and_tools() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        registry.add(EchoTool())
        provider = ScriptedProvider(
            [
                ProviderResponse(
                    content="",
                    tool_calls=[ToolCall(id="echo-1", name="echo", arguments={"text": "background"})],
                ),
                ProviderResponse(content="background done"),
            ]
        )
        manager = SubagentManager(
            root_dir=Path(tmp) / "subagents",
            parent_session_id="parent",
            provider=provider,
            registry_getter=lambda: registry,
            parent_max_steps=20,
            gitstate_dir=Path(tmp) / "gitstate",
        )
        started = manager.run_task(
            {"prompt": "echo in background", "description": "bg", "run_in_background": True}
        )
        waited = manager.wait(started["subagent_id"], timeout_seconds=5)
        tool_registry = default_registry(task_runner=manager.run_task, subagent_manager=manager)
        names = set(tool_registry.names())

        _assert(started["subagent"] == "started", "background task returns immediately with subagent id")
        _assert(waited["status"] == "completed", "wait_subagent can wait for background completion")
        _assert(
            {"task", "subagent_status", "subagent_output", "wait_subagent", "cancel_subagent"}.issubset(names),
            "default registry includes subagent management tools",
        )


def test_subagent_manager_marks_stale_running_records_interrupted() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "subagents"
        run_dir = root / "parent" / "stale"
        run_dir.mkdir(parents=True)
        state = {
            "subagent_id": "stale",
            "parent_session_id": "parent",
            "parent_tool_call_id": "call-1",
            "description": "stale",
            "task": "old task",
            "status": "running",
            "tools": ["echo"],
            "max_steps": 5,
            "run_in_background": True,
            "created_at": 1.0,
            "started_at": 1.0,
            "finished_at": 0.0,
            "answer": "",
            "error": "",
            "state_path": str(run_dir / "state.json"),
            "events_path": str(run_dir / "events.jsonl"),
            "session_path": str(run_dir / "session.jsonl"),
            "git_baseline_path": str(Path(tmp) / "gitstate" / "stale.json"),
        }
        Path(state["state_path"]).write_text(json.dumps(state), encoding="utf-8")
        registry = ToolRegistry()
        registry.add(EchoTool())
        manager = SubagentManager(
            root_dir=root,
            parent_session_id="parent",
            provider=ScriptedProvider([]),
            registry_getter=lambda: registry,
            parent_max_steps=20,
            gitstate_dir=Path(tmp) / "gitstate",
        )
        record = manager.status("stale")["subagents"][0]

        _assert(record["status"] == "interrupted", "stale running subagent is marked interrupted on startup")


if __name__ == "__main__":
    test_effective_steps_are_bounded()
    test_run_subagent_filters_tools_and_nests_events()
    test_task_tool_passes_parent_call_id_inside_agent_loop()
    test_subagent_git_events_do_not_replace_parent_git_summary()
    test_subagent_manager_foreground_persists_state_events_and_session()
    test_subagent_manager_background_wait_and_tools()
    test_subagent_manager_marks_stale_running_records_interrupted()
    print("All subagent tests passed.")
