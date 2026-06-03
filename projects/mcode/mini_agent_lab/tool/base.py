from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: JsonObject


class Tool(ABC):
    """A capability the agent can execute for the model."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def schema(self) -> JsonObject:
        raise NotImplementedError

    @property
    def read_only(self) -> bool:
        return False

    @abstractmethod
    def execute(self, arguments: JsonObject) -> str:
        raise NotImplementedError

