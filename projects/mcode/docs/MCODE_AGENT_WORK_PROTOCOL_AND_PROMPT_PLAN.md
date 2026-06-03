# Mcode Agent Work Protocol and Prompt Plan

## Goal

提升 Mcode 在复杂长任务里的稳定性、条理性和最终交付质量。

当前问题不只是模型能力本身，而是 agent 框架还缺少一套稳定的工作协议：

- 如何拆解复杂任务。
- 如何在执行中维护状态。
- 如何记录证据和风险。
- 如何把工具结果转成清晰的阶段性判断。
- 如何用一致、专业、可复查的格式交付最终结果。

目标是让 agent 从“会调用工具的聊天模型”升级为：

```text
Structured Agent Operator
  = Work Protocol
  + Task Ledger
  + Evidence Discipline
  + Final Answer Contract
```

## Product Principle

不要要求模型展示完整 chain-of-thought。

我们需要的是：

- 清晰的问题分析框架。
- 可执行的下一步计划。
- 可追踪的动作和证据。
- 可复查的验证结果。
- 简洁但完整的最终交付说明。

也就是说，用户应该看到的是 **professional work summary**，不是模型的私有推理过程。

## Current Weakness

### 1. Agent 输出过于依赖自由发挥

当前 agent 的最终回复往往由模型临场组织。复杂长任务中，模型容易出现：

- 总结遗漏关键改动。
- 只说“完成了”，但没有证据。
- 测试命令和结果不完整。
- 没有说明当前分支、服务地址、截图、产物位置。
- 不清楚哪些问题已解决，哪些只是暂时绕过。

成熟 agent 的条理感通常来自固定契约，而不是每次自由发挥。

### 2. ReAct 流程没有足够产品化

低层 ReAct 只保证：

```text
think -> act -> observe
```

但工程任务需要更强的操作协议：

```text
objective -> constraints -> plan -> action -> evidence -> verification -> delivery
```

如果没有这层协议，长任务会逐渐变成松散工具调用。

### 3. 缺少跨步骤 Task Ledger

复杂任务里，仅靠上下文记忆不够稳定。agent 需要一个结构化账本记录：

- 当前目标。
- 已完成事项。
- 关键决策。
- 修改文件。
- 验证命令。
- 本地服务。
- 产物和截图。
- 风险、阻塞、未完成项。

最终回复应该从 ledger 生成，而不是让模型凭记忆回忆整轮过程。

## Target Behavior

一个成熟的 coding agent 在复杂任务中应该呈现这种节奏：

```text
我先确认目标和当前代码结构。
我发现核心入口在 X，关联模块是 Y/Z。
我会先改 A，再补 B 的测试，最后跑 C 验证。

已修改：
- A：做了什么
- B：做了什么

验证：
- npm test：通过
- npm run build：通过
- python3 scripts/product_acceptance.py：15/15 通过

当前服务：
- http://127.0.0.1:8018/

剩余注意：
- 真实第三方 API 需要有效 key 才能完整验证
```

这种条理应由系统设计保证，而不是希望模型每次自然写好。

## Universal Agent Work Protocol

建议加入 system prompt 或 agent runtime instruction，作为所有非平凡任务的通用协议。

### Task Classification

每轮开始先判断任务类型：

- `answer_only`: 直接回答即可。
- `inspect`: 只读代码、日志、文档或状态。
- `small_change`: 单点修改。
- `implementation`: 多文件实现。
- `debug`: 复现、定位、修复。
- `review`: 代码审查。
- `research`: 需要查资料或比较方案。
- `long_running_goal`: 多阶段目标，需要持续 ledger。

不同类型触发不同强度的计划、验证和最终格式。

### Work Protocol

对于 `small_change`、`implementation`、`debug`、`long_running_goal`：

```text
1. Clarify Objective
   - 用一句话确认用户真正想完成什么。
   - 提取成功标准。

2. Inspect Before Acting
   - 先读相关代码、文档、测试和配置。
   - 不凭空假设项目结构。

3. Form Working Plan
   - 只在任务有明显多步骤时显式列计划。
   - 计划要能执行，不写空泛原则。

4. Execute Incrementally
   - 每次编辑前说明要改哪里、为什么。
   - 每次工具结果后更新 ledger。

5. Preserve Evidence
   - 记录关键命令、测试结果、截图、产物路径。
   - 失败也记录，不藏起来。

6. Verify Against Goal
   - 验证要覆盖用户关心的行为。
   - 不把“构建通过”误认为“产品行为验证通过”。

7. Deliver With Contract
   - 最终回复按固定格式交付。
   - 明确完成、验证、风险、下一步。
```

### Reasoning Safety

不要要求模型展示私有 chain-of-thought。

允许展示：

- “我在检查配置入口。”
- “我发现失败来自 provider 鉴权。”
- “我选择先补单元测试，因为 replay 去重是核心风险。”

不展示：

- 原始长推理。
- provider reasoning_content。
- 未过滤的内部推理日志。

## Task Ledger

新增一个轻量任务账本，作为 run summary 的增强层。

### Suggested Schema

```json
{
  "objective": "Implement trace streaming UX",
  "task_type": "implementation",
  "status": "running",
  "success_criteria": [
    "assistant text streams via delta events",
    "SSE reconnect does not duplicate UI",
    "product acceptance passes"
  ],
  "completed": [
    "Added EventBroker and SSE endpoint",
    "Added frontend EventSource client"
  ],
  "current_focus": "Verify browser QA",
  "changed_files": [
    "mcode-ui/backend/app.py",
    "mcode-ui/frontend/src/state/runTrace.ts"
  ],
  "validations": [
    {
      "command": "npm test",
      "status": "passed",
      "summary": "15 files / 79 tests passed"
    }
  ],
  "artifacts": [
    {
      "kind": "screenshot",
      "path": "notes/mcode_real_api_qa_2026-06-02.png"
    }
  ],
  "local_services": [
    {
      "url": "http://127.0.0.1:8018/",
      "status": "running"
    }
  ],
  "open_risks": [
    "Real provider QA depends on a valid API key"
  ],
  "handoff_notes": [
    "Feature branch merged into main at commit 6e661ed"
  ]
}
```

### Ledger Update Rules

Ledger 不需要每个 token 都更新，只在这些时刻更新：

- 创建或调整计划。
- 完成一个实现小节。
- 发现重要约束或风险。
- 修改文件后。
- 测试或构建后。
- 启动、停止或重启本地服务后。
- 生成截图、文档、报告或其他产物后。
- 最终交付前。

### Event Mapping

可以逐步把现有事件映射到 ledger：

- `file_edited` -> `changed_files`
- `verification_completed` -> `validations`
- `verification_failed` -> `validations` + `open_risks`
- `turn_status` -> `current_focus`
- `provider_error` -> `open_risks`
- `assistant_message_completed` -> `handoff_notes` candidate
- browser QA screenshot -> `artifacts`

## Prompt Contract

建议把 prompt 拆成三层：

```text
Base Identity
  - agent 是什么、基本安全边界、代码协作风格。

Work Protocol
  - 如何处理任务、如何计划、如何验证、如何维护 ledger。

Delivery Contract
  - 最终答复怎么写。
```

### System Prompt Patch

可加入系统提示：

```text
For non-trivial engineering tasks, operate with a task ledger.

Before editing, inspect the relevant files and state what you are changing.
After meaningful actions, update your internal ledger:
- objective
- completed work
- changed files
- validations
- artifacts
- local services
- risks or blockers

Do not expose private chain-of-thought. Expose concise professional reasoning:
what you checked, what you found, what you changed, and how you verified it.

Final answers must be evidence-backed. Mention tests and commands actually run.
If a requested validation could not be performed, say exactly why.
```

### Final Answer Contract

对完成型 coding task，最终回复建议固定为：

```text
已完成 <一句话结果>。

改动重点：
- <模块/文件>：<用户能理解的行为变化>
- <模块/文件>：<用户能理解的行为变化>

验证：
- <command>：通过 / 失败
- <command>：通过 / 失败

运行状态：
- <local URL / artifact path / screenshot path>

注意：
- <风险、未验证项、外部依赖>
```

如果改动很小，可以压缩为两三句话；但复杂任务必须保留证据区。

### Final Answer Examples

#### Implementation Handoff

```text
这轮把 trace UI 组件拆出来了，AgentRunBlock 不再承载全部展示逻辑。

新增：
- ThoughtSummaryPanel.tsx
- TraceStepList.tsx
- TraceActionItem.tsx
- StreamingAssistantMessage.tsx
- traceUi.tsx

验证：
- npm test：15 files / 79 tests passed
- npm run build：通过
- python3 tests/test_agent_run_events.py：通过
- python3 scripts/product_acceptance.py：15/15 通过

本地 QA 服务已重启：
- http://127.0.0.1:8018/
```

#### Debug Handoff

```text
问题定位到了：SSE replay 和 polling fallback 同时返回同一批 delta 时，runTrace 会重复拼接 assistant draft。

修复：
- runTrace.ts 增加事件去重入口。
- 无 seq 事件按 kind + data 去重，并保持原始相对顺序。
- assistant draft 按 message_id 隔离，避免恢复场景串稿。

验证：
- npm test -- runTrace.test.ts：通过
- npm test：79 tests passed
- npm run build：通过
```

#### Blocked Handoff

```text
实现已完成，但真实 provider streaming QA 还不能验证。

原因：
- 当前 DeepSeek API key 返回 401 authentication failure。

已验证：
- mock streaming provider 可以产生 assistant_delta / completed / turn_completed。
- provider failure trace 能在 UI 中恢复显示。

继续前需要：
- 在 Settings 中配置有效 DeepSeek API key。
```

## Finalizer Design

建议新增一个 finalizer 阶段，不让主 agent 完全凭记忆写最终回复。

### Inputs

Finalizer 接收：

- 用户原始目标。
- task ledger。
- recent trace events。
- final summary。
- git changed files。
- validation results。
- artifacts。
- known risks。

### Output

Finalizer 只生成用户可见最终回复，不调用工具。

要求：

- 简洁。
- 证据驱动。
- 不展示私有推理。
- 不虚构测试。
- 不把失败包装成成功。
- 对复杂任务使用稳定结构。

### Suggested Finalizer Prompt

```text
You are writing the final handoff for an engineering agent.

Use the provided task ledger and validation records.
Do not invent commands, files, screenshots, or results.
Do not expose private chain-of-thought.

Write in the user's language.
Start with the outcome.
Then summarize key changes, validations, local services/artifacts, and remaining risks.
Keep it concise, concrete, and easy to scan.
```

## Implementation Plan

### Phase 1: Prompt Only

Low risk, immediate improvement.

- Update system prompt with Work Protocol.
- Add Final Answer Contract.
- Add 3 to 5 few-shot examples.
- Tune final response style for Chinese and English.

Acceptance:

- Complex task final replies consistently include changes and validation.
- Agent stops saying vague “已完成” without evidence.
- Review tasks still use review format and do not become implementation summaries.

### Phase 2: Runtime Task Ledger

Add structured ledger to run summary.

- Add `TaskLedger` dataclass.
- Store in `.runs/<session>.summary.json`.
- Update ledger from trace events and validation events.
- Surface ledger in finalizer input.

Acceptance:

- Refreshing session preserves completed work and validation history.
- Final response can be regenerated from ledger.
- Long tasks survive context compaction better.

### Phase 3: Finalizer

Introduce finalizer as a separate no-tool model call or deterministic renderer.

Options:

- Deterministic renderer for common coding tasks.
- LLM finalizer for richer narrative, constrained by ledger.
- Hybrid: deterministic skeleton + LLM wording.

Acceptance:

- Final answer mentions only actual validations.
- Final answer includes changed files or modules when useful.
- Blocked tasks clearly say what blocked them.

### Phase 4: Self-Audit Before Completion

Before final answer, agent runs a short checklist:

```text
- Did I satisfy the user's explicit request?
- Did I preserve user changes?
- Did I run appropriate validation?
- Did I mention failures or skipped checks?
- Is the local service/artifact path correct?
```

Acceptance:

- Fewer premature “done” responses.
- Better handling of dirty worktrees and partial validation.

## Testing Plan

### Prompt Regression Cases

Create fixture tasks:

- Single-file bug fix.
- Multi-file frontend refactor.
- Backend API + frontend UI change.
- Provider failure / blocked external dependency.
- Browser QA with screenshot.
- Merge branch with dirty worktree.

For each case, assert final response includes:

- Outcome.
- Key changes.
- Validations.
- Risks or skipped validation if any.
- Local URL or artifact when applicable.

### Ledger Tests

- Ledger records changed files from file events.
- Ledger records validation command and result.
- Ledger preserves open risks.
- Ledger survives summary reload.
- Finalizer does not invent commands absent from ledger.

### Human Evaluation Rubric

Score 1 to 5:

- Clarity: easy to scan and understand.
- Completeness: includes relevant changes and evidence.
- Honesty: does not hide failed/skipped checks.
- Brevity: no unnecessary narration.
- Continuity: long task state remains coherent.

## Risks

### Over-Structured Replies

Risk:

- Small tasks may get overly heavy final formatting.

Mitigation:

- Apply full contract only to non-trivial tasks.
- Tiny tasks can use one short paragraph.

### Fake Confidence

Risk:

- A polished template can make weak evidence look strong.

Mitigation:

- Finalizer must only cite ledger-backed facts.
- Skipped validations must be explicit.

### Prompt Bloat

Risk:

- System prompt becomes too long and hurts model focus.

Mitigation:

- Keep base protocol short.
- Put examples in retrievable prompt snippets.
- Use task-type-specific contracts.

### Ledger Drift

Risk:

- Ledger becomes stale if not updated after important actions.

Mitigation:

- Update ledger from events automatically where possible.
- Use final self-audit to detect missing validations or artifacts.

## Definition of Done

- Agent has a reusable Work Protocol in prompt.
- Complex task final responses consistently include outcome, changes, validation, artifacts, and risks.
- Task Ledger records enough state to survive long tasks and context compaction.
- Finalizer produces concise, evidence-backed handoffs.
- No raw chain-of-thought or provider reasoning is exposed.
- Prompt regressions cover implementation, debug, blocked, browser QA, and merge workflows.

