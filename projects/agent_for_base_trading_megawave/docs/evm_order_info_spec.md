# EVM Market Order and Conditional Limit Order Info Spec

## 目标

本文定义 EVM 链市价单和本地 watcher 条件限价单的统一信息结构。它们是系统底层交易基础设施，后续 Telegram 参数命令、自然语言 Agent、跟单交易、聪明钱 cash flow 策略都必须转换成这里定义的订单信息，再交给 OrderService、RiskEngine 和 Execution Engine 处理。

本文只定义 info/spec，不涉及具体代码实现。

## 设计原则

- 订单参数必须结构化，不能依赖脚本里的散落变量。
- 市价单和条件限价单使用同一套基础字段。
- 条件限价单触发后必须转换成市价单执行。
- 策略层、Agent 层、Telegram 层不能直接接触私钥。
- 所有订单必须经过风控和状态记录。
- 敏感信息只通过引用传递，例如 `wallet_id`、`secret_ref`，不在订单参数中出现私钥明文。

## 基础概念

### Market Order

市价单表示“立即按当前可用报价执行 swap”。它适合：

- Telegram `/buy`、`/sell`、`/swap` 命令。
- 自然语言即时交易。
- 跟单策略生成的即时复制单。
- 条件限价单触发后的最终执行单。

### Conditional Limit Order

本地 watcher 条件限价单表示“机器人持续观察条件，满足后生成一笔 Market Order”。它不是链上原生限价单。

适合：

- 价格低于某值买入。
- 价格高于某值卖出。
- cash flow 超过阈值后买入。
- 目标地址买入后延迟确认执行。

限制：

- 需要本地进程在线。
- 触发价不等于最终成交价。
- 必须设置最大滑点和最大 price impact。
- 触发后仍需重新获取 OKX quote 并经过风控。

## 通用字段

所有订单都应包含以下字段。

```yaml
id: "ord_..."
source: "telegram_command | telegram_nl | agent | copy_trade | smart_money | cli | api | watcher"
order_type: "market | conditional"
chain:
  namespace: "evm"
  chain_id: 8453
  chain_name: "base"
wallet:
  wallet_id: "base_main"
  address: "0x..."
token_in:
  symbol: "USDC"
  address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
  decimals: 6
token_out:
  symbol: "VIRTUAL"
  address: "0x..."
  decimals: 18
amount:
  type: "exact_in"
  value: "200"
  unit: "token"
trade:
  side: "buy | sell | swap"
  route_provider: "okx"
  execution_mode: "immediate | watcher_triggered"
safety:
  max_slippage_percent: 0.8
  max_price_impact_percent: 3.0
  allow_partial_fill: false
  allow_honeypot: false
  max_buy_tax_percent: 5.0
  max_sell_tax_percent: 5.0
approval:
  require_confirmation: true
  confirmation_channel: "telegram"
metadata:
  note: ""
  created_by: "telegram_user_id"
  created_at: "2026-05-28T00:00:00Z"
```

## Market Order Info

### 最小参数

市价单最少需要：

- `source`
- `chain`
- `wallet.wallet_id`
- `token_in`
- `token_out`
- `amount`
- `safety.max_slippage_percent`
- `approval.require_confirmation`

### 标准示例

```yaml
order_type: "market"
source: "telegram_command"
chain:
  namespace: "evm"
  chain_id: 8453
  chain_name: "base"
wallet:
  wallet_id: "base_main"
token_in:
  symbol: "USDC"
  address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
  decimals: 6
token_out:
  symbol: "VIRTUAL"
  address: "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
  decimals: 18
amount:
  type: "exact_in"
  value: "200"
  unit: "token"
trade:
  side: "buy"
  route_provider: "okx"
  execution_mode: "immediate"
safety:
  max_slippage_percent: 0.8
  max_price_impact_percent: 3.0
  allow_honeypot: false
  max_buy_tax_percent: 5.0
  max_sell_tax_percent: 5.0
approval:
  require_confirmation: true
  confirmation_channel: "telegram"
```

### 市价单执行流程

```text
MarketOrder Info
  -> OrderService normalize
  -> TokenResolver 补全 decimals/address
  -> BalanceService 检查余额
  -> OKX Quote
  -> RiskEngine 检查滑点、price impact、honeypot、tax、金额
  -> ApprovalEngine 判断是否确认
  -> OKX Swap Tx
  -> LocalSigner 签名
  -> BroadcastService 广播
  -> ReceiptTracker 更新状态
```

## Conditional Limit Order Info

### 最小参数

条件限价单最少需要：

- `source`
- `chain`
- `wallet.wallet_id`
- `trigger`
- `action`
- `safety`
- `lifecycle`

### 价格条件单示例

```yaml
order_type: "conditional"
source: "telegram_nl"
chain:
  namespace: "evm"
  chain_id: 8453
  chain_name: "base"
wallet:
  wallet_id: "base_main"
trigger:
  type: "price"
  source: "debank"
  token:
    symbol: "VIRTUAL"
    address: "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
  operator: "<="
  target_price_usd: "1.20"
  poll_interval_seconds: 30
action:
  order_type: "market"
  token_in:
    symbol: "USDC"
    address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    decimals: 6
  token_out:
    symbol: "VIRTUAL"
    address: "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
    decimals: 18
  amount:
    type: "exact_in"
    value: "200"
    unit: "token"
  trade:
    side: "buy"
    route_provider: "okx"
safety:
  max_slippage_percent: 0.8
  max_price_impact_percent: 3.0
  allow_honeypot: false
  max_buy_tax_percent: 5.0
  max_sell_tax_percent: 5.0
approval:
  require_confirmation_on_create: false
  require_confirmation_on_trigger: true
  confirmation_channel: "telegram"
lifecycle:
  status: "active"
  expires_at: "2026-05-29T00:00:00Z"
  cancel_after_trigger_failure: false
  max_trigger_attempts: 3
```

### 条件触发流程

```text
ConditionalOrder ACTIVE
  -> Watcher poll price
  -> Trigger condition matched
  -> Build MarketOrder from action
  -> OKX Quote
  -> RiskEngine re-check
  -> Telegram confirmation if required
  -> Execute MarketOrder
  -> ConditionalOrder FILLED / FAILED / EXPIRED
```

## 参数管理方案

参数分四层管理。

### 1. Runtime Config

运行环境，不含私钥明文。

```yaml
chains:
  base:
    namespace: "evm"
    chain_id: 8453
    rpc_url_ref: "ENV:BASE_RPC_URL"

wallets:
  base_main:
    chain: "base"
    address: "0x..."
    signer_ref: "KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1"

providers:
  debank:
    access_key_ref: "ENV:DEBANK_ACCESS_KEY"
  okx:
    api_key_ref: "ENV:OKX_API_KEY"
    secret_key_ref: "ENV:OKX_SECRET_KEY"
    passphrase_ref: "ENV:OKX_API_PASSPHRASE"
    project_id_ref: "ENV:OKX_PROJECT_ID"
```

### 2. Risk Policy

全局风控默认值。

```yaml
risk:
  max_single_trade_usd: 500
  max_daily_trade_usd: 3000
  max_slippage_percent: 1.0
  max_price_impact_percent: 3.0
  allow_honeypot: false
  max_buy_tax_percent: 5.0
  max_sell_tax_percent: 5.0
  require_confirmation_for_natural_language: true
```

### 3. Strategy Config

策略参数。

```yaml
copy_trade:
  enabled: true
  target_addresses:
    - "0x..."
  max_delay_seconds: 300
  buy_ratio: 0.3
  sell_ratio: 0.5
  max_copy_trade_usd: 300

conditional_order:
  default_price_source: "debank"
  poll_interval_seconds: 30
  default_expire_hours: 24
  require_confirmation_on_trigger: true
```

### 4. Per-order Overrides

单笔订单可以覆盖部分参数，但不能突破全局风控上限。

例如用户指定：

```yaml
safety:
  max_slippage_percent: 0.5
```

如果全局最大滑点是 `1.0%`，该订单有效。如果用户指定 `3.0%`，RiskEngine 必须拒绝或降级到全局上限，不能直接执行。

## 密钥保密方案

### 核心边界

密钥不属于订单参数。订单参数只引用 `wallet_id` 或 `signer_ref`。

```text
OrderInfo.wallet.wallet_id = "base_main"
RuntimeConfig.wallets.base_main_test.signer_ref = "KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1"
LocalSigner -> SecretProvider -> Keychain/Env -> private key
```

上层模块只能看到：

```yaml
wallet:
  wallet_id: "base_main"
  address: "0x..."
```

不能看到：

```yaml
private_key: "0x..."
```

### SecretProvider

统一密钥读取接口。

```text
SecretProvider
  EnvSecretProvider
  KeychainSecretProvider
  CompositeSecretProvider
```

读取规则：

- `ENV:DEBANK_ACCESS_KEY` 从环境变量读取。
- `KEYCHAIN:base_wallet_main` 从 macOS Keychain 读取。
- 业务模块只拿 `secret_ref`，不能自己读取系统密钥。

### LocalSigner

LocalSigner 是唯一允许使用私钥的模块。

职责：

- 接收待签名交易。
- 根据 `wallet_id` 找到 `signer_ref`。
- 通过 SecretProvider 读取私钥。
- 签名交易。
- 立即清理局部私钥变量。
- 返回 signed transaction。

禁止：

- 打印私钥。
- 返回私钥。
- 把私钥传给 Agent。
- 把私钥传给 Telegram。
- 把私钥写入数据库。

### 数据库存储边界

数据库可以存：

- `wallet_id`
- `wallet_address`
- `order_id`
- `quote`
- `risk_decision`
- `tx_hash`
- `signed_tx_hash`
- `status`

数据库不能存：

- private key
- Telegram bot token
- OKX secret
- DeBank access key
- OpenAI key

### 日志边界

日志允许：

- 地址截断显示，例如 `0x1234...abcd`
- token symbol
- token address
- tx hash
- 风控结论
- 错误类型

日志禁止：

- private key
- mnemonic
- API secret
- Telegram token
- raw signed transaction，除非明确进入 debug 安全模式且本地文件加密

### 交易签名安全流程

```text
OrderService
  -> RiskEngine approved
  -> ApprovalEngine confirmed
  -> Executor build unsigned tx
  -> LocalSigner.sign(wallet_id, unsigned_tx)
       -> SecretProvider.resolve(signer_ref)
       -> sign transaction locally
       -> clear private key variable
  -> BroadcastService.broadcast(signed_tx)
```

### 当前旧代码迁移要求

旧代码中已经存在硬编码和打印敏感信息的问题。迁移时必须：

- 删除硬编码 OKX key。
- 删除硬编码 DeBank key。
- 删除硬编码 Telegram bot token。
- 删除 import 时读取私钥的行为。
- 删除任何打印 key/token/private_key 的语句。
- 将所有私钥读取移动到 LocalSigner。
- 已暴露过的 key/token 后续应旋转。

## 信息结构与上层任务适配

### Telegram 参数命令

命令：

```text
/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 200
```

转换为：

```text
MarketOrder Info
```

Telegram 交易命令只接受合约地址，默认中间资产为 Base USDC。`/buy TOKEN_OUT_ADDRESS AMOUNT` 的 `AMOUNT` 是 USDC 数量；`/sell TOKEN_IN_ADDRESS AMOUNT` 的 `AMOUNT` 是卖出代币数量，默认卖成 USDC。如需覆盖默认中间资产，使用 `--with TOKEN_IN_ADDRESS` 或 `--to TOKEN_OUT_ADDRESS`。限价单使用 `TOKEN_ADDRESS AMOUNT at TARGET_PRICE`，`TARGET_PRICE` 是 USD 计价触发价；`/limit_buy` 用 `<=` 触发，`/limit_sell` 用 `>=` 触发。

### 自然语言

输入：

```text
VIRTUAL 跌到 1.2 用 200U 买入，滑点 0.8%
```

转换为：

```text
ConditionalOrder Info
```

### 跟单交易

检测目标地址买入：

```text
target bought TOKEN with 1000 USDC
```

转换为：

```text
MarketOrder Info
source = copy_trade
amount = min(1000 * copy_ratio, max_copy_trade_usd)
```

### 聪明钱 Cash Flow

检测信号：

```text
TOKEN 1h smart money net inflow > 500000 USDC
```

转换为：

```text
Signal only
or ConditionalOrder / MarketOrder after policy approval
```

## 建议文件落点

后续实现时建议：

```text
app/core/order_info.py
app/core/order_state.py
app/config/settings.py
app/config/risk_policy.yaml
app/config/strategies.yaml
app/secrets/provider.py
app/signing/local_signer.py
app/orders/order_service.py
app/orders/conditional_watcher.py
app/execution/okx_executor.py
```
