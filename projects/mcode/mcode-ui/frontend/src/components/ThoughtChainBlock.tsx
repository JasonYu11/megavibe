import { useState, useEffect, useRef } from "react";
import { Brain, Check, ChevronDown, ChevronRight, Loader2, X } from "lucide-react";
import type { ThoughtChain } from "../types";
import { ThoughtStepItem } from "./ThoughtStepItem";

interface ThoughtChainBlockProps {
  chain: ThoughtChain;
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

export function ThoughtChainBlock({ chain }: ThoughtChainBlockProps) {
  const running = chain.status === "running";
  const [expanded, setExpanded] = useState(running);
  const [userToggled, setUserToggled] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const wasRunning = useRef(running);
  const timer = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    if (running && chain.startedAt) {
      timer.current = setInterval(() => setElapsed(Date.now() - chain.startedAt!), 200);
    } else {
      if (timer.current) clearInterval(timer.current);
    }
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [running, chain.startedAt]);

  useEffect(() => {
    if (wasRunning.current && !running && !userToggled) setExpanded(false);
    wasRunning.current = running;
  }, [running, userToggled]);

  const toggle = () => { setExpanded((v) => !v); if (!userToggled) setUserToggled(true); };

  const tools = chain.steps.filter((s) => s.kind === "tool_call").length;
  const thoughts = chain.steps.filter((s) => s.kind === "thought").length;
  const dur = running ? elapsed
    : chain.completedAt && chain.startedAt ? chain.completedAt - chain.startedAt : undefined;

  const statParts: string[] = [];
  if (tools) statParts.push(`${tools} 次调用`);
  if (thoughts) statParts.push(`${thoughts} 条消息`);

  return (
    <section className={`thoughtChain thoughtChain--${chain.status}`}>
      <button className="thoughtChain__bar" onClick={toggle}>
        <span className="thoughtChain__chevron">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="thoughtChain__badge">
          {running
            ? <Loader2 size={13} className="spin" />
            : chain.status === "failed" ? <X size={13} />
            : <Check size={13} />}
        </span>
        <span className="thoughtChain__label">
          {running ? "处理中" : chain.status === "failed" ? "失败" : "已完成"}
        </span>
        {statParts.length > 0 && (
          <span className="thoughtChain__stats">{statParts.join(" · ")}</span>
        )}
        {dur !== undefined && dur > 0 && (
          <span className="thoughtChain__time">{fmtMs(dur)}</span>
        )}
      </button>
      {expanded && (
        <div className="thoughtChain__body">
          {chain.steps.map((step, i) => (
            <ThoughtStepItem key={`${step.id}-${i}`} step={step} autoExpand={!userToggled} />
          ))}
        </div>
      )}
    </section>
  );
}
