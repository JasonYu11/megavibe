import { Check, RotateCcw, X } from "lucide-react";
import { useState } from "react";
import type { PendingPlan } from "../types";
import { FinalAnswerRenderer } from "./FinalAnswerRenderer";

export function PlanApprovalCard({
  plan,
  busy,
  onApprove,
  onRefine,
  onCancel,
}: {
  plan: PendingPlan;
  busy?: boolean;
  onApprove: () => void;
  onRefine: (feedback: string) => void;
  onCancel: () => void;
}) {
  const [feedback, setFeedback] = useState("");
  const canRefine = feedback.trim().length > 0 && !busy;
  const todos = Array.isArray(plan.todos) ? plan.todos : [];
  const revision = typeof plan.revision === "number" && plan.revision > 0 ? plan.revision : 1;
  const todoCount = typeof plan.todo_count === "number" ? plan.todo_count : todos.length;

  return (
    <section className="planApproval" data-testid="plan-approval-card">
      <div className="planApproval__header">
        <div>
          <strong>计划已生成 · 第 {revision} 版</strong>
          <span>确认后 agent 才会开始修改或执行命令{todoCount ? ` · 将创建 ${todoCount} 项 todo` : ""}</span>
        </div>
        <div className="planApproval__actions">
          <button className="secondaryButton" onClick={onCancel} disabled={busy} type="button">
            <X size={15} />
            取消
          </button>
          <button className="primaryButton" onClick={onApprove} disabled={busy} type="button">
            <Check size={15} />
            执行计划
          </button>
        </div>
      </div>
      <div className="planApproval__body">
        <FinalAnswerRenderer text={plan.plan_text} />
        {todos.length > 0 && (
          <ol className="planApproval__todos" aria-label="计划对应 todo">
            {todos.slice(0, 6).map((todo, index) => (
              <li className={todo.level ? "planApproval__todoSubstep" : undefined} key={`${todo.content || "todo"}-${index}`}>
                <span>{todo.status === "in_progress" ? "进行中" : "待处理"}</span>
                {todo.content}
              </li>
            ))}
            {todos.length > 6 && <li className="planApproval__todoMore">还有 {todos.length - 6} 项</li>}
          </ol>
        )}
      </div>
      <div className="planApproval__refine">
        <textarea
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          placeholder="补充或修改计划，例如：先加测试，再改实现"
          disabled={busy}
        />
        <button className="secondaryButton" onClick={() => onRefine(feedback.trim())} disabled={!canRefine} type="button">
          <RotateCcw size={15} />
          更新计划
        </button>
      </div>
    </section>
  );
}
