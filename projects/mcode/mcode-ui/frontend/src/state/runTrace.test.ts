import { describe, expect, it } from "vitest";
import { buildRunTrace, hasTraceEvents } from "./runTrace";

describe("runTrace", () => {
  it("builds steps, actions, thought summary, and assistant draft from trace events", () => {
    const events = [
      { kind: "turn_started", data: { input: "fix tests" }, seq: 1 },
      { kind: "turn_status", data: { status: "running", phase: "executing_tools", message: "正在执行工具调用" }, seq: 2 },
      { kind: "thought_summary_delta", data: { text: "正在检查测试失败" }, seq: 3 },
      { kind: "step_started", data: { step_id: "step-1", title: "验证失败" }, seq: 4 },
      { kind: "action_started", data: { action_id: "a1", step_id: "step-1", kind: "verification", title: "运行 npm test" }, seq: 5 },
      { kind: "verification_completed", data: { action_id: "a1", step_id: "step-1", command: "npm test", exit_code: 0, duration_ms: 42 }, seq: 6 },
      { kind: "action_completed", data: { action_id: "a1", summary: "tests passed" }, seq: 7 },
      { kind: "step_completed", data: { step_id: "step-1", summary: "验证通过" }, seq: 8 },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "已完成" }, seq: 9 },
      { kind: "turn_completed", data: { answer: "已完成" }, seq: 10 },
    ];

    expect(hasTraceEvents(events)).toBe(true);
    expect(buildRunTrace(events)).toMatchObject({
      status: "completed",
      phase: "executing_tools",
      thoughtSummary: "正在检查测试失败",
      assistantDraft: "已完成",
      steps: [
        {
          id: "step-1",
          title: "验证失败",
          status: "completed",
          summary: "验证通过",
          actions: [{ id: "a1", kind: "verification", status: "completed", command: "npm test", exitCode: 0 }],
        },
      ],
    });
  });

  it("shows streaming tool-call construction as sanitized tool progress", () => {
    const events = [
      { kind: "turn_started", data: { input: "inspect" }, seq: 1 },
      { kind: "step_started", data: { step_id: "step-model", title: "生成下一步" }, seq: 2 },
      {
        kind: "tool_call_started",
        data: { message_id: "m1", tool_call_index: 0, tool_name: "read_file", step_id: "step-model" },
        seq: 3,
      },
      {
        kind: "tool_call_delta",
        data: { message_id: "m1", tool_call_index: 0, tool_name: "read_file", step_id: "step-model", received_chars: 24 },
        seq: 4,
      },
      {
        kind: "tool_call_completed",
        data: { message_id: "m1", tool_call_index: 0, tool_name: "read_file", step_id: "step-model" },
        seq: 5,
      },
    ];

    expect(hasTraceEvents(events)).toBe(true);
    expect(buildRunTrace(events).steps[0].actions[0]).toMatchObject({
      id: "tool-call-m1-0",
      kind: "tool",
      title: "准备 read_file",
      status: "completed",
      summary: "工具调用已准备完成",
    });
  });

  it("does not duplicate streamed text when replayed events are merged into a trace", () => {
    const events = [
      { kind: "turn_started", data: { input: "stream" }, seq: 1 },
      { kind: "thought_summary_delta", data: { text: "正在整理上下文" }, seq: 2 },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "你好" }, seq: 3 },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "，世界" }, seq: 4 },
      { kind: "thought_summary_delta", data: { text: "正在整理上下文" }, seq: 2 },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "你好" }, seq: 3 },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "，世界" }, seq: 4 },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "。" } },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "。" } },
    ];

    expect(buildRunTrace(events)).toMatchObject({
      thoughtSummary: "正在整理上下文",
      assistantDraft: "你好，世界。",
    });
  });

  it("keeps assistant streaming drafts separated by message id", () => {
    const events = [
      { kind: "turn_started", data: { input: "recover" }, seq: 1 },
      { kind: "assistant_message_started", data: { message_id: "m1" }, seq: 2 },
      { kind: "assistant_delta", data: { message_id: "m1", delta: "旧草稿" }, seq: 3 },
      { kind: "assistant_message_failed", data: { message_id: "m1", error: "stream failed" }, seq: 4 },
      { kind: "assistant_message_started", data: { message_id: "m2" }, seq: 5 },
      { kind: "assistant_delta", data: { message_id: "m2", delta: "恢复" }, seq: 6 },
      { kind: "assistant_delta", data: { message_id: "m2", delta: "回答" }, seq: 7 },
    ];

    expect(buildRunTrace(events).assistantDraft).toBe("恢复回答");
  });

  it("marks open steps and actions as cancelled when a running turn is paused by cancellation", () => {
    const events = [
      { kind: "turn_started", data: { input: "cancel me" }, seq: 1 },
      { kind: "turn_status", data: { status: "running", phase: "executing_tools", message: "正在执行工具调用" }, seq: 2 },
      { kind: "step_started", data: { step_id: "step-tools", title: "执行工具调用" }, seq: 3 },
      {
        kind: "action_started",
        data: { action_id: "a1", step_id: "step-tools", kind: "command", title: "运行长命令" },
        seq: 4,
      },
      { kind: "turn_cancel_requested", data: { running: true }, seq: 5 },
      { kind: "turn_paused", data: { message: "cancelled before model call", cancelled: true }, seq: 6 },
    ];

    expect(buildRunTrace(events)).toMatchObject({
      status: "cancelled",
      message: "cancelled before model call",
      steps: [
        {
          id: "step-tools",
          status: "cancelled",
          summary: "已取消",
          actions: [{ id: "a1", status: "cancelled", summary: "已取消" }],
        },
      ],
    });
  });
});
