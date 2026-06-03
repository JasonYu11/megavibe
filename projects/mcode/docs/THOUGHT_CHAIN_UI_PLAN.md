# 思维链 UI 改造计划

> 目标：将当前扁平的 thinking 块 + 独立 ToolCard 改为结构化的思维链块，支持两级折叠、计时、实时状态，让用户真正看到 agent 的工作进展。

---

## 一、当前问题

```
现状:
┌─ 💭 思考 ─────────────┐   (手动折叠)
│  🔧 read_file        │   工具和思考扁平罗列
│  🔧 grep timeout     │   无计时、无统计
│  📝 "找到了..."       │   无实时状态（转圈）
│  🔧 edit_file         │   完成后不会自动折叠
└──────────────────────┘
```

核心缺陷：
- **扁平化**：思考消息和工具调用是同等层级的独立卡片，没有形成"思考→行动→观察→再思考"的链条感
- **无进度感**：不知道 agent 当前在做什么、做了多久、完成了多少步
- **无统计**：一轮对话中 agent 做了多少次工具调用、输出了多少条思考消息，用户无感知
- **无计时**：每个步骤没有耗时统计，无法判断哪一步是瓶颈

---

## 二、目标效果

```
┌─ 🧠 思维链 · 4次调用 · 2条消息 · ⏱ 8.3s ────┐  ← 一级折叠：统计 + 总计时
│                                               │
│  ┌─ 💬 分析超时配置...  ✓  1.2s ──────────┐  │  ← 二级折叠：单个步骤
│  │   模型分析了 deepseek.py 的 timeout     │  │     展开可看详情
│  │   设置，发现默认只有30秒...             │  │
│  └──────────────────────────────────────────┘  │
│  ┌─ 🔧 read_file · deepseek.py  ✓  2.1s ──┐  │
│  │   参数: {file_path: "...", limit: 100}  │  │
│  │   返回: 322行 Python 代码               │  │
│  └──────────────────────────────────────────┘  │
│  ┌─ 🔧 grep · "timeout"  ✓  1.5s ─────────┐  │
│  └──────────────────────────────────────────┘  │
│  ┌─ 💬 找到了，改成流式...  ✓  0.8s ────────┐  │
│  └──────────────────────────────────────────┘  │
│  ┌─ 🔧 edit_file · deepseek.py  ⏳ 运行中 ──┐  │  ← 当前正在执行
│  │   🔄 正在写入...                        │  │     转圈动画
│  └──────────────────────────────────────────┘  │
│                                               │
└────────────────────────────────────────────────┘

完成后自动折叠为一行:
┌─ 🧠 思维链 · 5次调用 · 2条消息 · ⏱ 10.2s  ✓ ─┐
└─────────────────────────────────────────────────┘
```

---

## 三、数据模型设计

### 3.1 ThoughtStep — 思维链中的单个步骤

```typescript
interface ThoughtStep {
  id: string;
  kind: "thought" | "tool_call";

  // 显示用
  title: string;             // "分析超时配置" / "read_file deepseek.py"
  status: "pending" | "running" | "completed" | "failed";

  // 完成后的摘要
  summary?: string;          // 一行简写，如 "读取322行代码"

  // 展开后的详情
  detail?: string;           // 思考原文 / 工具输出摘要

  // 计时
  startedAt?: number;        // ms timestamp
  completedAt?: number;
  durationMs?: number;

  // tool_call 专属
  toolName?: string;
  toolArgs?: Record<string, unknown>;

  // 错误
  error?: string;

  // 子步骤（如 tool_call 中嵌套的 command 执行）
  children?: ThoughtStep[];
}
```

### 3.2 ThoughtChain — 思维链块

```typescript
interface ThoughtChain {
  id: string;
  steps: ThoughtStep[];
  status: "running" | "completed" | "failed";

  // 统计
  stats: {
    toolCalls: number;        // "N次调用"
    thoughtMessages: number;  // "N条消息"
    totalSteps: number;       // 总步骤数
    failedSteps: number;      // 失败步骤数
  };

  // 计时
  startedAt?: number;
  completedAt?: number;

  // 一级折叠时显示的摘要文本
  summary?: string;
}
```

### 3.3 UiItem 扩展

```typescript
// UiItem 新增 kind
type UiItem =
  | ... // 现有的
  | { kind: "thought_chain"; chain: ThoughtChain; ... }
```

---

## 四、改造文件清单

| # | 文件 | 改动 | 工作量 |
|---|------|------|--------|
| 1 | `types.ts` | 新增 `ThoughtStep`, `ThoughtChain` 类型；`UiItem` 加 `thought_chain` | 小 |
| 2 | `state/events.ts` | `itemsFromChronologicalEvents()` 输出 `thought_chain` 替代 `thinking` | **大** |
| 3 | `components/ThoughtChainBlock.tsx` | **新文件**，思维链块主组件 | 中 |
| 4 | `components/ThoughtStepItem.tsx` | **新文件**，单步骤渲染组件 | 小 |
| 5 | `components/ChatWorkspace.tsx` | `renderItem()` 新增 `thought_chain` case | 小 |
| 6 | `styles/thoughtChain.css` | **新文件**，思维链样式 | 中 |

---

## 五、核心逻辑：events.ts 重组

### 5.1 当前逻辑

```
turn_started      → 创建 thinking = { items: [] }
assistant_message → 有 tool_calls: 不做任何事（等待 tool_dispatch）
                  → 无 tool_calls: append 为 final answer
tool_dispatch     → append 到 thinking.items[]
tool_result       → 更新对应 tool 的 output/status
command_started   } 更新 tool 的命令元数据
command_finished  }
turn_completed    → flush thinking, 输出 assistant answer
```

### 5.2 改造后逻辑

```
turn_started      → 创建 chain: ThoughtChain (status="running", startedAt=now)
assistant_message (有 reasoning)
                  → chain.steps.push(ThoughtStep(kind="thought", status="completed"))
                     chain.stats.thoughtMessages++
tool_dispatch     → chain.steps.push(ThoughtStep(kind="tool_call", status="running"))
                     chain.stats.toolCalls++, chain.stats.totalSteps++
tool_result (成功) → 更新对应 ThoughtStep: status="completed", completedAt, summary
tool_result (失败) → 更新对应 ThoughtStep: status="failed", error
                     chain.stats.failedSteps++
assistant_message (纯文本, 无 tool_calls)
                  → 如果是最终回答: 不加入 chain, 作为 final answer 独立渲染
                  → 如果是中间思考: chain.steps.push(ThoughtStep(kind="thought"))
turn_completed    → chain.status="completed", chain.completedAt=now
                     输出 UiItem(kind="thought_chain", chain)
```

### 5.3 step 标题生成规则

```
thought step:
  标题: reasoning 的前 30 个字符，去掉换行
  如: "分析 deepseek.py 的超时配置，流式模式..."

tool_call step:
  标题: "{tool_name} {关键参数}"
  如: "read_file · deepseek.py"
  如: "grep · timeout · provider/"
  如: "edit_file · deepseek.py:56"
```

### 5.4 计时实现

```typescript
// 每个 step 记录 startedAt / completedAt
// completedAt 不存在时，前端实时计算: elapsed = Date.now() - startedAt
// completedAt 存在时: durationMs = completedAt - startedAt

// 前端使用 useEffect + setInterval 每秒刷新 running 状态
const [elapsed, setElapsed] = useState(0);
useEffect(() => {
  if (status !== "running") return;
  const timer = setInterval(() => setElapsed(Date.now() - startedAt), 1000);
  return () => clearInterval(timer);
}, [status, startedAt]);
```

---

## 六、组件设计

### 6.1 ThoughtChainBlock — 思维链主块

```
Props: { chain: ThoughtChain; defaultExpanded?: boolean }

States:
  - collapsed (一级折叠)
  - expanded  (一级展开，显示所有 steps)

Header (一级):
  [🧠 思维链] · [N次调用] · [N条消息] · [⏱ 8.3s]
  [Chevron 折叠按钮]
  [状态图标: ⏳ running / ✓ completed / ✗ failed]

Body (展开时):
  <ThoughtStepItem /> × N
```

### 6.2 ThoughtStepItem — 单个步骤

```
Props: { step: ThoughtStep }

States:
  - compact   (二级折叠，显示一行摘要)
  - detailed  (二级展开，显示完整内容)

Header (二级):
  [💬/🔧 图标] [title] [状态: ⏳ ✓ ✗] [1.2s]

Body (展开时):
  thought:
    显示 detail 文本 (reasoning 完整内容)
  tool_call:
    显示 toolArgs (格式化的 JSON)
    显示 summary / error
    有 children 时递归渲染
```

### 6.3 自动折叠行为

```
规则:
1. chain 中所有 steps 完成 → 自动折叠为一级 (只显示 header)
2. chain 中有 step 正在运行 → 自动展开该 step
3. 用户手动折叠后 → 不再自动展开/折叠 (尊重用户意图)
4. 新的 step 开始运行 → 如果用户没有手动干预，自动滚动到该 step

实现:
const [userToggled, setUserToggled] = useState(false);
const autoExpand = !userToggled && chain.status === "running";
```

---

## 七、样式规格

### 7.1 颜色方案

```css
/* 一级块边框 */
.thoughtChain { border: 1px solid var(--border); border-radius: 8px; }
.thoughtChain--running { border-color: var(--accent); }
.thoughtChain--completed { border-color: var(--success); opacity: 0.85; }
.thoughtChain--failed { border-color: var(--danger); }

/* 二级步骤 */
.thoughtStep--running { background: var(--accent-bg); }
.thoughtStep--completed { opacity: 0.7; }
.thoughtStep--failed { background: var(--danger-bg); }

/* 计时器 */
.duration { font-family: monospace; font-size: 0.8em; color: var(--muted); }
.duration--running { color: var(--accent); }
```

### 7.2 动画

```
步骤进入:   slideDown + fadeIn, 200ms
转圈动画:   spin 1s linear infinite (复用现有 Loader2)
状态切换:   icon 颜色渐变, 300ms
折叠展开:   max-height transition, 300ms ease
```

---

## 八、与 trace 模式的关系

```
决定用哪条路径的条件:
  - events 中有 trace 事件 (step_started/action_started 等)
    → 走 agent_run / RunTrace 路径（已有 AgentRunBlock）
  - events 中无 trace 事件
    → 走 thought_chain 路径（本次改造）

两者互斥，不冲突：
  trace 模式：更结构化，适合 UI 化的 agent 产品
  thought_chain：更轻量，适合从原始事件自动推导
```

---

## 九、实施步骤

| 阶段 | 内容 | 预估 |
|---|---|---|
| **Phase 1** | `types.ts` 新增类型 + `events.ts` 重组逻辑 | 先改数据层 |
| **Phase 2** | `ThoughtStepItem.tsx` 组件 | 最小可渲染单元 |
| **Phase 3** | `ThoughtChainBlock.tsx` 组件 + CSS | 组合到一起 |
| **Phase 4** | `ChatWorkspace.tsx` 接入 + 联调 | 替换 thinking case |
| **Phase 5** | 计时刷新 + 自动折叠 + 滚动行为 | 体验打磨 |

---

## 十、验收标准

- [ ] agent 执行工具时，前端显示 ⏳ 转圈 + 计时
- [ ] 工具完成后，自动标记 ✓ 并显示耗时
- [ ] 整个思维链完成后，自动折叠为一行摘要
- [ ] 一级头部显示 "N次调用 · N条消息 · ⏱ X.Xs"
- [ ] 每个步骤可单独展开/折叠查看详情
- [ ] 新的 step 开始执行时，自动滚动到该 step
- [ ] 步骤失败时，链上显示 ✗ 标记和错误信息
- [ ] 与现有 trace 模式不冲突，根据事件有无 trace 自动选择路径
