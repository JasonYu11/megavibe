# Mcode Composer Plus and Speech Fix Plan

## Goal

修复 composer 底部交互与语音输入体验，让 Mcode 更接近 Codex 的输入框模型：

- `+` 负责打开添加菜单，而不是直接触发单一动作。
- 计划模式从独立按钮迁移到 `+` 菜单，开启后在底部显示状态图标。
- 暂时移除无实际作用的“能力”入口。
- 移除可见 `Local` 语音按钮，默认使用 macOS Speech bridge。
- 语音输入停止后把识别文本写入输入框，但不自动发送。
- 发送按钮始终保持在底部工具条右侧，不因控件过多掉到下一行。

## Implementation Changes

- Composer `+` 菜单：
  - `+` 打开 popover。
  - 菜单包含“添加照片和文件”和“计划模式”。
  - “添加照片和文件”复用现有隐藏 file input。
  - “计划模式”切换现有 `plan` 状态。
  - 开启计划模式后，底部工具条显示 `ListChecks` 图标，点击可关闭计划模式。

- Composer cleanup：
  - 删除独立 `Plan` pill。
  - 删除 `PluginMenu` / “能力”入口。
  - 删除可见 `Local` 语音切换。
  - 语音 start 固定发送 `{ action: "start", localOnly: false }`。

- Speech flow：
  - idle 点击麦克风：开始 listening。
  - listening 点击麦克风：发送 stop，进入 finalizing。
  - interim transcript 只更新状态文案。
  - final transcript 写入 textarea，不调用 send。
  - stop 后 final 为空时，使用最后一次 interim transcript 兜底写入。
  - error transcript 显示错误，不修改 textarea。

- Layout：
  - composer bar 改为单行、不换行。
  - 左侧工具组可压缩，发送按钮固定在右侧。
  - 模型和权限按钮在窄宽度下 ellipsis。
  - voice status 放在 textarea 与工具条之间，不挤压发送按钮。

## Test and Acceptance

- Unit/component tests:
  - 点击 `+` 显示“添加照片和文件”和“计划模式”。
  - 点击“添加照片和文件”触发隐藏 file input。
  - 点击“计划模式”调用 `onPlanChange(true)`。
  - plan=true 时显示“计划模式已开启”图标。
  - 页面不出现“能力”按钮。
  - 页面不出现 `Local` 按钮。
  - 语音 start 事件为 `{ action: "start", localOnly: false }`。
  - 语音 stop 事件为 `{ action: "stop" }`。
  - final transcript 写入 textarea 且不调用 `onSend`。
  - final 为空时使用最后一次 interim transcript 写入 textarea。

- Browser QA:
  - 使用 Codex in-app Browser，并设置可见，让用户能看到调试过程。
  - 打开 `http://127.0.0.1:4177/`。
  - 检查 console 无 error/warn。
  - 检查 `1440x900`、`1180x820`、`900x820`、`760x820`。
  - 每个视口确认 composer 不横向溢出，发送按钮不掉到下一行。
  - 真实点击 `+`，确认菜单、计划模式和文件入口正常。
  - 用 Browser evaluate 模拟 transcript，确认文本进入输入框且不发送。

- Acceptance commands:
  - `npm run test -- --run`
  - `npm run build`
  - `python3 scripts/product_acceptance.py`
  - 打开 `Mcode.app` 后确认 `/api/health` 返回 `{"ok": true}`。
