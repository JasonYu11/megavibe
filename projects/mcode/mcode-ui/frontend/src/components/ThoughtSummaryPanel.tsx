import { StreamingAssistantMessage } from "./StreamingAssistantMessage";

export function ThoughtSummaryPanel({
  thoughtSummary,
  assistantDraft,
  streaming,
}: {
  thoughtSummary: string;
  assistantDraft: string;
  streaming: boolean;
}) {
  if (!thoughtSummary && !(assistantDraft && streaming)) return null;
  return (
    <div className="agentRun__summary">
      {thoughtSummary && <p>{thoughtSummary}</p>}
      {streaming && <StreamingAssistantMessage text={assistantDraft} />}
    </div>
  );
}
