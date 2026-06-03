import type { SubagentInfo } from "../types";

export function SubagentPanel({ subagents }: { subagents: SubagentInfo[] }) {
  return (
    <div className="panelBody">
      {subagents.length === 0 && <div className="emptyNote">暂无 subagent</div>}
      {subagents.map((subagent) => (
        <div className="subagentCard" key={subagent.subagent_id}>
          <div className="subagentCard__head">
            <strong>{subagent.description || subagent.subagent_id}</strong>
            <span>{subagent.status}</span>
          </div>
          {subagent.task && <p>{subagent.task}</p>}
          {subagent.answer && <pre>{subagent.answer}</pre>}
          {subagent.error && <div className="toolCard__error">{subagent.error}</div>}
        </div>
      ))}
    </div>
  );
}
