# Mcode Layout Fix and Acceptance Plan

## Goal

修复当前 Mcode workbench 的布局可靠性问题，并把右侧区域推进到更接近 Codex 的工具窗格体验：

- 中间对话区有稳定最小宽度，文字、卡片、composer 不因侧栏拖动而溢出。
- 左右分界线都能持续拖动，不会因为先拖动一侧导致另一侧失效。
- 右侧侧边栏可以显式隐藏/显示。
- 右侧 `+` 用于创建多个工具窗格，例如文件、终端、浏览器、事件、设置、侧聊。
- 所有窄宽度场景都有可测试的验收标准。

## Current Problems

### 1. 中间对话区宽度没有被产品级保护

当前 `layoutColumns(layout)` 返回：

```text
left minmax(460px, 1fr) right
```

这只能给 grid 中间列一个 CSS 下限，但没有结合实际 viewport 宽度、左右侧栏宽度和折叠策略做统一计算。结果是：

- viewport 不够宽时，中间区域可能被左右侧栏挤压。
- 消息卡片、变更卡片、状态条、composer 都依赖各自的 `max-width` 和局部 `min-width: 0`，没有一个统一的内容宽度边界。
- 长路径、长英文 token、代码片段、中文混排内容在某些卡片里仍可能撑出父容器。

### 2. 右侧 Dock 内容容易超过框大小

当前 `WorkspaceDock` 是一个单 panel 多 tab 结构：

```text
files | terminal | browser | events | subagents | settings | side_chat
```

问题：

- header 工具按钮全部横向排列，窄宽度下依赖横向滚动，视觉上像“超出框”。
- 部分 panel 内部仍有固定列宽、按钮组和长路径文本，缺少统一的 compact 模式。
- 右侧 dock 没有显式隐藏按钮，只能靠双击分界线或右侧 rail 恢复，用户不容易发现。

### 3. 分界线拖动 bug 来自边界计算脱节

当前两个 handle 是绝对定位：

```css
.layoutHandle--left { left: calc(var(--left-width) - 4px); }
.layoutHandle--right { right: calc(var(--right-width) - 4px); }
```

拖动逻辑则只修改单侧宽度：

```ts
leftWidth = startLayout.leftWidth + delta
rightWidth = startLayout.rightWidth - delta
```

这里有两个核心问题：

- handle 位置由 `leftWidth/rightWidth` 直接推导，不等于 grid 实际布局后的列边界。
- 左侧拖动改变了中间剩余空间，但右侧 handle 仍按 `rightWidth` 从 viewport 右边倒推；当中间列被压缩或 grid 重新分配时，第二个 handle 会和真实可拖动边界错位。

所以用户看到的“第一个分界线拖动后，第二个拖动不了”是合理的代码结果。

### 4. `+` 的语义不清且右侧缺少创建窗格能力

当前界面里有多个 `+`：

- 左侧侧栏：创建项目或新会话相关。
- composer：添加附件。
- 右侧 dock：目前没有真正的“添加工具窗格”入口。

用户期望的是 Codex 风格：右侧 `+` 创建多个工作窗口/工具窗格，比如终端、文件、浏览器等。这需要从“切 tab”升级为“pane list / pane instances”模型。

## Recommended Direction

### 1. 引入 Workbench Layout Engine

把布局计算从 CSS 字符串升级为纯函数布局引擎，例如：

```ts
computeWorkbenchLayout({
  containerWidth,
  requestedLeftWidth,
  requestedRightWidth,
  leftCollapsed,
  rightCollapsed,
  minMainWidth,
})
```

输出：

```ts
{
  leftWidth,
  mainWidth,
  rightWidth,
  leftCollapsed,
  rightCollapsed,
  leftHandleX,
  rightHandleX,
}
```

建议约束：

- `MIN_MAIN_DESKTOP = 620`
- `MIN_MAIN_COMPACT = 520`
- `MIN_LEFT = 220`
- `MAX_LEFT = 360`
- `MIN_RIGHT = 300`
- `MAX_RIGHT = 560`
- 当空间不足时，优先收缩右侧 dock，再折叠右侧 dock，再考虑左侧 compact/折叠。

这样拖动任意一侧时，都基于同一个 container width 和同一个 min-main 约束重新计算，不再出现两个 handle 各算各的。

### 2. 改造 grid 结构，让 handle 成为真实列

推荐从三列：

```text
left | main | right
```

改为五列：

```text
left | left-handle | main | right-handle | right
```

好处：

- handle 不再绝对定位。
- handle 永远处在真实列边界。
- CSS grid 和 React state 不会出现边界脱节。
- 可测试性更高，Playwright 可以直接测 handle bounding box。

### 3. 给中间对话区设置真实最小宽度和溢出策略

中间区必须有一个产品级最窄限制，而不是只靠局部卡片自适应。

建议：

- `.workspace` 设置 `min-width: var(--main-min-width)`。
- `.transcript > *` 使用 `width: min(100%, 820px)`，不要让子元素靠内容撑宽。
- 所有消息、notice、approval、change review、composer 根节点都加 `min-width: 0; max-width: 100%`。
- 普通文本使用 `overflow-wrap: anywhere`。
- `pre/code` 不强制拆散代码，使用 `overflow-x: auto`。
- 路径、URL、模型名、session preview 用 ellipsis 或可复制 tooltip，不直接撑开布局。

### 4. 右侧 Dock 改为 Codex-like Pane Model

把 `DockView` 从单值：

```ts
type DockView = "files" | "terminal" | "browser" | ...
```

升级为 pane list：

```ts
interface DockPane {
  id: string;
  type: "files" | "terminal" | "browser" | "events" | "settings" | "side_chat" | "subagents";
  title: string;
  collapsed?: boolean;
}
```

右侧 header 建议提供：

- hide button：显式隐藏右侧 dock。
- `+` button：打开 Add Pane menu。
- pane switcher：显示当前 pane 或 pane stack。
- close button：关闭当前 pane。

第一版可以先做“多 pane 单激活显示”，随后再升级成垂直 split stack。这样风险较小，但已经满足“通过加号手动创建多个窗口”的产品方向。

### 5. 明确各个 `+` 的职责

需要给所有 `+` 设置清晰的 accessible label 和 tooltip：

- 左侧 `+`：`新建项目` 或 `添加项目`。
- composer `+`：`添加附件`。
- 右侧 dock `+`：`添加工具窗格`。

不要让三个 `+` 在视觉和语义上混成一个动作。

## Implementation Plan

### Phase A: 修复布局引擎和拖动 bug

1. 新建或重写 `layoutState.ts` 的布局纯函数。
2. 添加 container width 监听，使用 `ResizeObserver` 记录 app shell 宽度。
3. 用 `computeWorkbenchLayout` 统一计算 left/main/right。
4. grid 改为五列：left、left handle、main、right handle、right。
5. 拖动左侧时也保护右侧和中间最小宽度；拖动右侧时同理。
6. 空间不足时自动折叠右侧 dock，保证中间对话区不会低于最小宽度。

### Phase B: 修复文字和内容溢出

1. 审查 message、notice、change review、approval、composer、dock panel 的根容器。
2. 统一补齐 `min-width: 0`、`max-width: 100%`、`overflow-wrap`。
3. 对 `pre/code`、文件预览、事件 JSON、终端输出使用横向滚动。
4. 对路径、tab label、header title 使用 ellipsis 和 `title`。
5. 给右侧 dock header 增加 compact 样式：窄宽时只显示图标，label 进 tooltip 或菜单。

### Phase C: 右侧 Dock 显式隐藏/显示

1. 在 dock header 加 hide button。
2. 保留右侧 rail 恢复按钮，但文案改为更清晰的“显示工具区”。
3. 添加快捷键可选：例如 `Cmd+Option+R` toggle right dock。
4. 折叠状态持久化到 layout storage。

### Phase D: 右侧 `+` 创建工具窗格

1. 引入 `DockPane` 数据结构。
2. 默认 panes：Files + Terminal 或 Files 单 pane。
3. `+` 打开 Add Pane menu，支持添加：
   - 文件
   - 终端
   - 浏览器
   - 事件
   - 设置
   - 侧聊
   - 子任务
4. pane 支持切换、关闭、重命名显示标题。
5. pane list 持久化，保留用户下次打开时的右侧工作台状态。

### Phase E: 视觉打磨

1. 对齐 Codex 的轻量工具栏风格：少文字、明确图标、紧凑 tab/pane。
2. 分界线 hover/active 状态更明显。
3. 拖动过程中给 body 加 `is-resizing`，避免文本选择和闪动。
4. 窄屏下优先保中间区，右侧作为 overlay 或自动隐藏。

## Test and Acceptance Standards

### Unit Tests

新增/更新 `layoutState.test.ts`：

- `computeWorkbenchLayout` 在 1440、1180、900、760 宽度下都返回合法列宽。
- 中间列永远不低于配置的 `minMainWidth`，除非进入明确 compact/overlay 状态。
- 先拖左侧再拖右侧，右侧宽度仍可变化。
- 先拖右侧再拖左侧，左侧宽度仍可变化。
- persisted layout 中的过大/过小宽度会被 clamp。
- 空间不足时按规则优先折叠右侧 dock。

### Component Tests

新增/更新 React Testing Library 测试：

- 右侧 dock header 存在 `隐藏工具区` 按钮，点击后 dock 折叠。
- 折叠后存在 `显示工具区` rail/button，点击后恢复。
- 右侧 `添加工具窗格` 按钮可以打开菜单。
- 选择 `终端` 后出现 terminal pane。
- 选择 `浏览器` 后出现 browser pane。
- 选择 `文件` 后出现 files pane。
- composer 的 `添加附件`、左侧的 `添加项目`、右侧的 `添加工具窗格` 三个按钮拥有不同 accessible label。
- 长中文、长英文 token、长路径消息渲染后仍在 message 容器内。

### Browser / Visual QA

使用 Playwright 或 Browser 插件验收：

- viewport `1440x900`：三栏都显示，左右 handle 可拖动。
- viewport `1180x820`：中间区不低于最小宽度，右侧 dock 可显示但 header 不溢出。
- viewport `900x760`：右侧 dock 自动隐藏或进入 overlay，composer 不被挤压。
- viewport `760x720`：主对话区优先显示，左右栏不造成横向页面滚动。
- 拖动顺序测试：
  - 左 handle 拖动 3 次后，右 handle 仍可拖动。
  - 右 handle 拖动 3 次后，左 handle 仍可拖动。
  - 快速来回拖动不会让 handle 消失或错位。
- 长内容测试：
  - 一段超长中文消息不溢出。
  - 一个超长英文 token 自动换行。
  - 一个很长的文件路径在 header/card 中 ellipsis。
  - 代码块保留横向滚动，不撑破父容器。

### macOS App Acceptance

在 native app 中验收，而不只是在 Vite browser 中验收：

- `npm run test -- --run` 通过。
- `npm run build` 通过。
- `mcode-ui/macos/build_app.sh` 通过。
- 打开 `Mcode.app` 后 `/api/health` 返回 `{"ok": true}`。
- 在 WKWebView 中重复拖动左右分界线，不出现第二分界线失效。
- 右侧隐藏/显示按钮可点击。
- 右侧 `+` 可创建至少文件、终端、浏览器三类 pane。

### Product Acceptance

更新 `scripts/product_acceptance.py`，加入布局验收项：

- frontend layout unit tests。
- dock pane creation component tests。
- build artifact 存在。
- app health endpoint 正常。

最终通过标准：

```text
product_acceptance: all passed
frontend tests: all passed
native app: launches and health ok
visual QA: no overflow and both resize handles remain usable
```

## Definition of Done

- 截图中出现的文字溢出、右侧超框、composer 挤压问题被修复。
- 中间对话区有明确最小宽度，低于阈值时侧栏让位。
- 左右分界线使用同一套布局计算，任意拖动顺序都可继续工作。
- 右侧工具区有显式隐藏/显示按钮。
- 右侧 `+` 可以创建多个工具窗格。
- 自动化测试覆盖布局计算、dock 交互和关键视觉约束。
- macOS native app 内验收通过。
