import { FlaskConical, Loader2 } from "lucide-react";
import type { TestRun } from "../types";

export function TestDock({ run, onRun }: { run?: TestRun | null; onRun: (label?: string) => void }) {
  const running = run?.status === "running";
  return (
    <div className="testDock" data-testid="test-dock">
      <button className="testDock__button" onClick={() => onRun("product")} disabled={running}>
        {running ? <Loader2 className="spin" size={15} /> : <FlaskConical size={15} />}
        产品验收
      </button>
      <button className="testDock__button testDock__button--secondary" onClick={() => onRun("subagent")} disabled={running}>
        子测试
      </button>
      <button className="testDock__button testDock__button--secondary" onClick={() => onRun("benchmark-dry")} disabled={running}>
        回归规格
      </button>
      <button className="testDock__button testDock__button--secondary" onClick={() => onRun("benchmark")} disabled={running} title="真实 agent benchmark，会调用模型 API">
        8项回归
      </button>
      {run && (
        <div className={`testDock__status testDock__status--${run.status}`}>
          <span>{run.label}</span>
          <strong>{run.status}</strong>
        </div>
      )}
      {run?.output && <pre className="testDock__output">{run.output.slice(-900)}</pre>}
    </div>
  );
}
