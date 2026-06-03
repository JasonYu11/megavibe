# Plan Mode & Todo 验收记录

## Plan Mode 流程

1. 用户提出任务后，Agent 进入只读探索模式，仅可使用 `read_file`、`ls`、`grep`、`glob` 等只读工具。
2. Agent 理解任务后，以双层 Markdown 列表（顶层阶段 + 缩进子步骤）提交计划。
3. 计划展示后停等用户批准。用户批准前不可执行任何写操作。
4. 用户批准后，Plan Mode 关闭，Agent 开始执行计划并用 `todo_write` 跟踪进度。

## Todo 的作用

- `todo_write` 是可见的进度跟踪工具，用于多步骤任务。
- 每次调用发送完整任务列表，替换之前的列表。
- 始终保持至多一个 `in_progress` 项，完成后立即标记 `completed`。
- 支持双层结构：`level 0` 为阶段/里程碑，`level 1` 为具体子步骤。
- 简单单步任务可跳过 todo_write。

## 测试日期

2026-06-01
