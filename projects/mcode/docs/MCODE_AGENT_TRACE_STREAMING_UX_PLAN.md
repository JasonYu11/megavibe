# Mcode Agent Trace and Streaming UX Plan

## Goal

把 Mcode 从“聊天框 + 工具日志”升级为 Codex-style agent workbench：

- assistant 文本支持流式输出，而不是等待模型完整返回后一次性显示。
- agent 执行过程被结构化为可解释、可折叠、可恢复的 trace。
- UI 展示“正在理解、读取文件、编辑文件、运行验证、完成交付”等专业步骤。
- 前端不再靠猜测底层工具事件来组织过程，而是消费后端归一化的产品级事件。
- 保留当前事件文件和轮询机制作为 fallback，同时新增 SSE 作为实时通道。

核心方向不是单纯做 token streaming，而是做：

```text
Agent Trace + Streaming Transport + Workbench UI
```

## Current State

当前 Mcode 已有 agent loop、事件记录和前端轮询，但还不是完整的 agent trace 体验。

### Provider

- `mini_agent_lab/provider/deepseek.py` 里请求体使用 `"stream": False`。
- 模型调用结束后，后端一次性得到完整 `content`、`reasoning_content` 和 `tool_calls`。
- 没有 token delta、reasoning delta、tool-call argument delta 的解析逻辑。

### Agent Loop

- `mini_agent_lab/agent/agent.py` 当前核心事件包括：
  - `turn_started`
  - `assistant_message`
  - `tool_dispatch`
  - `tool_result`
  - `notice`
  - `todo_updated`
  - `turn_completed`
- 这些是底层执行事件，不是产品级 trace。
- 前端需要根据 `tool_dispatch` / `tool_result` 自己猜测用户应该看到什么。
- agent 的“思考过程”缺少稳定阶段：
  - 没有 step started/completed。
  - 没有 action intent。
  - 没有 file read/edit/verify 的归一化事件。
  - 没有正在生成中的 assistant message。

### Backend Transport

- 后端提供：
  - `GET /api/projects/{project_id}/sessions/{session_id}/events`
- 前端每 500ms 轮询一次事件。
- 没有 SSE / WebSocket。
- 轮询可以展示工具进度，但不适合 token 级流式输出。

### Frontend UI

- `state/events.ts` 负责把事件拼成 transcript item。
- 当前 UI 可以展示 thinking group、tool item、approval、change review、todo 等。
- 但 UI 仍然偏“事件日志整理”，不是规范的 step trace：
  - 工具事件粒度过低。
  - 同类动作没有统一卡片。
  - 文件读取、文件编辑、命令验证没有稳定视觉模型。
  - assistant 文本没有 streaming draft 状态。

## Product Principle

不要展示裸露 chain-of-thought。

应该展示的是 **sanitized thought summary** 和 **execution trace**：

```text
正在理解需求
正在读取 auto_review.py
发现需要同步 control.py 的配置传递
正在修改 auto_review.py
正在运行测试验证
```

不应该展示模型完整私有推理。

专业 agent UI 的目标是让用户看见：

- agent 当前在做什么。
- 为什么要做这个动作的简短摘要。
- 读了什么。
- 改了什么。
- 验证了什么。
- 哪一步完成了，哪一步失败了。
- 最终交付和过程证据是否一致。

## Target UX

一次 turn 在中间对话区应呈现为：

```text
用户消息

Agent Run
  状态：正在执行 / 等待确认 / 已完成 / 失败 / 已取消

  深度思考
    正在检查 auto_review.py 的配置入口

  步骤 1：理解配置入口
    已读取 auto_review.py L1-末尾
    已读取 control.py L1-L220

  步骤 2：接入配置
    编辑 auto_review.py +141 -16
    编辑 control.py +22 -4

  步骤 3：验证
    运行 python3 scripts/test_auto_review.py
    验证通过

最终回答
  已完成 auto review 配置接入...
```

### UI Structure

推荐新增或重构为以下组件：

- `AgentRunBlock`
  - 一次 turn 的容器。
  - 显示运行状态、耗时、取消状态、错误状态。

- `ThoughtSummaryPanel`
  - 可折叠。
  - 展示 sanitized summary，不展示完整原始推理。
  - 支持 streaming delta。

- `TraceStepList`
  - 展示 step。
  - 每个 step 有状态：`pending` / `running` / `completed` / `failed` / `cancelled`。

- `TraceActionItem`
  - 读取文件、编辑文件、运行命令、调用工具、请求审批、验证结果等统一 action。

- `StreamingAssistantMessage`
  - 接收 `assistant_delta`。
  - turn 结束后固化为 final assistant message。

### Visual Style

- 参考 Codex 风格，整体克制、工程化、可扫描。
- 默认折叠长过程，只展开当前 running step 和失败 step。
- 工具详情、长输出、diff preview 默认折叠。
- 文件路径使用 monospace，新增/删除用绿色/红色轻量数字。
- 每个 action 左侧使用稳定图标：
  - read: eye/file icon
  - edit: pencil icon
  - command: terminal icon
  - verify: check icon
  - approval: shield icon
  - error: alert icon
- 不把所有事件都渲染成聊天气泡；trace 是一个独立工作区块。

## Event Model

新增一层产品级 trace events。底层事件仍然保留，trace event 用于 UI。

### Turn Events

```text
turn_started
turn_status
turn_completed
turn_failed
turn_cancel_requested
turn_cancelled
```

`turn_status` 示例：

```json
{
  "status": "running",
  "phase": "executing_tools",
  "message": "正在执行工具调用"
}
```

### Thought Summary Events

```text
thought_summary_started
thought_summary_delta
thought_summary_completed
thought_summary_redacted
```

示例：

```json
{
  "text": "正在检查 auto_review.py 的配置入口"
}
```

规则：

- 不直接暴露完整 reasoning_content。
- provider 若返回 reasoning delta，后端先做摘要/过滤，再发给 UI。
- 第一阶段可以不接 reasoning stream，而是由 agent 在关键动作前发简短 `trace_note`。

### Step Events

```text
step_started
step_progress
step_completed
step_failed
```

示例：

```json
{
  "step_id": "step-2",
  "title": "接入 auto review 配置",
  "source": "plan",
  "todo_id": "todo-2"
}
```

### Action Events

```text
action_started
action_completed
action_failed
```

通用字段：

```json
{
  "action_id": "action-7",
  "step_id": "step-2",
  "kind": "file_edit",
  "title": "编辑 auto_review.py",
  "status": "completed",
  "summary": "接入 strictness 配置",
  "started_at": 1780390000.1,
  "completed_at": 1780390001.4
}
```

`kind` 建议枚举：

```text
thought
file_read
file_edit
command
verification
tool
approval
todo
subagent
browser
error
```

### File Events

```text
file_read
file_edited
file_created
file_deleted
file_reverted
```

示例：

```json
{
  "path": "mini_agent_lab/auto_review.py",
  "line_range": "L1-末尾",
  "step_id": "step-1"
}
```

```json
{
  "path": "mini_agent_lab/auto_review.py",
  "additions": 141,
  "deletions": 16,
  "diff_preview": "...",
  "step_id": "step-2"
}
```

### Command / Verification Events

```text
command_started
command_output
command_finished
verification_started
verification_completed
verification_failed
```

当前已有部分 command/job events，可归一为 trace action。

示例：

```json
{
  "command": "python3 scripts/test_auto_review.py",
  "status": "passed",
  "exit_code": 0,
  "duration_ms": 840,
  "summary": "auto review tests passed"
}
```

### Assistant Streaming Events

```text
assistant_message_started
assistant_delta
assistant_message_completed
assistant_message_failed
```

示例：

```json
{
  "message_id": "assistant-12",
  "delta": "已完成 auto review"
}
```

完成事件：

```json
{
  "message_id": "assistant-12",
  "content": "已完成 auto review 配置接入...",
  "tool_calls": []
}
```

### Tool Call Streaming Events

如果 provider 支持 tool call delta，后续增加：

```text
tool_call_started
tool_call_delta
tool_call_completed
```

第一阶段可以先不做 tool call argument streaming，只在 tool call 完整出现后发 `tool_dispatch` / `action_started`。

## Backend Architecture

### 1. Keep Existing Event Store

保留：

- `.runs/<session>.events.jsonl`
- `.runs/<session>.summary.json`
- `GET /events`

原因：

- 可以恢复历史会话。
- 可以支持 SSE 断线重连。
- 可以保留产品验收和 replay 能力。

### 2. Add Trace Event Layer

新增：

```text
mini_agent_lab/trace.py
```

核心对象：

```python
class TraceEmitter:
    def thought_delta(...)
    def step_started(...)
    def step_completed(...)
    def action_started(...)
    def action_completed(...)
    def file_read(...)
    def file_edited(...)
    def verification_completed(...)
    def assistant_delta(...)
```

它不替代 `RunRecorder`，而是对 `RunRecorder.emit(Event(...))` 做产品级封装。

建议结构：

```text
Agent
  -> TraceEmitter
      -> RunRecorder
          -> events.jsonl
          -> optional downstream SSE broker
```

### 3. Add Event Broker for Live Streaming

新增：

```text
mcode-ui/backend/event_broker.py
```

功能：

- 按 `project_id/session_id` 维护 subscriber。
- `RunRecorder` 写入事件后同步推送给 broker。
- SSE endpoint 订阅 broker。
- 支持从 `last_seq` 补发历史事件。

接口：

```text
GET /api/projects/{project_id}/sessions/{session_id}/stream?last_seq=123
```

返回 `text/event-stream`：

```text
event: run_event
id: 124
data: {"seq":124,"kind":"assistant_delta","data":{"delta":"..."}}
```

### 4. Polling Fallback

保留当前前端轮询：

- SSE 可用时使用 SSE。
- SSE 断开时自动回退到 `/events` 轮询。
- SSE 重连带上最后 seq。

### 5. Provider Streaming

新增 provider API，而不是破坏现有 `complete(...)`：

```python
def stream_complete(
    self,
    messages: list[Message],
    tools: Optional[list[dict]] = None,
    max_tokens: Optional[int] = None,
) -> Iterator[ProviderStreamEvent]:
```

事件类型：

```text
content_delta
reasoning_delta
tool_call_delta
message_completed
error
```

保留 `complete(...)`：

- compact、settings API test、auto review 等低风险调用继续使用非流式。
- agent 主对话使用 stream。

### 6. Agent Loop Streaming

agent loop 要支持两种路径：

```text
non-stream complete path
stream complete path
```

第一阶段推荐只对“无 tool call 的最终 assistant message”做 streaming。

第二阶段再支持：

- reasoning summary streaming。
- tool call delta aggregation。
- streaming 中断恢复。

关键要求：

- session history 里最终仍只保存完整 assistant message。
- events 里可以有 delta，但 `assistant_message_completed` 必须包含完整内容。
- 如果 streaming 中断，需要发 `assistant_message_failed` 和 `turn_failed`。

## Frontend Architecture

### 1. Event Store Normalization

新增或改造：

```text
mcode-ui/frontend/src/state/runTrace.ts
```

职责：

- 根据 events 构造 `RunTrace`。
- 合并 `assistant_delta`。
- 把 step/action 状态归一。
- 保证重复事件、断线重放不会造成重复 UI。

核心类型：

```ts
type RunTrace = {
  turnId: string;
  status: "running" | "completed" | "failed" | "cancelled" | "awaiting_approval";
  thought?: ThoughtSummary;
  steps: TraceStep[];
  assistantDraft?: StreamingMessage;
  finalAnswer?: string;
};
```

### 2. SSE Client

新增：

```text
mcode-ui/frontend/src/api/stream.ts
```

职责：

- 打开 EventSource。
- 记录 last seq。
- 自动重连。
- 断开时通知 App 回退轮询。

### 3. UI Components

新增：

```text
components/AgentRunBlock.tsx
components/ThoughtSummaryPanel.tsx
components/TraceStepList.tsx
components/TraceActionItem.tsx
components/StreamingAssistantMessage.tsx
```

`ChatWorkspace` 改造：

- 不再直接把所有 event 转为普通 item。
- 对 `turn_started -> turn_completed` 的事件组生成 `AgentRunBlock`。
- 历史消息仍兼容旧事件。

### 4. UX Details

- running assistant message 使用光标/淡入，不改变输入框布局。
- 正在执行的 step 自动展开。
- 已完成 step 默认收起，只显示摘要。
- 失败 step 自动展开并显示错误。
- 工具输出超过阈值默认折叠。
- 用户滚动离开底部时不要强制 autoscroll。
- 新 delta 到达且用户仍在底部时自动跟随。

## Implementation Phases

### Phase 1: Trace Event Foundation

目标：不做 token streaming，先把 agent 过程规范化。

Backend:

- 新增 `TraceEmitter`。
- 在 agent loop 中发出：
  - `step_started`
  - `action_started`
  - `action_completed`
  - `file_read`
  - `file_edited`
  - `verification_completed`
- 把常见工具映射成 action：
  - read/list/grep/glob -> file or search action
  - python/bash -> command/verification action
  - todo_write -> todo action
  - complete_step -> step completed evidence
- 保留现有事件。

Frontend:

- 新增 `runTrace.ts`。
- 新增 `AgentRunBlock` 初版。
- 在 UI 中展示结构化步骤和 action。

Acceptance:

- 一次包含读文件、编辑、测试的 turn 能显示清晰步骤。
- 旧事件仍能显示。
- 产品验收不退化。

### Phase 2: SSE Transport

目标：事件实时推送，替代主路径轮询。

Backend:

- 新增 `EventBroker`。
- `RunRecorder` 支持 downstream broker。
- 新增 `/stream` SSE endpoint。
- 支持 `last_seq` 补发。

Frontend:

- 新增 `EventSource` client。
- App 优先使用 SSE。
- SSE 失败时 fallback 轮询。
- 增加连接状态 debug。

Acceptance:

- 工具事件无需等待 500ms 轮询即可出现。
- 断开 SSE 后能重连。
- 重连不重复显示事件。
- 手动关闭 SSE 后轮询仍可工作。

### Phase 3: Assistant Text Streaming

目标：最终回答可以逐段显示。

Provider:

- `DeepSeekProvider.stream_complete(...)`。
- 解析 content delta。
- 聚合最终 content。

Agent:

- 支持 stream path。
- 发：
  - `assistant_message_started`
  - `assistant_delta`
  - `assistant_message_completed`
- session history 保存完整 assistant message。

Frontend:

- `StreamingAssistantMessage` 拼接 delta。
- completed 后固化。
- 支持 markdown 渐进渲染。

Acceptance:

- 普通问答可以逐段显示。
- turn 完成后刷新页面，最终消息仍完整。
- delta 重放不会重复拼接。

### Phase 4: Thought Summary Streaming

目标：展示 sanitized “深度思考摘要”，不展示原始 chain-of-thought。

Backend:

- 对 reasoning delta 做过滤/摘要。
- 或在工具动作前后由 agent 生成 `thought_summary_delta`。
- 增加红线：不把完整 reasoning_content 直接写入 UI 事件。

Frontend:

- `ThoughtSummaryPanel` 支持 delta。
- 默认折叠历史 thought，展开当前 running thought。

Acceptance:

- UI 展示类似“正在检查配置入口”的摘要。
- 不出现大段原始推理。
- 设置中可关闭 thought summary。

### Phase 5: Tool Call Delta and Advanced Recovery

目标：更完整支持 streaming tool call。

Backend:

- 解析 tool call argument delta。
- 聚合工具调用。
- 工具调用完成后再执行。
- streaming 失败时保留 partial event 和错误状态。

Frontend:

- tool call 处于 constructing 状态时显示“正在准备工具调用”。
- 完成后转为 action/tool item。

Acceptance:

- tool call argument streaming 不破坏工具执行。
- 异常中断不产生半个不可恢复工具调用。

## Data Compatibility

必须兼容旧事件：

- 老 `.events.jsonl` 没有 trace events 时，继续走当前 `itemsFromMessagesAndEvents`。
- 新事件存在时，优先用 `runTrace.ts`。
- `assistant_message` 继续保留，不能只依赖 delta。
- 产品验收和 replay 脚本需要支持新旧格式。

## Testing Plan

### Backend Unit Tests

- `TraceEmitter` 生成合法事件。
- step/action id 稳定且唯一。
- `complete_step` 能映射到 `step_completed` evidence。
- file read/edit 工具能映射为 file events。
- SSE broker 能：
  - 订阅 session。
  - 推送事件。
  - 按 last_seq 补发。
  - 多 subscriber 不互相阻塞。

### Provider Tests

- 非流式 `complete(...)` 不退化。
- streaming content delta 能聚合为完整 content。
- bad chunk / invalid JSON 能发明确 error。
- retry 策略不破坏已有非流式调用。

### Agent Tests

- 普通 turn 发出 `assistant_delta` 和 completed。
- tool turn 在工具前后发 trace action。
- plan-approved execution 能把 todo / complete_step 映射到 step 状态。
- cancel 时 running step 变成 cancelled。
- provider failure 时 trace 进入 failed。

### Frontend Tests

- `runTrace.ts` 能从 events 构造 run block。
- delta 事件按 message id 拼接。
- repeated SSE replay 不重复拼接。
- failed step 自动展开。
- old events fallback 仍能渲染。
- autoscroll 只在用户位于底部时触发。

### Browser QA

使用 Codex in-app Browser：

- 打开 `http://127.0.0.1:4177/`。
- 检查 console 无 error/warn。
- 发送普通问答，确认 assistant streaming draft 出现。
- 发送需要读文件和运行测试的任务，确认 trace step/action 正常。
- 断开/重连 SSE，确认事件不重复。
- 刷新页面，确认最终 transcript 和 trace 可恢复。
- 视口测试：
  - `1440x900`
  - `1180x820`
  - `900x820`
  - `760x820`
- 确认 trace 不横向溢出，长路径、长命令、长输出都能折叠或换行。

## Acceptance Commands

```bash
python3 tests/test_agent_run_events.py
python3 tests/test_todo_plan.py
python3 tests/test_ui_backend.py
python3 scripts/product_acceptance.py
```

Frontend:

```bash
cd mcode-ui/frontend
npm run test -- --run
npm run build
```

macOS:

```bash
./mcode-ui/macos/build_app.sh
codesign --verify --deep --strict mcode-ui/dist/Mcode.app
```

Runtime:

```bash
curl http://127.0.0.1:18080/api/health
```

Expected:

```json
{"ok": true}
```

## Risks

### Raw Reasoning Exposure

风险：

- 直接展示 `reasoning_content` 可能暴露不适合展示的原始 chain-of-thought。

处理：

- UI 只展示 sanitized thought summary。
- 原始 reasoning 不进入普通 UI events。
- debug 模式也默认不显示完整 reasoning。

### Event Duplication

风险：

- SSE 重连和轮询 fallback 可能重复事件。

处理：

- 所有事件使用稳定 `seq`。
- 前端按 `seq` 去重。
- delta 按 `message_id + delta_index` 或 `seq` 去重。

### Markdown Streaming Flicker

风险：

- markdown 未闭合时反复重排。

处理：

- streaming draft 使用轻量 markdown 渲染。
- code fence 未闭合时保持 plain/pre fallback。
- completed 后再做完整 markdown render。

### Tool Call Streaming Complexity

风险：

- tool call arguments 可能分片到达，提前执行会出错。

处理：

- Phase 3 先只 stream content。
- Phase 5 再做 tool call delta。
- 工具必须等 `tool_call_completed` 后执行。

### Increased Backend State

风险：

- SSE broker 需要维护 subscriber，可能泄漏连接。

处理：

- 使用 finally 清理 subscriber。
- 设置 heartbeat。
- 设置 idle timeout。
- 保留轮询 fallback。

## Recommended First PR Scope

第一批不要做 provider streaming，先做 trace foundation：

- 新增 `TraceEmitter`。
- 映射 read/edit/command/todo/complete_step 到 trace events。
- 前端新增 `AgentRunBlock` 和 `TraceStepList`。
- 继续使用现有轮询。

这样风险最低，但 UI 专业感提升最大。

第二批再加 SSE。

第三批再加 assistant_delta。

## Definition of Done

- 用户能看到清晰的 agent 工作步骤，而不是散乱工具日志。
- 每个 turn 都有稳定的 run block。
- 文件读取、编辑、命令、验证有统一视觉表达。
- 最终回答可以流式显示。
- 页面刷新后 trace 和最终回答保持一致。
- SSE 断线不会丢事件或重复展示。
- 不暴露原始 chain-of-thought。
- `product_acceptance.py`、frontend tests、macOS build 全部通过。
