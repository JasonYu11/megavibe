import type { RunEvent, RunTrace, TraceAction, TraceStatus, TraceStep } from "../types";

const TRACE_EVENT_KINDS = new Set([
  "turn_status",
  "thought_summary_started",
  "thought_summary_delta",
  "thought_summary_completed",
  "thought_summary_redacted",
  "step_started",
  "step_progress",
  "step_completed",
  "step_failed",
  "action_started",
  "action_completed",
  "action_failed",
  "file_read",
  "file_edited",
  "verification_completed",
  "verification_failed",
  "assistant_message_started",
  "assistant_delta",
  "assistant_message_completed",
  "assistant_message_failed",
  "tool_call_started",
  "tool_call_delta",
  "tool_call_completed",
  "turn_cancel_requested",
]);

export function hasTraceEvents(events: RunEvent[]): boolean {
  return events.some((event) => TRACE_EVENT_KINDS.has(event.kind));
}

export function buildRunTraces(events: RunEvent[]): RunTrace[] {
  const sortedEvents = uniqueSortedEvents(events);
  const groups: RunEvent[][] = [];
  let current: RunEvent[] = [];

  const flush = () => {
    if (current.length && hasTraceEvents(current)) groups.push(current);
    current = [];
  };

  for (const event of sortedEvents) {
    if (event.kind === "turn_started") {
      flush();
      current = [event];
      continue;
    }
    if (current.length) {
      current.push(event);
      continue;
    }
    if (TRACE_EVENT_KINDS.has(event.kind)) current = [event];
  }
  flush();

  return groups.map((group) => buildRunTrace(group));
}

export function buildRunTrace(events: RunEvent[]): RunTrace {
  const sortedEvents = uniqueSortedEvents(events);
  const steps = new Map<string, TraceStep>();
  const actions = new Map<string, TraceAction>();
  let status: TraceStatus = "running";
  let phase = "";
  let message = "";
  let thoughtSummary = "";
  let assistantDraft = "";
  let assistantMessageId = "";
  let id = "agent-run";

  const ensureStep = (stepId: string, title = "执行步骤"): TraceStep => {
    const existing = steps.get(stepId);
    if (existing) {
      if (title && existing.title === "执行步骤") existing.title = title;
      return existing;
    }
    const step: TraceStep = { id: stepId, title, status: "pending", actions: [] };
    steps.set(stepId, step);
    return step;
  };

  const ensureAction = (actionId: string, stepId: string, title = "执行动作", kind = "tool"): TraceAction => {
    const existing = actions.get(actionId);
    if (existing) return existing;
    const step = ensureStep(stepId);
    const action: TraceAction = { id: actionId, stepId, kind, title, status: "pending" };
    actions.set(actionId, action);
    step.actions.push(action);
    return action;
  };

  for (const event of sortedEvents) {
    const data = event.data || {};
    if (event.kind === "turn_started") {
      id = `agent-run-${String(event.seq ?? "latest")}`;
      status = "running";
      continue;
    }
    if (event.kind === "turn_status") {
      status = normalizeStatus(data.status, status);
      phase = text(data.phase);
      message = text(data.message);
      continue;
    }
    if (event.kind === "turn_completed") {
      status = "completed";
      continue;
    }
    if (event.kind === "turn_failed") {
      status = "failed";
      message = text(data.error || data.message || message);
      continue;
    }
    if (event.kind === "turn_cancel_requested") {
      if (data.running !== false) status = "cancelled";
      message = "正在取消";
      continue;
    }
    if (event.kind === "turn_paused") {
      status = data.cancelled ? "cancelled" : status;
      message = text(data.message || message);
      if (data.cancelled) cancelOpenTraceItems(steps, actions);
      continue;
    }
    if (event.kind === "thought_summary_delta" || event.kind === "thought_summary_completed") {
      thoughtSummary = appendUnique(thoughtSummary, text(data.text));
      continue;
    }
    if (event.kind === "thought_summary_redacted") {
      thoughtSummary = appendUnique(thoughtSummary, "部分思考摘要已隐藏");
      continue;
    }
    if (event.kind === "step_started") {
      const step = ensureStep(text(data.step_id) || `step-${event.seq ?? steps.size + 1}`, text(data.title) || "执行步骤");
      step.status = "running";
      continue;
    }
    if (event.kind === "step_progress") {
      const step = ensureStep(text(data.step_id) || `step-${event.seq ?? steps.size + 1}`);
      step.summary = text(data.message);
      if (step.status === "pending") step.status = "running";
      continue;
    }
    if (event.kind === "step_completed") {
      const step = ensureStep(text(data.step_id) || `step-${event.seq ?? steps.size + 1}`);
      step.status = "completed";
      step.summary = text(data.summary);
      continue;
    }
    if (event.kind === "step_failed") {
      const step = ensureStep(text(data.step_id) || `step-${event.seq ?? steps.size + 1}`);
      step.status = "failed";
      step.summary = text(data.error);
      continue;
    }
    if (event.kind === "action_started") {
      const action = ensureAction(
        text(data.action_id) || `action-${event.seq ?? actions.size + 1}`,
        text(data.step_id),
        text(data.title) || text(data.kind) || "执行动作",
        text(data.kind) || "tool",
      );
      action.status = "running";
      action.summary = text(data.summary);
      continue;
    }
    if (event.kind === "action_completed") {
      const action = ensureAction(text(data.action_id) || `action-${event.seq ?? actions.size + 1}`, text(data.step_id));
      action.status = "completed";
      action.summary = text(data.summary);
      continue;
    }
    if (event.kind === "action_failed") {
      const action = ensureAction(text(data.action_id) || `action-${event.seq ?? actions.size + 1}`, text(data.step_id));
      action.status = "failed";
      action.error = text(data.error);
      continue;
    }
    if (event.kind === "file_read") {
      const action = ensureAction(text(data.action_id) || `file-read-${event.seq}`, text(data.step_id), `读取 ${text(data.path)}`, "file_read");
      action.path = text(data.path);
      action.status = action.status === "pending" ? "completed" : action.status;
      continue;
    }
    if (event.kind === "file_edited") {
      const action = ensureAction(text(data.action_id) || `file-edit-${event.seq}`, text(data.step_id), `编辑 ${text(data.path)}`, "file_edit");
      action.path = text(data.path);
      action.additions = number(data.additions);
      action.deletions = number(data.deletions);
      action.diffPreview = text(data.diff_preview);
      continue;
    }
    if (event.kind === "verification_completed" || event.kind === "verification_failed") {
      const action = ensureAction(text(data.action_id) || `verification-${event.seq}`, text(data.step_id), `验证 ${text(data.command)}`, "verification");
      action.command = text(data.command);
      action.status = event.kind === "verification_completed" ? "completed" : "failed";
      action.exitCode = nullableNumber(data.exit_code);
      action.durationMs = number(data.duration_ms);
      action.summary = text(data.summary);
      continue;
    }
    if (event.kind === "assistant_message_started") {
      const nextMessageId = text(data.message_id);
      if (nextMessageId && nextMessageId !== assistantMessageId) {
        assistantMessageId = nextMessageId;
        assistantDraft = "";
      }
      continue;
    }
    if (event.kind === "assistant_delta") {
      const nextMessageId = text(data.message_id);
      if (nextMessageId && nextMessageId !== assistantMessageId) {
        assistantMessageId = nextMessageId;
        assistantDraft = "";
      }
      assistantDraft += text(data.delta);
      continue;
    }
    if (event.kind === "assistant_message_completed") {
      const nextMessageId = text(data.message_id);
      if (nextMessageId) assistantMessageId = nextMessageId;
      assistantDraft = text(data.content) || assistantDraft;
      continue;
    }
    if (event.kind === "assistant_message_failed") {
      status = "failed";
      message = text(data.error || message);
      continue;
    }
    if (event.kind === "tool_call_started") {
      const action = ensureAction(
        toolCallActionId(data, event.seq),
        text(data.step_id),
        toolCallTitle(data),
        "tool",
      );
      action.status = "running";
      action.summary = "正在准备工具调用";
      continue;
    }
    if (event.kind === "tool_call_delta") {
      const action = ensureAction(
        toolCallActionId(data, event.seq),
        text(data.step_id),
        toolCallTitle(data),
        "tool",
      );
      action.status = "running";
      action.summary = `正在准备工具调用${number(data.received_chars) ? ` (${number(data.received_chars)} chars)` : ""}`;
      continue;
    }
    if (event.kind === "tool_call_completed") {
      const action = ensureAction(
        toolCallActionId(data, event.seq),
        text(data.step_id),
        toolCallTitle(data),
        "tool",
      );
      action.status = "completed";
      action.summary = "工具调用已准备完成";
    }
  }

  return {
    id,
    status,
    phase,
    message,
    thoughtSummary,
    assistantDraft,
    steps: Array.from(steps.values()),
  };
}

function uniqueSortedEvents(events: RunEvent[]): RunEvent[] {
  const byKey = new Map<string, { event: RunEvent; index: number }>();
  events.forEach((event, index) => {
    const existing = byKey.get(eventKey(event));
    byKey.set(eventKey(event), { event, index: existing?.index ?? index });
  });
  return Array.from(byKey.values())
    .sort((a, b) => compareEventOrder(a.event, b.event, a.index, b.index))
    .map((entry) => entry.event);
}

function compareEventOrder(a: RunEvent, b: RunEvent, aIndex: number, bIndex: number): number {
  const aSeq = seqValue(a);
  const bSeq = seqValue(b);
  if (aSeq !== null && bSeq !== null) {
    const diff = aSeq - bSeq;
    return diff || aIndex - bIndex;
  }
  if (aSeq !== null) return -1;
  if (bSeq !== null) return 1;
  return aIndex - bIndex;
}

function eventKey(event: RunEvent): string {
  if (event.seq !== undefined && event.seq !== null) return `seq:${String(event.seq)}`;
  return `${event.kind}:${JSON.stringify(event.data ?? {})}`;
}

function seqValue(event: RunEvent): number | null {
  if (event.seq === undefined || event.seq === null) return null;
  const value = Number(event.seq);
  return Number.isFinite(value) ? value : null;
}

function normalizeStatus(value: unknown, fallback: TraceStatus): TraceStatus {
  const raw = text(value);
  if (raw === "completed" || raw === "complete") return "completed";
  if (raw === "failed" || raw === "error") return "failed";
  if (raw === "cancelled" || raw === "cancelling" || raw === "paused") return "cancelled";
  if (raw === "pending") return "pending";
  if (raw) return "running";
  return fallback;
}

function appendUnique(current: string, next: string): string {
  if (!next || current.endsWith(next)) return current;
  return current ? `${current}\n${next}` : next;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function cancelOpenTraceItems(steps: Map<string, TraceStep>, actions: Map<string, TraceAction>): void {
  for (const action of actions.values()) {
    if (action.status === "running" || action.status === "pending") {
      action.status = "cancelled";
      if (!action.error && !action.summary) action.summary = "已取消";
    }
  }
  for (const step of steps.values()) {
    if (step.status === "running" || step.status === "pending") {
      step.status = "cancelled";
      if (!step.summary) step.summary = "已取消";
    }
  }
}

function toolCallActionId(data: Record<string, unknown>, seq: unknown): string {
  const messageId = text(data.message_id) || "assistant";
  const index = nullableNumber(data.tool_call_index) ?? seq ?? 0;
  return `tool-call-${messageId}-${index}`;
}

function toolCallTitle(data: Record<string, unknown>): string {
  const toolName = text(data.tool_name);
  return toolName ? `准备 ${toolName}` : "准备工具调用";
}
