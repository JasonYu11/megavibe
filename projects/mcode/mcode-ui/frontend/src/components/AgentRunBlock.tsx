import type { RunTrace } from "../types";
import { ThoughtSummaryPanel } from "./ThoughtSummaryPanel";
import { TraceStepList } from "./TraceStepList";
import { phaseText, statusText } from "./traceUi";

export function AgentRunBlock({ trace }: { trace: RunTrace }) {
  const visibleMessage = trace.message || statusText(trace.status);

  return (
    <section className={`agentRun agentRun--${trace.status}`}>
      <header className="agentRun__header">
        <div>
          <strong>Agent Run</strong>
          <span>{visibleMessage}</span>
        </div>
        <span className="agentRun__phase">{phaseText(trace.phase)}</span>
      </header>
      <ThoughtSummaryPanel
        thoughtSummary={trace.thoughtSummary}
        assistantDraft={trace.assistantDraft}
        streaming={trace.status === "running"}
      />
      <TraceStepList steps={trace.steps} />
    </section>
  );
}
