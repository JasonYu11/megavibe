# Phase 1 Development Plan With Verifiable Tests

## 目标

第一阶段目标是建立安全、可测试、可扩展的 EVM/Base 交易底座：

```text
Telegram / CLI / Strategy / Natural Language
  -> OrderIntent
  -> OrderService
  -> RiskEngine
  -> Quote
  -> LocalSigner
  -> Broadcast
  -> SQLite State
```

阶段一完成后，系统应具备：

- 不依赖 Basescan。
- 支持 EVM 市价单。
- 支持本地 watcher 条件限价单。
- 使用 DeBank 作为主要数据层。
- 使用 OKX 作为报价、swap tx、广播通道。
- 私钥只在 LocalSigner 中使用。
- 所有订单状态落库。
- Telegram 可以查询、下单、确认、取消。

## 当前执行目标：真实广播测试收口

从当前阶段开始，Phase 1 的收口目标调整为以真实广播测试为核心。`dry_run` 和 `sign_only` 仍然是必需的安全前置步骤，但不能替代 Phase 1 完成条件。

Phase 1 必须用真实广播证明以下链路可用：

- 原生 ETH、USDC、VIRTUAL 三个资产之间的 OKX 真实交易路径可用。
- 市价单可以完成 quote、risk、approval、LocalSigner、本地签名、OKX v6 broadcast、receipt/post-trade observation。
- 本地 watcher 限价单可以真实读取 DeBank 价格，触发后生成 MarketOrder，并在显式确认下完成 live broadcast。
- 每笔真实广播测试金额默认约 `0.01 USD` 价值，硬上限 `0.05 USD`，只允许测试钱包。
- 真实广播结果必须进入可审计证据：SQLite 持久库、pytest 输出和 `docs/phase1_progress.md` 至少两处。

当前真实广播验收优先级：

1. 持久化 `USDC_TO_VIRTUAL` 和原生 `ETH_TO_USDC` 两条 0.01 USD live swap 证据。
2. 持久化本地 watcher 限价单显式确认后的 0.01 USD live broadcast 验收。
3. 用 DeBank/OKX/RPC 对真实交易做 post-trade observation。
4. 将 Telegram 通知接入真实广播结果回传。

## 测试模式

所有交易执行相关测试必须区分三种模式。

```yaml
execution_mode: dry_run
```

只做参数校验、quote、风控、订单状态流转，不签名，不广播。

```yaml
execution_mode: sign_only
```

构造 unsigned tx，本地签名，但不广播。

```yaml
execution_mode: live
```

真实广播交易。只允许在显式配置、测试钱包、小额金额、Telegram 确认后执行。

默认开发测试必须使用 `dry_run`。

## 全局测试约束

- 任何测试不得读取或打印私钥明文。
- 任何测试不得打印 API secret、Telegram bot token。
- 未显式设置 `execution_mode: live` 时不得广播交易。
- live 测试必须使用测试钱包。
- live 测试单笔金额默认约 `0.01 USD` 价值，硬上限不超过 `0.05 USD` 价值。
- ETH 测试使用 Base 原生 ETH 地址 `0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE`，不是 WETH。
- live 测试必须同时设置 `RUN_LIVE_TRADE_TESTS=1` 和 `CONFIRM_LIVE_TRADE_BASE=YES`。
- 所有网络测试要能通过环境变量开关跳过。

建议测试标记：

```text
unit: 不访问网络，不签名真实交易。
integration: 访问 DeBank/OKX/RPC，但不广播。
signing: 读取本地 Keychain 并签名，不广播。
live: 小额真实广播，默认跳过。
```

## 真实测试配置

真实测试用于第一阶段最终验收，但不得作为默认测试运行。所有真实测试必须可单独运行、可明确跳过、可审计结果。

需要的配置：

```bash
DEBANK_ACCESS_KEY=...

OKX_API_KEY=...
OKX_SECRET_KEY=...
OKX_API_PASSPHRASE=...
OKX_PROJECT_ID=...

TELEGRAM_BOT_TOKEN=...
TELEGRAM_DEFAULT_CHAT_ID=...

BASE_RPC_URL=https://mainnet.base.org
LIVE_TRADE_USD_VALUE=0.01
LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL
LIVE_EVIDENCE_DB_PATH=var/phase1_live_evidence.sqlite
CONFIRM_LIVE_LIMIT_TRADE_BASE=NO
DEBANK_TEST_ADDRESS=...
```

钱包私钥只允许放在 macOS Keychain：

```text
KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1
```

写入命令：

```bash
security add-generic-password -U \
  -a base_main_test \
  -s AGENT_WALLET_PRIVATE_KEY_BASE_TEST1 \
  -w 'YOUR_TEST_WALLET_PRIVATE_KEY'
```

测试钱包要求：

- Base 主网测试钱包。
- 有少量 ETH 支付 gas。
- 有少量 Base USDC 做 swap 测试。
- 不使用主资金钱包。
- live swap 默认 `LIVE_TRADE_USD_VALUE=0.01`。
- 测试硬上限 `LIVE_TRADE_USD_VALUE <= 0.05`。
- sign_only 真实矩阵覆盖 `ETH -> USDC` 和 `USDC -> VIRTUAL`，其中 ETH 使用原生 ETH。

真实测试执行顺序：

1. 环境检查：DeBank、OKX、Telegram、Base RPC、Keychain 全部 OK。
2. DeBank 只读测试：token info、wallet balance、user history。
3. OKX 只读测试：quote。
4. Telegram 只读/发送测试：sendMessage、getUpdates。
5. OKX `sign_only`：真实 swap tx 构造 + 本地签名 + 不广播。
6. OKX 小额 live swap：显式确认后广播。
7. receipt tracking：通过 OKX 查询广播结果。
8. DeBank post-trade observation：验证测试钱包历史中可观察到交易活动。

推荐命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m app.config.environment_check
PYTHONDONTWRITEBYTECODE=1 pytest -q tests
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_DEBANK_TESTS=1 pytest -q tests/test_live_integrations.py
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_okx_quote_when_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TELEGRAM_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_telegram_send_message_when_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_okx_swap_sign_only_when_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_conditional_limit_sign_only_when_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL pytest -q tests/test_live_integrations.py::test_live_small_trade_when_explicitly_enabled
```

真实测试证据必须落到以下至少一种位置：

- pytest 输出。
- SQLite order/execution/event 记录。
- `docs/phase1_progress.md` 的人工验收记录。

真实交易不以“命令执行过”为完成标准，必须能说明：

- 使用的是 Base 链 `chain_id=8453`。
- 使用的是测试钱包，不是主资金钱包。
- 金额按 `LIVE_TRADE_USD_VALUE` 折算成 token exact-in 数量，且不超过 `0.05 USD` 价值。
- 交易经过 quote、risk、approval、sign、broadcast、receipt tracking。
- Telegram 或 CLI 至少有一种方式能回传订单状态和 tx link。
- 交易后能通过 DeBank 或 OKX/RPC 观察到结果。
- live broadcast 证据必须写入 `LIVE_EVIDENCE_DB_PATH`，默认 `var/phase1_live_evidence.sqlite`。

## Step 1: 项目骨架和配置加载

### 开发内容

建立新目录：

```text
app/
  core/
  config/
  secrets/
  signing/
  data/
  execution/
  risk/
  orders/
  storage/
  bot/
  strategies/
tests/
```

实现配置加载：

- runtime config
- risk policy
- strategies config
- env loading

### 可验证测试

#### Test 1.1: 配置文件可解析

输入：

- `configs/runtime.example.yaml`
- `configs/risk_policy.example.yaml`
- `configs/strategies.example.yaml`

测试：

```text
load all example configs
validate required fields
```

通过标准：

- 三个配置文件都能解析。
- `execution_mode` 默认为 `dry_run`。
- `wallets.base_main_test.signer_ref` 等于 `KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1`。
- 风控默认 `max_single_trade_usd <= 5`。

#### Test 1.2: 缺失配置会失败

输入：

- 删除 `wallets` 或 `risk.max_single_trade_usd` 的测试配置。

通过标准：

- 配置加载失败。
- 错误信息能指出缺失字段。

## Step 2: SecretProvider 和 LocalSigner

### 开发内容

实现：

```text
SecretProvider
  EnvSecretProvider
  KeychainSecretProvider
  CompositeSecretProvider

LocalSigner
```

密钥引用格式：

```text
ENV:DEBANK_ACCESS_KEY
KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1
```

### 可验证测试

#### Test 2.1: EnvSecretProvider

输入：

```text
ENV:TEST_SECRET_VALUE
```

通过标准：

- 能读取测试环境变量。
- 未设置变量时返回明确错误。
- 日志不包含 secret value。

#### Test 2.2: KeychainSecretProvider

输入：

```text
KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1
```

通过标准：

- 能读取本地 Keychain item。
- 读取失败时返回明确错误。
- 测试输出不显示私钥。

#### Test 2.3: LocalSigner sign_only

输入：

- 一笔本地 mock EVM transaction。
- `wallet_id=base_main_test`。

通过标准：

- 能生成 signed transaction。
- 能从 signed transaction 恢复 signer address。
- 不广播。
- 日志不包含私钥。

#### Test 2.4: 禁止 import 读取私钥

测试：

```text
import app modules
```

通过标准：

- import 不访问 Keychain。
- import 不访问 ENV secret。
- 只有显式调用 `LocalSigner.sign()` 时读取私钥。

## Step 3: 订单模型

### 开发内容

实现：

```text
OrderIntent
MarketOrder
ConditionalOrder
QuoteResult
RiskDecision
ExecutionResult
OrderStatus
```

金额使用 Decimal，不使用 float。

### 可验证测试

#### Test 3.1: MarketOrder 最小参数校验

输入：

```yaml
order_type: market
source: cli
chain:
  chain_id: 8453
wallet:
  wallet_id: base_main_test
token_in:
  symbol: USDC
  address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
  decimals: 6
token_out:
  symbol: VIRTUAL
  address: "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
  decimals: 18
amount:
  type: exact_in
  value: "2"
```

通过标准：

- 构造成功。
- amount 是 Decimal。
- 缺少 token 或 amount 时校验失败。

#### Test 3.2: ConditionalOrder 生成 MarketOrder

输入：

- 一个 `price <= 1.2` 的条件单。

通过标准：

- 条件单 action 能生成 MarketOrder。
- 生成的 MarketOrder 保留 source、wallet、token、amount、safety。

#### Test 3.3: 金额精度测试

输入：

- `0.1`
- `0.000001`
- `1000000000.123456`

通过标准：

- 内部不出现 float。
- 转换 wei/token unit 可逆。

## Step 4: SQLite 存储层

### 开发内容

实现表：

```text
orders
conditional_orders
quotes
risk_decisions
executions
events
```

### 可验证测试

#### Test 4.1: 创建订单落库

输入：

- 一个 MarketOrder。

通过标准：

- `orders` 表新增记录。
- status 初始为 `DRAFT`。
- created_at 存在。

#### Test 4.2: 状态流转落库

输入：

```text
DRAFT -> RISK_CHECKED -> QUOTED -> PENDING_CONFIRMATION
```

通过标准：

- orders 当前状态正确。
- events 表有完整状态变更记录。

#### Test 4.3: active 条件单恢复

输入：

- 存入一个 `ACTIVE` 条件单。
- 重启 storage/session。

通过标准：

- 能查询出 active 条件单。
- 已 `FILLED/CANCELLED/EXPIRED` 的条件单不会被恢复为 active。

## Step 5: DeBank 数据层

### 开发内容

实现：

```text
DebankClient
  get_user_history()
  get_token_info()
  get_token_price()
  get_top_holders()
  get_user_token_list()
  get_user_chain_balance()
```

### 可验证测试

#### Test 5.1: token 信息查询

输入：

- Base USDC token address。

通过标准：

- 返回 symbol。
- 返回 decimals。
- 返回 price 或明确的空值。
- 不使用 Basescan。

#### Test 5.2: 地址历史查询

输入：

- 一个公开 Base 地址。

通过标准：

- 返回 history list。
- 能解析 send/receive token。
- 能提取 tx hash、时间、token_dict。

#### Test 5.3: top holders 查询

输入：

- 一个 Base token address。

通过标准：

- 返回 holder list 或明确错误。
- 错误不会导致程序崩溃。

#### Test 5.4: 无 API key 行为

输入：

- 不设置 `DEBANK_ACCESS_KEY`。

通过标准：

- client 初始化或请求失败。
- 错误信息明确。
- 不出现 traceback 泄露环境变量内容。

## Step 6: OKX v6 Client

### 开发内容

实现：

```text
OkxDexClient
  quote()
  approve_transaction()
  swap()
  broadcast()
  get_order_status()
```

### 可验证测试

#### Test 6.1: quote dry_run

输入：

- Base USDC -> VIRTUAL
- amount 2 USDC

通过标准：

- 返回 quote。
- 包含可用于风控的字段。
- 不签名。
- 不广播。

#### Test 6.2: swap tx dry_run

输入：

- 同上。

通过标准：

- 返回 unsigned tx 信息。
- 包含 to、data、value、gas 相关字段。
- 不签名。
- 不广播。

#### Test 6.3: 缺少 OKX key 行为

输入：

- 不设置 OKX key。

通过标准：

- quote/swap 返回明确错误。
- 不打印 secret ref 对应的真实值。

## Step 7: RiskEngine

### 开发内容

实现风控检查：

- 单笔最大金额。
- 每日最大金额。
- 最大滑点。
- 最大 price impact。
- honeypot。
- 买卖税率。
- token allowlist/blocklist。
- 合约 blocklist。
- 钱包余额。
- 是否需要确认。

### 可验证测试

#### Test 7.1: 金额超限拒绝

输入：

- `max_single_trade_usd=5`
- 订单金额 `10 USDC`

通过标准：

- RiskDecision 为 `REJECTED`。
- reason 包含 `max_single_trade_usd`。

#### Test 7.2: 未知 token 拒绝

输入：

- `allow_unknown_tokens=false`
- token 不在 allowed list。

通过标准：

- RiskDecision 为 `REJECTED`。

#### Test 7.3: price impact 超限拒绝

输入：

- mock quote `priceImpactPercent=10`
- policy `max_price_impact_percent=3`

通过标准：

- RiskDecision 为 `REJECTED`。

#### Test 7.4: 自然语言订单需要确认

输入：

- `source=telegram_nl`

通过标准：

- RiskDecision 或 ApprovalDecision 标记 `requires_confirmation=true`。

## Step 8: MarketOrderExecutor

### 开发内容

实现市价单执行管线：

```text
MarketOrder
  -> normalize
  -> quote
  -> risk check
  -> approval
  -> swap tx
  -> sign
  -> broadcast
  -> receipt tracking
```

### 可验证测试

#### Test 8.1: dry_run 全流程

输入：

- `execution_mode=dry_run`
- 2 USDC -> VIRTUAL。

通过标准：

- 创建订单。
- 获取 quote。
- 完成风控。
- 状态停在 `PENDING_CONFIRMATION` 或 `DRY_RUN_COMPLETED`。
- 不签名。
- 不广播。

#### Test 8.2: sign_only 全流程

输入：

- `execution_mode=sign_only`
- 测试钱包。

通过标准：

- 创建 unsigned tx。
- LocalSigner 签名。
- 不广播。
- 状态为 `SIGNED_NOT_BROADCASTED`。

#### Test 8.3: live 模式保护

输入：

- `execution_mode=live`
- 未确认订单。

通过标准：

- 不广播。
- 状态为 `PENDING_CONFIRMATION`。

#### Test 8.4: live 小额成交

默认跳过，只在手动允许时运行。

输入：

- 测试钱包。
- `RUN_LIVE_TRADE_TESTS=1`。
- `CONFIRM_LIVE_TRADE_BASE=YES`。
- `LIVE_TRADE_USD_VALUE=0.01`，硬上限不超过 `0.05`。
- `LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL` 或 `ETH_TO_USDC`。
- Telegram 或 CLI 明确确认。

通过标准：

- 广播成功。
- 返回 tx hash。
- receipt status 成功或失败都落库。
- Telegram/CLI 输出 tx link。
- DeBank 或 OKX/RPC 能在交易后观察到该测试钱包的状态变化或交易记录。

## Step 9: ConditionalOrderWatcher

### 开发内容

实现本地 watcher 条件单。

### 可验证测试

#### Test 9.1: 创建条件单

输入：

- `VIRTUAL <= 1.2 buy 2 USDC`

通过标准：

- 条件单入库。
- status 为 `ACTIVE`。
- trigger/action 字段完整。

#### Test 9.2: 条件未触发

输入：

- mock price 不满足条件。

通过标准：

- status 保持 `ACTIVE`。
- 不创建 MarketOrder。

#### Test 9.3: 条件触发

输入：

- mock price 满足条件。

通过标准：

- status 变为 `TRIGGERED`。
- 生成 MarketOrder。
- MarketOrder 继续走 RiskEngine。
- 不绕过确认。

#### Test 9.4: 条件单过期

输入：

- `expires_at` 小于当前时间。

通过标准：

- status 变为 `EXPIRED`。
- 不再轮询。

#### Test 9.5: 重启恢复

输入：

- active 条件单已在 SQLite。
- 重启 watcher。

通过标准：

- watcher 恢复该订单。
- 不重复触发已 filled 的订单。

## Step 10: Telegram 参数命令

### 开发内容

第一版只做参数命令，不做自然语言自动执行。

命令：

```text
/status
/balance
/quote 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 5
/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 5
/sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 10000
/limit_buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 5 at 1.2
/limit_sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 10000 at 1.8
/orders
/cancel ORDER_ID
/confirm ORDER_ID
/reject ORDER_ID
```

交易命令默认中间资产为 Base USDC。`/buy TOKEN_OUT_ADDRESS AMOUNT` 表示用 USDC 买入目标代币，`AMOUNT` 是 USDC 数量；`/sell TOKEN_IN_ADDRESS AMOUNT` 表示卖出该代币数量并默认换成 USDC。非 USDC 中间资产必须显式指定：`/buy TOKEN_OUT_ADDRESS AMOUNT --with TOKEN_IN_ADDRESS`，`/sell TOKEN_IN_ADDRESS AMOUNT --to TOKEN_OUT_ADDRESS`。限价单统一使用 `TOKEN_ADDRESS AMOUNT at TARGET_PRICE`，`TARGET_PRICE` 是 USD 计价触发价；`/limit_buy` 价格小于等于触发价时执行，`/limit_sell` 价格大于等于触发价时执行。交易代币参数只接受合约地址；原生 ETH 使用 OKX/native 地址 `0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE`。

### 可验证测试

#### Test 10.1: 命令解析

输入：

```text
/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 5
```

通过标准：

- 解析为 MarketOrder。
- source 为 `telegram_command`。
- amount 为 Decimal。

#### Test 10.2: quote 命令

输入：

```text
/quote 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 5
```

通过标准：

- 返回 quote 摘要。
- 不创建 live 交易。
- 不签名。

#### Test 10.3: confirm/reject

输入：

- 一个等待确认的订单。
- `/confirm ORDER_ID`
- `/reject ORDER_ID`

通过标准：

- confirm 后继续执行。
- reject 后状态为 `CANCELLED` 或 `REJECTED_BY_USER`。

#### Test 10.4: Telegram 消息安全

通过标准：

- 消息不包含私钥。
- 消息不包含 API key。
- 地址可以截断显示。
- tx hash 可以完整显示。

## Step 11: 旧功能迁移

### 开发内容

只迁移最关键旧能力：

```text
旧 okx_swap_mev
  -> MarketOrderExecutor

旧 followbot_v3_okxswap
  -> CopyTradeStrategy draft

旧 debank_token_info
  -> DebankClient + TokenReport
```

Kyber 和 Virtual.fun 专用执行器暂时保留为 legacy。

### 可验证测试

#### Test 11.1: 旧 OKX 市价能力覆盖

输入：

- 旧脚本支持的 USDC -> token swap 场景。

通过标准：

- 新 MarketOrderExecutor dry_run 能完成同样 quote/swap tx。
- 风控字段更完整。

#### Test 11.2: 跟单事件生成 OrderIntent

输入：

- mock DeBank history: target address buy token。

通过标准：

- CopyTradeStrategy 生成 MarketOrder。
- 不直接交易。
- source 为 `copy_trade`。
- amount obeys `buy_ratio` 和 `max_copy_trade_usd`。

#### Test 11.3: Token report 覆盖

输入：

- token address。

通过标准：

- 返回 token info。
- 返回 price。
- 返回 top holders。
- 能格式化 Telegram 消息。

## Step 12: 真实服务验收

### 开发内容

把 DeBank、OKX、Telegram、Base RPC、Keychain 和 SQLite 串成一组默认跳过的真实验收测试。该步骤不是新增交易功能，而是验证第一阶段交易底座能在真实服务中闭环。

验收链路：

```text
EnvironmentCheck
  -> DeBank read
  -> OKX quote
  -> Telegram send/getUpdates
  -> OKX swap sign_only
  -> OKX live small swap
  -> ReceiptTracker
  -> DeBank post-trade observation
  -> SQLite evidence
```

### 可验证测试

#### Test 12.1: 环境检查

输入：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m app.config.environment_check
```

通过标准：

- DeBank key 存在且不打印明文。
- OKX key/passphrase/project id 存在且不打印明文。
- Telegram bot token/chat id 存在且不打印明文。
- Base RPC 可配置。
- Keychain private key 可读取，但输出只显示 masked/ref/length。

#### Test 12.2: DeBank 真实只读

输入：

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_DEBANK_TESTS=1 pytest -q tests/test_live_integrations.py
```

通过标准：

- token info 可返回。
- 测试地址资产或链余额可返回。
- user history 查询不会依赖 Basescan。
- 输出不包含 DeBank access key。

#### Test 12.3: OKX 真实 quote

输入：

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_okx_quote_when_enabled
```

通过标准：

- Base USDC -> 目标 token quote 成功。
- 返回 `toTokenAmount` 或等价字段。
- 能解析 `priceImpactPercent`、fee、router result 中可用字段。
- 输出不包含 OKX secret。

#### Test 12.4: OKX sign_only 真实交易构造

输入：

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_okx_swap_sign_only_when_enabled
```

通过标准：

- OKX 返回 unsigned swap transaction。
- 本地 Keychain 私钥完成签名。
- 不广播。
- 签名结果和订单状态落库或被测试断言。

#### Test 12.5: Telegram 真实交互

输入：

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TELEGRAM_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_telegram_send_message_when_enabled
```

通过标准：

- bot 能向私人 chat id 发送测试消息。
- getUpdates 或等价接口能读取最近交互。
- 消息不包含 API key、bot token、private key。

#### Test 12.6: OKX 小额 live swap

输入：

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL LIVE_EVIDENCE_DB_PATH=var/phase1_live_evidence.sqlite pytest -q tests/test_live_integrations.py::test_live_small_trade_when_explicitly_enabled
```

通过标准：

- 只在 Base 链执行。
- 单笔金额默认约 `0.01 USD` 价值，自动化测试硬上限 `0.05 USD`。
- 交易通过 quote、risk、approval、sign、broadcast。
- 返回 tx hash 或 OKX order id。
- order/execution/event 至少记录 order id、mode、chain id、amount、status、tracking id。
- 证据写入 `LIVE_EVIDENCE_DB_PATH` 指向的持久 SQLite 文件。

#### Test 12.6b: 本地 watcher 限价单 sign_only

输入：

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 LIVE_TRADE_USD_VALUE=0.01 pytest -q tests/test_live_integrations.py::test_live_conditional_limit_sign_only_when_enabled
```

测试方法：

- 使用 DeBank 读取 VIRTUAL 当前价格。
- 创建一笔 `VIRTUAL <= current_price * 1.01` 的本地 watcher 条件单，使测试可立即触发。
- 条件触发后生成 `USDC -> VIRTUAL` MarketOrder。
- MarketOrder 继续走 quote、risk、approval、OKX swap tx、LocalSigner。
- 使用 `sign_only`，不广播。

通过标准：

- ConditionalOrder 从 `ACTIVE` 变为 `TRIGGERED`。
- 生成的 MarketOrder 进入 `SIGNED_NOT_BROADCASTED`。
- SQLite 记录 conditional status event、market order、quote、risk decision、execution。
- 不绕过二次 quote、风控或确认。

#### Test 12.6c: 本地 watcher 限价单 live broadcast

输入：

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES CONFIRM_LIVE_LIMIT_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_EVIDENCE_DB_PATH=var/phase1_live_evidence.sqlite pytest -q tests/test_live_integrations.py::test_live_conditional_limit_trade_when_explicitly_enabled
```

测试方法：

- 使用 DeBank 当前 VIRTUAL 价格创建一笔立即触发的本地 watcher 条件单。
- 条件触发后生成 `USDC -> VIRTUAL` MarketOrder。
- MarketOrder 继续走 quote、risk、approval、OKX swap tx、LocalSigner、OKX v6 broadcast。
- 交易后执行 receipt tracking 和 DeBank post-trade observation。

通过标准：

- ConditionalOrder 从 `ACTIVE` 变为 `TRIGGERED`。
- 生成的 MarketOrder 进入 `BROADCASTED`，随后 receipt tracking 返回 `BROADCASTED`、`FILLED` 或 `FAILED` 中的一种明确状态。
- SQLite 持久库记录 conditional event、market order、quote、risk decision、approval、execution、post-trade observation。
- Telegram 或 CLI 能输出 tracking reference。

#### Test 12.7: receipt 和 post-trade observation

输入：

- Test 12.6 生成的 tx hash 或 OKX order id。
- 测试钱包地址。

通过标准：

- ReceiptTracker 能返回明确状态。
- DeBank user history 或 wallet balance 能观察到交易后的活动或资产变化。
- 若 DeBank 延迟导致暂时不可见，必须记录 OKX/RPC receipt 成功，并在 `docs/phase1_progress.md` 标注 DeBank 延迟复查时间。

## 完成标准

第一阶段完成必须全部满足：

- 所有 unit tests 通过。
- 所有 dry_run integration tests 通过。
- DeBank 真实只读测试通过，且不使用 Basescan。
- OKX 真实 quote 测试通过。
- sign_only 能构造真实 OKX swap tx、签名但不广播。
- Telegram 真实 sendMessage/getUpdates 通过。
- live 小额测试至少成功执行一次，默认约 `0.01 USD` 价值，硬上限 `0.05 USD`，且可通过配置关闭。
- 本地 watcher 限价单 live broadcast 至少成功执行一次，且写入持久 SQLite 证据库。
- live 交易完成后，receipt tracking 和 DeBank/OKX/RPC post-trade observation 至少一种真实证据可追踪。
- 无 Basescan 依赖进入新主流程。
- 私钥只在 LocalSigner 中读取。
- 订单参数不包含私钥明文。
- 所有订单状态写入 SQLite。
- 条件单可创建、触发、取消、过期、重启恢复。
- Telegram 可以完成查询、下单、确认、取消。
- 旧跟单逻辑迁移为 OrderIntent 生成器，不直接交易。

## 推荐执行顺序

1. 项目骨架 + 配置加载。
2. SecretProvider + LocalSigner。
3. 订单模型。
4. SQLite 存储层。
5. DeBankClient。
6. OKX v6 Client。
7. RiskEngine。
8. MarketOrderExecutor。
9. ConditionalOrderWatcher。
10. Telegram 参数命令。
11. 旧功能迁移。
12. 真实服务验收。
