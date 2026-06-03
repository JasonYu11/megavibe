import type { RunEvent } from "../types";

type EventSourceConstructor = new (url: string) => EventSourceLike;

interface EventSourceLike {
  onopen: ((event?: Event) => void) | null;
  onerror: ((event?: Event) => void) | null;
  addEventListener(type: "run_event", listener: (event: MessageEvent) => void): void;
  close(): void;
}

export interface RunEventStreamOptions {
  projectId: string;
  sessionId: string;
  getLastSeq: () => number;
  onEvent: (event: RunEvent) => void;
  onOpen?: () => void;
  onError?: (error: Error) => void;
  reconnectDelayMs?: number;
  eventSourceFactory?: EventSourceConstructor;
}

export interface RunEventStream {
  close: () => void;
}

export function runEventStreamUrl(projectId: string, sessionId: string, lastSeq = 0): string {
  const params = lastSeq > 0 ? `?last_seq=${encodeURIComponent(String(lastSeq))}` : "";
  return `/api/projects/${projectId}/sessions/${sessionId}/stream${params}`;
}

export function startRunEventStream(options: RunEventStreamOptions): RunEventStream {
  const Source = (options.eventSourceFactory ?? globalThis.EventSource) as EventSourceConstructor | undefined;
  if (!Source) throw new Error("EventSource is not available");

  let closed = false;
  let source: EventSourceLike | null = null;
  let reconnectTimer = 0;
  const reconnectDelayMs = options.reconnectDelayMs ?? 1000;

  const clearReconnect = () => {
    if (reconnectTimer) {
      globalThis.clearTimeout(reconnectTimer);
      reconnectTimer = 0;
    }
  };

  const connect = () => {
    if (closed) return;
    clearReconnect();
    source?.close();
    const nextSource = new Source(runEventStreamUrl(options.projectId, options.sessionId, options.getLastSeq()));
    source = nextSource;
    nextSource.onopen = () => {
      if (!closed) options.onOpen?.();
    };
    nextSource.onerror = () => {
      if (closed) return;
      source?.close();
      options.onError?.(new Error("event stream disconnected"));
      reconnectTimer = globalThis.setTimeout(connect, reconnectDelayMs);
    };
    nextSource.addEventListener("run_event", (event) => {
      try {
        options.onEvent(JSON.parse(event.data) as RunEvent);
      } catch (exc) {
        options.onError?.(new Error(`event stream parse failed: ${String(exc)}`));
      }
    });
  };

  connect();

  return {
    close() {
      closed = true;
      clearReconnect();
      source?.close();
      source = null;
    },
  };
}
