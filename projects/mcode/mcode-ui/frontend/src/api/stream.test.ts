import { afterEach, describe, expect, it, vi } from "vitest";
import { runEventStreamUrl, startRunEventStream } from "./stream";
import type { RunEvent } from "../types";

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  private listeners = new Map<string, (event: MessageEvent) => void>();

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: "run_event", listener: (event: MessageEvent) => void): void {
    this.listeners.set(type, listener);
  }

  emit(record: RunEvent): void {
    this.listeners.get("run_event")?.({ data: JSON.stringify(record) } as MessageEvent);
  }

  emitRaw(data: string): void {
    this.listeners.get("run_event")?.({ data } as MessageEvent);
  }

  close(): void {
    this.closed = true;
  }
}

describe("run event stream", () => {
  afterEach(() => {
    vi.useRealTimers();
    FakeEventSource.instances = [];
  });

  it("builds stream URLs with last_seq replay cursor", () => {
    expect(runEventStreamUrl("p1", "s1")).toBe("/api/projects/p1/sessions/s1/stream");
    expect(runEventStreamUrl("p1", "s1", 42)).toBe("/api/projects/p1/sessions/s1/stream?last_seq=42");
  });

  it("reconnects with the latest observed sequence", () => {
    vi.useFakeTimers();
    let lastSeq = 3;
    const received: RunEvent[] = [];
    const open = vi.fn();
    const disconnected = vi.fn();
    const stream = startRunEventStream({
      projectId: "p1",
      sessionId: "s1",
      getLastSeq: () => lastSeq,
      onOpen: open,
      onError: disconnected,
      onEvent: (event) => {
        received.push(event);
        lastSeq = Math.max(lastSeq, Number(event.seq ?? 0) || 0);
      },
      reconnectDelayMs: 25,
      eventSourceFactory: FakeEventSource,
    });

    expect(FakeEventSource.instances[0].url).toBe("/api/projects/p1/sessions/s1/stream?last_seq=3");
    FakeEventSource.instances[0].onopen?.();
    FakeEventSource.instances[0].emit({ kind: "assistant_delta", data: { delta: "ok" }, seq: 4 });
    FakeEventSource.instances[0].onerror?.();
    vi.advanceTimersByTime(25);

    expect(open).toHaveBeenCalledOnce();
    expect(disconnected).toHaveBeenCalledOnce();
    expect(received).toHaveLength(1);
    expect(FakeEventSource.instances[0].closed).toBe(true);
    expect(FakeEventSource.instances[1].url).toBe("/api/projects/p1/sessions/s1/stream?last_seq=4");
    stream.close();
  });

  it("does not reconnect after close", () => {
    vi.useFakeTimers();
    const stream = startRunEventStream({
      projectId: "p1",
      sessionId: "s1",
      getLastSeq: () => 0,
      onEvent: vi.fn(),
      reconnectDelayMs: 25,
      eventSourceFactory: FakeEventSource,
    });
    stream.close();
    FakeEventSource.instances[0].onerror?.();
    vi.advanceTimersByTime(50);

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("reports parse failures without closing the stream", () => {
    const errors: string[] = [];
    startRunEventStream({
      projectId: "p1",
      sessionId: "s1",
      getLastSeq: () => 0,
      onEvent: vi.fn(),
      onError: (error) => errors.push(error.message),
      eventSourceFactory: FakeEventSource,
    });

    FakeEventSource.instances[0].emitRaw("{bad json");

    expect(errors[0]).toContain("event stream parse failed");
    expect(FakeEventSource.instances[0].closed).toBe(false);
  });
});
