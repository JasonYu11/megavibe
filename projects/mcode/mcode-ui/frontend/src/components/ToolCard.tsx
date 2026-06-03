import { Check, ChevronDown, ChevronRight, Loader2, X, Wrench } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import type { UiItem } from "../types";

type ToolItem = Extract<UiItem, { kind: "tool" }>;

export function ToolCard({ item, children }: { item: ToolItem; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const outputPreview = item.modelSummary || item.outputPreview || compactOutput(item.output || "");
  return (
    <div className={`toolCard toolCard--${item.status}`} data-testid="tool-card">
      <button className="toolCard__head" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <Wrench size={15} />
        <span>{item.name}</span>
        {item.summary && <span className="toolCard__summary">{item.summary}</span>}
        <span className="toolCard__status">
          {item.status === "running" && <Loader2 className="spin" size={14} />}
          {item.status === "done" && <Check size={14} />}
          {(item.status === "error" || item.status === "blocked") && <X size={14} />}
          {item.status}
        </span>
      </button>
      {hasMeta(item) && (
        <div className="toolCard__meta">
          {item.commandKind && <span>{item.commandKind}</span>}
          {item.exitCode !== undefined && item.exitCode !== null && <span>exit {item.exitCode}</span>}
          {typeof item.durationMs === "number" && <span>{formatDuration(item.durationMs)}</span>}
          {item.jobId && <span>{item.jobId}</span>}
          {item.runtime && <span title={item.runtime}>{shortenMiddle(item.runtime, 72)}</span>}
        </div>
      )}
      {open && (
        <div className="toolCard__body">
          <section>
            <h4>参数</h4>
            <pre>{JSON.stringify(item.args, null, 2)}</pre>
          </section>
          {item.command && (
            <section>
              <h4>命令</h4>
              <pre>{item.command}</pre>
            </section>
          )}
          {outputPreview && (
            <section>
              <h4>输出摘要</h4>
              <pre>{outputPreview}</pre>
            </section>
          )}
          {item.output && item.output !== outputPreview && (
            <details>
              <summary>完整工具返回</summary>
              <pre>{item.output}</pre>
            </details>
          )}
          {item.error && <div className="toolCard__error">{item.error}</div>}
        </div>
      )}
      {children && <div className="toolCard__nested">{children}</div>}
    </div>
  );
}

function hasMeta(item: ToolItem): boolean {
  return Boolean(item.commandKind || item.exitCode !== undefined || item.durationMs !== undefined || item.runtime || item.jobId);
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

function compactOutput(output: string): string {
  const clean = output.replace(/\n?\[(python|command)\]\s+exit_code=.*$/s, "").trim();
  if (!clean) return "";
  return clean.length <= 1200 ? clean : `...[${clean.length - 1200} chars omitted]...\n${clean.slice(-1200)}`;
}

function shortenMiddle(text: string, max: number): string {
  if (text.length <= max) return text;
  const keep = Math.floor((max - 3) / 2);
  return `${text.slice(0, keep)}...${text.slice(-keep)}`;
}
