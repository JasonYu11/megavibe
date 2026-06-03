# Agent 专家级工具扩充计划

> 从 agent 专家视角设计：每个工具解决 agent 在复杂长任务中的一个特定能力缺口。

---

## 现状评估

当前 mcode agent 的工具栈：

| 层级 | 现有工具 | 缺口 |
|---|---|---|
| 文件操作 | read_file, write_file, edit_file | — |
| 搜索 | grep, glob | 只有文本/文件名，无法语义检索、无法符号检索 |
| 执行 | bash, python_run | — |
| 知识 | ❌ 无 | 无法联网、无法查官方文档、模型知识过期 |
| 状态管理 | todo_write | 无结构化 ledger，长任务全靠记忆 |
| git | git_status/diff/commit/... | — |
| 子 agent | task | — |
| 记忆 | remember, list_memory | 跨会话，非任务内 |

---

## 三优先级工具设计

### 第一优先级：联网知识检索

agent 最常见的失败模式：模型训练的截止日期在这之后，API 参数变了、库升级了、macOS/iOS 新规范不知道。

#### 工具 1: `web_search`

```
名称: web_search
描述: Search the web for up-to-date information. Use for current facts,
       API parameters, library versions, legal/pricing info, recent events.
       Returns top results with URLs and snippets.

参数:
  query          (string, required)   搜索关键词
  domains        (string[], optional)  限定域名，如 ["github.com", "docs.python.org"]
  recency        (string, optional)    时效过滤："day" | "week" | "month" | "year" | "any"(默认)
  max_results    (integer, default=5)  最大返回数

返回:
  {
    "query": "...",
    "results": [
      {
        "title": "...",
        "url": "...",
        "snippet": "...",
        "date": "2026-05-15"
      }
    ],
    "total_estimated": 1234
  }

使用规则:
- 不替代 read_file / grep 查找本地代码
- 结果必须与本地代码上下文交叉验证
- 引用来源时给出 URL
- 模型可以自行判断时效性不够时主动降级为不联网查询
```

实现：基于 DuckDuckGo Instant Answer API 或 SerpAPI。DuckDuckGo 免费无需 key，适合开发环境。

#### 工具 2: `official_docs_search`

```
名称: official_docs_search
描述: Search a specific product's official documentation. Preferred over
       web_search for API references, framework docs, and language specs.

参数:
  product        (string, required)   产品/域名，如 "python" | "react" | "vite" | "deepseek"
  query          (string, required)   搜索关键词
  version        (string, optional)   版本号，如 "3.12" | "19" | "6"

映射表 (product → 搜索 URL):
  python         → docs.python.org/3/search.html?q={query}
  react          → react.dev 搜索
  vite           → vitejs.dev 搜索
  typescript     → typescriptlang.org/docs 搜索
  node           → nodejs.org/docs 搜索
  deepseek       → api-docs.deepseek.com 搜索
  openai         → platform.openai.com/docs 搜索
  swift          → developer.apple.com/documentation 搜索
  macos          → developer.apple.com/documentation 搜索
  git            → git-scm.com/docs 搜索
  docker         → docs.docker.com 搜索
  aws            → docs.aws.amazon.com 搜索
  ...可扩展

返回:
  {
    "product": "python",
    "query": "asyncio.run",
    "results": [
      {
        "title": "asyncio — Asynchronous I/O",
        "url": "https://docs.python.org/3/library/asyncio.html",
        "snippet": "...",
        "section": "coroutines and tasks"
      }
    ]
  }
```

实现：直接 fetch 对应文档站的搜索/OpenSearch 接口，解析 HTML 或 JSON 返回。

---

### 第二优先级：代码库智能检索

agent 在长任务中经常只改"看到的那个文件"，漏掉调用方/被调用方/同级模块。

#### 工具 3: `symbol_search`

```
名称: symbol_search
描述: Find function/class/variable definitions in the codebase by name.
       Faster and smarter than grep for locating symbols across the project.

参数:
  name           (string, required)   符号名，如 "ToolRegistry"
  kind           (string, optional)   过滤类型："function" | "class" | "variable" | "any"(默认)
  file_pattern   (string, optional)   限定文件 glob，如 "*.py"

返回:
  {
    "symbol": "ToolRegistry",
    "matches": [
      {
        "file": "mini_agent_lab/tool/registry.py",
        "line": 6,
        "kind": "class",
        "signature": "class ToolRegistry:",
        "context": "  def __init__(self) -> None:\n    self._tools: dict[str, Tool] = {}"
      }
    ],
    "count": 1
  }
```

实现：LSP (Language Server Protocol)。mcode 项目的后端是 Python，可以通过 jedi-language-server 或 pyright 获取符号信息。

轻量实现（无 LSP）：对 Python 用 AST 解析 `grep "def name\|class name"` 结构化。

#### 工具 4: `call_graph`

```
名称: call_graph
描述: Show who calls a function or class, and what it calls.
       Essential for understanding impact of a change.

参数:
  symbol         (string, required)   符号名
  direction      (string, default="both")
                 "callers" — 谁调用了它
                 "callees" — 它调用了谁
                 "both"    — 两者

返回:
  {
    "symbol": "flushChain",
    "file": "mcode-ui/frontend/src/state/events.ts",
    "callers": [
      { "symbol": "itemsFromChronologicalEvents", "file": "...", "line": 244 }
    ],
    "callees": [
      { "symbol": "items.push", ... }
    ]
  }
```

实现：轻量版用 AST 静态分析。Python 用 `ast` 模块解析函数调用，TypeScript 用 ts-morph。

#### 工具 5: `dependency_graph`

```
名称: dependency_graph
描述: Show import/dependency relationships for a file or module.
       Understand which modules depend on the file being changed.

参数:
  file_or_module (string, required)  文件路径或模块名
  direction      (string, default="dependents")
                 "dependencies" — 此文件导入了什么
                 "dependents"   — 谁导入了此文件
                 "both"

返回:
  {
    "file": "mini_agent_lab/tool/registry.py",
    "dependencies": ["mini_agent_lab/tool/base.py"],
    "dependents": ["mini_agent_lab/tool/builtin.py", "mini_agent_lab/agent/agent.py"]
  }
```

实现：Python 用 `ast` 解析 `import` / `from ... import` 语句；再用 grep 反向搜索。

---

### 第三优先级：任务账本工具

这不是外部工具，而是 agent 内部状态的结构化载体。当前 agent 依赖 session messages + todo_write 维护状态，但长任务容易丢失上下文。

#### 工具 6: `ledger_update`

```
名称: ledger_update
描述: Update the task ledger — a structured record of what has been done,
       what files changed, what was validated, and what risks remain.
       Call this after completing a meaningful unit of work.

参数 (全部可选，只更新传入的字段):
  objective      (string)      一句话目标
  task_type      (string)      任务类型: "implementation" | "debug" | "review" | "research"
  completed      (string[])    已完成事项的描述列表，传入替换整个列表
  changed_files  (string[])    本次修改的文件路径列表，传入替换整个列表
  validations    (object[])    验证记录，每项: {command, status:"passed"|"failed", summary}
  artifacts      (object[])    产物，每项: {kind, path}
  local_services (object[])    本地服务，每项: {url, status}
  risks          (string[])    风险和未验证项，传入替换整个列表
  next_focus     (string)      下一步做什么

调用时机:
- 完成一个实现小节后
- 测试/构建通过/失败后
- 发现重要约束或风险后
- 启动/停止本地服务后
- 生成产物后

返回:
  "ledger updated: 3 completed, 2 changed_files, 1 validation, 1 risk"
```

#### 工具 7: `ledger_read`

```
名称: ledger_read
描述: Read the current task ledger. Use this to recall what has been done
       after context compaction or when resuming a long task.

参数: 无

返回:
  当前 ledger 的完整 JSON
```

---

## 集成设计

### 工具注册

所有新工具遵循现有 `Tool` 基类：

```python
# mini_agent_lab/tool/knowledge.py
class WebSearchTool(Tool): ...
class OfficialDocsSearchTool(Tool): ...

# mini_agent_lab/tool/code_intel.py
class SymbolSearchTool(Tool): ...
class CallGraphTool(Tool): ...
class DependencyGraphTool(Tool): ...

# mini_agent_lab/tool/ledger.py
class LedgerUpdateTool(Tool): ...
class LedgerReadTool(Tool): ...
```

在 `default_registry()` 中按优先级逐步注册：

```python
def default_registry(...) -> ToolRegistry:
    registry = ToolRegistry()
    # ... 现有工具 ...
    
    # === 第三优先级：账本（即刻可用）===
    registry.add(LedgerUpdateTool())
    registry.add(LedgerReadTool())
    
    return registry
```

### Agent Prompt 补充

在系统提示的 Tool Guidance 节加入：

```
For knowledge-limited decisions (API parameters, library versions,
framework features, macOS/iOS specs), use web_search or official_docs_search.
Do not guess current facts — verify.

For multi-file changes, use symbol_search to find all definitions and
call_graph to understand impact before editing.

Maintain a task ledger via ledger_update. This is your durable working
memory across long tasks and context compaction. Read it back with
ledger_read when resuming.
```

### Ledger 与 RunRecorder 的协同

`ledger_update` 不是替代 `RunRecorder`，而是互补：

| | RunRecorder | Ledger |
|---|---|---|
| 谁写入 | 事件驱动，自动 | 模型主动调用工具 |
| 粒度 | 每个事件 | 每个里程碑 |
| 用途 | UI 预览、调试 | agent 记忆、最终回复生成 |
| 结构 | 固定 schema | 灵活，agent 自定义 |

Ledger 写入时会 emit 一个 `ledger_updated` 事件，RunRecorder 同步到 summary。

---

## 分阶段实施计划

### Phase 1: Ledger Tools（1-2小时）

**价值**: 即刻改善长任务稳定性。纯 Python，无外部依赖。

```
文件:
  mini_agent_lab/tool/ledger.py        # LedgerUpdateTool + LedgerReadTool
  mini_agent_lab/tool/builtin.py       # default_registry 注册

验收:
  1. agent 在一次长任务中至少调用 ledger_update 3 次
  2. ledger 内容在最终回复中可被引用
  3. context compaction 后 ledger_read 能恢复状态
```

### Phase 2: Web Search（2-3小时）

**价值**: 解决模型知识过期问题。DuckDuckGo 免费。

```
文件:
  mini_agent_lab/tool/knowledge.py     # WebSearchTool + OfficialDocsSearchTool
  mini_agent_lab/tool/builtin.py       # default_registry 注册

依赖: pip install duckduckgo-search (或 httpx + BeautifulSoup 自实现)

验收:
  1. agent 在 API 参数问题上自动调用 web_search
  2. agent 在问"最新版本"时不凭空猜测
  3. 搜索结果在最终回复中附带引用来源
```

### Phase 3: Code Intelligence（3-4小时）

**价值**: 长任务中最能提升 agent 准确率的工具。

```
文件:
  mini_agent_lab/tool/code_intel.py    # SymbolSearch + CallGraph + DependencyGraph

依赖: Python ast 模块（内置），无需额外安装

验收:
  1. agent 修改文件前用 call_graph 检查影响面
  2. agent 用 symbol_search 找到跨文件的类/函数定义
  3. 最终回复中说明"impacted N modules"
```

---

## Agent 行为契约

新增工具后，agent 的行为契约补充如下：

```
When you need current factual information:
  → web_search or official_docs_search
  → cite source URLs in response

When changing code that has callers:
  → call_graph to find impact
  → edit all affected files, not just the one you see

Throughout a complex task:
  → ledger_update after each milestone
  → ledger_read when context was compacted

Never:
  → Guess API parameters — web_search instead
  → Assume library versions — official_docs_search(python, "asyncio.to_thread", version="3.12")
  → Claim "no impact" without call_graph or dependency_graph
```

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| web_search 返回过期/错误信息 | 标注 URL 来源；agent 交叉验证；official_docs_search 优先 |
| call_graph 在大型项目中太慢 | 限制深度(默认2层)；缓存 AST 解析结果 |
| ledger 与 run summary 不一致 | ledger_updated 事件桥接；最终回复以 ledger 为准 |
| DuckDuckGo API 不可用 | 回退到 web_search 用 httpx + HTML 抓取 |
