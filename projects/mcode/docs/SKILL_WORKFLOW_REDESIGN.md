# Skill 工作流重设计

> 核心洞察：Skill 不是硬编码流程，而是专家级**指导性 playbook**。
> Agent 读取 skill 后获得领域知识和行为准则，但在具体执行中保有自主权。

---

## 一、Skill 的本质

```
Skill ≠ 固定步骤序列 (workflow engine)
Skill = 领域上下文 + 行为准则 + 检查清单 + 反模式警示
```

类比：一个资深工程师带新人时，不会说"你必须先做 A，再做 B，再做 C"，
而是说"做这类任务时，记住这几条原则，避开这几个坑，最后确认这几件事都做了"。

Agent 也是这样 — Skill 是它戴上的"领域眼镜"，戴上后就能用正确的思维模式处理任务。

---

## 二、Skill 格式升级

### 2.1 新字段设计

```yaml
---
name: debug-python
description: 系统化调试 Python 错误的流程
runAs: inline
domain: debugging

context: |
  调试 Python 代码时应使用以下工具和策略：
  - python_run 运行脚本，捕获完整 traceback
  - read_file 逐层检查调用栈中的文件
  - grep 搜索符号定义和引用关系
  - 对于导入错误，检查 sys.path 和环境变量

heuristics:
  - "先复现再修复" — 确认问题能稳定复现后再动手
  - "最小改动优先" — 最可能引入 bug 的地方是最近的改动
  - "isolate before diagnose" — 先隔离问题到最小可复现范围
  - "类型和 None 是高频元凶" — 优先怀疑类型不匹配和 None 引用

checklist:
  - 是否运行了完整 traceback 的最小复现脚本？
  - 是否检查了调用栈中每一层的变量状态？
  - 是否确认了所有依赖版本正确？
  - 修复后是否跑了相关测试？
  - 是否检查了是否有类似问题存在于其他文件中？

anti_patterns:
  - "别碰无关代码" — 不要顺手重构调试目标之外的代码
  - "别猜原因" — 必须实际运行代码验证假设
  - "别静默修复" — 修复后要能解释 root cause
  - "别忽略 warning" — warnings 往往是 bug 的前兆

output_format: |
  问题定位: [root cause 一句话]
  修复: [改动文件和关键变更]
  验证: [如何确认已修复]
---

# Debug Python Skill

## 你在调试一个 Python 错误

### 第一步：复现
用 python_run 运行用户报告的脚本或最小复现用例。完整记录 error type, message, traceback 文件路径和行号。

### 第二步：定位
从 traceback 最深的一帧开始，用 read_file 读取文件，找到出错的那一行。不要只看那一行 — 检查周围的变量定义、类型注解、条件分支。

### 第三步：隔离
用 python_run 运行一个只包含问题逻辑的最小脚本（5-10行）。如果最小脚本能复现，就找到了 root cause；如果不能，重新审视调用链。

### 第四步：修复
做最小改动。修复后立即用 python_run 测试。

### 第五步：巩固
grep 搜索相似的调用模式，确认没有同类问题。如果改动涉及公共函数，检查所有调用方。
```

### 2.2 字段说明

| 字段 | 作用 | 示例 |
|---|---|---|
| `context` | 领域知识：工具选择、概念解释、相关文件约定 | "用 python_run 而不是 bash python" |
| `heuristics` | 行为准则：决策原则，不是步骤 | "最小改动优先" |
| `checklist` | 完成前确认清单：agent 自己检查 | "是否跑了相关测试？" |
| `anti_patterns` | 不要做的事：常见错误警示 | "别碰无关代码" |
| `output_format` | 交付格式：期望的输出结构 | "问题定位/修复/验证" |

这些字段是**建议性的**，agent 在具体场景中可以跳过、调整、或增加步骤。

---

## 三、Skill 如何影响 Agent 行为

### 3.1 不是"执行步骤"，而是"切换思维模式"

```
没有 Skill:
  Agent: "有个 bug...我看看代码...改一下...好了"
  问题: 可能缺检查、可能修错地方、可能忘记验证

有 debug-python Skill:
  Agent 做了这些决策 (不是被迫的):
  1. "我需要先复现" (来自 heuristic: 先复现再修复)
  2. "从 traceback 最深帧读起" (来自 context: 工具策略)
  3. "做了最小改动，只改了这一行" (来自 heuristic: 最小改动优先)
  4. "grep 检查了类似调用，确认没有同类问题" (来自 anti_pattern: 别忽略关联)
  5. "修复后跑了测试，确认通过" (来自 checklist: 是否跑了测试)
```

### 3.2 System Prompt 注入方式

```
当前: skill 索引 + run_skill 返回 skill 文本

升级后: 当 agent 决定使用某个 skill 时:
  1. skill 的 context → 追加到 system prompt (一次)
  2. heuristics + anti_patterns → 作为行为约束 (持续生效)
  3. checklist → 在每次接近完成时自动提醒
  4. output_format → 影响最终回答结构
```

---

## 四、Skill Pipeline（轻量串联）

### 4.1 不是硬连，是自然过渡

```
用户: "帮我重写这个组件"

Agent 内部分析:
  1. 这需要先理解现有代码 → 自动加载 "explore" skill
  2. 探索完成，需要开始实现 → 自动加载 "implement" skill
  3. 实现完成 → 自动加载 "review" skill
  4. 审查通过 → 自动加载 "test" skill

不是: run_skill("explore") → run_skill("implement") → ...
而是: agent 在任务推进中，自然地"戴上"下一个领域的眼镜
```

### 4.2 实现：skill 预加载

```
agent 启动时预加载 3-5 个最可能相关的 skill 到旁路 context
不需要每次调用 run_skill，agent 可以在对话中自然引用
```

---

## 五、Skill 在 UI 中的呈现

### 5.1 当前：完全不可见

agent 内部用了什么 skill，用户完全不知道。

### 5.2 改进：Skill 作为标签/徽章

```
┌─ 🧠 思维链 ──────────────────────────────┐
│ 📦 已加载: debug-python                     │
│ ▏ 💬 先复现这个错误...                     │
│ 🔧 python_run · test_error.py         ✓    │
│ ▏ 💬 发现是 NoneType，检查调用链...         │
│ 🔧 read_file · handler.py             ✓    │
│ 🔧 edit_file · handler.py       ✓  +1 -1   │
│ 🔧 python_run · test_fix.py          ✓     │
│ ✅ checklist: 5/5 通过                     │
└────────────────────────────────────────────┘
```

- 顶部一行显示当前激活的 skill
- 底部显示 checklist 完成度
- Skill 本身不占用折叠空间，而是作为环境标签存在

### 5.3 实现：event 扩展

```typescript
// 新增事件类型
{ kind: "skill_activated", data: { name, fields: ["context", "heuristics"] } }
{ kind: "skill_checklist", data: { total, completed } }
{ kind: "skill_deactivated", data: { name, outcome } }
```

---

## 六、Skill 加载模式对比

| 模式 | 旧 | 新 |
|---|---|---|
| 触发方式 | agent 手动调用 run_skill | agent 自主判断 + 系统提示 |
| 加载内容 | 全部 body 文本 | context + heuristics + checklist |
| 对用户可见 | 否 | 是（标签徽章 + checklist） |
| 执行方式 | inline 或 subagent | 始终 inline，但可选 subagent 子任务 |
| 完成验证 | 无 | checklist 自检 |

---

## 七、实现计划

### Phase 1: Skill 格式升级（核心）

| 文件 | 改动 |
|---|---|
| `mini_agent_lab/skill.py` | Skill 加 context/heuristics/checklist/anti_patterns/output_format 字段 |
| `mini_agent_lab/skill.py` | parse_frontmatter 支持新字段解析 |
| 现有内置 skills | 用新格式重写 (test/init/explore/review/security-review) |

### Phase 2: Agent 行为注入

| 文件 | 改动 |
|---|---|
| `mini_agent_lab/agent/agent.py` | run_skill 触发时，将 context 注入 system prompt 旁路 |
| `mini_agent_lab/tool/skill_tools.py` | run_skill 返回 skill 元数据 + 行为准则摘要 |

### Phase 3: UI 可见性

| 文件 | 改动 |
|---|---|
| `mcode-ui/frontend/src/state/events.ts` | skill_activated/checklist 事件处理 |
| `mcode-ui/frontend/src/components/ThoughtChainBlock.tsx` | skill 标签 + checklist 进度渲染 |

### Phase 4: 上下文预加载

| 文件 | 改动 |
|---|---|
| `mini_agent_lab/agent/agent.py` | 启动时预加载 3-5 个高相关 skill |
| `mini_agent_lab/skill.py` | skill 加 triggers 触发词，用于匹配 |

---

## 八、验收标准

- [ ] Skill 支持 context/heuristics/checklist/anti_patterns 字段
- [ ] Agent 加载 skill 后行为明显更规范（检查更全面，错误更少）
- [ ] Skill 激活/卸载在 UI 中可见
- [ ] Checklist 完成度在对话底部展示
- [ ] 现有 inline/subagent 模式向后兼容
- [ ] 不强制步骤执行 — agent 保有用 skill 指导的自适应能力
