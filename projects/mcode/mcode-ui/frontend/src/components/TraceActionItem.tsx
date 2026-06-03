import type { TraceAction } from "../types";
import { ActionIcon, statusText } from "./traceUi";

export function TraceActionItem({ action }: { action: TraceAction }) {
  return (
    <div className={`traceAction traceAction--${action.status}`}>
      <div className="traceAction__icon">
        <ActionIcon kind={action.kind} />
      </div>
      <div className="traceAction__main">
        <div className="traceAction__top">
          <strong>{action.title}</strong>
          <span>{statusText(action.status)}</span>
        </div>
        <div className="traceAction__meta">
          {action.path && <code>{action.path}</code>}
          {action.command && <code>{action.command}</code>}
          {(action.additions || action.deletions) && (
            <span>
              <b>+{action.additions || 0}</b> <i>-{action.deletions || 0}</i>
            </span>
          )}
          {typeof action.exitCode === "number" && <span>exit {action.exitCode}</span>}
          {action.durationMs ? <span>{Math.round(action.durationMs)}ms</span> : null}
        </div>
        {(action.summary || action.error) && <p>{action.error || action.summary}</p>}
      </div>
    </div>
  );
}
