"""Integration test for Agent -> RunRecorder event flow."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.agent import Session
from mini_agent_lab.agent.agent import Agent
from mini_agent_lab.provider import Message, ProviderError, ProviderResponse, ProviderStreamEvent, ToolCall
from mini_agent_lab.plan import PLAN_MODE_MARKER
from mini_agent_lab.run_recorder import RunRecorder
from mini_agent_lab.tool.builtin import EchoTool
from mini_agent_lab.tool import ToolRegistry
from mini_agent_lab.tool.complete_step import CompleteStepTool
from mini_agent_lab.tool.todo import TodoWriteTool


class FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        if self.calls == 1:
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="todo_write",
                        arguments={
                            "todos": [
                                {"content": "Check event flow", "status": "completed"},
                            ]
                        },
                    )
                ],
            )
        return ProviderResponse(content="事件记录完成。")


class StreamingFinalProvider:
    def __init__(self) -> None:
        self.complete_calls = 0
        self.stream_calls = 0

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        self.complete_calls += 1
        raise AssertionError("streaming final provider should not use complete")

    def stream_complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ):
        self.stream_calls += 1
        yield ProviderStreamEvent(kind="content_delta", delta="流式")
        yield ProviderStreamEvent(kind="content_delta", delta="完成")
        yield ProviderStreamEvent(kind="message_completed", response=ProviderResponse(content="流式完成"))


class ReasoningFinalProvider:
    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(content="安全回答", reasoning="PRIVATE COT: hidden non-stream reasoning")


class StreamingReasoningProvider:
    def stream_complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ):
        yield ProviderStreamEvent(kind="reasoning_delta", delta="PRIVATE COT: hidden stream reasoning")
        yield ProviderStreamEvent(kind="content_delta", delta="安全")
        yield ProviderStreamEvent(kind="content_delta", delta="回答")
        yield ProviderStreamEvent(
            kind="message_completed",
            response=ProviderResponse(content="安全回答", reasoning="PRIVATE COT: hidden stream reasoning"),
        )


class StreamingToolCallProvider:
    def __init__(self) -> None:
        self.stream_calls = 0

    def stream_complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ):
        self.stream_calls += 1
        if self.stream_calls == 1:
            yield ProviderStreamEvent(
                kind="tool_call_delta",
                delta="PRIVATE TOOL ARG FRAGMENT",
                tool_call_index=0,
                tool_call_id="call-1",
                tool_call_name="todo_write",
            )
            yield ProviderStreamEvent(
                kind="message_completed",
                response=ProviderResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="todo_write",
                            arguments={"todos": [{"content": "Check streaming tool call", "status": "completed"}]},
                        )
                    ],
                ),
            )
            return
        yield ProviderStreamEvent(kind="content_delta", delta="工具")
        yield ProviderStreamEvent(kind="content_delta", delta="完成")
        yield ProviderStreamEvent(kind="message_completed", response=ProviderResponse(content="工具完成"))


class StreamingFailureProvider:
    def stream_complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ):
        yield ProviderStreamEvent(kind="content_delta", delta="部分")
        raise ProviderError(kind="network_reset", message="stream reset", retryable=True, attempt=1)


class EmptyFinalProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.final_tools: list[list[dict] | None] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        self.final_tools.append(tools)
        if self.calls == 1:
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="todo_write",
                        arguments={"todos": [{"content": "Do work", "status": "completed"}]},
                    )
                ],
            )
        if self.calls == 2:
            return ProviderResponse(content="")
        return ProviderResponse(content="已完成，生成结果文件并通过验证。")


class EmptyFirstProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.final_tools: list[list[dict] | None] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        self.final_tools.append(tools)
        if self.calls == 1:
            return ProviderResponse(content="")
        return ProviderResponse(content="已恢复空回复。")


class FailingProvider:
    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        raise ProviderError(
            kind="network_timeout",
            message="read timed out",
            retryable=True,
            attempt=3,
        )


class PlanProvider:
    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(content="1. 检查代码\n2. 实现改动\n3. 运行测试")


class PlanToolSchemaProvider:
    def __init__(self) -> None:
        self.tools_seen: list[dict] | None = None

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        self.tools_seen = tools
        return ProviderResponse(content="1. 读取上下文\n2. 输出计划")


class CaptureUserProvider:
    def __init__(self) -> None:
        self.user_messages: list[str] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        self.user_messages = [message.content for message in messages if message.role == "user"]
        return ProviderResponse(content="1. 检查代码\n2. 输出计划")


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def test_agent_records_run_events() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        registry.add(TodoWriteTool())
        recorder = RunRecorder(tmp, run_id="agent-events")
        agent = Agent(
            provider=FakeProvider(),
            tools=registry,
            session=Session("system"),
            max_steps=3,
            sink=recorder,
        )

        answer = agent.run("测试事件流")
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        kinds = [event["kind"] for event in events]

        _assert(answer == "事件记录完成。", "agent returns final answer")
        _assert("assistant_message" in kinds, "assistant messages are recorded")
        _assert("turn_status" in kinds, "product trace status is recorded")
        _assert("step_started" in kinds, "trace steps are recorded")
        _assert("action_started" in kinds, "trace actions are recorded")
        _assert("assistant_delta" in kinds, "assistant draft delta is recorded")
        _assert("tool_dispatch" in kinds, "tool dispatch is recorded")
        _assert("todo_updated" in kinds, "todo update is recorded")
        _assert(kinds[-1] == "turn_completed", "turn completion is recorded")
        _assert(summary["status"] == "completed", "summary is completed")
        _assert(summary["todo"]["completed"] == 1, "summary todo is updated")
        _assert(summary["final_answer"] == "事件记录完成。", "summary final answer is updated")


def test_agent_streams_provider_deltas() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        provider = StreamingFinalProvider()
        recorder = RunRecorder(tmp, run_id="agent-stream")
        agent = Agent(
            provider=provider,
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=recorder,
        )

        answer = agent.run("测试流式输出")
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        deltas = [event["data"]["delta"] for event in events if event["kind"] == "assistant_delta"]
        completed = [event for event in events if event["kind"] == "assistant_message_completed"]

        _assert(answer == "流式完成", "agent returns streamed final answer")
        _assert(provider.stream_calls == 1 and provider.complete_calls == 0, "agent uses provider stream_complete when available")
        _assert(deltas == ["流式", "完成"], "agent records provider deltas as separate assistant_delta events")
        _assert(completed[-1]["data"]["content"] == "流式完成", "agent records streamed assistant completion")


def test_agent_does_not_expose_non_stream_reasoning_in_events() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(tmp, run_id="agent-reasoning-redaction")
        agent = Agent(
            provider=ReasoningFinalProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=recorder,
        )

        answer = agent.run("测试非流式 reasoning 脱敏")
        raw_events = recorder.event_path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in raw_events.splitlines() if line.strip()]
        assistant_messages = [event for event in events if event["kind"] == "assistant_message"]

        _assert(answer == "安全回答", "agent returns non-stream answer with internal reasoning")
        _assert(agent.session.messages[-1].reasoning.startswith("PRIVATE COT"), "session keeps assistant reasoning for provider replay")
        _assert("PRIVATE COT" not in raw_events, "run events do not expose raw non-stream reasoning")
        _assert("reasoning" not in assistant_messages[-1]["data"], "assistant_message event omits reasoning field")


def test_agent_sanitizes_streaming_reasoning_in_events() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(tmp, run_id="agent-stream-reasoning-redaction")
        agent = Agent(
            provider=StreamingReasoningProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=recorder,
        )

        answer = agent.run("测试流式 reasoning 脱敏")
        raw_events = recorder.event_path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in raw_events.splitlines() if line.strip()]
        thought_deltas = [event["data"]["text"] for event in events if event["kind"] == "thought_summary_delta"]
        assistant_deltas = [event["data"]["delta"] for event in events if event["kind"] == "assistant_delta"]

        _assert(answer == "安全回答", "agent returns streamed answer with internal reasoning")
        _assert(agent.session.messages[-1].reasoning.startswith("PRIVATE COT"), "session keeps streamed reasoning for provider replay")
        _assert("PRIVATE COT" not in raw_events, "run events do not expose raw streamed reasoning")
        _assert("正在分析上下文" in thought_deltas, "agent emits sanitized reasoning progress summary")
        _assert(assistant_deltas == ["安全", "回答"], "agent only streams assistant content deltas")


def test_agent_can_disable_thought_summary_events() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(tmp, run_id="agent-thought-summary-disabled")
        agent = Agent(
            provider=StreamingReasoningProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=recorder,
            show_thought_summary=False,
        )

        answer = agent.run("测试关闭思考摘要")
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = [event["kind"] for event in events]

        _assert(answer == "安全回答", "agent returns answer when thought summary is disabled")
        _assert(not any(kind.startswith("thought_summary_") for kind in kinds), "agent omits thought summary events when disabled")
        _assert("step_started" in kinds, "agent still records trace steps when thought summary is disabled")
        _assert("assistant_delta" in kinds, "agent still records assistant deltas when thought summary is disabled")


def test_agent_records_streaming_tool_call_construction_without_argument_deltas() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        registry.add(TodoWriteTool())
        provider = StreamingToolCallProvider()
        recorder = RunRecorder(tmp, run_id="agent-stream-tool-call")
        agent = Agent(
            provider=provider,
            tools=registry,
            session=Session("system"),
            max_steps=3,
            sink=recorder,
        )

        answer = agent.run("测试流式工具调用")
        raw_events = recorder.event_path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in raw_events.splitlines() if line.strip()]
        kinds = [event["kind"] for event in events]
        tool_call_deltas = [event for event in events if event["kind"] == "tool_call_delta"]

        _assert(answer == "工具完成", "agent executes streamed tool call and returns final answer")
        _assert(provider.stream_calls == 2, "agent continues after streamed tool call result")
        _assert("tool_call_started" in kinds, "agent records streamed tool call start")
        _assert("tool_call_delta" in kinds, "agent records streamed tool call progress")
        _assert("tool_call_completed" in kinds, "agent records streamed tool call completion")
        _assert("tool_dispatch" in kinds, "agent dispatches tool only after completed response")
        _assert("PRIVATE TOOL ARG FRAGMENT" not in raw_events, "run events do not expose raw tool call argument deltas")
        _assert("delta" not in tool_call_deltas[-1]["data"], "tool_call_delta event omits raw delta text")
        _assert(tool_call_deltas[-1]["data"]["received_chars"] > 0, "tool_call_delta records sanitized progress size")


def test_agent_marks_failed_streaming_draft() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(tmp, run_id="agent-stream-failure")
        agent = Agent(
            provider=StreamingFailureProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=recorder,
        )

        answer = agent.run("测试流式失败")
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = [event["kind"] for event in events]

        _assert("网络连接问题" in answer, "agent returns recoverable fallback after streaming failure")
        _assert("assistant_message_failed" in kinds, "agent records failed streaming assistant draft")
        _assert("turn_failed" in kinds, "agent records failed turn after streaming failure")


def test_agent_recovers_empty_final_answer() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        registry.add(TodoWriteTool())
        provider = EmptyFinalProvider()
        recorder = RunRecorder(tmp, run_id="empty-final")
        agent = Agent(
            provider=provider,
            tools=registry,
            session=Session("system"),
            max_steps=3,
            sink=recorder,
        )

        answer = agent.run("测试空最终回答恢复")
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        _assert(answer == "已完成，生成结果文件并通过验证。", "agent recovers empty final answer")
        _assert(provider.final_tools[-1] == [], "recovery call disables tools")
        _assert(summary["final_answer"] == answer, "recovered final answer is recorded")
        _assert(any(event["kind"] == "notice" for event in events), "recovery emits a notice")


def test_agent_recovers_empty_first_response() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        provider = EmptyFirstProvider()
        recorder = RunRecorder(tmp, run_id="empty-first")
        agent = Agent(
            provider=provider,
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=recorder,
        )

        answer = agent.run("测试首轮空回复恢复")
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))

        _assert(answer == "已恢复空回复。", "agent recovers empty first response")
        _assert(provider.final_tools[-1] == [], "first-response recovery disables tools")
        _assert(summary["final_answer"] == answer, "recovered first response is recorded")


def test_agent_records_recoverable_provider_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(tmp, run_id="provider-failure")
        agent = Agent(
            provider=FailingProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=recorder,
        )

        answer = agent.run("测试网络失败")
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        _assert("模型请求超时" in answer, "provider failure returns user-visible fallback answer")
        _assert(agent.session.messages[-1].role == "assistant", "provider failure appends assistant fallback")
        _assert(summary["status"] == "failed", "provider failure records failed turn")
        _assert(summary["recoverable"] is True, "provider failure is marked recoverable")
        _assert(summary["provider_error"]["kind"] == "network_timeout", "provider error kind is summarized")
        _assert(any(event["kind"] == "provider_error" for event in events), "provider_error event is emitted")


def test_plan_mode_records_pending_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(tmp, run_id="plan-mode")
        agent = Agent(
            provider=PlanProvider(),
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=recorder,
        )
        agent.set_plan_mode(True)

        answer = agent.run("制定计划")
        summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in recorder.event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        _assert(answer.startswith("1. 检查代码"), "plan mode returns plan text")
        _assert(any(event["kind"] == "plan_pending" for event in events), "plan pending event is recorded")
        _assert(summary["status"] == "awaiting_plan_decision", "summary waits for plan decision")
        _assert(summary["pending_plan"]["status"] == "awaiting_approval", "pending plan is awaiting approval")
        _assert(summary["pending_plan"]["revision"] == 1, "pending plan starts at revision 1")
        _assert(summary["pending_plan"]["todo_count"] == 3, "pending plan stores parsed todos")
        _assert(summary["pending_plan"]["todos"][0]["status"] == "in_progress", "first plan todo is in progress")


def test_plan_mode_auto_injects_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        provider = CaptureUserProvider()
        agent = Agent(
            provider=provider,
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=RunRecorder(tmp, run_id="plan-marker"),
        )
        agent.set_plan_mode(True)

        agent.run("制定计划")

        _assert(provider.user_messages[0].startswith(PLAN_MODE_MARKER), "plan mode injects marker into model input")
        _assert(provider.user_messages[0].endswith("制定计划"), "plan mode preserves the original task text")


def test_plan_mode_does_not_double_inject_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        provider = CaptureUserProvider()
        agent = Agent(
            provider=provider,
            tools=ToolRegistry(),
            session=Session("system"),
            max_steps=1,
            sink=RunRecorder(tmp, run_id="plan-marker-once"),
        )
        agent.set_plan_mode(True)

        agent.run(PLAN_MODE_MARKER + "\n\n制定计划")

        _assert(provider.user_messages[0].count(PLAN_MODE_MARKER) == 1, "plan marker is injected at most once")


def test_plan_mode_only_exposes_read_only_tools() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        registry = ToolRegistry()
        registry.add(EchoTool())
        registry.add(TodoWriteTool())
        registry.add(CompleteStepTool())
        provider = PlanToolSchemaProvider()
        agent = Agent(
            provider=provider,
            tools=registry,
            session=Session("system"),
            max_steps=1,
            sink=RunRecorder(tmp, run_id="plan-tool-schemas"),
        )
        agent.set_plan_mode(True)

        agent.run("制定计划")
        tool_names = {tool["name"] for tool in provider.tools_seen or []}

        _assert("echo" in tool_names, "plan mode exposes read-only tools")
        _assert("todo_write" not in tool_names, "plan mode hides write tools from the model")
        _assert("complete_step" not in tool_names, "plan mode hides execution sign-off tools")


if __name__ == "__main__":
    test_agent_records_run_events()
    test_agent_streams_provider_deltas()
    test_agent_does_not_expose_non_stream_reasoning_in_events()
    test_agent_sanitizes_streaming_reasoning_in_events()
    test_agent_can_disable_thought_summary_events()
    test_agent_records_streaming_tool_call_construction_without_argument_deltas()
    test_agent_marks_failed_streaming_draft()
    test_agent_recovers_empty_final_answer()
    test_agent_recovers_empty_first_response()
    test_agent_records_recoverable_provider_failure()
    test_plan_mode_records_pending_plan()
    test_plan_mode_auto_injects_marker()
    test_plan_mode_does_not_double_inject_marker()
    test_plan_mode_only_exposes_read_only_tools()
    print("All agent run event tests passed.")
