import { useState, useEffect } from "react";
import { Check, ChevronDown, ChevronRight, Circle, Eye, FilePen, GitBranch, ListChecks, Loader2, MessageSquare, Search, Terminal, Wrench, X } from "lucide-react";
import type { ThoughtStep } from "../types";

function toolIcon(name: string) {
  if (!name) return <Wrench size={14} />;
  if (name === "read_file") return <Eye size={14} />;
  if (name === "write_file" || name === "edit_file") return <FilePen size={14} />;
  if (name === "bash" || name === "python_run") return <Terminal size={14} />;
  if (name === "grep" || name === "glob" || name === "find") return <Search size={14} />;
  if (name.startsWith("git")) return <GitBranch size={14} />;
  if (name === "task") return <MessageSquare size={14} />;
  if (name === "todo_write") return <ListChecks size={14} />;
  return <Wrench size={14} />;
}

interface ThoughtStepItemProps {
  step: ThoughtStep;
  autoExpand?: boolean;
}

export function ThoughtStepItem({ step, autoExpand }: ThoughtStepItemProps) {
  const [open, setOpen] = useState(false);
  const running = step.status === "running";
  const isPlanItem = step.id.startsWith("todo-");

  useEffect(() => {
    if (autoExpand && running) setOpen(true);
  }, [autoExpand, running]);

  const hasDetail = Boolean(step.detail || step.toolArgs);

  return (
    <div className={`thoughtStep thoughtStep--${step.status} thoughtStep--${step.kind}`}>
      <button
        className="thoughtStep__head"
        onClick={() => hasDetail && setOpen((v) => !v)}
        style={{ cursor: hasDetail ? "pointer" : "default" }}
      >
        {hasDetail ? (
          open ? <ChevronDown size={14} /> : <ChevronRight size={14} />
        ) : (
          <span style={{ width: 14 }} />
        )}
        <span className="thoughtStep__icon">
          {step.kind === "thought" ? <MessageSquare size={14} /> : toolIcon(step.toolName || "")}
        </span>
        <span className="thoughtStep__title">{step.title}</span>
        {step.diffAdded !== undefined && step.diffAdded > 0 && (
          <span className="thoughtStep__diff thoughtStep__diff--add">+{step.diffAdded}</span>
        )}
        {step.diffRemoved !== undefined && step.diffRemoved > 0 && (
          <span className="thoughtStep__diff thoughtStep__diff--del">-{step.diffRemoved}</span>
        )}
        {running && <Loader2 size={14} className="spin thoughtStep__spin" />}
        {!running && isPlanItem && step.status !== "completed" && <Circle size={14} className="thoughtStep__pending" />}
        {step.status === "completed" && <Check size={14} className="thoughtStep__check" />}
        {step.status === "failed" && <X size={14} className="thoughtStep__fail" />}
      </button>
      {open && hasDetail && (
        <div className="thoughtStep__body">
          {step.kind === "thought" && step.detail && (
            <p className="thoughtStep__detail">{step.detail}</p>
          )}
          {step.kind === "tool_call" && step.toolArgs && (
            <pre className="thoughtStep__args">
              {JSON.stringify(step.toolArgs, null, 2)}
            </pre>
          )}
          {step.kind === "tool_call" && step.detail && (
            <pre className="thoughtStep__output">{step.detail}</pre>
          )}
          {step.error && <div className="thoughtStep__error">{step.error}</div>}
        </div>
      )}
    </div>
  );
}
