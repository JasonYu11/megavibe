# Mcode Timeline

这个文档记录我们从零搭建一个学习版 coding agent 的过程。目标不是复制 Reasonix 的全部功能，而是逐步理解 agent runtime 的核心框架和工程取舍。

## 0. 项目初始化

- 创建 `mini-agent-lab/`
- 添加 `README.md`
- 添加 `.env.example` / `.env`
- 配置 DeepSeek：
  - `DEEPSEEK_BASE_URL=https://api.deepseek.com`
  - `DEEPSEEK_MODEL=deepseek-v4-flash`
  - `DEEPSEEK_API_KEY` 由用户填写

学习点：

- API key 不进代码
- 配置应独立于 agent 逻辑

## 1. Provider 与 Session

新增：

- `mini_agent_lab/config.py`
- `mini_agent_lab/provider/types.py`
- `mini_agent_lab/provider/deepseek.py`
- `mini_agent_lab/agent/session.py`
- `scripts/chat_once.py`
- `scripts/chat.py`

能力：

- 从 `.env` 读取配置
- 调 DeepSeek 完成单轮对话
- 用 `Session` 保存多轮上下文

学习点：

- `Session` 是上下文存储
- Provider 是模型调用抽象
- 多轮对话靠把历史 messages 再发给模型

## 2. Tool 接口与 Registry

新增：

- `mini_agent_lab/tool/base.py`
- `mini_agent_lab/tool/registry.py`
- `mini_agent_lab/tool/builtin.py`
- `scripts/tool_demo.py`

第一批工具：

- `echo`
- `read_file`
- `write_file`
- `bash`

工具调用 JSON 规范：

```json
{
  "name": "read_file",
  "arguments": {
    "path": "README.md",
    "offset": 0,
    "limit": 20
  }
}
```

学习点：

- 所有工具统一实现 `Tool`
- `Registry` 负责注册、查找、导出 schemas
- 模型未来只需要返回 tool name + arguments

## 3. Agent Loop 接入工具

新增：

- `mini_agent_lab/agent/agent.py`
- `scripts/agent_chat.py`

修改：

- Provider 支持发送 tool schemas
- Provider 解析模型返回的 `tool_calls`
- `Message` 支持 assistant tool calls 和 tool result

能力：

- 模型主动调用 `read_file`
- Agent 执行工具
- 工具结果回填 Session
- 模型基于工具结果继续回答

核心循环：

```text
user input
-> session.add(user)
-> provider.complete(messages, tools)
-> assistant tool_calls
-> registry.get(tool)
-> tool.execute(args)
-> session.add(tool result)
-> provider.complete(...)
-> final answer
```

学习点：

- 模型决定调用哪个工具
- 程序负责校验、执行和回填结果
- agent 能力来自模型和工具之间的循环

## 4. 扩展基础工具

新增工具：

- `ls`
- `glob`
- `grep`
- `edit_file`

能力：

- 列目录
- 按 glob 找文件
- 搜索文本
- 精确替换文件内容

学习点：

- `read_file` 需要 `offset/limit` 控制上下文
- `edit_file` 要求 `old_string` 唯一，避免误改
- 写工具不能随便并行

## 5. SafetyGate

新增：

- `mini_agent_lab/safety.py`
- `scripts/safety_demo.py`

初始策略：

- 低风险只读工具：allow
- 写工具和 bash：ask
- 极高风险 bash：deny

后来升级为配置驱动：

- `mcode-policy.json`
- `mcode-policy.example.json`

默认策略：

- 只读工具：allow
- `write_file` / `edit_file` 写 workspace 内：allow
- 写 workspace 外：ask
- 保护路径：deny
- `bash` 默认：ask
- 极高风险 bash：deny

学习点：

- 权限控制放在工具执行前
- 模型可以提出动作，程序决定是否执行
- 策略应该可配置，不应全部硬编码

## 6. 后台任务机制

新增：

- `mini_agent_lab/jobs.py`
- `scripts/background_demo.py`

新增工具：

- `bash_output`
- `wait`
- `kill_shell`

增强：

- `bash` 支持 `run_in_background=true`

能力：

- 长命令不阻塞 agent loop
- 后台任务返回 `job_id`
- 可读取新输出
- 可等待完成
- 可终止任务

学习点：

- 下载、服务、训练、watcher 这类任务不能用同步 bash 卡住主循环
- 长任务应变成可观察、可等待、可终止的 job

## 7. 组合工具测试

新增：

- `scripts/integration_demo.py`

覆盖：

- `ls -> glob -> grep -> read_file`
- `write_file -> read_file -> edit_file -> read_file`
- `bash(run_in_background) -> bash_output -> wait`
- SafetyGate 决策

真实 LLM 测试：

- 模型组合使用 `ls + grep + read_file`
- 模型组合使用 `write_file + read_file`
- 模型组合使用后台 `bash + wait`

学习点：

- 工具单测和真实 LLM 测试都需要
- LLM 会按自己的计划组合工具
- agent loop 必须能处理多轮 tool calls

## 8. Checkpoint 与 Diff Preview

新增：

- `mini_agent_lab/change.py`
- `mini_agent_lab/checkpoint.py`
- `scripts/checkpoint_list.py`
- `scripts/checkpoint_restore.py`

增强：

- `write_file.preview()`
- `edit_file.preview()`
- Agent 执行写工具前打印 unified diff
- Agent 执行写工具前保存 checkpoint

能力：

- 修改前看到 diff
- 修改前保存旧内容
- 可按 checkpoint id 回滚

执行链：

```text
tool call
-> SafetyGate
-> preview diff
-> checkpoint save
-> execute write/edit
-> tool result includes checkpoint id
```

学习点：

- Preview 解释“将要改什么”
- Checkpoint 保存“原来是什么”
- rollback 对 coding agent 很重要

## 9. Tool Output Truncation

新增：

- `scripts/truncation_demo.py`

增强：

- Agent 对所有工具结果统一截断
- 默认上限：`12000` 字符
- 保留头尾，中间插入截断提示

学习点：

- 工具输出不能无限制塞给模型
- `grep`、`bash`、大文件读取都可能撑爆上下文
- 截断应该在 agent 层统一处理

## 10. Session 保存与 Resume

新增：

- `mini_agent_lab/session_store.py`
- `scripts/session_list.py`

增强：

- `Message.to_dict()` / `Message.from_dict()`
- `ToolCall.to_dict()` / `ToolCall.from_dict()`
- `Session.has_content()`
- `scripts/agent_chat.py` 支持：
  - `--session <id>`
  - `--resume <id>`
  - `--list-sessions`

能力：

- 每轮对话保存到 `.sessions/<session-id>.jsonl`
- 保存 system/user/assistant/tool 消息
- 保存 assistant 的 tool_calls
- 保存 tool result 的 `tool_call_id` 和工具名
- 新进程可恢复旧 session 继续对话

验证：

```text
agent_chat.py --session resume-demo "请读取 README.md..."
-> 保存 .sessions/resume-demo.jsonl

agent_chat.py --resume resume-demo "刚才你读过哪个文件？"
-> 模型基于历史回答 README.md，不需要重新读取
```

学习点：

- agent 的上下文不应只活在内存里
- tool_calls 和 tool results 必须成对保存
- resume 是长任务、审计、继续工作的基础

## 11. Context Compact

新增：

- `mcode-config.json`
- `mcode-config.example.json`
- `mini_agent_lab/app_config.py`
- `mini_agent_lab/compact.py`
- `scripts/compact_demo.py`

配置：

```json
{
  "context": {
    "context_window_tokens": 200000,
    "compact_ratio": 0.75,
    "chars_per_token": 3,
    "recent_keep": 12,
    "auto_compact": true,
    "summary_mode": "llm",
    "target_summary_ratio": 0.1,
    "min_summary_tokens": 10000,
    "max_summary_tokens": 20000
  }
}
```

默认触发：

```text
200000 tokens * 0.75 * 3 chars/token = 450000 chars
```

能力：

- 估算 session 字符数
- 超过阈值自动 compact
- 支持 `/context` 查看当前上下文大小
- 支持 `/compact` 手动压缩
- 支持 `scripts/compact_demo.py <session-id> --force`
- 保留 system prompt 和最近 N 条消息
- 将中间旧消息归档到 `.archives/`
- 默认调用 DeepSeek 生成结构化语义摘要替代旧消息
- 仅当 `summary_mode` 显式设为 `"local"` 时，使用本地规则摘要

验证：

```text
resume-demo: 7 messages -> 4 messages
archive: .archives/20260601-194351-846.jsonl
compact 后 --resume 仍能回答：之前读过 README.md

llm-compact-structured2: 8 messages -> 3 messages
archive: .archives/20260601-195101-352.jsonl
LLM summary 按固定标题输出 Goal / Decisions / Files Read / Files Modified / Commands & Results / Errors & Fixes / Pending
compact 后 --resume 能基于摘要回答 README.md 与 TIMELINE.md 前 30 行内容
```

学习点：

- compact 是 agent runtime 的内部内存管理，不是普通业务工具
- 长会话不能无限增长
- 最近上下文要原样保留，旧上下文要摘要化并归档
- 默认应使用 LLM semantic summary；本地摘要只适合调试或离线模式
- LLM compact 要给 reasoning 模型足够输出预算，否则可能出现 visible answer 为空
- 当前摘要预算设置为 10000-20000 tokens，避免压缩过度造成任务记忆变差

## 12. Event Stream

新增：

- `mini_agent_lab/events.py`

增强：

- `Agent` 接收 `EventSink`
- CLI 默认使用 `PrintSink`
- `Approver` 通过事件输出 safety ask
- Agent 不再把工具、preview、checkpoint、compact 状态散落为直接 `print`

事件类型：

- `turn_started`
- `tool_dispatch`
- `tool_result`
- `safety_ask`
- `safety_deny`
- `preview`
- `checkpoint_saved`
- `compact_check`
- `compact_skipped`
- `compact_started`
- `compact_done`
- `compact_failed`
- `notice`

能力：

- CLI 仍然能打印人类可读状态
- 后续 UI 可以换成 WebSocket/React sink
- agent core 和展示层开始解耦

验证：

```text
agent 调用 read_file 时，PrintSink 渲染：
[notice] step 1: model requested 1 tool call(s)
[tool] read_file(...)
<tool result>
```

学习点：

- Agent runtime 不应该直接控制 UI
- Agent 应该发结构化事件
- CLI/TUI/Web UI 各自决定如何展示事件
- 自动上下文压缩也应该有状态流：检查、跳过、开始、完成、失败

## 13. Project Memory

参考 Reasonix 的 `REASONIX.md` 机制，新增：

- `MEMORY.md`
- `mini_agent_lab/memory.py`

增强：

- `scripts/agent_chat.py` 创建新 session 时加载项目记忆
- 将 memory markdown 合成到 system prompt
- 支持简单 `@path` 导入
- 跳过 workspace 外、隐藏文件、敏感文件和循环导入
- `MEMORY.local.md` 预留给本机私有记忆，并加入 `.gitignore`

能力：

- 新会话天然知道项目目标、工程约定、当前架构和当前重点
- 长期稳定信息不需要每轮用户重复输入
- resume 旧 session 时保持原 system prompt，不中途改变历史上下文

学习点：

- Memory 本质上是“进入上下文的项目级说明”
- 它不是工具调用，而是 prompt 组成的一部分
- 适合放长期稳定事实，不适合放 API key、临时输出、大段日志
- 简化版先做项目级 memory，后面再考虑全局用户 memory 和 remember 工具

## 14. Durable Memory Store

参考 Reasonix 的 auto-memory store，新增：

- `AutoMemoryStore`
- `SavedMemory`
- `remember` 工具
- `list_memory` 工具

存储结构：

```text
.memory/
  MEMORY.md
  facts/
    prefers-chinese.md
    project-agent-runtime.md
```

设计：

- `MEMORY.md` 是索引，启动时进入 system prompt
- 每条事实一个 markdown 文件，带 frontmatter
- 同名记忆覆盖旧文件，鼓励更新而不是重复追加
- 单条 description 限制 240 字符，body 限制 2000 字符
- `remember` 默认 allow，但会拒绝 secret-like 内容
- `list_memory` 是只读工具
- `.memory/` 加入 `.gitignore`

学习点：

- 长期记忆不能把全部正文都塞进 prompt
- prompt 里放索引，正文按需读取
- durable memory 是工具写入的事实库，不是聊天记录仓库
- 记忆分类先保持小而稳定：user / feedback / project / reference

## 15. Todo Tool

参考 Reasonix 的 `todo_write`，新增：

- `mini_agent_lab/tool/todo.py`
- `todo_write` 工具
- `todo_updated` 事件

设计：

- 不做 TodoStore，不单独落盘
- 模型每次调用 `todo_write` 都发送完整任务列表
- 新列表替换旧列表
- 工具只校验参数并返回统计
- Agent 将完整 todos 转成 `todo_updated` 事件
- CLI 暂时渲染简洁任务状态，未来 UI 可以渲染固定 TodoPanel
- system prompt 要求模型在复杂任务中主动创建 todo，并在每完成一步后更新完整列表
- 触发条件进一步收紧：预计会读多个文件、调用多个工具或修改代码时，第一个工具调用应是 `todo_write`
- 工具层硬校验：最多 20 条、最多一个 `in_progress`、`level=1` 必须跟在 `level=0` 后
- `todo_updated` 事件增加 `current`、`done`、`progress_text`
- 新增 `scripts/todo_demo.py` 覆盖正常和异常路径

字段：

- `content`: 任务描述
- `status`: `pending` / `in_progress` / `completed`
- `activeForm`: 进行中显示文案
- `level`: `0` 阶段 / `1` 子步骤

学习点：

- Todo 是“当前工作状态”，不是长期记忆
- 它天然存在于 session history 的 tool call 参数里
- UI 应该显示最近一次 `todo_write`，全部 completed 后可隐藏
- 主动使用 todo 依赖模型行为规范和工具描述共同约束

## 16. Plan Mode

参考 Reasonix 的 plan mode，新增：

- `mini_agent_lab/plan.py`
- `scripts/plan_demo.py`
- `scripts/agent_chat.py --plan`
- 交互命令 `/plan <task>`

流程：

```text
/plan <task>
-> prepend PLAN_MODE_MARKER
-> Agent.set_plan_mode(true)
-> 模型只能使用只读工具探索
-> 模型输出 markdown plan 并停止
-> CLI 询问 Approve this plan?
-> 批准后 parse markdown list
-> emit todo_updated 作为 seeded todo
-> Agent.set_plan_mode(false)
-> 发送 PLAN_APPROVED_MESSAGE 执行计划
```

设计：

- Plan mode 是运行模式，不是普通工具
- plan mode 不修改 system prompt，而是把 marker 放进当前 user message
- Agent 在 plan mode 下硬阻断非只读工具
- markdown plan 会解析成 todo 结构：顶层列表是 `level=0`，缩进列表是 `level=1`
- 自动 seed todo 是 UI 状态，不额外落盘
- 真实测试中模型曾同时设置 phase/sub-step 为 `in_progress`；工具层拒绝并促使模型修正，因此批准提示和工具描述补充了“总共只能一个 in_progress”

学习点：

- 单靠 prompt 让模型主动用 todo 并不总稳定
- plan mode 用程序保证“先规划、再批准、再执行”
- todo 是执行阶段的进度仪表，plan mode 是执行前的安全闸门

## 17. Run Events / Preview State

为了给后续 UI 预览做准备，新增运行事件落盘：

- `mini_agent_lab/run_recorder.py`
- `tests/test_run_recorder.py`
- `mcode-config.json` 增加 `paths.run_dir`

输出文件：

```text
.runs/<session-id>.events.jsonl
.runs/<session-id>.summary.json
```

事件流保存完整过程，适合回放：

- `turn_started`
- `assistant_message`
- `tool_dispatch`
- `tool_result`
- `command_started` / `command_output` / `command_finished`
- `job_started` / `job_output` / `job_finished`
- `todo_updated`
- `preview`
- `checkpoint_saved`
- `safety_ask` / `safety_deny`
- `compact_started` / `compact_done` / `compact_failed`
- `turn_completed` / `turn_paused`

summary 保存当前状态，适合 UI 轮询：

- `status`: `created` / `running` / `tool_running` / `command_running` / `job_running` / `waiting_approval` / `compacting` / `completed` / `paused`
- `current_tool`
- `current_command`
- `jobs`
- `todo`
- `file_changes`
- `last_tool_result`
- `last_error`
- `final_answer`
- `recent_events`

学习点：

- session 是模型上下文记录，run events 是运行过程记录
- JSONL 适合追加和回放，summary JSON 适合前端快速预览
- agent 核心循环不需要知道 UI，只要发事件即可

## 18. Bash / Job Events

为了让终端过程也能预览，bash 工具和后台任务新增事件：

- 前台命令：`command_started`、`command_output`、`command_finished`
- 后台任务：`job_started`、`job_output`、`job_finished`

新增/修改：

- `mini_agent_lab/jobs.py`
- `mini_agent_lab/tool/builtin.py`
- `tests/test_bash_events.py`
- `mcode-config.json` 增加 `paths.job_dir`

行为：

```text
bash(command="printf hi")
-> command_started
-> command_output
-> command_finished
-> tool_result

bash(command="long task", run_in_background=true)
-> job_started
-> 返回 job_id
-> job_output 持续追加
-> .jobs/<job_id>.log 持久化输出
-> job_finished
```

学习点：

- 前台命令适合短任务，agent 等它完成后继续
- 后台 job 适合下载、dev server、长测试、训练等连续过程
- UI 不应该只看最终 tool_result，而应该消费 command/job 事件展示实时过程

## 19. Git Safety Baseline

参考 Codex 的工作区保护思路，新增第一阶段 git 感知能力：

- `mini_agent_lab/git_state.py`
- `mini_agent_lab/tool/git_tools.py`
- `tests/test_git_state.py`
- `mcode-config.json` 增加 `paths.gitstate_dir`

核心能力：

```text
Agent.run()
-> capture git baseline
-> save .gitstate/<session-id>.baseline.json
-> emit git_baseline_captured

git_classify_changes()
-> load baseline
-> snapshot current git status
-> classify:
   user_existing
   agent_created
   agent_modified
   overlap
   resolved_baseline_dirty
```

只读工具：

- `git_status`
- `git_diff`
- `git_baseline`
- `git_classify_changes`

设计边界：

- 第一阶段不做 `commit` / `push` / `reset` / `stash` / `clean`
- git baseline 不负责回滚；回滚仍由 checkpoint 负责
- git baseline 负责识别“任务开始前用户已经改了什么”和“任务后新增了什么风险”
- `overlap` 是高价值风险信号：baseline 中已经 dirty 的文件现在仍 dirty，agent 总结时应提醒用户检查

## 20. Git Overlap Write Guard

在写工具真正执行前，新增 baseline dirty 文件保护：

```text
write_file/edit_file
-> preview diff
-> load .gitstate/<session>.baseline.json
-> target path relative to git root
-> if target in baseline dirty:
     emit git_overlap_risk
     ask user approval
-> checkpoint
-> execute write
```

行为：

- baseline clean 文件：直接允许
- baseline dirty 文件：发 `git_overlap_risk`，默认 ask
- 用户拒绝：阻断写入，文件不变
- 非 git repo：不阻断
- baseline 缺失：发 `git_baseline_missing`，不阻断

summary 新增：

- `git.overlap_risks`
- `git.baseline_missing`

学习点：

- 这是 Codex 风格“保护用户已有改动”的核心层
- 它不是禁止修改用户文件，而是在混合改动前让用户明确授权
- checkpoint 保护回滚，git overlap guard 保护意图边界

## 21. Git Command Safety Policy

为了避免模型通过 `bash` 绕过 git 安全边界，新增 git 命令风险分类：

- `mini_agent_lab/safety.py`
- `tests/test_git_command_safety.py`

分类：

```text
allow:
  git status
  git diff
  git log
  git show
  git blame
  git ls-files

ask:
  git add
  git commit
  git push
  git stash
  git reset
  git restore
  git checkout
  git fetch / pull / clone

deny:
  git push --force
  git push -f
  git push --delete
  git push --mirror
  git reset --hard
  git clean -f / -fd / -xfd
  git checkout -- .
  git restore .
```

额外规则：

- `git diff --output ...`、`git show --output=...` 不是自动 allow，因为会写文件
- `git status && ...`、`git diff > patch.txt` 等 shell 组合不会自动 allow
- 全局危险 bash deny pattern 优先级更高，例如 `git status && sudo reboot` 仍然 deny

学习点：

- 不要让 git 写操作只靠自由 bash 表达
- 在专用 `git_commit` 工具出现前，bash 安全层必须先兜住风险
- 普通 `git push` 不是 deny，而是 ask；force/delete/mirror push 才是 deny

## 22. Git Human Approval Explanation

为了让不懂 git 的用户也能做安全决定，git ask 原因从工程师语言升级为普通用户说明：

示例：

```text
git commit:
  会把当前已暂存的本地改动保存成一次提交。
  不会上传到远程仓库，但会改变本地项目历史。
  如果你不确定，建议拒绝。

git push:
  会把本地提交上传到远程仓库，别人可能会看到这些改动。
  如果你不确定，建议拒绝。

git stash:
  会把当前未提交改动临时收起来，让工作区变干净。
  改动通常还能找回，但初学者容易找不到。
  如果你不确定，建议拒绝。
```

测试新增：

- ask 类 git 命令必须包含具体影响说明
- ask 提示必须包含“不确定”用户指引
- `git diff --output ...` 说明它可能写文件

学习点：

- 安全不只是 deny/allow，还包括让用户理解自己在批准什么
- 对普通用户来说，“repository state”不是有效提示
- 默认建议应该偏保守：不确定就拒绝

## 23. Final Git Change Summary

为了让 git baseline 形成完整闭环，Agent 在每轮结束前自动分类当前 git 变化：

```text
Agent.run start
-> git_baseline_captured

writer tools
-> git_overlap_risk when needed

Agent.run completion or pause
-> git_changes_classified
```

summary 中会自动出现：

- `git.current_dirty`
- `git.user_existing`
- `git.agent_created`
- `git.agent_modified`
- `git.overlap`
- `git.resolved_baseline_dirty`

设计：

- 非 git repo 自动跳过，不算失败
- classify 失败会发 `git_classify_failed`，但不影响最终回答
- `.runs/`、`.gitstate/`、`.sessions/`、`.checkpoints/`、`.archives/`、`.jobs/` 等 agent 内部目录不会进入变更总结

学习点：

- git baseline 的价值在于闭环：开始记录、写前保护、结束总结
- agent 内部状态文件不能污染用户项目 diff 总结
- 最终回答和 git summary 解耦，git 检查失败不应让任务失败

## 24. Controlled Git Commit Tool

新增本地提交工具：

- `git_commit`
- `tests/test_git_commit_tool.py`

参数：

```json
{
  "files": ["src/app.py", "tests/test_app.py"],
  "message": "feat: add validation"
}
```

安全边界：

- 只提交显式传入的文件
- 拒绝空 message
- 拒绝空 files
- 拒绝 `.` / `./`
- 拒绝 repo 外路径
- 拒绝 `.runs/`、`.gitstate/`、`.sessions/` 等 agent 内部文件
- 不使用 `git add .`
- 使用 `git commit --only -m <message> -- <files>`，避免把其他已暂存文件混进提交
- `git_commit` 默认 ask，提示说明“不会上传远程，但会改变本地项目历史”

事件：

- `git_commit_started`
- `git_commit_done`
- `git_commit_failed`

学习点：

- 让 agent 能提交，不等于让模型自由执行 bash git commit
- 专用工具的价值在于把危险自由度收窄
- 本地 commit 是可控写操作；远程 push 仍然应该更谨慎

## 当前架构

```text
scripts/agent_chat.py
  -> Config
  -> DeepSeekProvider
  -> Session
  -> ToolRegistry
  -> SafetyGate
  -> CheckpointStore
  -> SessionStore
  -> AppConfig / ContextConfig
  -> RunRecorder / EventSink / PrintSink
  -> GitState / git baseline
  -> Project Memory
  -> SkillStore / skills index
  -> Plan Mode
  -> Agent.run()
      -> provider.complete(messages, tools)
      -> save .gitstate/<session-id>.baseline.json
      -> emit git_baseline_captured
      -> emit assistant_message
      -> model tool_calls
      -> emit tool_dispatch
      -> safety check
      -> preview/checkpoint
      -> tool.execute
      -> emit tool_result
      -> truncate result
      -> session.add(tool result)
      -> maybe compact
      -> provider.complete(...)
      -> save .sessions/<session-id>.jsonl
      -> append .runs/<session-id>.events.jsonl
      -> update .runs/<session-id>.summary.json
```

## 31. Skills 完整接入

参考 Reasonix 的 skill 设计，新增稳定版 skill 能力：

- `mini_agent_lab/skill.py`
- `mini_agent_lab/tool/skill_tools.py`
- `tests/test_skills.py`

核心思想：

```text
system prompt
  -> 只注入 Skills index: name + description + run_as

model needs a playbook
  -> run_skill(name, arguments)
  -> load full skill body on demand
```

发现路径优先级：

```text
project:
  .mcode/skills
  .reasonix/skills
  .agents/skills
  .agent/skills
  .claude/skills

custom:
  mcode-config.json paths.skill_custom_dirs

global:
  ~/.mcode/skills
  ~/.reasonix/skills
  ~/.agents/skills
  ~/.agent/skills
  ~/.claude/skills
```

支持两种布局：

```text
.mcode/skills/name.md
.mcode/skills/name/SKILL.md
```

目录布局还支持：

```text
.mcode/skills/name/references/*.md
```

Skill frontmatter：

```yaml
---
name: review
description: Review current changes
runAs: subagent
allowed-tools: [read_file, grep, git_diff]
model: optional-model
---
```

新增工具：

- `list_skills`
- `read_skill`
- `run_skill`
- `install_skill`

执行模式：

- `inline`: playbook 作为 `<skill-pin>` 工具结果返回父 Agent，由父 Agent 继续执行
- `subagent`: 创建隔离子 Agent，使用 skill body 作为子 Agent system prompt，只返回最终答案

安全边界：

- `install_skill` 拒绝覆盖已有 skill
- 无效 skill 名称跳过或拒绝
- subagent 默认移除 `run_skill` / `install_skill` / `list_skills` / `read_skill` / `todo_write` 等 meta 工具，避免递归委派
- `allowed-tools` 会进一步限制 subagent 可用工具

学习点：

- skill 不是普通长期记忆，而是可调用的工作流
- skill 正文不应该全部塞进 system prompt，否则 prompt 会快速膨胀
- 索引进 prompt，正文按需加载，是稳定扩展 skill 数量的关键
- inline skill 适合“让主 Agent 按说明做事”
- subagent skill 适合“把大范围探索/审查隔离出去，只拿最终结论”

## 后续路线

建议下一步：

1. 把审批事件结构化为 risk_kind / explanation / recommendation
2. 为 `git_commit` 增加提交前 summary card：将提交/不会提交/风险文件
3. stdout/stderr 分流、ANSI 清理和命令输出折叠
4. Subagent resume 策略：允许基于持久化 child session 明确继续一个 interrupted 子任务

## 2026-06-01 - Subagent / task tool 泛化

本轮把之前写在 `scripts/agent_chat.py` 里的 skill subagent 临时闭包，抽成正式运行时：

- 新增 `mini_agent_lab/subagent.py`
  - `run_subagent(...)`：创建独立 `Session` 和子 `Agent`
  - `filter_registry(...)`：从父 registry 复制工具，并移除 meta 工具
  - `NestedSink`：把子 Agent 的工具事件挂回父工具调用
  - `effective_subagent_max_steps(...)`：默认半数 step，显式值不超过父上限
- 新增 `task` 工具
  - 参数：`prompt`、`description`、`tools`、`max_steps`、`run_in_background`
  - 当前支持前台执行；后台队列保留 schema，后续单独做
  - 返回 JSON：包含子 Agent 最终答案
- `run_skill` 的 subagent 模式复用同一套 `run_subagent(...)`
- `Agent` 的 `tool_dispatch` / `tool_result` 事件新增 `id`
- 运行事件新增：
  - `subagent_started`
  - `subagent_completed`
  - `subagent_failed`
  - 子工具事件带 `subagent_id` 和 `parent_tool_call_id`
- `RunRecorder` 的 summary 新增 `subagents`
- 子 Agent 的 git baseline / classification 存入 `summary.subagents[*].git`，不会覆盖父 Agent 的 git 摘要
- `SafetyGate` 对 `task` / `run_skill` 本身 allow，真正风险在子 Agent 内部工具调用时继续检查

安全边界：

- 子 Agent 默认排除 `task`、`run_skill`、`install_skill`、`list_skills`、`read_skill`、`todo_write`、`git_commit`
- `allowed-tools` / `tools` 继续作为 allowlist
- plan mode 仍会阻断 `task` / `run_skill`，避免规划阶段间接写入
- 子 Agent 使用独立 git baseline 文件，避免覆盖父 Agent baseline

验收：

- `tests/test_subagent.py`
  - step 默认值和上限
  - 工具过滤
  - nested event 的 `subagent_id` / `parent_tool_call_id`
  - `task` 工具拿到父工具调用 id，并把结果回传父循环
- 回归：
  - `test_skills.py`
  - `test_agent_run_events.py`
  - `test_tool_outcomes.py`
  - `test_run_recorder.py`
  - `test_run_view.py`
  - `test_git_state.py`
  - `test_git_e2e_safety.py`
  - `test_git_commit_tool.py`
  - `test_git_command_safety.py`
  - `test_bash_events.py`
  - `test_todo_plan.py`
  - `PYTHONPYCACHEPREFIX=.pycache python3 -m compileall -q mini_agent_lab scripts tests`

## 2026-06-01 - Subagent 管理完善

本轮补上子 Agent 的管理层，让它从“临时前台委派”升级为“可查询、可落盘、可后台运行”的子任务系统。

新增模块：

- `mini_agent_lab/subagent_manager.py`
  - `SubagentManager.run_task(...)`
  - `status(...)`
  - `output(...)`
  - `wait(...)`
  - `cancel(...)`
- `.subagents/<session>/<subagent-id>/state.json`
  - 子任务状态、描述、父工具调用 id、路径、答案、错误
- `.subagents/<session>/<subagent-id>/events.jsonl`
  - 子 Agent 内部事件流
- `.subagents/<session>/<subagent-id>/session.jsonl`
  - 子 Agent 会话消息

新增/完善工具：

- `task`
  - 支持 `run_in_background: true`
  - 后台模式立即返回 `subagent_id`
- `subagent_status`
- `subagent_output`
- `wait_subagent`
- `cancel_subagent`

断线处理：

- 运行中的子任务状态会持续写入 `state.json`
- 事件会持续写入 `events.jsonl`
- 子 Agent 完成后会写入 `session.jsonl`
- 如果进程退出后重启，仍处于 `running` / `queued` / `cancel_requested` 的记录会标记为 `interrupted`
- 当前版本支持审计和重新发起任务；真正基于 child session 的 `resume_subagent` 作为下一步推进

事件流显示：

- 父 RunRecorder 继续记录全局事件
- 子 Agent 专属事件同时写入自己的 `events.jsonl`
- 子事件带 `subagent_id` 和 `parent_tool_call_id`
- UI 可以显示为：

```text
task(...)
  subagent_started
    tool_dispatch
    tool_result
  subagent_completed
```

验收补充：

- foreground subagent 状态/事件/session 落盘
- background subagent 启动、等待、完成
- stale running 记录自动标记 interrupted
- 默认 registry 包含 subagent 管理工具
