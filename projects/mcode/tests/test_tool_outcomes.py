"""Tests for structured tool outcomes and loop-guard behavior."""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent, MAX_MODEL_TOOL_SUMMARY_CHARS, MAX_TOOL_OUTPUT_CHARS
from mini_agent_lab.app_config import ContextConfig
from mini_agent_lab.provider import Message, ProviderResponse, ToolCall
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.tool import Tool, ToolRegistry
from mini_agent_lab.tool.base import JsonObject


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


class ScriptedProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self.responses = list(responses)

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        if not self.responses:
            raise AssertionError("provider called too many times")
        return self.responses.pop(0)


class TestTool(Tool):
    def __init__(self, name: str, output: str = "ok", read_only: bool = True, error: Exception | None = None) -> None:
        self._name = name
        self.output = output
        self._read_only = read_only
        self.error = error
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "test tool"

    @property
    def schema(self) -> JsonObject:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return self._read_only

    def execute(self, arguments: JsonObject) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


@dataclass
class SafetyDecision:
    decision: str
    reason: str


class FixedSafetyGate:
    def __init__(self, decision: str = "allow", reason: str = "test policy") -> None:
        self.decision = decision
        self.reason = reason

    def check(self, tool_name: str, arguments: dict, read_only: bool) -> SafetyDecision:
        return SafetyDecision(self.decision, self.reason)


class RecordingApprover:
    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.calls = 0

    def approve(self, tool_name: str, arguments: dict, reason: str) -> bool:
        self.calls += 1
        return self.allow


def _registry(*tools: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.add(tool)
    return registry


def _tool_call(name: str, args: dict[str, Any] | None = None, call_id: str = "call-1") -> ProviderResponse:
    return ProviderResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args or {})],
    )


def _run(responses: list[ProviderResponse], registry: ToolRegistry, safety_gate=None, approver=None):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    recorder = RunRecorder(root / ".runs", run_id="outcomes")
    agent = Agent(
        provider=ScriptedProvider(responses),
        tools=registry,
        session=Session("system"),
        max_steps=10,
        safety_gate=safety_gate or FixedSafetyGate("allow"),
        approver=approver or RecordingApprover(True),
        context_config=ContextConfig(auto_compact=False),
        sink=recorder,
    )
    answer = agent.run("test")
    return tmp, agent, recorder, answer


def _events(recorder: RunRecorder) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _summary(recorder: RunRecorder) -> dict[str, Any]:
    return json.loads(recorder.summary_path.read_text(encoding="utf-8"))


def _last_tool_result(recorder: RunRecorder) -> dict[str, Any]:
    events = [event for event in _events(recorder) if event["kind"] == "tool_result"]
    if not events:
        raise AssertionError("missing tool_result event")
    return events[-1]["data"]


def test_successful_tool_result_is_structured() -> None:
    tmp, agent, recorder, answer = _run(
        [_tool_call("echo"), ProviderResponse(content="done")],
        _registry(TestTool("echo", output="hello")),
    )
    with tmp:
        result = _last_tool_result(recorder)
        summary = _summary(recorder)

        _assert(answer == "done", "agent returns final answer")
        _assert(result["ok"] is True, "successful result has ok=true")
        _assert(result["output"] == "hello", "successful result includes output")
        _assert(result["model_summary"] == "hello", "short result model summary stays plain")
        _assert(result["error"] == "", "successful result has empty error")
        _assert(agent.session.messages[-2].content == "hello", "model still receives plain tool output")
        _assert(summary["last_tool_result"]["ok"] is True, "summary keeps ok flag")


def test_unknown_tool_result_is_structured() -> None:
    tmp, agent, recorder, _ = _run(
        [_tool_call("missing_tool"), ProviderResponse(content="done")],
        _registry(),
    )
    with tmp:
        result = _last_tool_result(recorder)

        _assert(result["ok"] is False, "unknown tool has ok=false")
        _assert(result["error_kind"] == "unknown_tool", "unknown tool is classified")
        _assert(result["output"].startswith("error:"), "unknown tool output is model-readable")
        _assert(agent.session.messages[-2].content.startswith("error:"), "unknown tool error goes back to model")


def test_safety_deny_and_user_deny_are_structured() -> None:
    tmp1, _, recorder1, _ = _run(
        [_tool_call("writer"), ProviderResponse(content="done")],
        _registry(TestTool("writer", read_only=False)),
        safety_gate=FixedSafetyGate("deny", "dangerous"),
    )
    with tmp1:
        deny = _last_tool_result(recorder1)
        _assert(deny["ok"] is False, "safety deny has ok=false")
        _assert(deny["blocked"] is True, "safety deny is blocked")
        _assert(deny["error_kind"] == "safety_deny", "safety deny is classified")

    approver = RecordingApprover(False)
    tmp2, _, recorder2, _ = _run(
        [_tool_call("writer"), ProviderResponse(content="done")],
        _registry(TestTool("writer", read_only=False)),
        safety_gate=FixedSafetyGate("ask", "needs approval"),
        approver=approver,
    )
    with tmp2:
        blocked = _last_tool_result(recorder2)
        _assert(approver.calls == 1, "user approval is requested once")
        _assert(blocked["ok"] is False, "user denied call has ok=false")
        _assert(blocked["blocked"] is True, "user denied call is blocked")
        _assert(blocked["error_kind"] == "blocked", "user denied call is classified as blocked")


def test_tool_exception_and_truncation_are_structured() -> None:
    tmp1, _, recorder1, _ = _run(
        [_tool_call("bad"), ProviderResponse(content="done")],
        _registry(TestTool("bad", error=ValueError("missing path"))),
    )
    with tmp1:
        failed = _last_tool_result(recorder1)
        summary = _summary(recorder1)

        _assert(failed["ok"] is False, "tool exception has ok=false")
        _assert(failed["error"] == "missing path", "tool exception records error")
        _assert(failed["error_kind"] == "invalid_args", "ValueError is classified as invalid_args")
        _assert(summary["last_error"] == "missing path", "summary stores concise error")

    long_output = "x" * (MAX_TOOL_OUTPUT_CHARS + 100)
    tmp2, agent, recorder2, _ = _run(
        [_tool_call("long"), ProviderResponse(content="done")],
        _registry(TestTool("long", output=long_output)),
    )
    with tmp2:
        truncated = _last_tool_result(recorder2)
        notice_texts = [event["data"].get("message", "") for event in _events(recorder2) if event["kind"] == "notice"]

        _assert(truncated["ok"] is True, "long successful output remains ok")
        _assert(truncated["truncated"] is True, "long output is marked truncated")
        _assert("[tool output truncated:" in truncated["output"], "truncated output contains model-readable marker")
        _assert(len(truncated["model_summary"]) <= MAX_MODEL_TOOL_SUMMARY_CHARS + 64, "long output has compact model summary")
        _assert(agent.session.messages[-2].content == truncated["model_summary"], "model receives compact summary")
        _assert(len(agent.session.messages[-2].content) < len(long_output), "model receives truncated output")
        _assert(any("tool output truncated" in text for text in notice_texts), "truncation emits notice")


def test_python_traceback_model_summary_keeps_core_error() -> None:
    traceback_output = "\n".join(
        [
            "pytest noise line " + str(index)
            for index in range(80)
        ]
        + [
            "Traceback (most recent call last):",
            '  File "demo.py", line 7, in <module>',
            "    main()",
            '  File "demo.py", line 4, in main',
            "    raise ValueError('bad path')",
            "ValueError: bad path",
            "[python] exit_code=1 duration_ms=25 executable=/usr/bin/python3 source=test",
        ]
    )
    tmp, agent, recorder, _ = _run(
        [_tool_call("python_run"), ProviderResponse(content="done")],
        _registry(TestTool("python_run", error=RuntimeError(f"python exited with 1\n{traceback_output}"))),
    )
    with tmp:
        failed = _last_tool_result(recorder)
        summary = failed["model_summary"]

        _assert(failed["ok"] is False, "python traceback result has ok=false")
        _assert("[python traceback]" in summary, "model summary labels traceback section")
        _assert("ValueError: bad path" in summary, "model summary keeps final traceback exception")
        _assert("[python] exit_code=1" in summary, "model summary keeps python exit code")
        _assert(agent.session.messages[-2].content == summary, "model receives traceback summary")


def test_loop_guard_escalates_repeated_failures() -> None:
    failing = TestTool("bad", error=ValueError("unexpected end of JSON input"))
    tmp, agent, recorder, _ = _run(
        [
            _tool_call("bad", {"attempt": 1}, "call-1"),
            _tool_call("bad", {"attempt": 2}, "call-2"),
            _tool_call("bad", {"attempt": 3}, "call-3"),
            ProviderResponse(content="done"),
        ],
        _registry(failing),
    )
    with tmp:
        tool_messages = [message.content for message in agent.session.messages if message.role == "tool"]
        notice_texts = [event["data"].get("message", "") for event in _events(recorder) if event["kind"] == "notice"]

        _assert(failing.calls == 3, "failing tool was called three times")
        _assert("[loop guard]" not in tool_messages[0], "loop guard stays silent on first failure")
        _assert("[loop guard]" not in tool_messages[1], "loop guard stays silent below threshold")
        _assert("[loop guard]" in tool_messages[2], "loop guard is added at threshold")
        _assert(any("loop guard" in text for text in notice_texts), "loop guard emits user-visible notice")


def test_loop_guard_resets_after_success() -> None:
    failing = TestTool("bad", error=ValueError("unexpected end of JSON input"))
    ok = TestTool("ok_tool", output="ok")
    tmp, agent, _, _ = _run(
        [
            _tool_call("bad", {"attempt": 1}, "call-1"),
            _tool_call("bad", {"attempt": 2}, "call-2"),
            _tool_call("ok_tool", {}, "call-3"),
            _tool_call("bad", {"attempt": 3}, "call-4"),
            _tool_call("bad", {"attempt": 4}, "call-5"),
            ProviderResponse(content="done"),
        ],
        _registry(failing, ok),
    )
    with tmp:
        tool_messages = [message.content for message in agent.session.messages if message.role == "tool"]
        _assert(not any("[loop guard]" in message for message in tool_messages), "success resets loop guard counter")


if __name__ == "__main__":
    test_successful_tool_result_is_structured()
    test_unknown_tool_result_is_structured()
    test_safety_deny_and_user_deny_are_structured()
    test_tool_exception_and_truncation_are_structured()
    test_python_traceback_model_summary_keeps_core_error()
    test_loop_guard_escalates_repeated_failures()
    test_loop_guard_resets_after_success()
    print("All tool outcome tests passed.")
