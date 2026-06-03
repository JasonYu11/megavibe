import { Bot, Check, ChevronDown, ChevronRight, Copy, FileDiff, Plus, RotateCcw, ShieldAlert, User } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ApprovalInfo, AttachmentInfo, PermissionMode, Summary, UiItem } from "../types";
import { AgentRunBlock } from "./AgentRunBlock";
import { ApprovalPanel } from "./ApprovalPanel";
import { ArtifactsPopover } from "./ArtifactsPopover";
import { Composer } from "./Composer";
import { FinalAnswerRenderer } from "./FinalAnswerRenderer";
import { PlanApprovalCard } from "./PlanApprovalCard";
import { SkillPicker } from "./SkillPicker";
import { ThoughtChainBlock } from "./ThoughtChainBlock";
import { ThoughtStepItem } from "./ThoughtStepItem";
import { ToolCard } from "./ToolCard";

type ToolItem = Extract<UiItem, { kind: "tool" }>;

export function ChatWorkspace({
  title,
  projectRoot,
  sessionId,
  appStatus,
  items,
  summary,
  running,
  plan,
  permissionMode = "auto_review",
  model = "deepseek-v4-flash",
  thinkingMode = false,
  attachments = [],
  onPlanChange,
  onPermissionModeChange = () => {},
  onModelChange,
  onAttachFiles,
  onRemoveAttachment,
  onRetryAttachment,
  onSend,
  onCancel,
  onRetry,
  onApprovePlan,
  onRefinePlan,
  onCancelPlan,
  onConfirmChanges,
  onUndoChanges,
  onUndoChangeFile,
  onOpenFile,
  approvals = [],
  onApprovalDecision,
  skills = [],
  onSkillSelect,
}: {
  title: string;
  projectRoot?: string;
  sessionId?: string;
  appStatus?: string;
  items: UiItem[];
  summary?: Summary | null;
  running: boolean;
  plan: boolean;
  permissionMode?: PermissionMode;
  model?: string;
  thinkingMode?: boolean;
  attachments?: AttachmentInfo[];
  onPlanChange: (value: boolean) => void;
  onPermissionModeChange?: (value: PermissionMode) => void;
  onModelChange?: (model: string, thinkingMode: boolean) => void;
  onAttachFiles?: (files: FileList) => void;
  onRemoveAttachment?: (id: string) => void;
  onRetryAttachment?: (id: string) => void;
  onSend: (text: string) => void;
  onCancel: () => void;
  onRetry?: (text: string) => void;
  onApprovePlan?: () => void;
  onRefinePlan?: (feedback: string) => void;
  onCancelPlan?: () => void;
  onConfirmChanges?: () => void;
  onUndoChanges?: () => void;
  onUndoChangeFile?: (path: string) => void;
  onOpenFile?: (path: string) => void;
  approvals?: ApprovalInfo[];
  onApprovalDecision?: (approvalId: string, approved: boolean) => void;
  skills?: Array<{ name: string; description: string; run_as: string }>;
  onSkillSelect?: (skillName: string) => void;
}) {
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const shouldFollowScrollRef = useRef(true);
  const [openThinking, setOpenThinking] = useState<Record<string, boolean>>({});
  const [openDiffs, setOpenDiffs] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState(false);
  const [skillOpen, setSkillOpen] = useState(false);
  const pendingApprovals = approvals.filter((item) => item.status === "pending");
  const firstApproval = pendingApprovals[0];
  const childTools = useMemo(() => collectChildTools(items), [items]);
  const activity = useMemo(() => summarizeActivity(items, approvals, running), [items, approvals, running]);

  const copyConversation = useCallback(() => {
    const lines: string[] = [];
    for (const item of items) {
      if (item.kind === "user") lines.push(`👤 ${item.text}`);
      else if (item.kind === "assistant") lines.push(`🤖 ${item.text}`);
      else if (item.kind === "thought_chain") {
        for (const step of item.chain.steps) {
          const prefix = step.kind === "thought" ? "💬" : "🔧";
          lines.push(`${prefix} ${step.title}`);
        }
      }
    }
    void navigator.clipboard.writeText(lines.join("\n\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [items]);
  const pendingPlan =
    summary?.pending_plan && summary.pending_plan.status === "awaiting_approval" ? summary.pending_plan : null;

  useEffect(() => {
    const node = transcriptRef.current;
    if (!node) return;
    if (!shouldFollowScrollRef.current) return;
    if (typeof node.scrollTo === "function") {
      node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
    } else {
      node.scrollTop = node.scrollHeight;
    }
  }, [items.length, running, summary?.status, approvals.length]);

  function handleTranscriptScroll() {
    const node = transcriptRef.current;
    if (!node) return;
    shouldFollowScrollRef.current = isNearBottom(node);
  }

  return (
    <main className="workspace" data-testid="chat-workspace">
      <header className="workspace__top">
        <div className="workspace__topInner">
          <div className="workspace__titleBlock">
            <h1>{title}</h1>
            <p>
              {appStatus || summary?.status || "ready"}
              {sessionId ? ` · ${sessionId}` : ""}
            </p>
            {projectRoot && <p className="workspace__root" title={projectRoot}>{projectRoot}</p>}
          </div>
          {firstApproval ? (
            <div className="workspace__topActions">
              <ArtifactsPopover items={items} onOpenFile={onOpenFile} />
              <div className="approvalStrip">
                <div>
                  <strong>{firstApproval.tool_name}</strong>
                  <span>等待审批</span>
                </div>
                <button className="secondaryButton" onClick={() => onApprovalDecision?.(firstApproval.id, false)}>
                  拒绝
                </button>
                <button className="primaryButton" onClick={() => onApprovalDecision?.(firstApproval.id, true)}>
                  允许
                </button>
              </div>
            </div>
          ) : (
            <div className="workspace__topActions">
              <ArtifactsPopover items={items} onOpenFile={onOpenFile} />
              {summary?.last_error && <div className="statusBadge statusBadge--error">{summary.last_error}</div>}
            </div>
          )}
        </div>
      </header>
      <div className="transcript" ref={transcriptRef} onScroll={handleTranscriptScroll}>
        {items.length === 0 && (
          <div className="welcome">
            <img className="welcome__logo" src="/mcode-logo.jpg" alt="" />
            <h2>Mcode</h2>
            <p>选择一个对话，或者新建对话开始测试 agent。</p>
          </div>
        )}
        {items.map((item, index) => renderItem(item, index, childTools))}
        {pendingPlan && (
          <PlanApprovalCard
            plan={pendingPlan}
            busy={running}
            onApprove={() => onApprovePlan?.()}
            onRefine={(feedback) => onRefinePlan?.(feedback)}
            onCancel={() => onCancelPlan?.()}
          />
        )}
      </div>
      <footer className="workspace__composer">
        {activity.length > 0 && (
          <div className="activityRow">
            <div className="activitySummary" aria-label="Agent activity summary">
              {activity.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
            <button className="copyButton" onClick={copyConversation} title="复制完整对话">
              <Copy size={14} />
              <span>{copied ? "已复制" : "复制对话"}</span>
            </button>
            {skills.length > 0 && (
              <div style={{ position: "relative" }}>
                <button className="copyButton" onClick={() => setSkillOpen((v) => !v)} title="调用 Skill">
                  <Plus size={14} />
                  <span>Skill</span>
                </button>
                {skillOpen && (
                  <SkillPicker
                    skills={skills}
                    onSelect={(name) => {
                      setSkillOpen(false);
                      onSkillSelect?.(name);
                    }}
                    onClose={() => setSkillOpen(false)}
                  />
                )}
              </div>
            )}
          </div>
        )}
        <ApprovalPanel approvals={approvals} onDecide={(id, approved) => onApprovalDecision?.(id, approved)} />
        <Composer
          running={running}
          busy={appStatus === "creating_session" || appStatus === "sending" || appStatus === "cancelling"}
          plan={plan}
          permissionMode={permissionMode}
          model={model}
          thinkingMode={thinkingMode}
          attachments={attachments}
          onPlanChange={onPlanChange}
          onPermissionModeChange={onPermissionModeChange}
          onModelChange={onModelChange}
          onAttachFiles={onAttachFiles}
          onRemoveAttachment={onRemoveAttachment}
          onRetryAttachment={onRetryAttachment}
          onSend={onSend}
          onCancel={onCancel}
        />
      </footer>
    </main>
  );

  function renderItem(item: UiItem, index: number, itemChildTools: Map<string, ToolItem[]>): JSX.Element | null {
    if (item.kind === "user") {
      return (
        <div className="message message--user" key={`${item.id}-${index}`}>
          <div>
            {item.text}
            {item.status === "pending" && <span className="messageStatus">发送中</span>}
            {item.status === "failed" && (
              <div className="messageError">
                {item.error || "发送失败"}
                {item.canRetry && <button onClick={() => onRetry?.(item.text)}>重试</button>}
              </div>
            )}
          </div>
          <User size={16} />
        </div>
      );
    }
    if (item.kind === "assistant") {
      return (
        <div className="message message--assistant" key={`${item.id}-${index}`}>
          <img src="/mcode-logo.jpg" alt="Mcode" className="message__avatar" />
          <FinalAnswerRenderer text={item.text} onOpenFile={onOpenFile} />
        </div>
      );
    }
    if (item.kind === "thinking") {
      const isOpen = openThinking[item.id] ?? (item.status === "running");
      const nestedChildTools = collectChildTools(item.items);
      const title = item.title || (item.status === "running" ? "思考与工具调用中" : "思考过程");
      return (
        <div className={`thinkingGroup thinkingGroup--${item.status}`} key={`${item.id}-${index}`}>
          <button
            className="thinkingGroup__head"
            onClick={() => setOpenThinking((current) => ({ ...current, [item.id]: !isOpen }))}
          >
            {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            <span>{title}</span>
            <span>{item.items.length} 步</span>
            <span>{item.status}</span>
          </button>
          {isOpen && (
            <div className="thinkingGroup__body">
              {item.items.map((child, childIndex) => renderItem(child, childIndex, nestedChildTools))}
            </div>
          )}
        </div>
      );
    }
    if (item.kind === "agent_run") {
      return <AgentRunBlock trace={item.trace} key={`${item.id}-${index}`} />;
    }
    if (item.kind === "thought_chain") {
      return <ThoughtChainBlock chain={item.chain} key={`${item.id}-${index}`} />;
    }
    if (item.kind === "change_review") {
      const fileCount = new Set(item.changes.map((change) => change.path)).size;
      const disabled = item.status !== "pending";
      const canUndo = item.changes.some((change) => change.checkpointId);
      return (
        <div className={`changeReview changeReview--${item.status}`} key={`${item.id}-${index}`}>
          <div className="changeReview__icon">
            <FileDiff size={19} />
          </div>
          <div className="changeReview__main">
            <div className="changeReview__top">
              <strong>已编辑 {fileCount} 个文件</strong>
              <span className="changeReview__stats">
                <span>+{item.additions}</span>
                <span>-{item.deletions}</span>
              </span>
            </div>
            <div className="changeReview__files">
              {item.changes.slice(0, 4).map((change) => (
                <div className="changeReview__fileWrap" key={`${change.path}-${change.checkpointId || change.kind}`}>
                  <button
                    className="changeReview__file"
                    onClick={() => {
                      onOpenFile?.(change.path);
                      if (change.diff) {
                        setOpenDiffs((current) => ({ ...current, [`${item.id}:${change.path}`]: !current[`${item.id}:${change.path}`] }));
                      }
                    }}
                    disabled={!change.path}
                  >
                    <span>
                      {change.path}
                      {change.source && change.source !== "tool" && <em>{change.source}</em>}
                    </span>
                    <span>
                      +{change.additions} -{change.deletions}
                    </span>
                  </button>
                  {riskLabels(change).length > 0 && (
                    <div className="changeReview__risks">
                      {riskLabels(change).map((label) => (
                        <span key={label}>{label}</span>
                      ))}
                    </div>
                  )}
                  {change.note && <div className="changeReview__note">{change.note}</div>}
                  {item.status === "pending" && change.checkpointId && (
                    <button
                      className="changeReview__fileUndo"
                      onClick={() => onUndoChangeFile?.(change.path)}
                      disabled={change.status === "reverted"}
                      title={change.status === "reverted" ? "该文件已撤销" : "只撤销这个文件"}
                    >
                      <RotateCcw size={13} />
                      {change.status === "reverted" ? "已撤销此文件" : "撤销此文件"}
                    </button>
                  )}
                  {change.diff && openDiffs[`${item.id}:${change.path}`] && (
                    <div className="changeReview__diff">
                      <div className="changeReview__diffTop">
                        <span>Diff preview</span>
                        <button onClick={() => void navigator.clipboard?.writeText(change.diff || "")}>复制 diff</button>
                      </div>
                      <pre>{change.diff}</pre>
                    </div>
                  )}
                </div>
              ))}
              {item.changes.length > 4 && <div className="changeReview__more">再显示 {item.changes.length - 4} 个文件</div>}
            </div>
          </div>
          <div className="changeReview__actions">
            {item.status === "confirmed" && <span className="changeReview__state">已确认</span>}
            {item.status === "reverted" && <span className="changeReview__state">已撤销</span>}
            {item.status === "pending" && (
              <>
                <button onClick={() => onUndoChanges?.()} disabled={disabled || !canUndo} title={canUndo ? "撤销本轮可恢复改动" : "没有可恢复 checkpoint"}>
                  <RotateCcw size={15} />
                  撤销
                </button>
                <button onClick={() => onConfirmChanges?.()} disabled={disabled}>
                  <Check size={15} />
                  确认
                </button>
              </>
            )}
          </div>
        </div>
      );
    }
    if (item.kind === "tool") {
      if (item.parentId) return null;
      return (
        <ToolCard item={item} key={`${item.id}-${index}`}>
          {itemChildTools.get(item.id)?.map((child) => <ToolCard item={child} key={child.id} />)}
        </ToolCard>
      );
    }
    if (item.kind === "approval") {
      return (
        <div className={`inlineApproval inlineApproval--${item.status}`} key={`${item.id}-${index}`}>
          <div className="inlineApproval__icon">
            <ShieldAlert size={16} />
          </div>
          <div className="inlineApproval__main">
            <div className="inlineApproval__top">
              <strong>{item.toolName}</strong>
              <span>{approvalStatusText(item.status)}</span>
            </div>
            <div className="inlineApproval__reason">{item.reason}</div>
            <details>
              <summary>参数摘要</summary>
              <pre>{JSON.stringify(item.args, null, 2)}</pre>
            </details>
          </div>
        </div>
      );
    }
    if (item.kind === "todo") {
      return (
        <div className="todoCard" key={`${item.id}-${index}`}>
          <strong>{item.progressText || "Todo updated"}</strong>
          <span>{item.todos.length} items</span>
        </div>
      );
    }
    if (item.kind === "subagent") {
      return (
        <div className="subagentInline" key={`${item.id}-${index}`}>
          subagent {item.id}: {item.status}
        </div>
      );
    }
    return (
      <div className="notice" key={`${item.id}-${index}`}>
        {item.text}
      </div>
    );
  }
}

function isNearBottom(node: HTMLElement): boolean {
  return node.scrollHeight - node.scrollTop - node.clientHeight <= 80;
}

function collectChildTools(items: UiItem[]): Map<string, ToolItem[]> {
  const map = new Map<string, ToolItem[]>();
  for (const item of items) {
    if (item.kind === "tool" && item.parentId) {
      const list = map.get(item.parentId) ?? [];
      list.push(item);
      map.set(item.parentId, list);
    }
  }
  return map;
}

function summarizeActivity(items: UiItem[], approvals: ApprovalInfo[], running: boolean): string[] {
  const tools = flattenTools(items);
  const commandCount = tools.filter((tool) => tool.commandKind || tool.name === "bash" || tool.name === "python_run").length;
  const editedFiles = new Set<string>();
  for (const item of items) {
    if (item.kind === "change_review") {
      for (const change of item.changes) editedFiles.add(change.path);
    }
  }
  const approvedCount = approvals.filter((approval) => approval.status === "approved" || approval.approved).length;
  const pendingCount = approvals.filter((approval) => approval.status === "pending").length;
  const parts: string[] = [];
  if (editedFiles.size) parts.push(`已编辑 ${editedFiles.size} 个文件`);
  if (commandCount) parts.push(`已运行 ${commandCount} 条命令`);
  if (approvedCount) parts.push(`已批准 ${approvedCount} 项请求`);
  if (pendingCount) parts.push(`等待 ${pendingCount} 项审批`);
  if (running) parts.push("正在处理");
  return parts.slice(0, 4);
}

function flattenTools(items: UiItem[]): ToolItem[] {
  const out: ToolItem[] = [];
  for (const item of items) {
    if (item.kind === "tool") out.push(item);
    if (item.kind === "thinking") out.push(...flattenTools(item.items));
    if (item.kind === "thought_chain") {
      for (const step of item.chain.steps) {
        if (step.kind === "tool_call") {
          out.push({
            kind: "tool",
            id: step.id,
            name: step.toolName || "tool",
            args: step.toolArgs || {},
            status: step.status === "running" ? "running" : step.status === "failed" ? "error" : "done",
            summary: step.summary,
            detail: step.detail,
            error: step.error,
          } as ToolItem);
        }
      }
    }
  }
  return out;
}

function riskLabels(change: { path: string; kind: string; recoverable?: boolean; source?: string }): string[] {
  const labels: string[] = [];
  if (change.kind === "delete") labels.push("删除文件");
  if (change.recoverable === false) labels.push("不可自动撤销");
  if (change.source === "command") labels.push("命令生成");
  if (change.path.startsWith("/") || change.path.startsWith("..")) labels.push("workspace 外路径");
  return labels;
}

function approvalStatusText(status: "pending" | "approved" | "denied"): string {
  if (status === "approved") return "已批准";
  if (status === "denied") return "已拒绝";
  return "等待审批";
}
