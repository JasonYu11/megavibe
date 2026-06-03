import { AlertTriangle, CheckCircle2, Circle, Eye, FilePenLine, Shield, Terminal, Wrench } from "lucide-react";
import type { TraceStep } from "../types";

export function StatusIcon({ status }: { status: TraceStep["status"] }) {
  if (status === "completed") return <CheckCircle2 size={15} />;
  if (status === "failed") return <AlertTriangle size={15} />;
  if (status === "running") return <Circle size={15} className="traceSpin" />;
  return <Circle size={15} />;
}

export function ActionIcon({ kind }: { kind: string }) {
  if (kind === "file_read") return <Eye size={15} />;
  if (kind === "file_edit") return <FilePenLine size={15} />;
  if (kind === "command" || kind === "verification") return <Terminal size={15} />;
  if (kind === "approval") return <Shield size={15} />;
  return <Wrench size={15} />;
}

export function statusText(status: string): string {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  if (status === "pending") return "等待中";
  return "正在执行";
}

export function phaseText(phase?: string): string {
  if (phase === "understanding") return "理解需求";
  if (phase === "model_call") return "生成中";
  if (phase === "executing_tools") return "执行工具";
  if (phase === "finalizing") return "交付";
  return phase || "trace";
}
