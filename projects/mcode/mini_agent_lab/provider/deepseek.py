from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Iterator, Optional

import httpx

from .errors import ProviderError
from .types import Message, ProviderResponse, ProviderStreamEvent, ToolCall


class DeepSeekProvider:
    """Minimal OpenAI-compatible DeepSeek chat provider.

    This first version intentionally ignores tool calls. We are only building the
    lowest provider layer: session messages go in, assistant text comes out.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.2,
        thinking_mode: bool = False,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        proxy_url: str | None = None,
        trust_env: bool | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.thinking_mode = thinking_mode
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.proxy_url = proxy_url
        self.trust_env = trust_env
        self.transport = transport

    def complete(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        max_tokens: Optional[int] = None,
    ) -> ProviderResponse:
        body = self._request_body(messages, tools=tools, max_tokens=max_tokens, stream=False)
        settings = self._request_settings()
        payload: dict | None = None
        last_error: ProviderError | None = None
        for attempt_index in range(settings["max_retries"] + 1):
            attempt = attempt_index + 1
            try:
                with self._client(settings) as client:
                    response = client.post(f"{self.base_url}/chat/completions", json=body)
                if response.status_code >= 400:
                    raise self._error_from_response(response, attempt)
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise ProviderError(
                        kind="bad_response",
                        message="DeepSeek API returned invalid JSON",
                        retryable=False,
                        status_code=response.status_code,
                        attempt=attempt,
                        request_id=self._request_id(response),
                    ) from exc
                break
            except httpx.TimeoutException as exc:
                last_error = ProviderError(
                    kind="network_timeout",
                    message=str(exc) or "DeepSeek API request timed out",
                    retryable=True,
                    attempt=attempt,
                )
                if not self._can_retry(last_error, attempt_index, settings["max_retries"]):
                    raise last_error from exc
            except httpx.TransportError as exc:
                last_error = ProviderError(
                    kind="network_reset",
                    message=str(exc) or exc.__class__.__name__,
                    retryable=True,
                    attempt=attempt,
                )
                if not self._can_retry(last_error, attempt_index, settings["max_retries"]):
                    raise last_error from exc
            except ProviderError as exc:
                last_error = exc
                if not self._can_retry(exc, attempt_index, settings["max_retries"]):
                    raise
            self._sleep_before_retry(attempt_index)
        else:
            if last_error is not None:
                raise last_error
            raise ProviderError(kind="api_error", message="DeepSeek API request failed", retryable=False)

        try:
            choice = payload["choices"][0]["message"] if payload is not None else {}
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                kind="bad_response",
                message="DeepSeek API response did not contain choices[0].message",
                retryable=False,
                details=payload,
            ) from exc
        tool_calls = self._parse_tool_calls(choice.get("tool_calls") or [])
        return ProviderResponse(
            content=choice.get("content", ""),
            reasoning=choice.get("reasoning_content", ""),
            raw_model=payload.get("model", "") if payload else "",
            tool_calls=tool_calls,
        )

    def stream_complete(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[ProviderStreamEvent]:
        body = self._request_body(messages, tools=tools, max_tokens=max_tokens, stream=True)
        settings = self._request_settings()
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        raw_model = ""
        tool_call_parts: dict[int, dict[str, Any]] = {}
        last_error: ProviderError | None = None

        for attempt_index in range(settings["max_retries"] + 1):
            attempt = attempt_index + 1
            try:
                with self._client(settings) as client:
                    with client.stream("POST", f"{self.base_url}/chat/completions", json=body) as response:
                        if response.status_code >= 400:
                            response.read()
                            raise self._error_from_response(response, attempt)
                        raw_model = response.headers.get("x-model", "") or raw_model
                        for payload in self._iter_sse_payloads(response):
                            if payload == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(payload)
                            except ValueError as exc:
                                raise ProviderError(
                                    kind="bad_response",
                                    message="DeepSeek API returned invalid streaming JSON",
                                    retryable=False,
                                    status_code=response.status_code,
                                    attempt=attempt,
                                    request_id=self._request_id(response),
                                ) from exc
                            raw_model = str(chunk.get("model") or raw_model)
                            choice = _first_choice(chunk)
                            delta = choice.get("delta") or {}
                            content_delta = str(delta.get("content") or "")
                            if content_delta:
                                content_parts.append(content_delta)
                                yield ProviderStreamEvent(kind="content_delta", delta=content_delta)
                            reasoning_delta = str(delta.get("reasoning_content") or delta.get("reasoning") or "")
                            if reasoning_delta:
                                reasoning_parts.append(reasoning_delta)
                                yield ProviderStreamEvent(kind="reasoning_delta", delta=reasoning_delta)
                            for event in self._tool_call_delta_events(delta.get("tool_calls") or [], tool_call_parts):
                                yield event
                response_event = ProviderStreamEvent(
                    kind="message_completed",
                    response=ProviderResponse(
                        content="".join(content_parts),
                        reasoning="".join(reasoning_parts),
                        raw_model=raw_model,
                        tool_calls=_tool_calls_from_stream_parts(tool_call_parts),
                    ),
                )
                yield response_event
                return
            except httpx.TimeoutException as exc:
                last_error = ProviderError(
                    kind="network_timeout",
                    message=str(exc) or "DeepSeek API request timed out",
                    retryable=True,
                    attempt=attempt,
                )
                if not self._can_retry(last_error, attempt_index, settings["max_retries"]) or content_parts or reasoning_parts or tool_call_parts:
                    raise last_error from exc
            except httpx.TransportError as exc:
                last_error = ProviderError(
                    kind="network_reset",
                    message=str(exc) or exc.__class__.__name__,
                    retryable=True,
                    attempt=attempt,
                )
                if not self._can_retry(last_error, attempt_index, settings["max_retries"]) or content_parts or reasoning_parts or tool_call_parts:
                    raise last_error from exc
            except ProviderError as exc:
                last_error = exc
                if not self._can_retry(exc, attempt_index, settings["max_retries"]) or content_parts or reasoning_parts or tool_call_parts:
                    raise
            self._sleep_before_retry(attempt_index)
        if last_error is not None:
            raise last_error
        raise ProviderError(kind="api_error", message="DeepSeek API stream request failed", retryable=False)

    def _request_body(
        self,
        messages: list[Message],
        tools: Optional[list[dict]] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_to_api(m) for m in messages],
            "temperature": self.temperature,
            "stream": stream,
            "thinking": {"type": "enabled" if self.thinking_mode else "disabled"},
        }
        if self.thinking_mode:
            body["reasoning_effort"] = "high"
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]
        user_id = os.environ.get("DEEPSEEK_USER_ID", "").strip()
        if user_id:
            body["user"] = user_id
        return body

    def _request_settings(self) -> dict[str, Any]:
        proxy_url = self.proxy_url if self.proxy_url is not None else os.environ.get("DEEPSEEK_PROXY_URL", "").strip()
        return {
            "timeout": self.timeout_seconds if self.timeout_seconds is not None else float(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "30")),
            "max_retries": self.max_retries if self.max_retries is not None else int(os.environ.get("DEEPSEEK_MAX_RETRIES", "4")),
            "proxy_url": proxy_url.strip() or None,
            "trust_env": (
                self.trust_env
                if self.trust_env is not None
                else os.environ.get("DEEPSEEK_TRUST_ENV", "false").strip().lower() in {"1", "true", "yes", "on"}
            ),
        }

    def _client(self, settings: dict[str, Any]) -> httpx.Client:
        return httpx.Client(
            timeout=self._timeout(float(settings["timeout"])),
            transport=self.transport,
            proxy=settings["proxy_url"],
            trust_env=bool(settings["trust_env"]),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

    @staticmethod
    def _iter_sse_payloads(response: httpx.Response) -> Iterator[str]:
        buffer: list[str] = []
        for raw_line in response.iter_lines():
            line = raw_line.strip()
            if not line:
                if buffer:
                    yield "\n".join(buffer)
                    buffer = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                buffer.append(line[5:].strip())
        if buffer:
            yield "\n".join(buffer)

    @staticmethod
    def _tool_call_delta_events(raw_calls: list[dict], parts: dict[int, dict[str, Any]]) -> Iterator[ProviderStreamEvent]:
        for raw in raw_calls:
            index = int(raw.get("index") or 0)
            current = parts.setdefault(index, {"id": "", "name": "", "arguments": []})
            if raw.get("id"):
                current["id"] = raw.get("id")
            fn = raw.get("function") or {}
            if fn.get("name"):
                current["name"] = fn.get("name")
            arg_delta = str(fn.get("arguments") or "")
            if arg_delta:
                current["arguments"].append(arg_delta)
            yield ProviderStreamEvent(
                kind="tool_call_delta",
                delta=arg_delta,
                tool_call_index=index,
                tool_call_id=str(current.get("id") or ""),
                tool_call_name=str(current.get("name") or ""),
            )

    @staticmethod
    def _timeout(seconds: float) -> httpx.Timeout:
        connect = min(10.0, max(1.0, seconds))
        read = max(1.0, seconds)
        return httpx.Timeout(timeout=seconds, connect=connect, read=read, write=10.0, pool=10.0)

    @staticmethod
    def _can_retry(error: ProviderError, attempt_index: int, max_retries: int) -> bool:
        return error.retryable and attempt_index < max_retries

    @staticmethod
    def _sleep_before_retry(attempt_index: int) -> None:
        time.sleep(min(1.0, 0.2 * (attempt_index + 1)) + random.uniform(0, 0.1))

    @classmethod
    def _error_from_response(cls, response: httpx.Response, attempt: int) -> ProviderError:
        detail = cls._response_detail(response)
        status = response.status_code
        if status == 429:
            return ProviderError(
                kind="rate_limit",
                message=detail,
                retryable=False,
                status_code=status,
                attempt=attempt,
                request_id=cls._request_id(response),
            )
        if status in {401, 403}:
            return ProviderError(
                kind="auth_error",
                message=detail,
                retryable=False,
                status_code=status,
                attempt=attempt,
                request_id=cls._request_id(response),
            )
        if status >= 500:
            return ProviderError(
                kind="server_error",
                message=detail,
                retryable=True,
                status_code=status,
                attempt=attempt,
                request_id=cls._request_id(response),
            )
        if status in {400, 413} and cls._looks_like_context_length(detail):
            return ProviderError(
                kind="context_length",
                message=detail,
                retryable=False,
                status_code=status,
                attempt=attempt,
                request_id=cls._request_id(response),
            )
        if status == 408:
            return ProviderError(
                kind="network_timeout",
                message=detail or "DeepSeek API request timed out",
                retryable=True,
                status_code=status,
                attempt=attempt,
                request_id=cls._request_id(response),
            )
        retryable = status in {408, 409, 425}
        return ProviderError(
            kind="api_error",
            message=detail,
            retryable=retryable,
            status_code=status,
            attempt=attempt,
            request_id=cls._request_id(response),
        )

    @staticmethod
    def _response_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:1000]
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("type") or error
                return str(message)
            if error:
                return str(error)
        return json.dumps(payload, ensure_ascii=False)[:1000]

    @staticmethod
    def _looks_like_context_length(detail: str) -> bool:
        text = detail.lower()
        return any(
            marker in text
            for marker in (
                "context length",
                "maximum context",
                "token limit",
                "too many tokens",
                "context_length_exceeded",
                "context window",
            )
        )

    @staticmethod
    def _request_id(response: httpx.Response) -> str:
        return (
            response.headers.get("x-request-id")
            or response.headers.get("x-ds-request-id")
            or response.headers.get("cf-ray")
            or ""
        )

    @staticmethod
    def _message_to_api(message: Message) -> dict:
        if message.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "name": message.name,
                "content": message.content,
            }

        out = {
            "role": message.role,
            "content": message.content,
        }
        if message.role == "assistant" and message.reasoning:
            out["reasoning_content"] = message.reasoning
        if message.tool_calls:
            out["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        return out

    @staticmethod
    def _parse_tool_calls(raw_calls: list[dict]) -> list[ToolCall]:
        calls = []
        for raw in raw_calls:
            fn = raw.get("function") or {}
            arg_text = fn.get("arguments") or "{}"
            try:
                arguments = json.loads(arg_text)
            except json.JSONDecodeError:
                arguments = {"_raw": arg_text}
            calls.append(
                ToolCall(
                    id=raw.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=arguments,
                )
            )
        return calls


def _first_choice(chunk: dict[str, Any]) -> dict[str, Any]:
    choices = chunk.get("choices") or []
    if not choices:
        return {}
    choice = choices[0]
    return choice if isinstance(choice, dict) else {}


def _tool_calls_from_stream_parts(parts: dict[int, dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for index in sorted(parts):
        raw = parts[index]
        arg_text = "".join(raw.get("arguments") or []) or "{}"
        try:
            arguments = json.loads(arg_text)
        except json.JSONDecodeError:
            arguments = {"_raw": arg_text}
        calls.append(
            ToolCall(
                id=str(raw.get("id") or ""),
                name=str(raw.get("name") or ""),
                arguments=arguments,
            )
        )
    return calls
