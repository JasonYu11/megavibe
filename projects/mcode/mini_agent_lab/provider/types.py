from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ToolCall":
        return cls(
            id=raw.get("id", ""),
            name=raw.get("name", ""),
            arguments=raw.get("arguments", {}),
        )


@dataclass
class Message:
    role: str
    content: str = ""
    reasoning: str = ""
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "reasoning": self.reasoning,
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "tool_calls": [c.to_dict() for c in self.tool_calls] if self.tool_calls else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Message":
        tool_calls = raw.get("tool_calls")
        return cls(
            role=raw.get("role", ""),
            content=raw.get("content", ""),
            reasoning=raw.get("reasoning", raw.get("reasoning_content", "")),
            tool_call_id=raw.get("tool_call_id"),
            name=raw.get("name"),
            tool_calls=[ToolCall.from_dict(c) for c in tool_calls] if tool_calls else None,
        )


@dataclass
class ProviderResponse:
    content: str
    reasoning: str = ""
    raw_model: str = ""
    tool_calls: Optional[list[ToolCall]] = None


@dataclass
class ProviderStreamEvent:
    kind: Literal["content_delta", "reasoning_delta", "tool_call_delta", "message_completed"]
    delta: str = ""
    tool_call_index: Optional[int] = None
    tool_call_id: str = ""
    tool_call_name: str = ""
    response: Optional[ProviderResponse] = None
