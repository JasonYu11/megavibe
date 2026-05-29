# Web 宣传片自动化制作 Plan

## 1. 目标

为 Megawave Trading Dashboard 制作一条可重复生成的 Web 宣传片，重点展示当前 Web 端真实具备的交易能力：

- 标准命令交易入口。
- 市价单表单。
- 限价单表单。
- 报价查询。
- 自然语言解析为标准命令。
- 交易草稿预览与“是 / 否”确认。
- 订单状态、历史记录、Tx/地址跳转。
- 跟单页面只做功能露出，不作为主演示流程。

宣传片不以 DEX 页面或钱包插件直接交易为主线。真实产品逻辑是：Web 表单或自然语言输入生成标准命令，统一进入 Dashboard 后端命令通道，再经过报价、风控、待确认、手动确认、执行状态记录。

## 2. 推荐视频版本

### 2.1 标准横屏版

- 比例：16:9。
- 时长：60-75 秒。
- 用途：官网、产品介绍页、客户演示、GitHub README。

### 2.2 竖屏短视频版

- 比例：9:16。
- 时长：30-45 秒。
- 用途：社媒、短视频、移动端传播。

### 2.3 长演示版

- 比例：16:9。
- 时长：2-3 分钟。
- 用途：技术说明、投资人/合作方演示、内部验收。

第一阶段建议先做 60 秒横屏版，验证流程、录屏、配音和导出链路后，再扩展竖屏和长演示版。

## 3. 真实产品流程

### 3.1 标准命令链路

```text
Web 表单 / 手动命令输入
  -> 生成标准命令
  -> POST /api/commands
  -> TelegramCommandHandler
  -> CommandParser
  -> OrderService / Store
  -> Web 端刷新订单状态
```

标准命令示例：

```text
/quote TOKEN_IN TOKEN_OUT AMOUNT
/buy TOKEN_OUT AMOUNT
/sell TOKEN_IN AMOUNT
/limit_buy TOKEN_OUT AMOUNT at TARGET_PRICE
/limit_sell TOKEN_IN AMOUNT at TARGET_PRICE
/orders
/history
/order ORDER_ID
/confirm ORDER_ID
/reject ORDER_ID
/cancel ORDER_ID
```

### 3.2 自然语言链路

```text
用户输入非 / 开头文本
  -> POST /api/nl-commands/parse
  -> NLCommandAgent
  -> 生成标准命令预览
  -> Web 显示“是 / 否”
  -> 用户点“是”
  -> sendParsedNlCommand(command)
  -> POST /api/commands
```

自然语言不会直接执行确认、拒绝、取消、删除跟单地址等高风险操作。这些操作必须通过手动按钮或精确标准命令完成。

### 3.3 限价单链路

```text
创建限价单
  -> 条件单进入待确认/运行状态
  -> 本地 watcher 按 DeBank 价格轮询
  -> 价格触发
  -> 条件单生成市价单
  -> 市价单继续走报价、风控、确认、执行流程
```

限价单不是链上 DEX 原生 limit order，而是本地条件 watcher 触发后的自动市价执行。

## 4. 演示 Token 与交易参数

演示 Token：

```text
0x5F980Dcfc4c0fa3911554cf5ab288ed0eb13DBa3
```

市价买入演示命令：

```text
/buy 0x5F980Dcfc4c0fa3911554cf5ab288ed0eb13DBa3 0.1
```

含义：默认使用 Base USDC 作为支付 Token，金额为 0.1 USDC，约等于 0.1 USD。

限价买入演示命令：

```text
/limit_buy 0x5F980Dcfc4c0fa3911554cf5ab288ed0eb13DBa3 0.1 at 0.0001
```

自然语言演示输入：

```text
用 0.1U 买入 0x5F980Dcfc4c0fa3911554cf5ab288ed0eb13DBa3
```

视频录制阶段建议优先使用 `dry_run` 或 `sign_only`，避免宣传片自动化脚本直接广播真实交易。若必须展示 live，小额交易也应保留人工确认步骤。

## 5. 60 秒分镜

### Scene 1: 开场总览

- 时长：0-6 秒。
- 页面：总览。
- 操作：打开 Dashboard，展示钱包、执行模式、订单数、watcher 状态。
- 画面重点：这是一个 Base 链交易 Agent 控制台。
- 字幕：`从命令到自然语言，统一管理 Base 链交易流程。`

### Scene 2: 市价单表单

- 时长：6-18 秒。
- 页面：交易指令。
- 操作：
  - 点击“交易指令”。
  - 在市价单表单选择“买入”。
  - 输入 Token 合约地址。
  - 输入数量 `0.1`。
  - 点击“生成市价单”。
- 画面重点：Web 表单自动生成 `/buy` 命令。
- 字幕：`市价单从表单生成标准命令，进入统一交易管线。`

### Scene 3: 待确认与风控

- 时长：18-28 秒。
- 页面：交易对话。
- 操作：展示返回的市价单确认消息和确认/拒绝按钮。
- 画面重点：订单不会绕过确认。
- 字幕：`报价、风控、待确认，执行前保留人工决策。`

### Scene 4: 限价单表单

- 时长：28-40 秒。
- 页面：交易指令。
- 操作：
  - 在限价单表单选择“限价买入”。
  - 输入同一 Token 合约。
  - 输入数量 `0.1`。
  - 输入目标价格。
  - 点击“创建限价单”。
- 画面重点：限价单由本地 watcher 到价触发。
- 字幕：`限价单由本地 watcher 监控价格，到价后生成市价单。`

### Scene 5: 自然语言解析

- 时长：40-52 秒。
- 页面：交易对话输入框。
- 操作：
  - 输入 `用 0.1U 买入 0x5F980Dcfc4c0fa3911554cf5ab288ed0eb13DBa3`。
  - 展示系统生成 `/buy ... 0.1`。
  - 展示“是 / 否”按钮。
- 画面重点：自然语言不是直接执行，而是解析成可审查的标准命令。
- 字幕：`自然语言先生成命令预览，确认后才进入交易流程。`

### Scene 6: 订单和历史

- 时长：52-64 秒。
- 页面：订单、历史、Tx 链接。
- 操作：
  - 切换到订单页。
  - 展示市价单和限价单状态。
  - 展示 Tx/地址链接位置。
- 画面重点：状态可追踪、结果可复盘。
- 字幕：`订单状态、历史记录、链上链接统一沉淀。`

### Scene 7: 跟单页面快速露出

- 时长：64-72 秒。
- 页面：跟单。
- 操作：快速切换到跟单页，展示跟单指令和地址列表区域。
- 画面重点：跟单是扩展能力，不作为本片主演示。
- 字幕：`跟单管理已接入同一控制台，可独立配置与追踪。`

## 6. 自动化制作流程

### 6.1 目录建议

```text
promo/
  scenes.yaml
  record.ts
  compose.tsx
  script.zh.md
  subtitles.zh.srt
  assets/
    logo.png
    bgm.mp3
    voiceover.zh.mp3
  output/
    megawave-promo-16x9.mp4
    megawave-promo-9x16.mp4
    cover.png
```

### 6.2 录屏自动化

使用 Playwright 或浏览器插件执行以下动作：

```text
1. 打开 http://localhost:<dashboard_port>
2. 等待 /api/status、/api/orders 数据加载
3. 录制总览页面
4. 切换交易指令页面
5. 填写市价单表单并提交
6. 捕获确认消息和按钮
7. 填写限价单表单并提交
8. 输入自然语言命令
9. 捕获命令预览和“是 / 否”
10. 切换订单页、跟单页
11. 停止录制
```

录制时需要隐藏或打码：

- 钱包完整地址。
- 数据库本地路径。
- API key、环境变量、终端日志中的敏感信息。
- 私钥、助记词、签名材料。

### 6.3 剪辑自动化

建议用 Remotion 或 ffmpeg：

```text
录屏片段
  -> 裁切无效等待
  -> 加入标题卡
  -> 加入鼠标高亮
  -> 加入局部放大
  -> 加入字幕
  -> 混入配音和背景音乐
  -> 导出 mp4
```

若需要更强的动态文字和响应式横竖屏适配，优先使用 Remotion。若只需要拼接、裁切、字幕和音频混合，ffmpeg 足够。

### 6.4 配音自动化

配音脚本按分镜生成，每句控制在 3-8 秒内：

```text
这是 Megawave，一个面向 Base 链交易的 Web 控制台。
市价单可以从表单直接生成标准命令。
每一笔交易都会经过报价、风控和人工确认。
限价单由本地 watcher 监控价格，到价后自动生成市价单。
自然语言会先被解析成可审查的命令预览。
订单状态、历史记录和链上链接会被统一沉淀。
```

输出：

- `voiceover.zh.mp3`
- `subtitles.zh.srt`
- 可选英文版 `voiceover.en.mp3` 和 `subtitles.en.srt`

## 7. 安全边界

### 7.1 默认安全模式

宣传片自动化默认使用：

```text
execution_mode=dry_run
live_enabled=false
```

这样可以完整展示命令、报价、风控、确认、订单状态，而不会真实广播交易。

### 7.2 sign_only 模式

如需展示签名能力，可以使用：

```text
execution_mode=sign_only
```

该模式可以展示签名结果，但不广播交易。

### 7.3 live 模式

如需展示真实 0.1 USD 小额交易：

- 自动化只负责填表、生成命令、展示待确认状态。
- 人工检查 Token、金额、执行模式、gas、风险提示。
- 人工触发确认。
- 自动化继续录制订单状态和 Tx 链接。

禁止在宣传片脚本中保存或读取私钥、助记词、主钱包敏感信息。

## 8. 验收标准

### 8.1 功能真实性

- 视频中的功能必须与当前 Web 端实现一致。
- 市价单必须展示表单生成 `/buy` 或 `/sell`。
- 限价单必须展示表单生成 `/limit_buy` 或 `/limit_sell`。
- 自然语言必须展示“解析为标准命令”与“是 / 否”确认预览。
- 不得把自然语言包装成直接执行交易。
- 不得把本地 watcher 限价单描述成 DEX 原生限价单。
- 跟单只做页面露出，不占主演示流程。

### 8.2 安全验收

- 视频中不得出现私钥、助记词、API key。
- 钱包地址和本地数据库路径需要打码或只展示短地址。
- 默认演示必须是 `dry_run` 或 `sign_only`。
- 如使用 live，必须保留人工确认片段或明确说明人工确认。
- 自然语言确认、拒绝、取消订单的禁区必须体现为“不能执行”或人工操作。

### 8.3 画面验收

- 16:9 版本分辨率不低于 1920x1080。
- 9:16 版本分辨率不低于 1080x1920。
- 页面文字清晰，无明显压缩糊化。
- 鼠标路径、表单输入、按钮点击可看清。
- 字幕不遮挡主要表单、按钮、订单状态。
- 订单状态、命令预览、是/否按钮至少各有一次清晰特写。

### 8.4 音频验收

- 配音无明显断句错误。
- 背景音乐不能盖过人声。
- 字幕与配音基本同步，误差不超过 300ms。
- 无明显爆音、底噪或音量忽大忽小。

### 8.5 自动化验收

- 一条命令可以重新录制主演示素材。
- 一条命令可以重新合成最终视频。
- 输出目录包含：
  - 横屏 mp4。
  - 竖屏 mp4。
  - 封面图。
  - 字幕文件。
  - 配音文件。
- 失败时能明确定位到录屏、配音、字幕或合成阶段。

### 8.6 测试验收

制作前至少通过以下测试：

```text
pytest -q \
  tests/test_command_parser.py \
  tests/test_nl_command_agent.py \
  tests/test_dashboard_static_ui.py \
  tests/test_dashboard_server.py \
  tests/test_simulated_telegram_flow.py
```

预期：

```text
32 passed
```

## 9. 第一阶段交付物

- `promo/scenes.yaml`
- `promo/record.ts`
- `promo/script.zh.md`
- `promo/subtitles.zh.srt`
- `promo/compose.tsx` 或 `promo/compose.sh`
- `promo/output/megawave-promo-16x9.mp4`
- `promo/output/cover.png`

第一阶段完成后，再扩展：

- 9:16 竖屏版。
- 英文旁白版。
- live 小额交易版。
- GitHub README 嵌入短版 GIF 或 MP4。

