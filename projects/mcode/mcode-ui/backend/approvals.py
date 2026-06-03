from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApprovalRequest:
    id: str
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    decided_at: float = 0.0
    approved: bool = False


class ApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, ApprovalRequest] = {}
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def create(self, *, session_id: str, tool_name: str, arguments: dict[str, Any], reason: str) -> ApprovalRequest:
        item = ApprovalRequest(
            id=f"approval-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
        )
        with self._lock:
            self._items[item.id] = item
            self._events[item.id] = threading.Event()
        return item

    def wait(self, approval_id: str, timeout_seconds: int = 300) -> bool:
        with self._lock:
            event = self._events.get(approval_id)
        if event is None:
            return False
        event.wait(timeout=timeout_seconds)
        with self._lock:
            item = self._items.get(approval_id)
            if item is None or item.status == "pending":
                if item is not None:
                    item.status = "expired"
                    item.decided_at = time.time()
                return False
            return item.approved

    def decide(self, approval_id: str, approved: bool) -> ApprovalRequest:
        with self._lock:
            item = self._items.get(approval_id)
            event = self._events.get(approval_id)
            if item is None or event is None:
                raise KeyError(f"unknown approval: {approval_id}")
            if item.status == "pending":
                item.approved = approved
                item.status = "approved" if approved else "denied"
                item.decided_at = time.time()
                event.set()
            return item

    def list(self, session_id: str = "") -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._items.values())
        if session_id:
            rows = [item for item in rows if item.session_id == session_id]
        return [
            {
                "id": item.id,
                "session_id": item.session_id,
                "tool_name": item.tool_name,
                "arguments": item.arguments,
                "reason": item.reason,
                "status": item.status,
                "created_at": item.created_at,
                "decided_at": item.decided_at,
                "approved": item.approved,
            }
            for item in sorted(rows, key=lambda value: value.created_at, reverse=True)
        ]
