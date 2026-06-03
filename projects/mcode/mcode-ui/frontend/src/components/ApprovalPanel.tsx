import { ShieldAlert } from "lucide-react";
import type { ApprovalInfo } from "../types";

export function ApprovalPanel({
  approvals,
  onDecide,
}: {
  approvals: ApprovalInfo[];
  onDecide: (approvalId: string, approved: boolean) => void;
}) {
  const pending = approvals.filter((item) => item.status === "pending");
  if (!pending.length) return null;
  return (
    <div className="approvalPanel">
      {pending.map((item) => (
        <section className="approvalCard" key={item.id}>
          <div className="approvalCard__title">
            <ShieldAlert size={16} />
            <strong>{item.tool_name}</strong>
            <span>需要审批</span>
          </div>
          <div className="approvalCard__summary">{approvalSummary(item)}</div>
          <dl className="approvalCard__meta">
            <div>
              <dt>风险原因</dt>
              <dd>{item.reason}</dd>
            </div>
            <div>
              <dt>参数预览</dt>
              <dd>{argumentPreview(item.arguments)}</dd>
            </div>
          </dl>
          <details className="approvalCard__details">
            <summary>查看完整参数 JSON</summary>
            <pre>{JSON.stringify(item.arguments, null, 2)}</pre>
          </details>
          <div className="approvalCard__actions">
            <button className="secondaryButton" onClick={() => onDecide(item.id, false)}>
              拒绝
            </button>
            <button className="primaryButton" onClick={() => onDecide(item.id, true)}>
              允许
            </button>
          </div>
        </section>
      ))}
    </div>
  );
}

function approvalSummary(item: ApprovalInfo): string {
  const args = toRecord(item.arguments);
  if (item.tool_name === "bash") return `执行 shell 命令：${stringValue(args.command) || "(empty command)"}`;
  if (item.tool_name === "python_run") {
    const target = stringValue(args.path) || stringValue(args.module) || (stringValue(args.code) ? "inline code" : "");
    return `运行 Python：${stringValue(args.mode) || "unknown"}${target ? ` · ${target}` : ""}`;
  }
  if (item.tool_name === "write_file" || item.tool_name === "edit_file") {
    return `${item.tool_name === "write_file" ? "写入文件" : "修改文件"}：${stringValue(args.path) || "(missing path)"}`;
  }
  return `调用工具：${item.tool_name}`;
}

function argumentPreview(value: unknown): string {
  const args = toRecord(value);
  const important = ["command", "path", "mode", "module", "timeout_seconds", "run_in_background"]
    .filter((key) => args[key] !== undefined)
    .map((key) => `${key}=${compactValue(args[key])}`);
  return important.length ? important.join(" · ") : compactValue(value);
}

function compactValue(value: unknown): string {
  if (typeof value === "string") return value.length > 120 ? `${value.slice(0, 117)}...` : value;
  return JSON.stringify(value);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function toRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}
