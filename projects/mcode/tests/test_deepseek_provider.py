"""Tests for DeepSeek provider transport, classification, and retry behavior."""

from __future__ import annotations

import sys
import json
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.provider import DeepSeekProvider, Message, ProviderError


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _provider(transport: httpx.BaseTransport) -> DeepSeekProvider:
    return DeepSeekProvider(
        "sk-test",
        "https://api.deepseek.com",
        "deepseek-v4-flash",
        transport=transport,
    )


def test_provider_retries_server_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, json={"model": "deepseek-test", "choices": [{"message": {"content": "ok"}}]})

    with (
        patch("time.sleep", lambda _: None),
        patch.dict("os.environ", {"DEEPSEEK_MAX_RETRIES": "2"}),
    ):
        response = _provider(httpx.MockTransport(handler)).complete([Message(role="user", content="hello")])

    _assert(calls["count"] == 2, "provider retries retryable HTTP 503 once")
    _assert(response.content == "ok", "provider returns successful retry response")


def test_provider_classifies_rate_limit_without_retry() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    with patch.dict("os.environ", {"DEEPSEEK_MAX_RETRIES": "2"}):
        try:
            _provider(httpx.MockTransport(handler)).complete([Message(role="user", content="hello")])
        except ProviderError as exc:
            _assert(exc.kind == "rate_limit", "HTTP 429 is classified as rate_limit")
            _assert(not exc.retryable, "rate_limit is not retried by default")
            _assert(exc.status_code == 429, "rate_limit keeps status code")
        else:
            raise AssertionError("expected ProviderError")

    _assert(calls["count"] == 1, "provider does not retry HTTP 429")


def test_provider_classifies_auth_error_without_retry() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with patch.dict("os.environ", {"DEEPSEEK_MAX_RETRIES": "2"}):
        try:
            _provider(httpx.MockTransport(handler)).complete([Message(role="user", content="hello")])
        except ProviderError as exc:
            _assert(exc.kind == "auth_error", "HTTP 401 is classified as auth_error")
            _assert(not exc.retryable, "auth_error is not retryable")
        else:
            raise AssertionError("expected ProviderError")

    _assert(calls["count"] == 1, "provider does not retry HTTP 401")


def test_provider_retries_timeout_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ReadTimeout("read timed out", request=request)
        return httpx.Response(200, json={"model": "deepseek-test", "choices": [{"message": {"content": "ok"}}]})

    with (
        patch("time.sleep", lambda _: None),
        patch.dict("os.environ", {"DEEPSEEK_MAX_RETRIES": "1"}),
    ):
        response = _provider(httpx.MockTransport(handler)).complete([Message(role="user", content="hello")])

    _assert(calls["count"] == 2, "provider retries network timeout")
    _assert(response.content == "ok", "provider returns response after timeout retry")


def test_provider_defaults_to_five_total_attempts() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ReadTimeout("read timed out", request=request)

    with (
        patch("time.sleep", lambda _: None),
        patch.dict("os.environ", {}, clear=True),
    ):
        try:
            _provider(httpx.MockTransport(handler)).complete([Message(role="user", content="hello")])
        except ProviderError as exc:
            _assert(exc.kind == "network_timeout", "default retry exhaustion surfaces timeout")
            _assert(exc.attempt == 5, "default retry policy stops on attempt 5")
        else:
            raise AssertionError("expected ProviderError")

    _assert(calls["count"] == 5, "default retry policy makes five total attempts")


def test_provider_classifies_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "deepseek-test", "choices": []})

    try:
        _provider(httpx.MockTransport(handler)).complete([Message(role="user", content="hello")])
    except ProviderError as exc:
        _assert(exc.kind == "bad_response", "missing choices is classified as bad_response")
        _assert(not exc.retryable, "bad_response is not retryable")
    else:
        raise AssertionError("expected ProviderError")


def test_provider_classifies_context_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "context length exceeded: too many tokens"}})

    try:
        _provider(httpx.MockTransport(handler)).complete([Message(role="user", content="hello")])
    except ProviderError as exc:
        _assert(exc.kind == "context_length", "context-window errors are classified")
        _assert(not exc.retryable, "context-window errors are not retried")
        _assert(exc.status_code == 400, "context-window errors keep status code")
    else:
        raise AssertionError("expected ProviderError")


def test_provider_sends_thinking_toggle() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"model": "deepseek-test", "choices": [{"message": {"content": "ok"}}]})

    _provider(httpx.MockTransport(handler)).complete([Message(role="user", content="hello")])
    DeepSeekProvider(
        "sk-test",
        "https://api.deepseek.com",
        "deepseek-v4-pro",
        thinking_mode=True,
        transport=httpx.MockTransport(handler),
    ).complete([Message(role="user", content="hello")])

    _assert(seen[0]["thinking"] == {"type": "disabled"}, "provider disables thinking mode by default")
    _assert("reasoning_effort" not in seen[0], "provider omits reasoning effort when thinking is disabled")
    _assert(seen[1]["thinking"] == {"type": "enabled"}, "provider enables thinking mode when requested")
    _assert(seen[1]["reasoning_effort"] == "high", "provider sends high reasoning effort for thinking mode")


def test_provider_replays_assistant_reasoning_content() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"model": "deepseek-test", "choices": [{"message": {"content": "ok"}}]})

    DeepSeekProvider(
        "sk-test",
        "https://api.deepseek.com",
        "deepseek-v4-pro",
        thinking_mode=True,
        transport=httpx.MockTransport(handler),
    ).complete([Message(role="assistant", content="", reasoning="reasoned path")])

    _assert(seen[0]["messages"][0]["reasoning_content"] == "reasoned path", "provider replays assistant reasoning content")


def test_provider_streams_content_reasoning_and_completion() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode("utf-8")))
        body = "\n\n".join(
            [
                'data: {"model":"deepseek-test","choices":[{"delta":{"reasoning_content":"检查"}}]}',
                'data: {"model":"deepseek-test","choices":[{"delta":{"content":"你"}}]}',
                'data: {"model":"deepseek-test","choices":[{"delta":{"content":"好"}}]}',
                "data: [DONE]",
                "",
            ]
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    events = list(_provider(httpx.MockTransport(handler)).stream_complete([Message(role="user", content="hello")]))

    _assert(seen[0]["stream"] is True, "stream_complete sends streaming request")
    _assert([event.kind for event in events] == ["reasoning_delta", "content_delta", "content_delta", "message_completed"], "stream_complete yields ordered deltas")
    _assert(events[0].delta == "检查", "stream_complete yields reasoning delta")
    _assert(events[-1].response is not None and events[-1].response.content == "你好", "stream_complete aggregates content")
    _assert(events[-1].response is not None and events[-1].response.reasoning == "检查", "stream_complete aggregates reasoning")


def test_provider_streams_tool_call_argument_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = "\n\n".join(
            [
                'data: {"model":"deepseek-test","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"echo","arguments":"{\\"text\\""}}]}}]}',
                'data: {"model":"deepseek-test","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":": \\"hi\\"}"}}]}}]}',
                "data: [DONE]",
                "",
            ]
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    events = list(_provider(httpx.MockTransport(handler)).stream_complete([Message(role="user", content="hello")]))
    completed = events[-1].response

    _assert([event.kind for event in events[:-1]] == ["tool_call_delta", "tool_call_delta"], "stream_complete yields tool call deltas")
    _assert(completed is not None and completed.tool_calls is not None, "stream_complete returns completed tool calls")
    _assert(completed.tool_calls[0].id == "call-1", "stream_complete preserves streamed tool call id")
    _assert(completed.tool_calls[0].name == "echo", "stream_complete preserves streamed tool call name")
    _assert(completed.tool_calls[0].arguments == {"text": "hi"}, "stream_complete aggregates tool call arguments")


if __name__ == "__main__":
    test_provider_retries_server_error()
    test_provider_classifies_rate_limit_without_retry()
    test_provider_classifies_auth_error_without_retry()
    test_provider_retries_timeout_then_succeeds()
    test_provider_defaults_to_five_total_attempts()
    test_provider_classifies_bad_response()
    test_provider_classifies_context_length()
    test_provider_sends_thinking_toggle()
    test_provider_replays_assistant_reasoning_content()
    test_provider_streams_content_reasoning_and_completion()
    test_provider_streams_tool_call_argument_deltas()
    print("All DeepSeek provider tests passed.")
