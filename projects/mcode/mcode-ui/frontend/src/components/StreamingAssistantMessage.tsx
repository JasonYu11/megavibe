export function StreamingAssistantMessage({ text }: { text: string }) {
  if (!text) return null;
  return <p className="agentRun__draft">{text}</p>;
}
