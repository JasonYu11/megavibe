# Mcode Parallel Optimization Worktrees

本文用于给其它 Codex 对话交接当前 mini-agent app 的并行开发任务。

## Current Baseline

主仓库：

```text
/Users/macbot/Documents/deepseek_agent_research/mini-agent-lab
```

当前主工作区分支：

```text
feature/settings-workspace-dock
```

并行 worktree 的共同基线提交：

```text
a2dcb56 Checkpoint before parallel optimization worktrees
```

主工作区当前还有一个未跟踪产物文件：

```text
lfm_matched_filter.py
```

这个文件是之前仿真测试生成的产物，不属于开发基线。其它对话不要依赖它，也不要把它作为功能代码提交。

## Worktree Map

| 方向 | 路径 | 分支 |
| --- | --- | --- |
| Prompt / final answer 优化 | `/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-prompt` | `feature/opt-prompt-final-answer` |
| Tool result 摘要优化 | `/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-tool-results` | `feature/opt-tool-result-summaries` |
| Plan -> Todo 衔接 | `/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-plan-todo` | `feature/opt-plan-todo-link` |
| UI 事件分层 | `/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-ui-events` | `feature/opt-ui-event-layering` |
| 失败恢复 | `/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-recovery` | `feature/opt-failure-recovery` |
| Benchmark 回归体系 | `/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-benchmarks` | `feature/opt-agent-benchmarks` |

建议先并行做前三项：

```text
prompt
tool-results
benchmarks
```

后面三项更容易和核心 loop / UI 状态互相影响，建议等第一批完成后再推进。

## Shared Rules For All Threads

每个 Codex 对话只在自己的 worktree 里开发，不要切到其它 worktree。

开始时先确认：

```bash
pwd
git status --short --branch
git log --oneline -3
```

要求：

- 只处理本分支任务，不做无关重构。
- 不要改 `.env`。
- 不要提交运行产物、截图、缓存、`.runs`、`.sessions`、`.attachments` 等。
- 如果必须修改共享核心文件，最后总结清楚，方便合并时处理冲突。
- 完成后运行相关测试，并写清楚测试结果。

常用验证命令：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mini-agent-pycache python3 tests/test_agent_run_events.py
PYTHONPYCACHEPREFIX=/private/tmp/mini-agent-pycache python3 tests/test_tool_outcomes.py
PYTHONPYCACHEPREFIX=/private/tmp/mini-agent-pycache python3 tests/test_ui_backend.py
cd mcode-ui/frontend && npm run test -- --run && npm run build
```

不是每个分支都必须跑全部测试，但必须跑和改动相关的测试。若改动跨 agent loop、run recorder、UI 状态映射，建议跑全套上面的测试。

## Task 1: Prompt / Final Answer Optimization

Worktree:

```text
/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-prompt
```

Branch:

```text
feature/opt-prompt-final-answer
```

目标：

优化模型行为，让 agent 更像 Codex：

- 最终回答更简洁。
- 明确说明做了什么、改了哪些文件、验证了什么。
- 不把大段日志塞进最终回答。
- Python 任务优先使用 `python_run`。
- 复杂任务主动使用 `todo_write`。
- plan mode 只输出计划，不执行写操作。
- 执行计划后按 todo 逐步更新。

可能修改模块：

```text
scripts/agent_chat.py
mini_agent_lab/plan.py
mini_agent_lab/agent/agent.py
mini_agent_lab/tool/builtin.py
mcode-ui/frontend/src/components/FinalAnswerRenderer.tsx
```

验收标准：

- final answer 风格接近 Codex：短、清楚、以结果和验证为主。
- 不出现“完整工作回顾”这类冗长模板。
- Python 仿真/脚本任务倾向使用 `python_run`，不是 bash。
- 计划模式不会直接执行写入或命令。
- 相关测试通过。

## Task 2: Tool Result Summaries

Worktree:

```text
/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-tool-results
```

Branch:

```text
feature/opt-tool-result-summaries
```

目标：

让工具结果对模型更高信息密度，对 UI 更可展开。

当前痛点：

- command output 容易过长。
- 模型看到的日志太多，影响后续推理。
- UI 和模型应该看到不同层级的信息。

优化方向：

- 为工具结果生成 `model_summary`。
- 大日志只给模型返回：
  - exit code
  - 关键错误
  - traceback 核心段
  - 最后 N 行
  - 生成/修改文件
  - 验证结论
- 完整日志保留在 `.runs` / `.jobs`，UI 可展开查看。
- Python traceback 自动提取核心错误。

可能修改模块：

```text
mini_agent_lab/agent/agent.py
mini_agent_lab/tool/builtin.py
mini_agent_lab/run_recorder.py
mcode-ui/frontend/src/components/ToolCard.tsx
mcode-ui/frontend/src/components/TerminalPanel.tsx
```

验收标准：

- 长 stdout 不再整段喂给模型。
- Python 错误能保留核心 traceback。
- UI 仍能查看完整或足够详细的输出。
- `tests/test_tool_outcomes.py` 和 `tests/test_python_run_tool.py` 通过。

## Task 3: Plan To Todo Link

Worktree:

```text
/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-plan-todo
```

Branch:

```text
feature/opt-plan-todo-link
```

当前状态：

Plan mode 已经支持：

- 生成计划后进入 `awaiting_plan_decision`
- UI 显示 `执行计划`
- UI 支持输入修改意见并重新生成计划
- UI 支持取消计划

目标：

让 plan approval 和 todo 执行更紧密：

- pending plan 存结构化 todos。
- 修改计划时记录 revision count。
- 执行计划后自动 seed todo。
- UI 能显示计划版本和对应 todo。
- 执行计划后 todo 自动从第一项开始 in_progress。

可能修改模块：

```text
mini_agent_lab/plan.py
mini_agent_lab/run_recorder.py
mini_agent_lab/agent/agent.py
mcode-ui/backend/app.py
mcode-ui/frontend/src/components/PlanApprovalCard.tsx
mcode-ui/frontend/src/components/ChatWorkspace.tsx
mcode-ui/frontend/src/state/events.ts
```

验收标准：

- 计划生成后 summary 中有 `pending_plan.todos`。
- 点击执行计划后第一轮执行会带上 todo seed。
- 修改计划后 revision count 增加。
- UI 能看出当前是第几版计划。
- `tests/test_agent_run_events.py`、`tests/test_run_recorder.py`、前端测试通过。

## Task 4: UI Event Layering

Worktree:

```text
/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-ui-events
```

Branch:

```text
feature/opt-ui-event-layering
```

目标：

进一步把 Chat、Thinking、Terminal、Events 分层，避免用户被事件流淹没。

当前期望：

- Chat 中只出现：
  - 用户消息
  - assistant 最终回答
  - thinking group
  - tool card summary
  - approval card
  - plan approval card
  - change review
- 右侧 Events 才显示 debug/time line。
- command output 默认只在 Terminal / ToolCard 细节中显示。
- thinking group 默认折叠，running 时展开。

可能修改模块：

```text
mcode-ui/frontend/src/state/events.ts
mcode-ui/frontend/src/components/ChatWorkspace.tsx
mcode-ui/frontend/src/components/EventTimeline.tsx
mcode-ui/frontend/src/components/ToolCard.tsx
mcode-ui/frontend/src/styles.css
```

验收标准：

- `command_output` 不进入中间聊天区。
- `compact_check`、`checkpoint_saved` 等 debug 事件不刷屏。
- thinking/tool 顺序和用户/assistant 顺序符合时间线。
- 右侧 Events 仍能查看完整事件。
- 前端测试通过。

## Task 5: Failure Recovery

Worktree:

```text
/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-recovery
```

Branch:

```text
feature/opt-failure-recovery
```

目标：

增强失败恢复能力，让 agent 不因为一次网络失败、空回复、工具失败而卡死。

优化方向：

- 区分模型请求失败类型：
  - 网络问题
  - API 限流
  - 上下文过长
  - 超时
  - 空回复
- tool 连续失败时提示模型换策略。
- failed turn 后 UI 可继续下一轮。
- send failed/pending 状态更稳定。
- cancel 后状态能回到可继续交互。

可能修改模块：

```text
mini_agent_lab/provider/deepseek.py
mini_agent_lab/agent/agent.py
mini_agent_lab/control.py
mcode-ui/backend/runtime.py
mcode-ui/frontend/src/App.tsx
mcode-ui/frontend/src/components/ChatWorkspace.tsx
```

验收标准：

- 模型空回复仍能 recovery final answer。
- 网络失败能显示清晰错误，不破坏 transcript。
- 工具连续同错会触发 loop guard。
- 失败后可以继续发下一条消息。
- `tests/test_tool_outcomes.py`、`tests/test_agent_run_events.py`、前端测试通过。

## Task 6: Agent Benchmarks

Worktree:

```text
/Users/macbot/Documents/deepseek_agent_research/mini-agent-opt-benchmarks
```

Branch:

```text
feature/opt-agent-benchmarks
```

目标：

建立轻量 agent 回归 benchmark，用于判断优化是否真的提升模型能力和交互稳定性。

建议任务集：

- 读取 README 并总结。
- 创建一个小 Python 脚本并运行。
- 修复一个简单 bug。
- 用附件完成总结或转换。
- 使用 plan mode 生成计划并执行。
- 触发 bash 审批。
- 使用 python_run 完成仿真。
- 生成文件后出现 change review。
- 长输出命令不刷屏。
- 失败工具调用后能换策略。

可能修改模块：

```text
benchmark_specs/
scripts/run_agent_ui_benchmarks.py
scripts/live_agent_simulation_test.py
scripts/product_acceptance.py
tests/
```

验收标准：

- 提供可重复运行的 benchmark 脚本。
- 输出 JSON/Markdown 报告。
- 报告至少包含：
  - 成功/失败
  - 用到哪些工具
  - 是否有最终回答
  - 是否生成目标文件
  - 是否触发审批
  - 是否出现 UI 关键事件
- dry-run 不需要真实 API。
- live-run 可以使用 DeepSeek API，但要有超时和失败分类。

## Merge Guidance

每个 worktree 完成后：

```bash
git status --short
git add <changed-files>
git commit -m "<clear message>"
```

回到主工作区合并前：

```bash
cd /Users/macbot/Documents/deepseek_agent_research/mini-agent-lab
git status --short --branch
git merge <branch>
```

合并顺序建议：

```text
1. benchmarks
2. prompt
3. tool-results
4. plan-todo
5. ui-events
6. recovery
```

原因：

- benchmark 相对独立，可先合并作为后续验收工具。
- prompt 和 tool-results 会影响模型行为，先合并有利于后续验证。
- plan-todo、ui-events、recovery 更容易碰核心 loop 和 UI 状态，放后面。

合并后建议运行：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/mini-agent-pycache python3 tests/test_agent_run_events.py
PYTHONPYCACHEPREFIX=/private/tmp/mini-agent-pycache python3 tests/test_tool_outcomes.py
PYTHONPYCACHEPREFIX=/private/tmp/mini-agent-pycache python3 tests/test_ui_backend.py
cd mcode-ui/frontend && npm run test -- --run && npm run build
```

