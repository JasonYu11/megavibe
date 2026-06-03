# Mcode UI Functional Gaps Fix Plan

## Goal

修复当前 Mcode UI 中“看起来可用但功能缺失/不完整”的问题，并补齐 macOS 原生体验：

- 全局文本选择、`Cmd+C`、`Cmd+V` 在 macOS app / WKWebView 中可用。
- 文件预览支持右键/菜单操作：Finder 中显示、默认方式打开、配置的 IDE 打开、复制路径。
- `+` 菜单里的“添加照片和文件”补齐真实附件体验，包括上传反馈、预览、错误处理和 agent 可读能力边界。
- 左侧“搜索”从静态文案升级为可用的项目/对话搜索。
- 设置面板改为带侧边栏的分区设置，不再是单条长滚动表单。
- 清理或补齐只有 UI 没有功能的入口。

## Current Findings

### Copy / Paste

- 前端没有全局禁止选择；`body.is-resizing { user-select: none; }` 只在拖动分栏时生效。
- `mcode-ui/macos/McodeApp.swift` 当前菜单只有 App、File、Window，没有标准 Edit menu。
- 在 macOS AppKit/WKWebView 中，缺少 Edit menu 往往会导致 `Cmd+C`、`Cmd+V`、`Cmd+A` 等 responder-chain 快捷键不可用或不稳定。

### File Preview

- `FileTreePanel` 预览区目前只有“打开文件”按钮。
- 前端 `api.openFile(projectId, path, app)` 已支持传入 app。
- 后端 `system_bridge.open_file` 已支持：
  - `cursor` -> Cursor 打开
  - `vscode` -> Visual Studio Code 打开
  - `finder/reveal` -> `open -R`
  - `system/default` -> 系统默认打开
- 当前缺口主要在 UI：没有右键菜单、没有复制路径、没有 Finder/default 操作入口。

### Attachments / Add Photos and Files

- 前端已经有附件入口：
  - `Composer` 的 `+` 菜单项“添加照片和文件”会触发隐藏 file input。
  - `App.attachFiles` 会创建 session，并调用 `api.uploadAttachment(...)`。
- 后端不是完全缺失，已有基础 endpoint：
  - `GET /api/projects/{project_id}/sessions/{session_id}/attachments`
  - `POST /api/projects/{project_id}/sessions/{session_id}/attachments`
  - `GET /api/projects/{project_id}/sessions/{session_id}/attachments/{attachment_id}/preview`
- 后端存储为项目根目录下 `.attachments/<session>/<attachment_id>/...`。
- 当前限制：
  - 最大 5MB。
  - `read_attachment` 只真正支持 UTF-8 文本；图片/二进制只返回“不是 UTF-8 文本”的提示。
  - 图片没有缩略图/预览 UI。
  - 上传中、上传失败、超过大小限制没有清晰 UI。
  - 附件 chip 只显示文件名，不能打开预览、复制 id/path、查看大小。
  - agent 收到的只是 attachment context，需要自己调用 `list_attachments/read_attachment`；图片没有视觉模型处理链路。

### Left Search

- `ProjectSidebar` 里的搜索目前是静态：
  - `<div className="searchBox"><Search /> <span>搜索</span></div>`
- 没有 input、没有 state、没有过滤逻辑。
- 项目列表和对话列表都可以在本地完成过滤，不需要新增后端 API。

### Settings Panel

- `SettingsPanel` 目前是单页面长表单，已有实际分组：
  - 模型 / API
  - Agent / Context
  - Runtime
  - 文件打开方式
  - Diagnostics
- 适合改成“设置内部侧边栏 + 内容区”的结构。
- 当前配置保存逻辑已经存在，应保留单一保存按钮或改为按分区保存，但首版建议保留现有保存语义，降低风险。

### UI Without Complete Function

- 左侧搜索：静态 UI，无功能。
- 文件预览操作：只有配置的默认 app 打开，缺少 Finder/default/copy path。
- `+` 菜单“添加照片和文件”：有基础上传链路，但缺少图片理解、预览、上传状态和失败反馈，容易表现为“没有工作”。
- `App.tsx` 中 `ProjectSidebar` 出现重复 `onRunTest` prop，属于无意义重复。
- `PluginMenu.tsx` 已经不在 composer 中使用，属于遗留代码，可删除或确认无引用后移除。
- `DockView` 仍包含 `home` 类型，但当前没有实际 home pane 入口；可保留为未来扩展，也可在类型中移除以减少误导。

## Implementation Plan

### 1. Restore Native Copy / Paste

修改 `mcode-ui/macos/McodeApp.swift` 的 `buildMenu()`：

- 新增标准 `Edit` menu，使用 AppKit 标准 selector：
  - Undo: `undo:`
  - Redo: `redo:`
  - Cut: `cut:`
  - Copy: `copy:`
  - Paste: `paste:`
  - Select All: `selectAll:`
- 保留现有 App/File/Window menu。
- 不在前端拦截 `Cmd+C` / `Cmd+V`。
- 前端只补充可选 CSS：
  - 普通 message、preview、code、settings 文本允许 selection。
  - button label 仍可默认不选中，避免误拖。

验收重点：

- 在聊天消息中选中文字，`Cmd+C` 后剪贴板内容正确。
- 在 composer textarea 中 `Cmd+V` 可粘贴。
- 在文件预览 `<pre>` 中可选中并复制。
- `Cmd+A` 在 textarea 聚焦时只选中输入框内容；非输入区按 WebView 默认行为执行。

### 2. Add File Preview Context Actions

修改 `FileTreePanel`：

- 预览标题右侧从单按钮改为“打开方式”菜单。
- 菜单项：
  - 默认打开：`onOpenFileExternal(path, "system")`
  - Finder 中显示：`onOpenFileExternal(path, "finder")`
  - 使用配置打开：`onOpenFileExternal(path, "")`
  - 复制路径：`navigator.clipboard.writeText(path)`
- 文件树文件行也支持右键菜单，至少提供：
  - 预览
  - Finder 中显示
  - 默认打开
  - 复制路径
- `onOpenFileExternal` 签名从 `(path: string) => void` 改成 `(path: string, app?: string) => void`。
- `App.openFileExternal` 改成按 app 参数调用：
  - app 为空：使用 `projectSettings?.ui.file_open_app`
  - app 为 `system/finder/cursor/vscode`：直接传给 `api.openFile`

验收重点：

- 右键文件树文件，菜单出现并可关闭。
- 点击“复制路径”后剪贴板为相对路径。
- 点击“Finder 中显示”调用 `/files/open` 且 body app 为 `finder`。
- 点击“默认打开”调用 app 为 `system`。
- 点击“使用配置打开”保持当前设置中的 Cursor/VS Code 行为。

### 3. Implement Left Sidebar Search

修改 `ProjectSidebar`：

- 将 `.searchBox` 改为真实 input。
- 新增本地 state `query`。
- 搜索范围：
  - projects: `project.name`、`project.root_path`
  - sessions: `session.preview`、`session.id`、`session.path`
- 搜索为空时保持当前列表。
- 搜索非空时：
  - 项目列表显示匹配项目。
  - 对话列表显示匹配对话。
  - 区块标题可显示数量，例如 `项目 2`、`对话 5`。
- 不新增后端 API；首版不做全文消息搜索。

验收重点：

- 输入项目名可过滤项目。
- 输入 session preview 可过滤对话。
- 清空搜索恢复全部列表。
- 搜索框内 `Cmd+A/C/V` 可正常工作。
- 无匹配时显示“无匹配项目/无匹配对话”。

### 4. Complete Add Photos and Files Attachment Flow

首版目标是让“添加照片和文件”明确可用，并清楚表达能力边界。

前端：

- `attachFiles` 增加上传状态：
  - uploading
  - uploaded
  - failed
- composer 附件 chip 显示：
  - 文件名
  - 文件大小
  - 类型图标：图片 / 文本 / 其它文件
  - 失败状态和重试/移除
- 点击附件 chip 打开附件 popover：
  - 基本信息：id、name、size、mime_type
  - 文本预览：显示 `preview`
  - 图片预览：如果 mime 是 `image/*`，使用后端 preview/content endpoint 或 data URL 渲染缩略图
  - 操作：复制 attachment id、复制文件名、移除
- 上传失败时给 composer 区域明确错误，不只写全局 error toast。
- 文件大小超过限制时，在上传前提示“最大 5MB”，并避免发请求。

后端：

- 保留现有 `AttachmentStore.add_base64`。
- 增加或扩展附件读取 endpoint：
  - 文本 preview 返回现有 `preview`。
  - 图片可返回安全的 base64/data URL preview，限制大小和 MIME。
- `AttachmentMeta.to_dict()` 可增加 `is_image`、`is_text`、`preview_available` 字段，减少前端猜测。
- 图片不要假装 agent 已能视觉理解；如果当前模型调用链没有 image input，就在 attachment context 中明确：
  - image attachment available by metadata only
  - no visual analysis unless a future vision provider path is added

Agent 行为：

- 文本文件：agent 可通过 `list_attachments/read_attachment` 读取内容。
- 图片文件：本轮只保证上传、预览和元数据可见；不承诺模型能“看图”。
- 如果需要真正图片理解，后续单独做 vision provider/message content schema 改造。

验收重点：

- 选择文本文件后出现 attachment chip。
- 选择图片后出现 image chip 和缩略预览。
- 超过 5MB 文件显示错误，不崩溃。
- 发送消息时 `attachment_ids` 被传给 `/messages`。
- agent 事件或 transcript 中能看到附件上下文。
- 文本附件可被 `read_attachment` 读取。
- 图片附件不会被错误地当 UTF-8 文本读取。

### 5. Refactor Settings Panel With Internal Sidebar

修改 `SettingsPanel` 为两栏结构：

- 左侧 settings nav：
  - 模型与 API
  - Agent 与上下文
  - 运行环境
  - 文件打开
  - 诊断
- 右侧显示当前 active section。
- 默认 section：模型与 API。
- 保留当前所有输入和保存逻辑。
- 顶部保存按钮保留在 settings header，作用仍是保存整个 settings。
- Runtime 的 python/shell 仍走 `onRuntimeChange`，不混入 settings save。
- 错误和 API test result 仍在当前分区显示。

验收重点：

- 点击每个设置侧边栏项，右侧内容切换。
- 修改 Base URL 后保存仍调用 `api.updateSettings`。
- API Key 保存/清除仍调用现有 endpoint。
- Runtime shell blur 仍调用 `onRuntimeChange`。
- 文件打开方式设置仍可选 Cursor、VS Code、Finder、系统默认、自定义 App。
- 窄宽度下 settings nav 自动变为顶部横向 tabs 或紧凑列表，不挤爆 dock。

### 6. Clean Up UI-Only / Dead Entries

- 删除 `ProjectSidebar` 重复 `onRunTest` prop。
- 检查 `PluginMenu.tsx` 是否已无引用；若无引用，删除文件和相关 CSS。
- 检查 `DockView = "home"` 是否无入口；首选移除 `home` 类型和 `titleFor/iconFor` 中的 home 分支，除非要马上实现 Home pane。
- 对所有“复制”按钮增加失败反馈：
  - clipboard API 不可用时显示短错误。
  - 成功后可显示“已复制”临时状态。

## Tests

### Unit / Component Tests

- `ProjectSidebar.test.tsx`
  - 搜索项目名过滤项目。
  - 搜索 session preview 过滤对话。
  - 无匹配状态正确。
  - 清空搜索恢复列表。

- `FileTreePanel.test.tsx`
  - 预览区菜单显示默认打开、Finder 中显示、使用配置打开、复制路径。
  - 文件行右键菜单显示相同操作。
  - 不同菜单项调用正确 callback app 参数。
  - 复制路径调用 `navigator.clipboard.writeText`。

- Attachment tests
  - 点击“添加照片和文件”触发 file input。
  - 上传文本文件后显示 chip、大小和 preview。
  - 上传图片后显示 image chip 和缩略预览。
  - 超过 5MB 文件显示错误，不调用 upload endpoint。
  - 上传失败显示 failed chip/error，并可移除。
  - 发送消息时携带 uploaded attachment ids。
  - 后端 attachment endpoint 保存、列出、预览文本和图片 metadata。

- `SettingsPanel.test.tsx`
  - 设置 nav 渲染 5 个分区。
  - 点击 nav 切换内容。
  - 保存设置、保存 API key、清除 API key、API test 行为不回归。

- macOS menu smoke test
  - 可通过 Swift 源码断言或轻量脚本检查 `McodeApp.swift` 包含 Edit menu 与 `copy:/paste:/selectAll:` selectors。

### Browser QA

- 打开 `http://127.0.0.1:4177/`。
- 检查 console 无 error/warn。
- 视口：
  - `1440x900`
  - `1180x820`
  - `900x820`
  - `760x820`
- 验证：
  - 左侧搜索输入、过滤、清空。
  - 文件预览菜单和右键菜单。
  - `+` -> 添加照片和文件，上传文本文件与图片文件。
  - 查看附件 chip/popover/图片缩略图。
  - 设置侧边栏切换。
  - composer textarea 可粘贴。
  - 文件预览文本可选择复制。
  - 无横向页面滚动，无 popover 被裁剪。

### Native App QA

- `mcode-ui/macos/build_app.sh`
- `open -n mcode-ui/dist/Mcode.app`
- `/api/health` 返回 `{"ok": true}`。
- 在 native app 中验证：
  - 选中聊天文字，`Cmd+C` 可复制。
  - 在 composer 中 `Cmd+V` 可粘贴。
  - 文件预览 `<pre>` 中 `Cmd+C` 可复制。
  - App menu 中出现 Edit menu。

### Acceptance Commands

```bash
npm run test -- --run
npm run build
python3 scripts/product_acceptance.py
```

## Non-goals

- 不做全文消息搜索；本轮只做项目和对话 metadata 过滤。
- 不引入复杂命令面板。
- 不改变后端文件安全边界；所有文件打开仍必须通过 `ensure_inside_project`。
- 不改变 settings 存储格式。
