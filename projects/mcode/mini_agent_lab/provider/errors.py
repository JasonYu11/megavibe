from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


FailureKind = Literal[
    "rate_limit",
    "auth_error",
    "server_error",
    "network_timeout",
    "network_reset",
    "context_length",
    "bad_response",
    "api_error",
]


@dataclass
class ProviderError(RuntimeError):
    """Structured provider failure used by runners and UI diagnostics."""

    kind: FailureKind
    message: str
    retryable: bool = False
    status_code: int | None = None
    attempt: int = 1
    request_id: str = ""
    details: Any = None

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.__str__())

    def __str__(self) -> str:
        parts = [f"{self.kind}: {self.message}"]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        parts.append(f"attempt={self.attempt}")
        parts.append(f"retryable={str(self.retryable).lower()}")
        return " | ".join(parts)
