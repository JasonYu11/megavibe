# Agent Trading Framework Architecture Plan

## 目标

构建一个面向 Base 链交易的本地 Agent 交易框架。系统需要覆盖旧架构已有能力，包括市价单、跟单交易、Telegram 通知、DeBank 数据查询、OKX Swap 执行，同时为后续自然语言下单、条件限价单、聪明钱 cash flow 分析和策略交易留下规范扩展空间。

核心原则：

- 市价单和本地 watcher 条件单是交易基础设施。
- 跟单、自然语言、聪明钱策略、Telegram 命令都只是订单意图来源。
- 上层策略不直接调用 OKX、不直接签名、不直接广播。
- 每笔交易必须经过统一风控、确认和状态记录。
- 私钥只允许在本地签名模块中出现。

## 当前架构收口目标：真实广播优先

当前 Phase 1 不再只以 dry-run/sign-only 作为完成依据，而是以小额真实广播测试作为最终验收核心。系统架构必须支持并记录真实交易闭环：

```text
OrderIntent
  -> OrderService
  -> RiskEngine
  -> Approval
  -> OKX Quote / Swap Tx
  -> LocalSigner
  -> OKX v6 Broadcast
  -> ReceiptTracker
  -> DeBank / OKX / RPC Observation
  -> SQLite Evidence
  -> Telegram / CLI Notification
```

真实广播验收边界：

- 只在 Base 链 `chain_id=8453`。
- 只用测试钱包。
- 默认交易价值约 `0.01 USD`，自动化测试硬上限 `0.05 USD`。
- ETH 交易使用 Base 原生 ETH，不使用 WETH 替代。
- 市价单必须完成真实 broadcast。
- 本地 watcher 限价单必须完成真实价格触发到 live broadcast。
- 所有真实广播必须持久化 order、quote、risk decision、approval、execution、receipt/post-trade observation，默认写入 `var/phase1_live_evidence.sqlite`。

## 总体架构

```text
Interfaces
  Telegram Bot
  CLI / Admin API
  Future Web UI

Intent Layer
  Parameter Command Parser
  Natural Language Agent
  CopyTrade Strategy
  SmartMoney CashFlow Strategy

Order Layer
  Order Service
  Market Order
  Conditional Order / Local Watcher
  Order State Machine

Risk Layer
  Risk Engine
  Approval Engine
  Policy Config

Data Layer
  DeBank Client
  OKX Quote Client
  Price Service
  Token Resolver
  Wallet Portfolio Service

Execution Layer
  OKX Swap Executor
  Local Signer
  Broadcast Service
  Receipt Tracker

Storage Layer
  SQLite / Postgres
  Order DB
  Strategy DB
  Event Log
  Position / PnL Records

Security Layer
  Secret Provider
  Keychain / Env
  Audit Log

Verification Layer
  Environment Check
  Live DeBank Read Tests
  Live OKX Quote Tests
  Live Telegram Tests
  Sign-Only Swap Tests
  Small Live Swap Tests
  Receipt / Post-Trade Observation
```

## 核心数据流

```text
用户/策略输入
  -> 生成 OrderIntent
  -> OrderService 标准化
  -> RiskEngine 风控检查
  -> QuoteService 获取报价
  -> ApprovalEngine 决定是否 Telegram 确认
  -> Executor 构造交易
  -> LocalSigner 本地签名
  -> BroadcastService 广播
  -> ReceiptTracker 跟踪结果
  -> Storage 记录状态
  -> Telegram 回传通知
```

## 真实验证层

真实验证层用于第一阶段验收，不是产品运行时的默认路径。它的目标是证明系统能在真实 DeBank、OKX、Telegram、Base RPC 和本地 Keychain 上闭环，同时把真实交易风险限制在测试钱包和小额金额内。

验收流：

```text
EnvironmentCheck
  -> DeBank token/balance/history read
  -> OKX quote
  -> Telegram sendMessage/getUpdates
  -> OKX swap transaction build
  -> LocalSigner sign_only
  -> OKX small live broadcast
  -> ReceiptTracker
  -> DeBank or OKX/RPC post-trade observation
  -> SQLite evidence
```

真实验证层的安全不变量：

- 默认不运行，必须显式打开 live test env flag。
- 真实广播只允许 Base 链 `chain_id=8453`。
- 只允许测试钱包，禁止主资金钱包。
- 第一阶段 live swap 默认约 `0.01 USD` 价值，自动化测试硬上限 `0.05 USD`。
- ETH 真实测试使用 Base 原生 ETH 地址 `0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE`，不是 WETH。
- sign_only 真实矩阵覆盖 `ETH -> USDC` 和 `USDC -> VIRTUAL`，live 广播通过 `LIVE_TRADE_ROUTE` 选择单条极小额路径。
- 真实广播必须同时满足 `RUN_LIVE_TRADE_TESTS=1` 和 `CONFIRM_LIVE_TRADE_BASE=YES`。
- 本地 watcher 限价单真实广播还必须额外满足 `CONFIRM_LIVE_LIMIT_TRADE_BASE=YES`。
- 私钥只通过 Keychain signer ref 读取，不进入 env、yaml、日志或 Telegram 消息。
- DeBank access key、OKX secret、Telegram bot token 不允许出现在日志、测试失败信息或消息正文中。
- 不使用 Basescan API；交易链接可以使用 OKLink 或其他非 API 浏览器链接。
- 每次 live 测试都必须留下持久 SQLite order/execution/event 和 `docs/phase1_progress.md` 验收记录。

## 订单基础设施

系统底座只保留两类订单。

EVM 市价单和本地 watcher 条件限价单的详细参数规格见 [evm_order_info_spec.md](evm_order_info_spec.md)。

### MarketOrder

立即执行市价 swap。执行前必须获取报价并通过风控检查。

典型来源：

- Telegram 参数命令
- 自然语言 Agent
- 跟单策略
- 条件单触发后生成的执行单
- 手动 CLI/API

### ConditionalOrder

本地 watcher 条件单。条件满足后生成一笔 MarketOrder，再走同一套风控、确认、签名和广播流程。

适用场景：

- 本地限价单，例如 `VIRTUAL <= 1.2 时用 200 USDC 买入`
- 时间窗口触发
- cash flow 条件触发
- 目标地址交易行为触发

注意：本地 watcher 条件单不是链上原生限价单。触发价和最终成交价可能不同，必须用 `max_slippage`、`max_price_impact` 和二次 quote 校验保护。

## 统一订单意图

所有上层输入最终都转换成 `OrderIntent`。

```json
{
  "source": "telegram_nl",
  "order_type": "market",
  "chain": "base",
  "side": "swap",
  "token_in": "USDC",
  "token_out": "VIRTUAL",
  "amount_in": "200",
  "max_slippage_percent": 0.8,
  "require_confirmation": true
}
```

条件单示例：

```json
{
  "source": "telegram_nl",
  "order_type": "conditional",
  "chain": "base",
  "trigger": {
    "type": "price",
    "operator": "<=",
    "price": 1.2,
    "source": "debank"
  },
  "action": {
    "token_in": "USDC",
    "token_out": "VIRTUAL",
    "amount_in": "200",
    "max_slippage_percent": 0.8
  }
}
```

## 模块职责

### Telegram Bot

- 接收参数命令。
- 接收自然语言交易请求。
- 展示 quote 和风险摘要。
- 发送确认按钮。
- 推送成交、失败、取消、风控拒绝消息。
- 不直接签名或广播交易。

### Natural Language Agent

- 将自然语言转成结构化 `OrderIntent` 或查询请求。
- 可以调用只读工具，例如 token 信息、钱包资产、订单状态。
- 不能接触私钥。
- 不能直接调用交易执行器。
- 默认自然语言交易需要人工确认。

### Order Service

- 创建订单。
- 标准化 token、数量、链、滑点。
- 管理 MarketOrder 和 ConditionalOrder。
- 调用 RiskEngine、QuoteService、ApprovalEngine 和 Executor。
- 维护订单状态机。

### Conditional Watcher

- 周期扫描 active 条件单。
- 查询 DeBank price 或 OKX quote。
- 判断触发条件。
- 触发后生成 MarketOrder。
- 支持暂停、取消、过期和失败重试。

### Risk Engine

统一检查：

- 单笔最大金额。
- 每日最大交易额。
- 最大滑点。
- 最大 price impact。
- honeypot 标记。
- 买卖税率。
- token 白名单/黑名单。
- 合约黑名单。
- 钱包余额。
- 是否需要人工确认。

### DeBank Client

DeBank 是主要数据层，用来替代旧 Basescan 查询路径。

职责：

- 查询目标地址历史交易。
- 查询钱包资产。
- 查询 token 信息和价格。
- 查询 top holders。
- 支持聪明钱 cash flow 分析。

旧功能映射：

```text
旧 Basescan tokentx/internal tx
  -> DeBank user history_list

旧 token price / holders
  -> DeBank token/list_by_ids + token/top_holders

旧钱包资产检查
  -> DeBank user token_list / user token / chain balance

聪明钱 cash_flow
  -> DeBank history + token_dict + wallet/token balance
```

风险点：DeBank 更适合地址历史和资产分析，不一定适合极低延迟监听。如果跟单需要秒级响应，后续可以增加 RPC websocket/log listener，但第一版按 DeBank-only 设计。

### OKX Client

OKX 是交易通道。

职责：

- 获取 quote。
- 获取 swap transaction。
- 获取 approve transaction。
- 广播 signed transaction。
- 查询交易状态。

执行前必须检查 OKX 返回字段：

- `minReceiveAmount`
- `priceImpactPercent`
- `isHoneyPot`
- `taxRate`
- `tradeFee`
- `routerResult`

### Local Signer

- 从 SecretProvider 读取私钥。
- 只签署已经通过风控和确认的交易。
- 不记录私钥。
- 不打印私钥。
- 不向 Agent、Telegram 或策略层暴露私钥。

### Storage

第一版使用 SQLite，后续可迁移 Postgres。

需要记录：

- 订单。
- 条件单。
- 跟单事件。
- cash flow 信号。
- quote 快照。
- 风控决策。
- 广播结果。
- tx hash。
- 错误日志。
- 审计事件。

## 配置体系

配置分三类。

### Secrets

敏感信息不进入普通配置文件，不提交 git。

包括：

- `WALLET_PRIVATE_KEY` 或本地 keychain 引用。
- `DEBANK_ACCESS_KEY`
- `OKX_API_KEY`
- `OKX_SECRET_KEY`
- `OKX_API_PASSPHRASE`
- `OKX_PROJECT_ID`
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`

### Runtime Config

运行环境配置，不包含敏感值。

示例：

```yaml
chain:
  name: base
  chain_id: 8453
  rpc_url_ref: ENV:BASE_RPC_URL

wallet:
  address: "0x..."
  private_key_ref: KEYCHAIN:base_wallet_main

telegram:
  chat_id: "-100..."
  bot_token_ref: ENV:TELEGRAM_BOT_TOKEN

debank:
  access_key_ref: ENV:DEBANK_ACCESS_KEY

okx:
  api_key_ref: ENV:OKX_API_KEY
  secret_key_ref: ENV:OKX_SECRET_KEY
  passphrase_ref: ENV:OKX_API_PASSPHRASE
  project_id_ref: ENV:OKX_PROJECT_ID
```

### Policy Config

风控和策略参数。

示例：

```yaml
risk:
  max_single_trade_usd: 500
  max_daily_trade_usd: 3000
  max_slippage_percent: 1.0
  max_price_impact_percent: 3.0
  allow_honeypot: false
  max_buy_tax_percent: 5
  max_sell_tax_percent: 5
  require_confirm_for_natural_language: true

copy_trade:
  enabled: true
  max_delay_seconds: 300
  buy_ratio: 0.3
  sell_ratio: 0.5
  max_copy_trade_usd: 300

conditional_order:
  poll_interval_seconds: 30
  default_expire_hours: 24
  require_confirm_on_trigger: true
```

## 密钥管理原则

- 业务模块不能直接读取环境变量或 keychain。
- 统一通过 `SecretProvider` 读取。
- 不允许模块 import 时读取密钥。
- 不允许日志打印 key、token、private key。
- 私钥只在 `LocalSigner` 中使用。
- 已硬编码或已经出现在历史代码中的 key/token 应视为已暴露，后续需要旋转。

建议实现：

```text
SecretProvider
  EnvSecretProvider
  KeychainSecretProvider
  CompositeSecretProvider
```

## 订单状态机

### MarketOrder

```text
DRAFT
RISK_CHECKED
PENDING_CONFIRMATION
APPROVED
QUOTED
SIGNING
BROADCASTED
FILLED
FAILED
CANCELLED
```

### ConditionalOrder

```text
ACTIVE
TRIGGERED
PENDING_CONFIRMATION
EXECUTING
FILLED
FAILED
EXPIRED
CANCELLED
PAUSED
```

## 策略层

策略层只产生订单意图，不执行交易。

### CopyTradeStrategy

- 使用 DeBank 查询目标地址历史。
- 识别 buy、sell、exchange。
- 根据策略参数生成 OrderIntent。
- 不直接调用 OKX。

### SmartMoneyCashFlowAnalyzer

- 聚合地址、token、时间窗口内的资金流。
- 输出信号、排名和告警。
- 可选生成 OrderIntent，但必须经过 RiskEngine。

### NaturalLanguageStrategy

- 将用户自然语言转成 OrderIntent 或 ConditionalOrder。
- 不直接执行。
- 默认需要确认。

## 第一版范围

第一版只做稳定基础设施：

1. DeBank 替代 Basescan 查询链路。
2. OKX 市价单执行。
3. 本地 watcher 条件单。
4. Telegram 命令和确认。
5. 统一 OrderService。
6. 统一 RiskEngine。
7. SQLite 状态持久化。
8. SecretProvider 密钥管理。
9. 小额真实交易验收测试。

暂不做：

- 链上原生限价单。
- 完全自动多 Agent 自主交易。
- 多链并发。
- 复杂 Web UI。
- 高频低延迟监听。
- 默认开启真实交易。

## 推荐实施顺序

第一阶段的可验证开发计划见 [phase1_development_plan.md](phase1_development_plan.md)。

1. 建立新目录结构和配置体系。
2. 迁移密钥读取，删除硬编码敏感信息。
3. 建立 `OrderIntent`、`MarketOrder`、`ConditionalOrder` 数据模型。
4. 建立 SQLite 存储。
5. 实现 DeBank client。
6. 实现 OKX v6 client。
7. 实现 RiskEngine。
8. 将旧 `okx_swap_mev()` 包装成 MarketOrder 执行器。
9. 实现 Conditional Watcher。
10. 接入 Telegram 命令和确认。
11. 迁移旧跟单逻辑到 CopyTradeStrategy。
12. 完成真实服务验收：DeBank、OKX quote、Telegram、sign_only、小额 live swap、receipt/post-trade observation。
13. 再接自然语言 Agent。
