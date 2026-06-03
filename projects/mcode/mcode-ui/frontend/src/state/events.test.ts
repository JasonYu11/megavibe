import { describe, expect, it } from "vitest";
import { classifyEventVisibility, itemsFromMessagesAndEvents } from "./events";

describe("itemsFromMessagesAndEvents", () => {
  it("keeps unknown events out of transcript", () => {
    const items = itemsFromMessagesAndEvents([], [{ kind: "surprise_event", data: { value: 1 }, seq: 1 }]);
    expect(items).toEqual([]);
  });

  it("does not duplicate assistant content already in session", () => {
    const items = itemsFromMessagesAndEvents(
      [{ role: "assistant", content: "OK" }],
      [{ kind: "assistant_message", data: { content: "OK" }, seq: 1 }],
    );
    expect(items.filter((item) => item.kind === "assistant")).toHaveLength(1);
  });

  it("does not render runtime log events in transcript", () => {
    const items = itemsFromMessagesAndEvents(
      [{ role: "assistant", content: "最终回答" }],
      [
        { kind: "command_output", data: { text: "line 1\n" }, seq: 1 },
        { kind: "checkpoint_saved", data: { path: "x.py" }, seq: 2 },
        { kind: "compact_check", data: {}, seq: 3 },
        { kind: "turn_completed", data: { answer: "最终回答" }, seq: 4 },
      ],
    );
    expect(items).toEqual([{ kind: "assistant", id: "m-0", text: "最终回答" }]);
  });

  it("keeps step notices and successful tool result output out of chat", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "notice", data: { message: "step 3: model requested 1 tool call(s)" }, seq: 1 },
      { kind: "tool_result", data: { id: "orphan", name: "bash", ok: true, output: "many logs" }, seq: 2 },
    ]);
    expect(items).toEqual([]);
  });

  it("renders compact tool summaries in chat", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "tool_dispatch", data: { id: "t1", name: "read_file", arguments: { path: "README.md" } }, seq: 1 },
      { kind: "tool_result", data: { id: "t1", name: "read_file", ok: true, output: "content" }, seq: 2 },
    ]);
    expect(items).toMatchObject([{ kind: "tool", name: "read_file", summary: "读取 README.md", status: "done" }]);
  });

  it("classifies noisy events as debug or hidden", () => {
    expect(classifyEventVisibility({ kind: "command_output", data: { text: "x" } })).toBe("debug");
    expect(classifyEventVisibility({ kind: "compact_check", data: {} })).toBe("debug");
    expect(classifyEventVisibility({ kind: "plan_pending", data: { plan_text: "plan" } })).toBe("debug");
    expect(classifyEventVisibility({ kind: "provider_error", data: { kind: "network_timeout" } })).toBe("timeline");
    expect(classifyEventVisibility({ kind: "notice", data: { message: "step 1: model requested 1 tool call(s)" } })).toBe("hidden");
  });

  it("renders provider failure fallback without duplicating provider diagnostics in chat", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "继续" }, seq: 1 },
      { kind: "provider_error", data: { kind: "network_timeout", message: "read timed out" }, seq: 2 },
      { kind: "assistant_message", data: { content: "模型请求超时，本轮没有继续执行工具。", tool_calls: [] }, seq: 3 },
      { kind: "turn_failed", data: { error: "network_timeout: read timed out", recoverable: true }, seq: 4 },
    ]);

    expect(items.map((item) => item.kind)).toEqual(["user", "assistant", "notice"]);
    expect(items[1]).toMatchObject({ kind: "assistant", text: "模型请求超时，本轮没有继续执行工具。" });
    expect(items[2]).toMatchObject({ kind: "notice", text: "network_timeout: read timed out" });
  });

  it("orders a turn as user, folded thinking process, then assistant answer", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "读取 README" }, seq: 1 },
      { kind: "tool_dispatch", data: { id: "t1", name: "read_file", arguments: { path: "README.md" } }, seq: 2 },
      { kind: "tool_result", data: { id: "t1", name: "read_file", ok: true, output: "content" }, seq: 3 },
      { kind: "assistant_message", data: { content: "README 内容如下" }, seq: 4 },
      { kind: "turn_completed", data: { answer: "README 内容如下" }, seq: 5 },
    ]);

    expect(items.map((item) => item.kind)).toEqual(["user", "thinking", "assistant"]);
    expect(items[0]).toMatchObject({ kind: "user", text: "读取 README" });
    expect(items[1]).toMatchObject({ kind: "thinking", status: "done" });
    expect((items[1] as Extract<(typeof items)[number], { kind: "thinking" }>).items).toMatchObject([
      { kind: "tool", name: "read_file", status: "done", summary: "读取 README.md" },
    ]);
    expect(items[2]).toMatchObject({ kind: "assistant", text: "README 内容如下" });
  });

  it("renders product trace events as an agent run block", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "读取 README" }, seq: 1 },
      { kind: "turn_status", data: { status: "running", phase: "executing_tools", message: "正在执行工具调用" }, seq: 2 },
      { kind: "thought_summary_delta", data: { text: "正在检查 README" }, seq: 3 },
      { kind: "step_started", data: { step_id: "step-1", title: "读取文件" }, seq: 4 },
      { kind: "action_started", data: { action_id: "a1", step_id: "step-1", kind: "file_read", title: "读取 README.md" }, seq: 5 },
      { kind: "file_read", data: { action_id: "a1", step_id: "step-1", path: "README.md" }, seq: 6 },
      { kind: "action_completed", data: { action_id: "a1", summary: "读取完成" }, seq: 7 },
      { kind: "step_completed", data: { step_id: "step-1", summary: "读取完成" }, seq: 8 },
      { kind: "assistant_message_completed", data: { message_id: "m1", content: "README 内容如下", tool_calls: [] }, seq: 9 },
      { kind: "assistant_message", data: { content: "README 内容如下", tool_calls: [] }, seq: 10 },
      { kind: "turn_completed", data: { answer: "README 内容如下" }, seq: 11 },
    ]);

    expect(items.map((item) => item.kind)).toEqual(["user", "agent_run", "assistant"]);
    expect(items[1]).toMatchObject({
      kind: "agent_run",
      trace: {
        thoughtSummary: "正在检查 README",
        steps: [{ title: "读取文件", actions: [{ kind: "file_read", path: "README.md" }] }],
      },
    });
  });

  it("renders separate agent run blocks for multiple traced turns", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "第一轮" }, seq: 1 },
      { kind: "turn_status", data: { status: "running", phase: "model_call", message: "生成第一轮" }, seq: 2 },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "答复一" }, seq: 3 },
      { kind: "assistant_message_completed", data: { message_id: "m1", content: "答复一", tool_calls: [] }, seq: 4 },
      { kind: "assistant_message", data: { content: "答复一", tool_calls: [] }, seq: 5 },
      { kind: "turn_completed", data: { answer: "答复一" }, seq: 6 },
      { kind: "turn_started", data: { input: "第二轮" }, seq: 7 },
      { kind: "turn_status", data: { status: "running", phase: "model_call", message: "生成第二轮" }, seq: 8 },
      { kind: "assistant_delta", data: { message_id: "m2", delta: "答复二" }, seq: 9 },
      { kind: "assistant_message_completed", data: { message_id: "m2", content: "答复二", tool_calls: [] }, seq: 10 },
      { kind: "assistant_message", data: { content: "答复二", tool_calls: [] }, seq: 11 },
      { kind: "turn_completed", data: { answer: "答复二" }, seq: 12 },
    ]);

    expect(items.map((item) => item.kind)).toEqual(["user", "agent_run", "assistant", "user", "agent_run", "assistant"]);
    const runs = items.filter((item) => item.kind === "agent_run");
    expect(runs).toHaveLength(2);
    expect(runs[0]).toMatchObject({ trace: { id: "agent-run-1", assistantDraft: "答复一" } });
    expect(runs[1]).toMatchObject({ trace: { id: "agent-run-7", assistantDraft: "答复二" } });
  });

  it("keeps command output out of the folded thinking process", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "运行脚本" }, seq: 1 },
      { kind: "tool_dispatch", data: { id: "t1", name: "python_run", arguments: { path: "demo.py" } }, seq: 2 },
      { kind: "command_output", data: { text: "many lines" }, seq: 3 },
      { kind: "tool_result", data: { id: "t1", name: "python_run", ok: true, output: "done" }, seq: 4 },
      { kind: "turn_completed", data: { answer: "完成" }, seq: 5 },
    ]);
    const thinking = items.find((item) => item.kind === "thinking");
    expect(thinking).toBeTruthy();
    expect((thinking as Extract<(typeof items)[number], { kind: "thinking" }>).items).toHaveLength(1);
  });

  it("renders approval events as a compact chat item inside the thinking group", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "运行受保护命令" }, seq: 1 },
      {
        kind: "safety_ask",
        data: { tool_name: "bash", arguments: { command: "touch demo.py" }, reason: "writes files" },
        seq: 2,
      },
      {
        kind: "safety_approved",
        data: { tool_name: "bash", arguments: { command: "touch demo.py" }, reason: "writes files" },
        seq: 3,
      },
      { kind: "turn_completed", data: { answer: "完成" }, seq: 4 },
    ]);

    const thinking = items.find((item) => item.kind === "thinking") as Extract<(typeof items)[number], { kind: "thinking" }>;
    expect(thinking.items).toMatchObject([
      {
        kind: "approval",
        toolName: "bash",
        reason: "writes files",
        status: "approved",
      },
    ]);
  });

  it("enriches command tools with exit code, duration, runtime, and output preview", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "运行 Python" }, seq: 1 },
      { kind: "tool_dispatch", data: { id: "t1", name: "python_run", arguments: { mode: "file", path: "demo.py" } }, seq: 2 },
      { kind: "command_started", data: { kind: "python", command: "/usr/bin/python3 demo.py" }, seq: 3 },
      { kind: "command_finished", data: { kind: "python", command: "/usr/bin/python3 demo.py", exit_code: 0, duration_ms: 1250, output_preview: "OK\n" }, seq: 4 },
      {
        kind: "tool_result",
        data: {
          id: "t1",
          name: "python_run",
          ok: true,
          output: "OK\n[python] exit_code=0 duration_ms=1250 executable=/usr/bin/python3 source=test",
        },
        seq: 5,
      },
      { kind: "turn_completed", data: { answer: "完成" }, seq: 6 },
    ]);
    const thinking = items.find((item) => item.kind === "thinking");
    const tool = (thinking as Extract<(typeof items)[number], { kind: "thinking" }>).items[0];
    expect(tool).toMatchObject({
      kind: "tool",
      commandKind: "python",
      command: "/usr/bin/python3 demo.py",
      exitCode: 0,
      durationMs: 1250,
      runtime: "/usr/bin/python3 (test)",
      outputPreview: "OK",
    });
  });

  it("adds a change review card after the final assistant answer", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "写文件" }, seq: 1 },
      { kind: "preview", data: { kind: "create", path: "demo.py", diff: "--- /dev/null\n+++ b/demo.py\n+print('ok')\n", source: "write_file" }, seq: 2 },
      { kind: "checkpoint_saved", data: { id: "cp1", path: "demo.py" }, seq: 3 },
      { kind: "assistant_message", data: { content: "已写好" }, seq: 4 },
      { kind: "turn_completed", data: { answer: "已写好" }, seq: 5 },
    ]);

    expect(items.map((item) => item.kind)).toEqual(["user", "assistant", "change_review"]);
    expect(items[2]).toMatchObject({
      kind: "change_review",
      status: "pending",
      additions: 1,
      deletions: 0,
      changes: [{ path: "demo.py", checkpointId: "cp1", diff: "--- /dev/null\n+++ b/demo.py\n+print('ok')\n", source: "write_file" }],
    });
  });

  it("updates the change review status from review events", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "写文件" }, seq: 1 },
      { kind: "preview", data: { kind: "create", path: "demo.py", diff: "--- /dev/null\n+++ b/demo.py\n+print('ok')\n" }, seq: 2 },
      { kind: "turn_completed", data: { answer: "完成" }, seq: 3 },
      { kind: "change_review_reverted", data: {}, seq: 4 },
    ]);

    expect(items.find((item) => item.kind === "change_review")).toMatchObject({ status: "reverted" });
  });

  it("marks single file change review entries as reverted", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "写文件" }, seq: 1 },
      { kind: "preview", data: { kind: "create", path: "demo.py", diff: "--- /dev/null\n+++ b/demo.py\n+print('ok')\n" }, seq: 2 },
      { kind: "checkpoint_saved", data: { id: "cp1", path: "demo.py" }, seq: 3 },
      { kind: "turn_completed", data: { answer: "完成" }, seq: 4 },
      { kind: "change_review_file_reverted", data: { path: "demo.py", checkpoint_id: "cp1" }, seq: 5 },
    ]);

    expect(items.find((item) => item.kind === "change_review")).toMatchObject({
      changes: [{ path: "demo.py", status: "reverted" }],
    });
  });

  it("adds command-generated workspace changes to the change review card", () => {
    const items = itemsFromMessagesAndEvents([], [
      { kind: "turn_started", data: { input: "运行脚本" }, seq: 1 },
      {
        kind: "workspace_changes_detected",
        data: {
          source_kind: "python",
          changes: [
            {
              path: "generated.py",
              kind: "create",
              additions: 1,
              deletions: 0,
              diff: "--- /dev/null\n+++ b/generated.py\n+print('ok')\n",
              recoverable: false,
              source: "command",
              note: "由命令产生",
            },
          ],
        },
        seq: 2,
      },
      { kind: "turn_completed", data: { answer: "完成" }, seq: 3 },
    ]);

    expect(items.find((item) => item.kind === "change_review")).toMatchObject({
      kind: "change_review",
      changes: [{ path: "generated.py", source: "command", recoverable: false, note: "由命令产生" }],
    });
  });
});
