import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatWorkspace } from "./ChatWorkspace";

describe("ChatWorkspace", () => {
  afterEach(() => {
    cleanup();
    window.localStorage?.removeItem("mcode.speech.localOnly.v1");
  });

  it("renders user, assistant, and tool cards", () => {
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "completed" }}
        running={false}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={[
          { kind: "user", id: "u1", text: "hello" },
          { kind: "assistant", id: "a1", text: "hi" },
          {
            kind: "tool",
            id: "t1",
            name: "python_run",
            args: { mode: "file", path: "demo.py" },
            status: "done",
            output: "ok\n[python] exit_code=0 duration_ms=42 executable=/usr/bin/python3 source=test",
            commandKind: "python",
            command: "/usr/bin/python3 demo.py",
            exitCode: 0,
            durationMs: 42,
            runtime: "/usr/bin/python3 (test)",
            outputPreview: "ok",
          },
        ]}
      />,
    );
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText("hi")).toBeInTheDocument();
    expect(screen.getByTestId("tool-card")).toBeInTheDocument();
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("exit 0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开添加菜单" })).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tool-card").querySelector("button") as HTMLElement);
    expect(screen.getByText("参数")).toBeInTheDocument();
    expect(screen.getByText("命令")).toBeInTheDocument();
    expect(screen.getByText("输出摘要")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("renders multiple agent run blocks in one transcript", () => {
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "completed" }}
        running={false}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={[
          { kind: "user", id: "u1", text: "第一轮" },
          {
            kind: "agent_run",
            id: "run-1",
            trace: {
              id: "run-1",
              status: "completed",
              phase: "finalizing",
              message: "第一轮完成",
              thoughtSummary: "检查第一轮",
              assistantDraft: "答复一",
              steps: [{ id: "s1", title: "第一步", status: "completed", actions: [] }],
            },
          },
          { kind: "assistant", id: "a1", text: "答复一" },
          { kind: "user", id: "u2", text: "第二轮" },
          {
            kind: "agent_run",
            id: "run-2",
            trace: {
              id: "run-2",
              status: "completed",
              phase: "finalizing",
              message: "第二轮完成",
              thoughtSummary: "检查第二轮",
              assistantDraft: "答复二",
              steps: [{ id: "s2", title: "第二步", status: "completed", actions: [] }],
            },
          },
          { kind: "assistant", id: "a2", text: "答复二" },
        ]}
      />,
    );

    expect(screen.getAllByText("Agent Run")).toHaveLength(2);
    expect(screen.getByText("第一轮完成")).toBeInTheDocument();
    expect(screen.getByText("第二轮完成")).toBeInTheDocument();
    expect(screen.getByText("检查第一轮")).toBeInTheDocument();
    expect(screen.getByText("检查第二轮")).toBeInTheDocument();
  });

  it("does not force autoscroll when the user has left the bottom", () => {
    const firstItems = [{ kind: "assistant" as const, id: "a1", text: "one" }];
    const nextItems = [...firstItems, { kind: "assistant" as const, id: "a2", text: "two" }];
    const { container, rerender } = render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "running" }}
        running={true}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={firstItems}
      />,
    );
    const transcript = container.querySelector(".transcript") as HTMLDivElement;
    const scrollTo = vi.fn();
    Object.defineProperty(transcript, "scrollTo", { configurable: true, value: scrollTo });
    Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(transcript, "clientHeight", { configurable: true, value: 400 });
    transcript.scrollTop = 100;
    fireEvent.scroll(transcript);

    scrollTo.mockClear();
    rerender(
      <ChatWorkspace
        title="Session"
        summary={{ status: "running" }}
        running={true}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={nextItems}
      />,
    );

    expect(screen.getByText("two")).toBeInTheDocument();
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("follows new transcript items while the user is near the bottom", () => {
    const firstItems = [{ kind: "assistant" as const, id: "a1", text: "one" }];
    const nextItems = [...firstItems, { kind: "assistant" as const, id: "a2", text: "two" }];
    const { container, rerender } = render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "running" }}
        running={true}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={firstItems}
      />,
    );
    const transcript = container.querySelector(".transcript") as HTMLDivElement;
    const scrollTo = vi.fn();
    Object.defineProperty(transcript, "scrollTo", { configurable: true, value: scrollTo });
    Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(transcript, "clientHeight", { configurable: true, value: 400 });
    transcript.scrollTop = 560;
    fireEvent.scroll(transcript);

    scrollTo.mockClear();
    rerender(
      <ChatWorkspace
        title="Session"
        summary={{ status: "running" }}
        running={true}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={nextItems}
      />,
    );

    expect(screen.getByText("two")).toBeInTheDocument();
    expect(scrollTo).toHaveBeenCalledWith({ top: 1000, behavior: "smooth" });
  });

  it("renders failed user message retry", () => {
    const onRetry = vi.fn();
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "failed" }}
        running={false}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onRetry={onRetry}
        items={[{ kind: "user", id: "p1", text: "hello again", status: "failed", error: "network", canRetry: true }]}
      />,
    );
    fireEvent.click(screen.getByText("重试"));
    expect(onRetry).toHaveBeenCalledWith("hello again");
  });

  it("renders change review actions", () => {
    const onConfirmChanges = vi.fn();
    const onUndoChanges = vi.fn();
    const onUndoChangeFile = vi.fn();
    const onOpenFile = vi.fn();
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "completed" }}
        running={false}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onConfirmChanges={onConfirmChanges}
        onUndoChanges={onUndoChanges}
        onUndoChangeFile={onUndoChangeFile}
        onOpenFile={onOpenFile}
        items={[
          {
            kind: "change_review",
            id: "changes-1",
            status: "pending",
            additions: 2,
            deletions: 1,
            changes: [
              {
                path: "demo.py",
                kind: "modify",
                additions: 2,
                deletions: 1,
                checkpointId: "cp1",
                diff: "--- a/demo.py\n+++ b/demo.py\n-print('old')\n+print('new')\n",
              },
              {
                path: "generated.png",
                kind: "create",
                additions: 0,
                deletions: 0,
                recoverable: false,
                source: "command",
              },
            ],
          },
        ]}
      />,
    );

    expect(screen.getAllByText("已编辑 2 个文件").length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByText("demo.py"));
    expect(onOpenFile).toHaveBeenCalledWith("demo.py");
    expect(screen.getByText("Diff preview")).toBeInTheDocument();
    expect(screen.getByText(/print\('new'\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("撤销此文件"));
    fireEvent.click(screen.getByText("撤销"));
    fireEvent.click(screen.getByText("确认"));
    expect(onUndoChangeFile).toHaveBeenCalledWith("demo.py");
    expect(screen.getByText("不可自动撤销")).toBeInTheDocument();
    expect(screen.getByText("命令生成")).toBeInTheDocument();
    expect(onUndoChanges).toHaveBeenCalledOnce();
    expect(onConfirmChanges).toHaveBeenCalledOnce();
  });

  it("shows change artifacts and opens file artifacts", () => {
    const onOpenFile = vi.fn();
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "completed" }}
        running={false}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onOpenFile={onOpenFile}
        items={[
          {
            kind: "change_review",
            id: "changes-1",
            status: "pending",
            additions: 1,
            deletions: 0,
            changes: [{ path: "src/generated-report.md", kind: "create", additions: 1, deletions: 0 }],
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByText("Artifacts"));
    fireEvent.click(screen.getAllByText("src/generated-report.md")[0]);
    expect(onOpenFile).toHaveBeenCalledWith("src/generated-report.md");
  });

  it("collapses completed thinking groups and expands them on click", () => {
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "completed" }}
        running={false}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={[
          { kind: "user", id: "u1", text: "读取 README" },
          {
            kind: "thinking",
            id: "think-1",
            status: "done",
            items: [
              {
                kind: "tool",
                id: "t1",
                name: "read_file",
                args: { path: "README.md" },
                summary: "读取 README.md",
                status: "done",
              },
            ],
          },
          { kind: "assistant", id: "a1", text: "完成" },
        ]}
      />,
    );

    expect(screen.getByText("思考过程")).toBeInTheDocument();
    expect(screen.queryByTestId("tool-card")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("思考过程"));
    expect(screen.getByTestId("tool-card")).toBeInTheDocument();
  });

  it("expands running thinking groups and renders inline approval status", () => {
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "waiting_approval" }}
        running={true}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={[
          {
            kind: "thinking",
            id: "think-approval",
            status: "running",
            items: [
              {
                kind: "approval",
                id: "approval-bash",
                toolName: "bash",
                reason: "writes files",
                args: { command: "touch demo.py" },
                status: "pending",
              },
            ],
          },
        ]}
      />,
    );

    expect(screen.getByText("思考与工具调用中")).toBeInTheDocument();
    expect(screen.getByText("等待审批")).toBeInTheDocument();
    expect(screen.getByText("writes files")).toBeInTheDocument();
    fireEvent.click(screen.getByText("参数摘要"));
    expect(screen.getByText(/touch demo.py/)).toBeInTheDocument();
  });

  it("renders approval decisions", () => {
    const onApprovalDecision = vi.fn();
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "waiting_approval" }}
        running={false}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onApprovalDecision={onApprovalDecision}
        approvals={[
          {
            id: "approval-1",
            session_id: "s1",
            tool_name: "bash",
            arguments: { command: "ls" },
            reason: "bash can change system state",
            status: "pending",
            created_at: 1,
            decided_at: 0,
            approved: false,
          },
        ]}
        items={[]}
      />,
    );
    expect(screen.getByText("执行 shell 命令：ls")).toBeInTheDocument();
    expect(screen.getByText("风险原因")).toBeInTheDocument();
    expect(screen.getByText("参数预览")).toBeInTheDocument();
    expect(screen.getByText("command=ls")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("允许")[0]);
    expect(onApprovalDecision).toHaveBeenCalledWith("approval-1", true);
  });

  it("changes permission mode from the composer menu", () => {
    const onPermissionModeChange = vi.fn();
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "idle" }}
        running={false}
        plan={false}
        permissionMode="auto_review"
        onPlanChange={vi.fn()}
        onPermissionModeChange={onPermissionModeChange}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={[]}
      />,
    );

    fireEvent.click(screen.getByText("自动审查"));
    fireEvent.click(screen.getByText("完全访问权限"));
    expect(onPermissionModeChange).toHaveBeenCalledWith("full_access");
  });

  it("opens the plus menu, toggles plan mode, and attaches files", () => {
    const onPlanChange = vi.fn();
    const inputClick = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => undefined);
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "idle" }}
        running={false}
        plan={false}
        permissionMode="auto_review"
        onPlanChange={onPlanChange}
        onPermissionModeChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={[]}
      />,
    );

    expect(screen.queryByText("能力")).not.toBeInTheDocument();
    expect(screen.queryByText("Local")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "打开添加菜单" }));
    fireEvent.click(screen.getByText("添加照片和文件"));
    expect(inputClick).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "打开添加菜单" }));
    fireEvent.click(screen.getByText("计划模式"));
    expect(onPlanChange).toHaveBeenCalledWith(true);
    inputClick.mockRestore();
  });

  it("shows the active plan indicator", () => {
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "idle" }}
        running={false}
        plan={true}
        permissionMode="auto_review"
        onPlanChange={vi.fn()}
        onPermissionModeChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        items={[]}
      />,
    );

    expect(screen.getByRole("button", { name: "计划模式已开启" })).toBeInTheDocument();
  });

  it("supports native speech start, stop, and transcript insertion without sending", async () => {
    window.localStorage?.removeItem("mcode.speech.localOnly.v1");
    const speechRequests: unknown[] = [];
    const onSend = vi.fn();
    const onSpeechRequest = (event: Event) => {
      speechRequests.push((event as CustomEvent).detail);
    };
    window.addEventListener("mcode:speech-request", onSpeechRequest);
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "idle" }}
        running={false}
        plan={false}
        permissionMode="auto_review"
        onPlanChange={vi.fn()}
        onPermissionModeChange={vi.fn()}
        onSend={onSend}
        onCancel={vi.fn()}
        items={[]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "语音输入" }));
    expect(speechRequests[speechRequests.length - 1]).toEqual({ action: "start", localOnly: false });
    window.dispatchEvent(new CustomEvent("mcode:speech-transcript", { detail: { text: "hello interim", final: false } }));
    expect(screen.queryByDisplayValue("hello interim")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "停止语音输入" }));
    expect(speechRequests[speechRequests.length - 1]).toEqual({ action: "stop" });
    window.dispatchEvent(new CustomEvent("mcode:speech-transcript", { detail: { text: "hello by voice", final: true } }));
    await waitFor(() => expect(screen.getByDisplayValue("hello by voice")).toBeInTheDocument());
    expect(onSend).not.toHaveBeenCalled();
    window.removeEventListener("mcode:speech-request", onSpeechRequest);
  });

  it("falls back to the last interim speech text when stop returns an empty final transcript", async () => {
    const onSend = vi.fn();
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "idle" }}
        running={false}
        plan={false}
        permissionMode="auto_review"
        onPlanChange={vi.fn()}
        onPermissionModeChange={vi.fn()}
        onSend={onSend}
        onCancel={vi.fn()}
        items={[]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "语音输入" }));
    window.dispatchEvent(new CustomEvent("mcode:speech-transcript", { detail: { text: "fallback voice", final: false } }));
    fireEvent.click(screen.getByRole("button", { name: "停止语音输入" }));
    window.dispatchEvent(new CustomEvent("mcode:speech-transcript", { detail: { text: "", final: true } }));
    await waitFor(() => expect(screen.getByDisplayValue("fallback voice")).toBeInTheDocument());
    expect(onSend).not.toHaveBeenCalled();
  });

  it("renders attachment chips and removes them", () => {
    const onRemoveAttachment = vi.fn();
    const onRetryAttachment = vi.fn();
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "idle" }}
        running={false}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onRemoveAttachment={onRemoveAttachment}
        onRetryAttachment={onRetryAttachment}
        attachments={[
          {
            id: "att_1",
            session_id: "s1",
            name: "notes.md",
            size: 10,
            mime_type: "text/markdown",
            preview: "hello",
            is_text: true,
            preview_available: true,
            created_at: 1,
          },
          {
            id: "att_2",
            session_id: "s1",
            name: "figure.png",
            size: 32,
            mime_type: "image/png",
            preview: "(binary attachment)",
            is_image: true,
            preview_available: true,
            data_url: "data:image/png;base64,iVBORw0KGgo=",
            created_at: 1,
          },
          {
            id: "local_failed",
            session_id: "s1",
            name: "large.bin",
            size: 6 * 1024 * 1024,
            mime_type: "application/octet-stream",
            preview: "",
            upload_status: "failed",
            error: "文件超过最大限制 5 MB",
            local_file: new File(["x"], "large.bin"),
            created_at: 1,
          },
        ]}
        items={[]}
      />,
    );

    expect(screen.getByText("notes.md")).toBeInTheDocument();
    fireEvent.click(screen.getByText("notes.md"));
    expect(screen.getByText("hello")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("关闭附件预览"));
    fireEvent.click(screen.getByText("figure.png"));
    expect(screen.getByAltText("figure.png")).toBeInTheDocument();
    expect(screen.getByText("有附件上传失败")).toBeInTheDocument();
    fireEvent.click(screen.getAllByTitle("移除附件")[0]);
    expect(onRemoveAttachment).toHaveBeenCalledWith("att_1");
  });

  it("summarizes running activity in the composer area", () => {
    render(
      <ChatWorkspace
        title="Session"
        summary={{ status: "running" }}
        running={true}
        plan={false}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        approvals={[
          {
            id: "approval-1",
            session_id: "s1",
            tool_name: "bash",
            arguments: { command: "ls" },
            reason: "bash ask",
            status: "approved",
            created_at: 1,
            decided_at: 2,
            approved: true,
          },
        ]}
        items={[
          {
            kind: "thinking",
            id: "think-1",
            status: "running",
            items: [
              {
                kind: "tool",
                id: "t1",
                name: "python_run",
                args: { mode: "file", path: "demo.py" },
                status: "running",
                commandKind: "python",
              },
            ],
          },
        ]}
      />,
    );

    expect(screen.getByText("已运行 1 条命令")).toBeInTheDocument();
    expect(screen.getByText("已批准 1 项请求")).toBeInTheDocument();
    expect(screen.getByText("正在处理")).toBeInTheDocument();
  });

  it("renders pending plan actions and refinement input", () => {
    const onApprovePlan = vi.fn();
    const onRefinePlan = vi.fn();
    const onCancelPlan = vi.fn();
    render(
      <ChatWorkspace
        title="Session"
        summary={{
          status: "awaiting_plan_decision",
          pending_plan: {
            status: "awaiting_approval",
            plan_text: "1. 检查代码\n2. 实现功能",
            revision: 2,
            todo_count: 2,
            todos: [
              { content: "检查代码", status: "in_progress", level: 0 },
              { content: "实现功能", status: "pending", level: 0 },
            ],
          },
        }}
        running={false}
        plan={true}
        onPlanChange={vi.fn()}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onApprovePlan={onApprovePlan}
        onRefinePlan={onRefinePlan}
        onCancelPlan={onCancelPlan}
        items={[{ kind: "assistant", id: "a1", text: "1. 检查代码\n2. 实现功能" }]}
      />,
    );

    expect(screen.getByTestId("plan-approval-card")).toBeInTheDocument();
    expect(screen.getByText("计划已生成 · 第 2 版")).toBeInTheDocument();
    expect(screen.getByText(/将创建 2 项 todo/)).toBeInTheDocument();
    expect(within(screen.getByLabelText("计划对应 todo")).getByText("检查代码")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("补充或修改计划，例如：先加测试，再改实现"), {
      target: { value: "先补测试" },
    });
    fireEvent.click(screen.getByText("更新计划"));
    fireEvent.click(screen.getByText("执行计划"));
    fireEvent.click(screen.getByText("取消"));
    expect(onRefinePlan).toHaveBeenCalledWith("先补测试");
    expect(onApprovePlan).toHaveBeenCalledOnce();
    expect(onCancelPlan).toHaveBeenCalledOnce();
  });
});
