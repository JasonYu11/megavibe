# Mcode Codebase Map

这份文档用于在进入 UI 开发前，固定当前代码库的结构认知。

## 顶层目录

```text
mini-agent-lab/
  mini_agent_lab/       核心 Python 包
  scripts/              CLI、demo、调试入口
  tests/                行为测试与回归测试
  docs/                 架构与事件流文档
  notes/                手动测试记录
  README.md             当前能力总览
  TIMELINE.md           构建过程时间线
  mcode-config.*   本地路径和上下文配置
  mcode-policy.*   工具安全策略配置
```

运行时目录：

```text
.sessions/     对话 session
.runs/         主 Agent 事件流和 summary
.subagents/    子 Agent 状态、事件流、子会话
.jobs/         后台 bash 日志
.gitstate/     git baseline
.checkpoints/  文件写入 checkpoint
.archives/     上下文压缩归档
.memory/       自动长期记忆
```

这些运行时目录不属于源码，默认应被忽略。

## 核心运行链路

```text
scripts/agent_chat.py
  -> load_config / load_app_config
  -> DeepSeekProvider
  -> Session / SessionStore
  -> ToolRegistry(default_registry)
  -> Agent.run()
  -> model response
  -> tool dispatch/result
  -> RunRecorder events + summary
```

核心文件：

- `mini_agent_lab/agent/agent.py`
  Agent 主循环：模型调用、工具执行、plan mode、safety、checkpoint、git baseline、context compact。
- `mini_agent_lab/agent/session.py`
  简单的消息容器。
- `mini_agent_lab/provider/deepseek.py`
  DeepSeek API provider。
- `mini_agent_lab/provider/types.py`
  `Message`、`ToolCall`、`ProviderResponse`。

## 工具系统

```text
mini_agent_lab/tool/base.py       Tool 抽象
mini_agent_lab/tool/registry.py   ToolRegistry
mini_agent_lab/tool/builtin.py    默认工具集合
```

当前工具模块：

- `builtin.py`
  `echo`、`read_file`、`ls`、`glob`、`grep`、`write_file`、`edit_file`、`bash`、后台 bash 管理。
- `git_tools.py`
  `git_status`、`git_diff`、`git_baseline`、`git_classify_changes`、`git_commit`。
- `todo.py`
  `todo_write` 和 todo 校验/事件数据。
- `memory.py`
  `remember`、`list_memory`。
- `skill_tools.py`
  `list_skills`、`read_skill`、`run_skill`、`install_skill`。
- `task.py`
  `task` 子 Agent 委派工具。
- `subagent_tools.py`
  `subagent_status`、`subagent_output`、`wait_subagent`、`cancel_subagent`。

## Safety / Git / Checkpoint

- `mini_agent_lab/safety.py`
  工具调用策略：低风险 allow，外部写入 ask，高危 bash/git deny。
- `mini_agent_lab/git_state.py`
  git snapshot、diff、baseline classify。
- `mini_agent_lab/checkpoint.py`
  文件变更前保存 checkpoint。
- `mini_agent_lab/change.py`
  diff preview 和 change 数据结构。

这部分是 UI 里“审批、风险提示、diff preview、git 状态”的数据来源。

## 事件流与状态快照

- `mini_agent_lab/events.py`
  `Event`、`EventSink`、`PrintSink`。
- `mini_agent_lab/run_recorder.py`
  写入 `.runs/<session>.events.jsonl` 和 `.runs/<session>.summary.json`。
- `mini_agent_lab/run_view.py`
  命令行回放和 summary 渲染。
- `docs/EVENT_STREAM.md`
  UI/debug 的事件契约文档。

UI 第一版主要读取：

```text
.runs/*.summary.json
.runs/*.events.jsonl
.subagents/<session>/*/state.json
.subagents/<session>/*/events.jsonl
.sessions/*.jsonl
```

## Context / Memory / Skill

- `mini_agent_lab/compact.py`
  自动上下文压缩，默认使用 LLM 摘要。
- `mini_agent_lab/memory.py`
  长期记忆索引和事实文件。
- `mini_agent_lab/skill.py`
  skill 发现、安装、渲染、内置 skill。
- `mini_agent_lab/plan.py`
  plan mode 文本转 todo。

这些属于“长期能力层”，UI 可以先只展示状态，后面再做管理页面。

## Subagent

- `mini_agent_lab/subagent.py`
  子 Agent 的纯运行函数：隔离 session、过滤工具、嵌套事件。
- `mini_agent_lab/subagent_manager.py`
  子 Agent 管理层：前台/后台运行、状态落盘、事件落盘、wait/cancel、interrupted 标记。
- `mini_agent_lab/tool/task.py`
  模型可调用的 `task` 工具。
- `mini_agent_lab/tool/subagent_tools.py`
  模型可调用的子任务管理工具。

落盘结构：

```text
.subagents/<session>/<subagent-id>/
  state.json
  events.jsonl
  session.jsonl
```

UI 显示建议：

```text
父 tool: task(...)
  subagent_started
    tool_dispatch
    tool_result
  subagent_completed / failed / interrupted
```

## CLI / Scripts

主入口：

- `scripts/agent_chat.py`
  当前最完整的交互式 Agent CLI。

辅助入口：

- `scripts/run_status.py`
- `scripts/run_replay.py`
- `scripts/session_list.py`
- `scripts/checkpoint_list.py`
- `scripts/checkpoint_restore.py`

Demo：

- `scripts/tool_demo.py`
- `scripts/background_demo.py`
- `scripts/compact_demo.py`
- `scripts/plan_demo.py`
- `scripts/safety_demo.py`
- `scripts/todo_demo.py`
- `scripts/truncation_demo.py`
- `scripts/integration_demo.py`

UI 后端可以先复用这些底层模块，不需要调用 demo 脚本。

## Tests

测试文件按能力分组：

- `test_tool_outcomes.py`
  工具结果结构、错误分类、截断、loop guard。
- `test_agent_run_events.py`
  Agent 事件流基础行为。
- `test_run_recorder.py`
  事件持久化和 summary。
- `test_run_view.py`
  事件回放和状态渲染。
- `test_todo_plan.py`
  todo 和 plan mode。
- `test_bash_events.py`
  前台/后台 bash。
- `test_git_state.py`
  git baseline、分类、写入保护。
- `test_git_e2e_safety.py`
  git safety 端到端。
- `test_git_commit_tool.py`
  `git_commit` 工具。
- `test_git_command_safety.py`
  bash 中 git 命令风险分类。
- `test_skills.py`
  skill 系统。
- `test_subagent.py`
  subagent 运行、后台管理和断线状态。

常用验收命令：

```bash
python3 tests/test_subagent.py
python3 tests/test_skills.py
python3 tests/test_run_recorder.py
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall -q mini_agent_lab scripts tests
```

完整回归可逐个运行 `tests/test_*.py`。

## 当前适合进入 UI 的原因

底层已有稳定数据契约：

- session 文件可读
- run event 可回放
- summary 可轮询
- subagent 状态可查询
- bash job 输出可查看
- git/diff/checkpoint 有结构化事件

因此 UI 第一阶段可以先做“只读控制台 + mock/文件读取 API”，再逐步接入真实发送消息和 agent 进程管理。
