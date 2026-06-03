import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AgentRunBlock } from "./AgentRunBlock";
import type { RunTrace } from "../types";

describe("AgentRunBlock", () => {
  afterEach(() => cleanup());

  it("renders split trace panels and action metadata", () => {
    render(<AgentRunBlock trace={traceFixture()} />);

    expect(screen.getByText("Agent Run")).toBeInTheDocument();
    expect(screen.getByText("正在执行工具调用")).toBeInTheDocument();
    expect(screen.getByText("正在检查配置入口")).toBeInTheDocument();
    expect(screen.getByText("流式回答草稿")).toBeInTheDocument();
    expect(screen.getByText("读取上下文")).toBeInTheDocument();
    expect(screen.getByText("已读取 README")).toBeInTheDocument();
    expect(screen.getByText("README.md")).toBeInTheDocument();
    expect(screen.getByText("运行测试")).toBeInTheDocument();
    expect(screen.getByText("npm test")).toBeInTheDocument();
    expect(screen.getByText("exit 0")).toBeInTheDocument();
    expect(screen.getByText("42ms")).toBeInTheDocument();
  });

  it("keeps completed steps collapsed until opened", () => {
    const trace = traceFixture();
    render(
      <AgentRunBlock
        trace={{
          ...trace,
          status: "completed",
          assistantDraft: "最终回答",
          steps: trace.steps.map((step) => ({ ...step, status: "completed" })),
        }}
      />,
    );

    expect(screen.getByText("读取上下文")).toBeInTheDocument();
    expect(screen.queryByText("README.md")).not.toBeInTheDocument();
    expect(screen.queryByText("最终回答")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("读取上下文"));
    expect(screen.getByText("README.md")).toBeInTheDocument();
  });
});

function traceFixture(): RunTrace {
  return {
    id: "run-1",
    status: "running",
    phase: "executing_tools",
    message: "正在执行工具调用",
    thoughtSummary: "正在检查配置入口",
    assistantDraft: "流式回答草稿",
    steps: [
      {
        id: "step-1",
        title: "读取上下文",
        status: "running",
        summary: "已读取 README",
        actions: [
          {
            id: "a1",
            stepId: "step-1",
            kind: "file_read",
            title: "读取 README.md",
            status: "completed",
            path: "README.md",
            summary: "读取完成",
          },
          {
            id: "a2",
            stepId: "step-1",
            kind: "verification",
            title: "运行测试",
            status: "completed",
            command: "npm test",
            exitCode: 0,
            durationMs: 42,
          },
        ],
      },
    ],
  };
}
