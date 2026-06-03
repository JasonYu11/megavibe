import type { Message, RunEvent, ThoughtChain, ThoughtStep, UiItem } from "../types";

export type EventVisibility = "chat" | "timeline" | "debug" | "hidden";

export function itemsFromMessagesAndEvents(messages: Message[], events: RunEvent[]): UiItem[] {
  if (events.some((event) => event.kind === "turn_started")) {
    return itemsFromChronologicalEvents(messages, events);
  }
  return legacyItemsFromMessagesAndEvents(messages, events);
}

function legacyItemsFromMessagesAndEvents(messages: Message[], events: RunEvent[]): UiItem[] {
  const items: UiItem[] = [];
  const toolIndex = new Map<string, number>();
  let seq = 0;

  for (const message of messages) {
    if (message.role === "user") {
      items.push({ kind: "user", id: `m-${seq++}`, text: stripAttachmentContext(message.content || "") });
    } else if (message.role === "assistant" && message.content) {
      items.push({ kind: "assistant", id: `m-${seq++}`, text: message.content });
    }
  }

  for (const event of events) {
    const data = event.data || {};
    const idBase = String(event.seq ?? seq++);
    const visibility = classifyEventVisibility(event);
    if (event.kind === "assistant_message" && visibility === "chat") {
      const content = String(data.content || "");
      const hasSessionAssistant = items.some((item) => item.kind === "assistant" && item.text === content);
      if (content && !hasSessionAssistant) items.push({ kind: "assistant", id: `e-${idBase}`, text: content });
    }
    if (event.kind === "tool_dispatch") {
      const id = String(data.id || `tool-${idBase}`);
      const item: UiItem = {
        kind: "tool",
        id,
        name: String(data.name || "tool"),
        args: data.arguments ?? {},
        summary: toolSummary(String(data.name || "tool"), data.arguments ?? {}),
        status: "running",
        parentId: data.parent_tool_call_id ? String(data.parent_tool_call_id) : undefined,
      };
      toolIndex.set(id, items.length);
      items.push(item);
    }
    if (event.kind === "tool_result") {
      const id = String(data.id || `tool-${idBase}`);
      const status = data.blocked ? "blocked" : data.ok === false ? "error" : "done";
      const existing = toolIndex.get(id);
      if (existing !== undefined && items[existing]?.kind === "tool") {
        items[existing] = {
          ...(items[existing] as Extract<UiItem, { kind: "tool" }>),
          status,
          summary: (items[existing] as Extract<UiItem, { kind: "tool" }>).summary,
          output: String(data.output ?? data.result ?? ""),
          modelSummary: String(data.model_summary ?? ""),
          error: String(data.error ?? ""),
        };
      } else if (status !== "done") {
        items.push({
          kind: "tool",
          id,
          name: String(data.name || "tool"),
          args: {},
          summary: toolSummary(String(data.name || "tool"), {}),
          status,
          output: String(data.output ?? data.result ?? ""),
          modelSummary: String(data.model_summary ?? ""),
          error: String(data.error ?? ""),
          parentId: data.parent_tool_call_id ? String(data.parent_tool_call_id) : undefined,
        });
      }
    }
    if (event.kind === "notice" && visibility === "chat") {
      items.push({ kind: "notice", id: `n-${idBase}`, text: String(data.message || event.kind), level: "info" });
    }
    if (!isKnownEvent(event.kind) && visibility === "chat") {
      items.push({ kind: "notice", id: `n-${idBase}`, text: String(data.message || event.kind), level: "info" });
    }
    if (event.kind === "todo_updated" && visibility === "chat") {
      items.push({
        kind: "todo",
        id: `todo-${idBase}`,
        progressText: String(data.progress_text || ""),
        todos: Array.isArray(data.todos) ? data.todos : [],
      });
    }
    if (event.kind.startsWith("subagent_") && visibility === "chat") {
      items.push({
        kind: "subagent",
        id: String(data.subagent_id || `sub-${idBase}`),
        status: event.kind.replace("subagent_", ""),
        parentToolCallId: data.parent_tool_call_id ? String(data.parent_tool_call_id) : undefined,
      });
    }
  }

  return dedupeAssistantNoise(items);
}

function itemsFromChronologicalEvents(messages: Message[], events: RunEvent[]): UiItem[] {
  const items: UiItem[] = [];
  type ChangeReviewItem = Extract<UiItem, { kind: "change_review" }>;
  let chain: (ThoughtChain & { _flushed?: boolean }) | null = null;
  let finalAnswerSeen = false;
  let seq = 0;
  let turnChanges: ChangeReviewItem["changes"] = [];
  let turnReviewStatus: ChangeReviewItem["status"] = "pending";
  let currentTime = Date.now();

  const sortedEvents = [...events].sort((a, b) => {
    const left = typeof a.seq === "number" ? a.seq : Number.MAX_SAFE_INTEGER;
    const right = typeof b.seq === "number" ? b.seq : Number.MAX_SAFE_INTEGER;
    if (left !== right) return left - right;
    return 0;
  });

  const startChain = (idBase: string) => {
    chain = {
      id: `chain-${idBase}`,
      steps: [],
      status: "running",
      startedAt: currentTime,
    };
  };

  const ensureChain = (): ThoughtChain => {
    if (!chain) startChain(`implicit-${seq++}`);
    return chain as ThoughtChain;
  };

  const latestStep = (): ThoughtStep | undefined => {
    const c = chain;
    if (!c || !c.steps.length) return undefined;
    return c.steps[c.steps.length - 1];
  };

  const addStep = (step: ThoughtStep) => {
    ensureChain().steps.push(step);
  };

  const flushChain = (status: ThoughtChain["status"] = "completed") => {
    if (!chain || chain._flushed) return;
    chain._flushed = true;
    chain.status = status;
    chain.completedAt = currentTime;
    if (chain.steps.length > 0) {
      items.push({ kind: "thought_chain", id: chain.id, chain });
    }
  };

  const applyToolResult = (id: string, status: ThoughtStep["status"], output: string, error: string) => {
    if (!chain) return;
    for (let i = chain.steps.length - 1; i >= 0; i -= 1) {
      if (chain.steps[i].id === id && chain.steps[i].kind === "tool_call") {
        const step = chain.steps[i];
        const { added, removed } = parseDiffStats(output);
        chain.steps[i] = {
          ...step,
          status,
          summary: toolSummary(step.toolName || "", step.toolArgs || {}),
          detail: output ? tail(output, 1200) : undefined,
          error: status === "failed" ? error : undefined,
          diffAdded: added ?? step.diffAdded,
          diffRemoved: removed ?? step.diffRemoved,
          completedAt: currentTime,
        };
        break;
      }
    }
  };

  const pushChangeReview = (idBase: string) => {
    if (!turnChanges.length) return;
    items.push({
      kind: "change_review",
      id: `changes-${idBase}`,
      status: turnReviewStatus,
      changes: turnChanges,
      additions: turnChanges.reduce((total, change) => total + change.additions, 0),
      deletions: turnChanges.reduce((total, change) => total + change.deletions, 0),
    });
  };

  const updateLastChangeReview = (status: ChangeReviewItem["status"]) => {
    turnReviewStatus = status;
    for (let index = items.length - 1; index >= 0; index -= 1) {
      if (items[index].kind === "change_review") {
        items[index] = { ...(items[index] as ChangeReviewItem), status };
        return;
      }
    }
  };

  const markChangeReverted = (path: string, checkpointId: string) => {
    const mark = (changes: ChangeReviewItem["changes"]) =>
      changes.map((change) =>
        change.path === path && (!checkpointId || change.checkpointId === checkpointId)
          ? { ...change, status: "reverted" as const }
          : change,
      );
    turnChanges = mark(turnChanges);
    for (let index = items.length - 1; index >= 0; index -= 1) {
      if (items[index].kind === "change_review") {
        const current = items[index] as ChangeReviewItem;
        items[index] = { ...current, changes: mark(current.changes) };
        return;
      }
    }
  };

  for (const event of sortedEvents) {
    currentTime = typeof event.time === "number" ? event.time * 1000 : Date.now();
    const data = event.data || {};
    const idBase = String(event.seq ?? seq++);
    const visibility = classifyEventVisibility(event);

    if (event.kind === "turn_started") {
      flushChain("completed");
      finalAnswerSeen = false;
      turnChanges = [];
      turnReviewStatus = "pending";
      const input = String(data.input || data.message || "");
      if (input) items.push({ kind: "user", id: `u-${idBase}`, text: stripAttachmentContext(input) });
      startChain(idBase);
      continue;
    }

    if (event.kind === "assistant_message") {
      const content = String(data.content || "");
      const reasoning = String(data.reasoning || data.reasoning_content || "");
      const toolCalls = Array.isArray(data.tool_calls) ? data.tool_calls : [];
      if (content && toolCalls.length === 0) {
        // 最终回答（无工具调用）— 输出为对话气泡，不进思维链
        flushChain("completed");
        if (!hasAssistant(items, content)) {
          items.push({ kind: "assistant", id: `a-${idBase}`, text: content });
        }
        finalAnswerSeen = true;
      } else if (content && visibility === "chat") {
        // 有工具调用的思考 — 进思维链
        const firstLine = content.replace(/\n/g, " ").trim();
        addStep({
          id: `thought-${ensureChain().steps.length}-${idBase}`,
          kind: "thought",
          title: firstLine.length > 80 ? firstLine.slice(0, 77) + "..." : firstLine,
          status: "completed",
          detail: content,
          completedAt: currentTime,
        });
      }
      // reasoning 始终进思维链
      if (reasoning && visibility === "chat") {
        const firstLine = reasoning.replace(/\n/g, " ").trim();
        addStep({
          id: `thought-${ensureChain().steps.length}-${idBase}`,
          kind: "thought",
          title: firstLine.length > 80 ? firstLine.slice(0, 77) + "..." : firstLine,
          status: "completed",
          detail: reasoning,
          completedAt: currentTime,
        });
      }
      continue;
    }

    if (event.kind === "tool_dispatch") {
      const id = String(data.id || `tool-${idBase}`);
      const name = String(data.name || "tool");
      addStep({
        id,
        kind: "tool_call",
        title: toolTitle(name, data.arguments ?? {}),
        status: "running",
        toolName: name,
        toolArgs: isRecord(data.arguments) ? data.arguments as Record<string, unknown> : {},
        startedAt: currentTime,
        parentId: data.parent_tool_call_id ? String(data.parent_tool_call_id) : undefined,
      });
      continue;
    }

    if (event.kind === "tool_result") {
      const id = String(data.id || `tool-${idBase}`);
      const status: ThoughtStep["status"] = data.blocked ? "failed" : data.ok === false ? "failed" : "completed";
      const output = String(data.output ?? data.result ?? "");
      applyToolResult(id, status, output, String(data.error || ""));
      continue;
    }

    if (event.kind === "command_started") {
      const step = latestStep();
      if (step && step.kind === "tool_call") {
        step.summary = `执行: ${truncate(String(data.command || ""), 40)}`;
      }
      continue;
    }

    if (event.kind === "command_finished") {
      const step = latestStep();
      if (step && step.kind === "tool_call") {
        step.detail = tail(String(data.output_preview || ""), 1200);
      }
      continue;
    }

    if (event.kind === "job_started") {
      const step = latestStep();
      if (step && step.kind === "tool_call") {
        step.summary = `后台: ${truncate(String(data.command || ""), 40)}`;
      }
      continue;
    }

    if (event.kind === "job_finished") {
      const step = latestStep();
      if (step && step.kind === "tool_call") {
        step.detail = step.detail || "";
        step.status = typeof data.exit_code === "number" && data.exit_code !== 0 ? "failed" : "completed";
        step.completedAt = currentTime;
      }
      continue;
    }

    if (event.kind === "safety_ask") {
      const approvalId = approvalKey(data);
      addStep({
        id: `approval-${approvalId}`,
        kind: "thought",
        title: `审批: ${String(data.tool_name || "tool")}`,
        status: "running",
        detail: String(data.reason || "requires approval"),
        startedAt: currentTime,
      });
      continue;
    }

    if (event.kind === "safety_approved" || event.kind === "safety_deny") {
      const step = latestStep();
      if (step && step.kind === "thought" && step.title.startsWith("审批:")) {
        step.status = event.kind === "safety_approved" ? "completed" : "failed";
        step.completedAt = currentTime;
      }
      continue;
    }

    // Auto-review events: show review decisions in the timeline
    if (event.kind === "auto_review_approved" || event.kind === "auto_review_rejected" || event.kind === "auto_review_escalated") {
      const arId = `ar-${idBase}`;
      const step = latestStep();
      if (step && step.kind === "thought" && step.title.startsWith("审批:")) {
        step.status = event.kind === "auto_review_approved" ? "completed"
          : event.kind === "auto_review_rejected" ? "failed"
          : "completed";
        step.detail = `🤖 自动审查: ${String(data.reason || "")}`;
        step.completedAt = currentTime;
      } else {
        addStep({
          id: arId,
          kind: "thought",
          title: `自动审查: ${String(data.tool_name || "tool")}`,
          status: event.kind === "auto_review_rejected" ? "failed" : "completed",
          detail: `🤖 ${String(data.reason || "")}`,
          completedAt: currentTime,
        });
      }
      continue;
    }

    if (event.kind === "todo_updated" && visibility !== "debug") {
      const todos = Array.isArray(data.todos) ? data.todos : [];
      for (let i = 0; i < todos.length; i++) {
        const todo = todos[i] as Record<string, unknown> | undefined;
        if (!todo) continue;
        const content = String(todo.content || "");
        const status = String(todo.status || "pending");
        addStep({
          id: `todo-${idBase}-${i}`,
          kind: "thought",
          title: `${i + 1}. ${content}`,
          status: status === "completed" ? "completed" : "running",
          completedAt: status === "completed" ? currentTime : undefined,
        });
      }
      continue;
    }

    if (event.kind.startsWith("subagent_") && visibility !== "hidden" && visibility !== "debug") {
      addStep({
        id: `sub-${idBase}`,
        kind: "tool_call",
        title: `子Agent: ${event.kind.replace("subagent_", "")}`,
        status: event.kind === "subagent_completed" ? "completed" : event.kind === "subagent_failed" ? "failed" : "running",
        completedAt: event.kind === "subagent_completed" || event.kind === "subagent_failed" ? currentTime : undefined,
      });
      continue;
    }

    if (event.kind === "turn_failed") {
      flushChain("failed");
      items.push({ kind: "notice", id: `n-${idBase}`, text: String(data.error || data.message || "turn failed"), level: "warn" });
      continue;
    }

    if (event.kind === "turn_paused") {
      flushChain("completed");
      items.push({ kind: "notice", id: `n-${idBase}`, text: String(data.message || "turn paused"), level: "warn" });
      continue;
    }

    if (event.kind === "turn_completed") {
      flushChain("completed");
      const answer = String(data.answer || "");
      if (answer && !finalAnswerSeen && !hasAssistant(items, answer)) {
        items.push({ kind: "assistant", id: `a-${idBase}`, text: answer });
        finalAnswerSeen = true;
      }
      pushChangeReview(idBase);
      continue;
    }

    if (event.kind === "preview") {
      const diff = String(data.diff || "");
      const stats = diffStats(diff);
      turnChanges.push({
        path: String(data.path || ""),
        kind: String(data.kind || "modify"),
        additions: stats.additions,
        deletions: stats.deletions,
        diff,
        recoverable: true,
        source: String(data.source || data.tool_name || "tool"),
      });
      continue;
    }

    if (event.kind === "workspace_changes_detected") {
      const changes = Array.isArray(data.changes) ? data.changes : [];
      for (const raw of changes) {
        if (!isRecord(raw)) continue;
        turnChanges.push({
          path: pickString(raw, "path"),
          kind: pickString(raw, "kind") || "modify",
          additions: Number(raw.additions || 0),
          deletions: Number(raw.deletions || 0),
          diff: pickString(raw, "diff"),
          recoverable: Boolean(raw.recoverable),
          source: pickString(raw, "source") || String(data.source_kind || "command"),
          note: pickString(raw, "note"),
        });
      }
      continue;
    }

    if (event.kind === "checkpoint_saved") {
      const path = String(data.path || "");
      for (let index = turnChanges.length - 1; index >= 0; index -= 1) {
        const change = turnChanges[index];
        if (!change.checkpointId && (!path || change.path === path)) {
          turnChanges[index] = { ...change, checkpointId: String(data.id || "") };
          break;
        }
      }
      continue;
    }

    if (event.kind === "change_review_confirmed") {
      updateLastChangeReview("confirmed");
      continue;
    }

    if (event.kind === "change_review_file_reverted") {
      const path = String(data.path || "");
      const checkpointId = String(data.checkpoint_id || "");
      markChangeReverted(path, checkpointId);
      continue;
    }

    if (event.kind === "change_review_reverted") {
      updateLastChangeReview("reverted");
      continue;
    }

    if ((event.kind === "notice" || !isKnownEvent(event.kind)) && visibility === "chat") {
      addStep({
        id: `notice-${idBase}`,
        kind: "thought",
        title: truncate(String(data.message || event.kind), 60),
        status: "completed",
        completedAt: currentTime,
      });
    }
  }

  flushChain("completed");

  for (const message of messages) {
    if (message.role === "assistant" && message.content && !hasAssistant(items, message.content)) {
      items.push({ kind: "assistant", id: `m-${seq++}`, text: message.content });
    }
  }

  return dedupeAssistantNoise(items);
}

export function classifyEventVisibility(event: RunEvent): EventVisibility {
  const kind = event.kind;
  const data = event.data || {};
  if (kind === "assistant_message") {
    return (data.content || data.reasoning || data.reasoning_content) ? "chat" : "hidden";
  }
  if (kind === "tool_dispatch") return "chat";
  if (kind === "tool_result") {
    if (data.blocked || data.ok === false || data.error) return "chat";
    return "timeline";
  }
  if (kind === "safety_ask" || kind === "safety_approved" || kind === "safety_deny" || kind === "turn_failed" || kind === "turn_paused") return "chat";
  if (kind === "provider_error") return "timeline";
  if (kind === "todo_updated") return "chat";
  if (kind === "notice") {
    const message = String(data.message || "");
    if (/^step \d+: model requested/i.test(message)) return "hidden";
    if (message.startsWith("UI turn failed")) return "chat";
    return "timeline";
  }
  if (kind === "command_started" || kind === "command_finished") return "timeline";
  if (kind === "job_started" || kind === "job_finished") return "timeline";
  if (kind === "preview") return "timeline";
  if (kind === "compact_started" || kind === "compact_done" || kind === "compact_failed") return "timeline";
  if (kind === "plan_pending" || kind === "plan_cancelled") return "debug";
  if (kind.startsWith("subagent_")) {
    return kind === "subagent_failed" || kind === "subagent_cancel_requested" ? "chat" : "timeline";
  }
  if (kind.startsWith("git_")) return "timeline";
  if (kind === "command_output" || kind === "job_output") return "debug";
  if (
    kind === "controller_started" ||
    kind === "turn_started" ||
    kind === "turn_completed" ||
    kind === "checkpoint_saved" ||
    kind === "workspace_changes_detected" ||
    kind === "change_review_confirmed" ||
    kind === "change_review_file_reverted" ||
    kind === "change_review_reverted" ||
    kind === "compact_check" ||
    kind === "compact_skipped" ||
    kind === "test_approval_auto_allowed"
  ) {
    return "debug";
  }
  return isTranscriptEvent(kind) ? "chat" : "debug";
}

function isKnownEvent(kind: string): boolean {
  return [
    "assistant_message",
    "tool_dispatch",
    "tool_result",
    "notice",
    "todo_updated",
    "controller_started",
    "turn_started",
    "turn_completed",
    "turn_failed",
    "turn_paused",
    "provider_error",
    "turn_cancel_requested",
    "command_started",
    "command_output",
    "command_finished",
    "job_started",
    "job_output",
    "job_finished",
    "checkpoint_saved",
    "workspace_changes_detected",
    "change_review_confirmed",
    "change_review_file_reverted",
    "change_review_reverted",
    "preview",
    "compact_check",
    "compact_skipped",
    "compact_started",
    "compact_done",
    "compact_failed",
    "plan_pending",
    "plan_cancelled",
    "safety_ask",
    "safety_approved",
    "safety_deny",
    "test_approval_auto_allowed",
    "git_baseline",
    "git_classify_changes",
    "git_overlap_risk",
    "git_commit_started",
    "git_commit_done",
    "git_commit_failed",
    "git_changes_classified",
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
  ].includes(kind) || kind.startsWith("subagent_");
}

function stripAttachmentContext(text: string): string {
  const marker = "\n[Attached files]";
  const index = text.indexOf(marker);
  if (index >= 0) return text.slice(0, index).trim();
  return text;
}

function isTranscriptEvent(kind: string): boolean {
  return kind.startsWith("user_") || kind.startsWith("agent_");
}

function dedupeAssistantNoise(items: UiItem[]): UiItem[] {
  const out: UiItem[] = [];
  let lastAssistant = "";
  for (const item of items) {
    if (item.kind === "assistant") {
      if (!item.text.trim() || item.text === lastAssistant) continue;
      lastAssistant = item.text;
    }
    out.push(item);
  }
  return out;
}

function hasAssistant(items: UiItem[], text: string): boolean {
  return items.some((item) => item.kind === "assistant" && item.text === text);
}

function toolFooterMetadata(output: string): Partial<Extract<UiItem, { kind: "tool" }>> {
  const metadata: Partial<Extract<UiItem, { kind: "tool" }>> = {};
  const python = output.match(/\[python\]\s+exit_code=(\d+)\s+duration_ms=(\d+)\s+executable=([^\s]+)\s+source=([^\n]+)/);
  if (python) {
    metadata.commandKind = "python";
    metadata.exitCode = Number(python[1]);
    metadata.durationMs = Number(python[2]);
    metadata.runtime = `${python[3]} (${python[4].trim()})`;
  }
  const command = output.match(/\[command\]\s+exit_code=(\d+)\s+duration_ms=(\d+)\s+shell=([^\n]+)/);
  if (command) {
    metadata.commandKind = "bash";
    metadata.exitCode = Number(command[1]);
    metadata.durationMs = Number(command[2]);
    metadata.runtime = command[3].trim();
  }
  const withoutFooter = output
    .replace(/\n?\[(python|command)\]\s+exit_code=.*$/s, "")
    .trim();
  if (withoutFooter) metadata.outputPreview = tail(withoutFooter, 1200);
  return metadata;
}

function tail(text: string, max: number): string {
  if (text.length <= max) return text;
  return `...[${text.length - max} chars omitted]...\n${text.slice(-max)}`;
}

function diffStats(diff: string): { additions: number; deletions: number } {
  let additions = 0;
  let deletions = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) additions += 1;
    else if (line.startsWith("-")) deletions += 1;
  }
  return { additions, deletions };
}

function toolTitle(name: string, args: unknown): string {
  const data = isRecord(args) ? args : {};
  const filePath = pickString(data, "file_path") || pickString(data, "path") || pickString(data, "file") || pickString(data, "target_path");
  const pattern = pickString(data, "pattern");
  const command = pickString(data, "command");
  if (name === "read_file" && filePath) return `read_file · ${truncate(filePath.replace(/.*\//, ""), 30)}`;
  if (name === "write_file" && filePath) return `write_file · ${truncate(filePath.replace(/.*\//, ""), 30)}`;
  if (name === "edit_file" && filePath) return `edit_file · ${truncate(filePath.replace(/.*\//, ""), 30)}`;
  if (name === "grep" && pattern) return `grep · ${truncate(pattern, 30)}`;
  if (name === "bash" && command) return `bash · ${truncate(command, 40)}`;
  if (name === "glob" && pattern) return `glob · ${truncate(pattern, 30)}`;
  if (name === "python_run") return "python_run";
  if (name === "task") return "子Agent";
  if (name === "todo_write") return "计划更新";
  return name;
}

function toolSummary(name: string, args: unknown): string {
  const data = isRecord(args) ? args : {};
  const path = pickString(data, "path") || pickString(data, "file") || pickString(data, "target_path");
  if (name === "read_file" && path) return `读取 ${path}`;
  if (name === "write_file" && path) return `写入 ${path}`;
  if (name === "edit_file" && path) return `修改 ${path}`;
  if (name === "python_run") {
    const file = pickString(data, "file") || pickString(data, "path") || pickString(data, "module");
    return file ? `运行 Python: ${file}` : "运行 Python";
  }
  if (name === "bash") {
    const command = pickString(data, "command");
    return command ? `执行命令: ${truncate(command, 96)}` : "执行 shell 命令";
  }
  if (name === "grep") {
    const pattern = pickString(data, "pattern");
    return pattern ? `搜索: ${pattern}` : "搜索代码";
  }
  if (name === "todo_write") return "更新计划";
  if (name === "task") return "启动子 agent";
  return name;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function pickString(data: Record<string, unknown>, key: string): string {
  const value = data[key];
  return typeof value === "string" ? value : "";
}

function approvalKey(data: Record<string, unknown>): string {
  const tool = String(data.tool_name || "tool");
  const args = stableStringify(data.arguments ?? {});
  return `${tool}:${args}`;
}

function stableStringify(value: unknown): string {
  if (!isRecord(value)) return JSON.stringify(value);
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) sorted[key] = value[key];
  return JSON.stringify(sorted);
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

function parseDiffStats(output: string): { added?: number; removed?: number } {
  const match = output.match(/\(([^)]*lines[^)]*)\)/);
  if (!match) return {};
  const inner = match[1];
  const added = inner.match(/\+(\d+)/);
  const removed = inner.match(/-(\d+)/);
  return {
    added: added ? parseInt(added[1], 10) : undefined,
    removed: removed ? parseInt(removed[1], 10) : undefined,
  };
}
