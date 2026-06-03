import type { RunEvent } from "../types";
import { classifyEventVisibility } from "../state/events";
import { useMemo, useState } from "react";

export function EventTimeline({ events }: { events: RunEvent[] }) {
  const [showDebug, setShowDebug] = useState(false);
  const [filter, setFilter] = useState("");
  const hiddenCount = useMemo(
    () => events.filter((event) => classifyEventVisibility(event) === "debug" || classifyEventVisibility(event) === "hidden").length,
    [events],
  );
  const rows = compactEvents(events, showDebug).filter((event) =>
    filter.trim() ? event.kind.toLowerCase().includes(filter.trim().toLowerCase()) : true,
  );
  return (
    <div className="panelBody timeline" data-testid="event-timeline">
      <div className="timeline__toolbar">
        <span>{showDebug ? "完整事件" : "关键事件"}</span>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="过滤 kind"
          aria-label="Filter event kind"
        />
        <button className="secondaryButton" onClick={() => setShowDebug(!showDebug)}>
          {showDebug ? "隐藏调试事件" : `显示调试事件${hiddenCount ? ` (${hiddenCount})` : ""}`}
        </button>
        <button className="secondaryButton" onClick={() => void navigator.clipboard?.writeText(JSON.stringify(rows, null, 2))}>
          复制 JSON
        </button>
      </div>
      {rows.length === 0 && <div className="emptyNote">暂无事件</div>}
      {rows.map((event, index) => (
        <div className="timeline__item" key={`${event.seq ?? index}-${event.kind}`}>
          <div className="timeline__kind">
            {event.kind}
            {event.count ? <span>{event.count} 条</span> : null}
          </div>
          <button className="timeline__copy" onClick={() => void navigator.clipboard?.writeText(JSON.stringify(event, null, 2))}>
            复制
          </button>
          <pre>{JSON.stringify(event.data, null, 2)}</pre>
        </div>
      ))}
    </div>
  );
}

type TimelineRow = RunEvent & { count?: number };

function compactEvents(events: RunEvent[], showDebug: boolean): TimelineRow[] {
  const rows: TimelineRow[] = [];
  const commandOutput = new Map<string, TimelineRow>();
  const jobOutput = new Map<string, TimelineRow>();

  for (const event of events) {
    const visibility = classifyEventVisibility(event);
    if (!showDebug && (visibility === "debug" || visibility === "hidden")) continue;
    if (event.kind === "command_output") {
      const commandId = String(event.data?.command_id || "command");
      const existing = commandOutput.get(commandId);
      const text = String(event.data?.text || "");
      if (existing) {
        existing.count = (existing.count || 1) + 1;
        existing.data = { ...existing.data, text: tailText(`${existing.data.text || ""}${text}`) };
      } else {
        const row = { ...event, data: { ...event.data, text: tailText(text) }, count: 1 };
        commandOutput.set(commandId, row);
        rows.push(row);
      }
      continue;
    }
    if (event.kind === "job_output") {
      const jobId = String(event.data?.job_id || "job");
      const existing = jobOutput.get(jobId);
      const text = String(event.data?.text || "");
      if (existing) {
        existing.count = (existing.count || 1) + 1;
        existing.data = { ...existing.data, text: tailText(`${existing.data.text || ""}${text}`) };
      } else {
        const row = { ...event, data: { ...event.data, text: tailText(text) }, count: 1 };
        jobOutput.set(jobId, row);
        rows.push(row);
      }
      continue;
    }
    rows.push(event);
  }
  return rows;
}

function tailText(text: string, maxChars = 1600): string {
  if (text.length <= maxChars) return text;
  return `...${text.slice(-maxChars)}`;
}
