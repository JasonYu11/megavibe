from __future__ import annotations

from mini_agent_lab.provider import Message


class Session:
    """Conversation history for one task."""

    def __init__(self, system_prompt: str = ""):
        self.messages: list[Message] = []
        if system_prompt:
            self.add("system", system_prompt)

    def add(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))

    def has_content(self) -> bool:
        return any(message.role != "system" for message in self.messages)
