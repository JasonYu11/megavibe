from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any, Iterator, Optional


Subscriber = queue.Queue[Optional[dict[str, Any]]]


class EventBroker:
    """In-process fanout for freshly persisted run events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[tuple[str, str], list[Subscriber]] = {}

    def publish(self, root: str | Path, session_id: str, record: dict[str, Any]) -> None:
        key = self.key(root, session_id)
        with self._lock:
            subscribers = list(self._subscribers.get(key, []))
        for subscriber in subscribers:
            _offer(subscriber, record)

    def subscribe(self, root: str | Path, session_id: str) -> Subscriber:
        key = self.key(root, session_id)
        subscriber: Subscriber = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.setdefault(key, []).append(subscriber)
        return subscriber

    def unsubscribe(self, root: str | Path, session_id: str, subscriber: Subscriber) -> None:
        key = self.key(root, session_id)
        with self._lock:
            subscribers = self._subscribers.get(key)
            if not subscribers:
                return
            self._subscribers[key] = [item for item in subscribers if item is not subscriber]
            if not self._subscribers[key]:
                self._subscribers.pop(key, None)
        _offer(subscriber, None)

    @staticmethod
    def key(root: str | Path, session_id: str) -> tuple[str, str]:
        return (str(Path(root).resolve(strict=False)), session_id)


event_broker = EventBroker()


def _offer(subscriber: Subscriber, record: Optional[dict[str, Any]]) -> None:
    try:
        subscriber.put_nowait(record)
        return
    except queue.Full:
        pass
    try:
        subscriber.get_nowait()
    except queue.Empty:
        pass
    try:
        subscriber.put_nowait(record)
    except queue.Full:
        pass


def sse_record(record: dict[str, Any]) -> str:
    seq = record.get("seq", "")
    payload = json.dumps(record, ensure_ascii=False, default=str)
    return f"event: run_event\nid: {seq}\ndata: {payload}\n\n"


def stream_records(
    broker: EventBroker,
    root: str | Path,
    session_id: str,
    replay: list[dict[str, Any]],
    last_seq: int = 0,
) -> Iterator[str]:
    subscriber = broker.subscribe(root, session_id)
    emitted = int(last_seq or 0)
    try:
        for record in replay:
            seq = _seq(record)
            if seq <= emitted:
                continue
            emitted = seq
            yield sse_record(record)
        while True:
            try:
                record = subscriber.get(timeout=15)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue
            if record is None:
                break
            seq = _seq(record)
            if seq <= emitted:
                continue
            emitted = seq
            yield sse_record(record)
    finally:
        broker.unsubscribe(root, session_id, subscriber)


def _seq(record: dict[str, Any]) -> int:
    try:
        return int(record.get("seq") or 0)
    except (TypeError, ValueError):
        return 0
