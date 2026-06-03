import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import type { TraceStep } from "../types";
import { TraceActionItem } from "./TraceActionItem";
import { StatusIcon, statusText } from "./traceUi";

export function TraceStepList({ steps }: { steps: TraceStep[] }) {
  const [openSteps, setOpenSteps] = useState<Record<string, boolean>>({});
  const openByDefault = useMemo(() => {
    const state: Record<string, boolean> = {};
    for (const step of steps) {
      state[step.id] = step.status === "running" || step.status === "failed";
    }
    return state;
  }, [steps]);

  return (
    <div className="agentRun__steps">
      {steps.map((step, index) => {
        const isOpen = openSteps[step.id] ?? openByDefault[step.id] ?? index === steps.length - 1;
        return (
          <div className={`traceStep traceStep--${step.status}`} key={step.id}>
            <button
              className="traceStep__head"
              onClick={() => setOpenSteps((current) => ({ ...current, [step.id]: !isOpen }))}
            >
              {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
              <StatusIcon status={step.status} />
              <span>{step.title}</span>
              <em>{statusText(step.status)}</em>
            </button>
            {isOpen && (
              <div className="traceStep__body">
                {step.summary && <p className="traceStep__summary">{step.summary}</p>}
                {step.actions.map((action) => (
                  <TraceActionItem action={action} key={action.id} />
                ))}
                {!step.actions.length && !step.summary && <p className="traceStep__empty">等待事件</p>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
