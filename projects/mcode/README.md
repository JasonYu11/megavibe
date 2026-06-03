# Mcode

一个本地优先的 AI 编程助手，为 macOS 原生构建。

Mcode 是一个全栈 coding agent：Python 后端 + DeepSeek API + React 前端 + macOS WKWebView 原生 App。支持工具调用、流式输出、深度思考、思维链可视化、Skills 系统、子 Agent、分层安全审查等完整特性。

## 快速开始

### 前提

- **macOS**（App 仅支持 macOS）
- **Python 3.12+**（建议 conda）
- **Node.js 22+**
- **DeepSeek API Key**

### 1. 安装依赖

```bash
# Python
pip install -r requirements.txt

# 前端（仅构建 App 时需要）
cd mcode-ui/frontend && npm install && cd ../..
```

### 2. 配置 API Key

```bash
export DEEPSEEK_API_KEY="sk-your-key-here"
```

或写入 `mcode-config.json` 中（不推荐提交到 Git）。

### 3. 运行

```bash
# CLI 交互模式
python scripts/agent_chat.py

# Web 模式（需同时启动后端和前端）
cd mcode-ui/backend && uvicorn app:app --port 8008 &
cd mcode-ui/frontend && npm run dev   # 开发模式，http://localhost:5173
```

### 4. 构建 macOS App

```bash
bash mcode-ui/macos/build_app.sh
open mcode-ui/dist/Mcode.app
```

## 项目结构

```
.
├── mini_agent_lab/          # 核心 Agent 库
│   ├── agent/agent.py       # Agent 主循环
│   ├── provider/            # LLM Provider（DeepSeek / OpenAI 兼容）
│   ├── tool/                # 工具系统（read_file, write_file, bash, grep...）
│   ├── safety.py            # 分层安全审查
│   ├── auto_review.py       # 自动化审批 Agent
│   ├── skill.py             # Skills 系统
│   ├── subagent.py          # 子 Agent 委派
│   ├── plan.py              # Plan Mode（先规划后执行）
│   ├── compact.py           # 上下文压缩
│   ├── trace.py             # 流式事件追踪
│   ├── run_recorder.py      # 事件记录与回放
│   ├── session_store.py     # 会话持久化
│   └── ...
├── mcode-ui/
│   ├── frontend/            # React + TypeScript + Vite
│   │   └── src/
│   │       ├── components/  # ThoughtChain, ChatWorkspace, Composer...
│   │       ├── state/       # 事件流 → UI 状态
│   │       └── api/         # 后端 API 客户端
│   ├── backend/             # FastAPI 后端
│   │   └── app.py           # REST + WebSocket + SSE
│   └── macos/               # Swift WKWebView 原生 App
│       ├── McodeApp.swift
│       └── build_app.sh
├── scripts/
│   └── agent_chat.py        # CLI 入口 + System Prompt
├── docs/                    # 设计文档
├── mcode-policy.json        # 安全策略
└── mcode-config.json        # 项目配置
```

## 核心能力

### 工具系统
- `read_file` / `write_file` / `edit_file` — 文件操作（写后自动静态检查）
- `bash` / `python_run` — 命令执行
- `grep` / `glob` — 代码搜索
- `task`（子 Agent）— 复杂任务委派
- `todo_write` — 任务进度管理
- Skills — 可复用工作流

### 安全审批（三层）
| 层级 | 规则 | 示例 |
|------|------|------|
| Tier 0: 自动放行 | 白名单匹配 | `ls`, `git status`, `npm test` |
| Tier 1: 自动审查 | AutoReviewAgent 判断 | `git commit`, `python_run` |
| Tier 2: 人工审批 | 高风险命令 | `sudo`, `rm -rf /`, `git push --force` |

### 思维链可视化
- 工具调用和思考过程实时展示
- 流式事件追踪（reasoning → tool_call → result）
- 完成后自动折叠，显示统计信息

### Skills
```yaml
# .mcode/skills/review/SKILL.md
---
name: review
description: 代码审查
context: 逐文件审查，关注正确性、风险、测试
checklist:
  - 类型错误是否修复
  - 边界情况是否处理
  - 是否有遗留日志
---
# 审查步骤...
```

从底部 `+ Skill` 按钮或输入框 `/skill review` 调用。

## 配置

### mcode-config.json
```json
{
  "provider": {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-pro",
    "temperature": 0.2
  },
  "agent": { "max_steps": 300 },
  "runtime": { "python": "", "shell": "/bin/zsh" }
}
```

### mcode-policy.json
安全策略配置（白名单、审批规则、strictness）。

## 外观

设置面板 → 外观 → 可选 **Codex Light** / **Codex Dark**

- 强调色 `#339CFF`
- Light: 背景 `#FFF` 前景 `#1A1C1F`
- Dark: 背景 `#181818` 前景 `#FFF`

## Requirements

```
fastapi
uvicorn
httpx
pydantic
openai
```

## License

MIT
