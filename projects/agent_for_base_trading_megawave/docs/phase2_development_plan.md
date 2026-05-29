# Phase 2 Development Plan

## 阶段目标

Phase 2 的目标是把 Phase 1 已验证的交易基础设施变成可长期运行的 Telegram 交易入口。核心不是新增交易执行路径，而是把用户输入、流程引导、确认、通知、运行时恢复和可观测性做规范。

本阶段仍然坚持：

- 默认公链为 Base，`chain_id=8453`。
- 默认交易中间资产为 Base USDC。
- 用户交易代币输入只接受合约地址；原生 ETH 使用 `0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE`。
- DeBank 是默认地址、资产、价格、交易内容查询方案，不使用 Basescan API。
- OKX DEX 是 swap quote、swap tx build、broadcast/status 的默认执行方案。
- 私钥只在本地 signer 模块读取，不进入 Telegram、日志、SQLite payload 或异常消息。
- 所有真实广播仍然必须经过 quote、risk、approval、execution、receipt/post-trade observation 和 SQLite evidence。

## 范围边界

### 本阶段要做

- Telegram 直接指令模式。
- Telegram 流程引导模式。
- Telegram 确认、取消、状态查询、订单列表、余额查询的可用体验。
- 本地 bot runtime 的长期运行、恢复和错误处理。
- ConditionalOrder watcher 的运行时接入和 Telegram 通知。
- Token resolver 和交易参数标准化，减少未知 token decimals 风险。
- 可验证的 dry-run、sign-only、小额 live 交易测试。

### 本阶段暂不做

- 自然语言自动下单。
- 复杂策略交易。
- 聪明钱 cash flow 自动交易。
- 多链。
- Web UI。
- 链上原生限价单。

自然语言后续应作为第三种输入适配器接入同一套 `MarketOrder` / `ConditionalOrder` / `OrderService`，不能绕过当前交易基础设施。

## Telegram 输入模型

### 模型一：直接指令模式

适合熟练用户、agent 调用、复制粘贴和自动化测试。

命令：

```text
/status
/balance
/orders
/quote TOKEN_IN_ADDRESS TOKEN_OUT_ADDRESS AMOUNT
/buy TOKEN_OUT_ADDRESS AMOUNT
/sell TOKEN_IN_ADDRESS AMOUNT
/limit_buy TOKEN_OUT_ADDRESS AMOUNT at TARGET_PRICE
/limit_sell TOKEN_IN_ADDRESS AMOUNT at TARGET_PRICE
/confirm ORDER_ID
/reject ORDER_ID
/cancel ORDER_ID
```

语义：

- `/buy TOKEN_OUT_ADDRESS AMOUNT`：默认用 Base USDC 买入，`AMOUNT` 是 USDC 数量。
- `/sell TOKEN_IN_ADDRESS AMOUNT`：默认卖成 Base USDC，`AMOUNT` 是卖出代币数量。
- `/limit_buy TOKEN_OUT_ADDRESS AMOUNT at TARGET_PRICE`：价格小于等于 USD 目标价时触发。
- `/limit_sell TOKEN_IN_ADDRESS AMOUNT at TARGET_PRICE`：价格大于等于 USD 目标价时触发。
- 覆盖默认中间资产：
  - `/buy TOKEN_OUT_ADDRESS AMOUNT --with TOKEN_IN_ADDRESS`
  - `/sell TOKEN_IN_ADDRESS AMOUNT --to TOKEN_OUT_ADDRESS`
  - `/limit_buy TOKEN_OUT_ADDRESS AMOUNT at TARGET_PRICE --with TOKEN_IN_ADDRESS`
  - `/limit_sell TOKEN_IN_ADDRESS AMOUNT at TARGET_PRICE --to TOKEN_OUT_ADDRESS`

### 模型二：流程引导模式

适合手动交易，降低参数顺序和地址输入错误。

入口：

```text
/trade
```

流程：

```text
/trade
  -> 选择 Market Buy / Market Sell / Limit Buy / Limit Sell
  -> 输入 token address
  -> 输入 amount
  -> 限价单输入 at price
  -> 显示 quote、风险摘要、默认 USDC 路由、预计输出、滑点、price impact
  -> Confirm / Cancel
```

引导模式只负责生成 `TradeDraft`，最终仍然转换成 `MarketOrder` 或 `ConditionalOrder`，再交给 `OrderService`。

建议状态结构：

```json
{
  "chat_id": "7433362014",
  "user_id": "7433362014",
  "mode": "guided_trade",
  "step": "awaiting_amount",
  "draft": {
    "kind": "limit_sell",
    "chain_id": 8453,
    "token_in": "0x...",
    "token_out": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "amount": null,
    "target_price_usd": null,
    "default_route_token": "USDC"
  }
}
```

## 软件结构

```text
app/bot/
  command_parser.py
  guided_flow.py
  telegram_handlers.py
  runtime.py
  message_format.py

app/orders/
  order_service.py
  conditional_watcher.py
  order_intent.py

app/data/
  debank_client.py
  price_provider.py
  token_resolver.py
  wallet_portfolio.py

app/execution/
  okx_client.py
  swap_executor.py
  receipt_tracker.py

app/storage/
  sqlite_store.py
  conversation_store.py
```

`command_parser.py` 和 `guided_flow.py` 都是输入适配器；它们不能直接调用 OKX、signer 或 broadcast。

## Step 1: Token Resolver 标准化

### 开发内容

- 新增或完善 `TokenResolver`。
- 对任意 `0x...` 交易地址查询 DeBank token metadata。
- 解析并缓存 `symbol`、`address`、`decimals`、`price_usd`、`chain_id`。
- 对 Base USDC、原生 ETH、WETH、VIRTUAL 保留内置 fallback。
- 未能解析 decimals 的 token 不允许进入真实交易，只允许 quote 尝试或 dry-run。

### 可验证测试

#### Test 1.1: 已知 token fallback

输入：

```text
0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
```

通过标准：

- 返回 USDC。
- decimals 为 6。
- 不需要网络。

#### Test 1.2: DeBank metadata 查询

输入：

```text
RUN_LIVE_DEBANK_TESTS=1
```

通过标准：

- 能查询 Base token metadata。
- 失败时不打印 DeBank access key。

#### Test 1.3: 未知 token 阻断真实交易

输入：

- 无法解析 decimals 的 token。
- execution_mode=`live`。

通过标准：

- OrderService 拒绝执行。
- 状态记录为 risk rejected 或 validation rejected。

## Step 2: Telegram 直接指令增强

### 开发内容

- 完成 `/limit_sell` handler 覆盖。
- 统一直接指令错误提示。
- Quote 和 order preview 使用统一格式。
- 限价单创建后的审核消息显示当前 USD 价格、目标 USD 价格和目标价相对当前价的百分比差距，例如 `distance +50%`。
- `/orders` 支持显示最近 market orders 和 conditional orders。
- `/status` 显示 watcher、runtime、DB、execution mode 的关键状态。
- `/balance` 通过 DeBank wallet portfolio service 返回精简资产摘要。

### 可验证测试

#### Test 2.1: market buy/sell 指令

输入：

```text
/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 0.01
/sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 10000
```

通过标准：

- 均创建 `MarketOrder`。
- 默认中间资产为 USDC。
- 未确认前不广播。

#### Test 2.2: limit buy/sell 指令

输入：

```text
/limit_buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 0.01 at 1.2
/limit_sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 10000 at 1.8
```

通过标准：

- 均创建 `ConditionalOrder`。
- buy trigger operator 为 `<=`。
- sell trigger operator 为 `>=`。
- action 仍然通过 `OrderService` 执行。

#### Test 2.2.1: 限价单审核价格差距

输入：

```text
current_price_usd = 1.2
/limit_sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 10000 at 1.8
```

通过标准：

- Telegram 审核消息显示当前价 `1.2 USD`。
- Telegram 审核消息显示目标价 `1.8 USD`。
- Telegram 审核消息显示相对差距 `+50%`。
- 当前价查询失败时不阻断条件单创建，消息显示 current price unavailable。

#### Test 2.3: 错误输入安全

输入：

```text
/buy VIRTUAL 1
/limit_buy 0x... 1 1.2
/sell 0x... -1
```

通过标准：

- 返回清晰错误。
- 不创建订单。
- 不打印 secret。

## Step 3: Telegram 流程引导模式

### 开发内容

- 新增 `TradeDraft`。
- 新增 `GuidedTradeFlow` 状态机。
- 新增 `ConversationStore`，先使用 SQLite。
- 支持 `/trade`、`/cancel`、按钮 callback 或文本选择。
- 每一步只接受一个输入。
- 最终 preview 后必须用户确认。

### 可验证测试

#### Test 3.1: market buy 引导

流程：

```text
/trade
Buy
TOKEN_OUT_ADDRESS
0.01
Confirm
```

通过标准：

- 状态按步骤推进。
- 最终生成 `MarketOrder`。
- 未 Confirm 前不执行。

#### Test 3.2: limit sell 引导

流程：

```text
/trade
Limit Sell
TOKEN_IN_ADDRESS
10000
1.8
Confirm
```

通过标准：

- 最终生成 `ConditionalOrder`。
- trigger operator 为 `>=`。
- target_price_usd 为 `1.8`。

#### Test 3.3: 中途取消

输入：

```text
/trade
Buy
/cancel
```

通过标准：

- conversation state 被清理。
- 不创建订单。

#### Test 3.4: 重启恢复

输入：

- 用户正在 `awaiting_amount`。
- bot 重启。

通过标准：

- SQLite 恢复 draft。
- 用户继续输入 amount 后能完成流程。

## Step 4: Approval 与 Telegram 交互

### 开发内容

- 统一确认消息格式。
- 显示：
  - side
  - token in/out
  - amount
  - route provider
  - estimated output
  - price impact
  - slippage
  - risk decision
  - order id
- 支持 `/confirm ORDER_ID`、`/reject ORDER_ID`。
- 支持 Telegram inline button callback。
- 任何 live broadcast 前必须确认，除非 policy 显式允许小额自动执行。

### 可验证测试

#### Test 4.1: confirm 后执行

输入：

- pending order。
- `/confirm ORDER_ID`。

通过标准：

- approval 记录为 APPROVED。
- order 进入 execution pipeline。
- dry-run 模式不真实广播。

#### Test 4.2: reject 后终止

输入：

- pending order。
- `/reject ORDER_ID`。

通过标准：

- approval 记录为 REJECTED。
- order 状态为 `REJECTED_BY_USER`。
- 不执行 quote/build/sign/broadcast。

#### Test 4.3: callback 与文本命令等价

输入：

- inline confirm callback。

通过标准：

- 与 `/confirm ORDER_ID` 产生同样状态变化。

## Step 5: Runtime Orchestrator

### 开发内容

- 建立本地 runtime 入口。
- 同时运行：
  - Telegram polling。
  - ConditionalOrder watcher。
  - Receipt tracker。
  - health heartbeat。
- 支持 graceful shutdown。
- 支持单次 tick 测试和长期 loop。
- 所有错误写入 event log，不让 bot 进程直接退出。

### 可验证测试

#### Test 5.1: 单次 tick

输入：

- fake Telegram update。
- active conditional order。

通过标准：

- Telegram update 被处理。
- watcher tick 被调用。
- offset 被保存。

#### Test 5.2: 错误隔离

输入：

- Telegram transport 抛异常。

通过标准：

- watcher 仍可运行。
- 错误进入 event log。
- 不打印 secret。

#### Test 5.3: 重启继续

输入：

- 已保存 Telegram offset。
- active conditional order。

通过标准：

- 重启后不重复处理旧消息。
- active conditional order 被恢复。

## Step 6: DeBank Wallet 与交易内容查询

### 开发内容

- `/balance` 使用 DeBank 查询钱包资产。
- `/wallet` 或 `/portfolio` 返回主要资产摘要。
- `/tx ADDRESS_OR_HASH` 后续可以查询地址交易内容或指定交易观察结果。
- 地址交易内容查询先做只读展示，不直接触发交易。

### 可验证测试

#### Test 6.1: live wallet balance

输入：

```text
RUN_LIVE_DEBANK_TESTS=1
```

通过标准：

- 返回测试钱包资产摘要。
- 不包含 DeBank key。

#### Test 6.2: Telegram balance

输入：

```text
/balance
```

通过标准：

- Telegram 返回精简资产摘要。
- 失败时返回可读错误。

## Step 7: 小额真实交易回归

### 开发内容

- 保留 Phase 1 live flags。
- 新增 Telegram 指令到 live broadcast 的手动验收脚本。
- 新增流程引导到 live broadcast 的手动验收脚本。
- 真实测试金额默认 `0.01 USD`，自动化硬上限 `0.05 USD`。

### 可验证测试

#### Test 7.1: 直接指令 live buy

输入：

```text
RUN_LIVE_TRADE_TESTS=1
CONFIRM_LIVE_TRADE_BASE=YES
/buy TOKEN_OUT_ADDRESS 0.01
/confirm ORDER_ID
```

通过标准：

- 完成 OKX broadcast。
- receipt tracker 记录结果。
- DeBank 或 OKX/RPC observation 记录 post-trade event。
- SQLite evidence 完整。

#### Test 7.2: 流程引导 live buy

输入：

```text
/trade
Buy
TOKEN_OUT_ADDRESS
0.01
Confirm
```

通过标准：

- 与直接指令共用同一条 OrderService 执行路径。
- evidence 表结构一致。

#### Test 7.3: limit sell watcher live

输入：

- 创建极小额 `/limit_sell`。
- 使用可立即触发或测试替身 price provider。

通过标准：

- watcher 触发。
- 生成 watcher-triggered MarketOrder。
- 真实模式必须经过二次 quote、risk、approval 和 broadcast。

## Step 8: 文档与运维

### 开发内容

- 更新 `README` 或新增运行手册。
- 记录必需 key：
  - `DEBANK_ACCESS_KEY`
  - OKX API key / secret / passphrase / project id
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_DEFAULT_CHAT_ID`
  - wallet private key Keychain ref
  - Base RPC URL
- 记录 live test flags。
- 记录如何启动 bot runtime。
- 记录如何暂停 watcher 和关闭 live broadcast。

### 可验证测试

#### Test 8.1: env check

输入：

```text
python -m app.config.environment_check
```

通过标准：

- 缺失 key 有明确提示。
- 存在 key 不打印真实值。

#### Test 8.2: dry-run startup

输入：

```text
execution_mode=dry_run
```

通过标准：

- bot runtime 可启动。
- Telegram `/status` 返回运行状态。
- 不会真实广播。

## 完成标准

Phase 2 完成时必须满足：

- 直接指令和流程引导都能生成同一套 `MarketOrder` / `ConditionalOrder`。
- `/limit_buy` 和 `/limit_sell` 都能通过 watcher 触发路径验证。
- Telegram 交互不会泄露私钥、API key、bot token 或 signer ref。
- 所有订单、确认、执行、receipt、post-trade observation 都持久化。
- bot runtime 能重启恢复 Telegram offset、active conditional orders 和 guided draft。
- 全量默认测试通过。
- live 测试必须显式开关，并保留小额真实交易 evidence。

## 当前进度

Completion audit:

- Current requirement-by-requirement audit is saved in [phase2_completion_audit.md](phase2_completion_audit.md).

### 2026-05-28 第一轮实现

已完成：

- `TokenResolver` 标准化：
  - Base USDC、原生 ETH、WETH、VIRTUAL 使用本地 fallback。
  - 未知 `0x...` token 可通过 DeBank metadata 解析 symbol、decimals、price。
  - 未配置 DeBank metadata 来源时，未知 token 明确失败。
  - live 模式会阻断 parser fallback 产生的未解析 token，避免用默认 18 decimals 真实交易。
- Telegram 直接指令增强：
  - `/limit_buy` 和 `/limit_sell` 支持 `TOKEN AMOUNT at TARGET_PRICE`。
  - 限价单创建审核消息显示当前价、目标价和相对差距，例如 `distance +50%`。
  - 当前价格查询失败时不阻断条件单创建。
- Telegram 流程引导模式底座：
  - `/trade` 启动 guided flow。
  - 支持 Buy、Sell、Limit Buy、Limit Sell。
  - 分步输入 token address、amount、target price。
  - 最终进入 review，用户发送 `Confirm` 后才创建订单。
  - `/cancel` 清理 draft。
  - draft 持久化在 SQLite，可重启恢复。
- Runtime Orchestrator 底座：
  - 单次 tick 同时调度 Telegram polling、ConditionalOrder watcher、ReceiptTracker、heartbeat。
  - Telegram offset 持久化到 SQLite。
  - watcher tick 和 runtime error 写入 event log。
  - 任一子模块异常不会阻断其他模块运行。

已验证：

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_data_services.py tests/test_order_service.py tests/test_command_parser.py
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_guided_flow.py tests/test_telegram_handlers.py tests/test_sqlite_store.py
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_runtime_orchestrator.py tests/test_bot_runtime.py tests/test_conditional_watcher.py
```

待完成：

- 将 `TokenResolver`、`DeBankPriceProvider`、`GuidedTradeFlow`、`RuntimeOrchestrator` 接入真实本地启动入口。
- `/status` 显示 bot、watcher、DB、execution_mode 的详细健康状态。
- `/orders` 输出更完整的 market/conditional order 摘要。
- `/balance` 接入真实 DeBank wallet portfolio 的 Telegram 展示格式。
- Telegram inline button callback。
- Phase 2 小额 live 回归脚本和 evidence 更新。

### 2026-05-28 第二轮实现

已完成：

- 真实运行对象组装：
  - 新增 `app/bootstrap.py`，按 `AppConfig` 创建 `SQLiteStore`、`DebankClient`、`OkxDexClient`、`TokenResolver`、`TelegramCommandParser`、`OrderService`、`DeBankPriceProvider`、`DebankBalanceService`、`GuidedTradeFlow`、`TelegramCommandHandler`、`ConditionalOrderWatcher`、`OkxReceiptTracker` 和 `RuntimeOrchestrator`。
  - `TokenResolver`、`DeBankPriceProvider`、`GuidedTradeFlow` 已接入 handler。
  - `ConditionalOrderWatcher` 和 `OkxReceiptTracker` 已接入 orchestrator。
  - 未配置 Telegram chat id 时，orchestrator 仍可运行 watcher、receipt tracker 和 heartbeat。
- 本地启动入口：
  - 新增 `python -m app.run_bot --once` 单次 tick 入口。
  - 新增 `python -m app.run_bot` 长期运行入口。
  - `--help` 已验证可用。
- Telegram 查询展示：
  - `/status` 显示 `execution_mode`、market/conditional order 数量、DB 路径、heartbeat、Telegram offset。
  - `/orders` 显示最近 market orders 和 conditional orders 的 id/status 摘要。
  - `/balance` 显示 DeBank 返回的总 USD 资产摘要。
- 配置：
  - `configs/runtime.example.yaml` 增加 `storage.sqlite_path` 和 `telegram.poll_interval_seconds`。

已验证：

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_bootstrap.py tests/test_config_settings.py tests/test_telegram_handlers.py tests/test_message_format.py
PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot --help
```

待完成：

- Phase 2 小额 live 回归执行和 evidence 更新。
- 当前环境检查显示 API、Telegram、RPC 已配置，但默认 Keychain signer ref 不可读；live 回归需要先配置 `KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1`，或通过 `LIVE_WALLET_SECRET_REF` 指向可用的本地 signer secret。

### 2026-05-28 第三轮实现

已完成：

- Telegram inline callback：
  - `confirm:ORDER_ID`、`reject:ORDER_ID`、`cancel:ORDER_ID` 与文本命令等价。
  - `trade:start`、`trade:buy`、`trade:sell`、`trade:limit_buy`、`trade:limit_sell` 可驱动 guided flow。
  - Telegram runtime 能处理 `callback_query` update，并调用 `answerCallbackQuery`。
  - pending market order 返回 Confirm / Reject / Cancel inline buttons。
  - active conditional order 返回 Cancel inline button。
  - guided flow 交易类型选择和 review 确认返回 inline buttons。
- `/status` 健康状态增强：
  - 显示 watcher 和 receipt tracker 最近 tick 是否成功。
  - Orchestrator 将 `watcher_last_ok` 和 `receipt_last_ok` 写入 runtime state。
- `/orders` 摘要增强：
  - market order 显示 side、amount、token in/out。
  - conditional order 显示 side、amount、trigger token、operator、target USD price。
- Phase 2 live 回归说明：
  - `docs/live_test_setup.md` 增加 runtime dry-run smoke test。
  - `docs/live_test_setup.md` 增加 Phase 2 evidence DB 命令示例 `var/phase2_live_evidence.sqlite`。

已验证：

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_telegram_handlers.py tests/test_bot_runtime.py tests/test_message_format.py tests/test_runtime_orchestrator.py
```

待完成：

- Phase 2 小额 live 回归执行和 evidence 更新。

### 2026-05-28 第四轮复核

已完成：

- 将 live integration 测试默认 evidence DB 从 `var/phase1_live_evidence.sqlite` 收口为 `var/phase2_live_evidence.sqlite`。
- 将 live 测试 Telegram 通知标签从 Phase 1 改为 Phase 2，避免验收记录混淆。
- 更新 [live_test_setup.md](live_test_setup.md) 的默认 `LIVE_EVIDENCE_DB_PATH` 和安全执行命令为 Phase 2 evidence DB。
- 更新 [phase2_completion_audit.md](phase2_completion_audit.md) 的最新测试结果和当前 live 阻塞说明。

已验证：

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests
139 passed, 13 skipped

PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot --once --db-path /private/tmp/phase2_runtime_check.sqlite
tick telegram_ok=True watcher_ok=True receipt_ok=True heartbeat_ok=True
```

当前 live 状态：

- 当前工作区只有 `var/phase1_live_evidence.sqlite`，尚无 `var/phase2_live_evidence.sqlite`。
- Codex 进程内 `python -m app.config.environment_check` 仍显示 `wallet.signer MISSING`。
- 用户交互式 Terminal 已显示同一路径下 `wallet.signer OK`，因此 Phase 2 小额真实广播可以先从用户 Terminal 执行，或先修复 Codex 进程对同一 Keychain signer 的访问权限。

待完成：

- 执行 Phase 2 小额市价单 live 回归，并写入 `var/phase2_live_evidence.sqlite`。
- 执行 Phase 2 本地 watcher 限价单 live 回归，并写入同一 evidence DB。
- 核验 evidence DB 中的 order、quote、risk decision、approval、execution、receipt/post-trade observation 记录。

### 2026-05-28 第五轮复核

已完成：

- `OkxReceiptTracker` 现在会在 OKX/RPC 状态仍为 `BROADCASTED` 时也持久化 receipt payload；最终 `FILLED` / `FAILED` 仍会同步更新订单状态。
- 新增 `app.verification.live_evidence_audit`，用于审计 `var/phase2_live_evidence.sqlite` 是否满足 Phase 2 live evidence 完成标准。
- 新增 `tests/test_live_evidence_audit.py`，覆盖完整 evidence、缺少限价 watcher、缺少 receipt payload、SQLite 泄露 secret marker、缺少 DB 等场景。
- [live_test_setup.md](live_test_setup.md) 增加 Phase 2 live evidence 审计命令。

已验证：

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_receipt_tracker.py tests/test_live_evidence_audit.py
9 passed

PYTHONDONTWRITEBYTECODE=1 pytest -q tests
144 passed, 13 skipped
```

真实广播完成后的验收命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m app.verification.live_evidence_audit --db-path var/phase2_live_evidence.sqlite
```

当前执行结果为预期失败，因为 `var/phase2_live_evidence.sqlite` 尚未生成。

### 2026-05-29 live 回归完成

已完成：

- 在沙箱外环境检查确认 Keychain signer 可读：
  - `wallet.signer | OK | signer resolves via runtime signer_ref; derived address 0x8EF454c23822C5373df37e8c5E8987aC64dB96F1`
- 先执行 OKX `sign_only` 回归，覆盖 `ETH -> USDC` 和 `USDC -> VIRTUAL`，无广播。
- 执行 Phase 2 小额市价单 live 回归：
  - route: `USDC_TO_VIRTUAL`
  - amount: `LIVE_TRADE_USD_VALUE=0.01`
  - evidence DB: `var/phase2_live_evidence.sqlite`
  - order: `ord_b5099081f50447838c4593b2cf7f0914`
  - tx: `0x103163b5f2a2965b02b0fb7b876a205a3363adbc2fb2d9a5336805f73d56f8c6`
- 执行 Phase 2 watcher 限价单 live 回归：
  - amount: `LIVE_TRADE_USD_VALUE=0.01`
  - evidence DB: `var/phase2_live_evidence.sqlite`
  - watcher-triggered order: `ord_258ecd99182f410186569dc9cc09da43`
  - tx: `0x389407085a27197222f628b90af2f55574f134dfde7d286899c33c0fab6b145e`
- 修复 Telegram 通知失败时的安全问题：
  - `TelegramHttpTransport` 不再保留 requests 原始异常链，避免 traceback 带出 bot token URL。
  - live test 的 Telegram 成交通知改为 best-effort，真实广播和 evidence 已完成时不会因 Telegram 网络失败判定交易回归失败。

已验证：

```text
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 LIVE_TRADE_USD_VALUE=0.01 pytest -q -rs tests/test_live_integrations.py::test_live_okx_swap_sign_only_when_enabled
2 passed

PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL LIVE_EVIDENCE_DB_PATH=var/phase2_live_evidence.sqlite pytest -q -rs tests/test_live_integrations.py::test_live_small_trade_when_explicitly_enabled
广播成功；测试在 Telegram 通知阶段失败，随后已修复通知失败处理。SQLite evidence 已通过审计。

PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES CONFIRM_LIVE_LIMIT_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_EVIDENCE_DB_PATH=var/phase2_live_evidence.sqlite pytest -q -rs tests/test_live_integrations.py::test_live_conditional_limit_trade_when_explicitly_enabled
1 passed

PYTHONDONTWRITEBYTECODE=1 python -m app.verification.live_evidence_audit --db-path var/phase2_live_evidence.sqlite
phase2 live evidence audit: OK
conditional_orders.triggered: 1
orders.live_complete: 2
orders.live_direct_market: 1
orders.live_watcher_triggered: 1
table.approvals: 2
table.conditional_orders: 1
table.events: 16
table.executions: 4
table.orders: 2
table.quotes: 2
table.risk_decisions: 2

PYTHONDONTWRITEBYTECODE=1 pytest -q tests
145 passed, 13 skipped
```

Phase 2 完成依据：

- 直接市价单真实广播证据已存在。
- 本地 watcher 限价单触发到真实广播证据已存在。
- evidence DB 包含 order、quote、risk decision、approval、execution、receipt/post-trade observation。
- SQLite payload 审计未发现 private key、signer ref、API key ref、DeBank key ref、OKX secret ref、Telegram bot token ref。

## Phase 2.5 Alpha 实施

目标：把 Phase 2 已验证功能封装成可本机长期运行的 alpha Telegram bot。默认 dry-run，live 交易必须显式启用。

已完成：

- 新增 `configs/runtime.local.yaml` 作为本机运行配置。
- 新增启动和审计脚本：
  - `scripts/check_env.sh`
  - `scripts/start_bot_dry_run.sh`
  - `scripts/start_bot_live.sh`
  - `scripts/audit_live_evidence.sh`
- `APP_EXECUTION_MODE` 可覆盖 YAML 中的 `app.execution_mode`，用于脚本安全切换 dry-run/live。
- `build_trading_runtime_app()` 会将 signer 派生钱包地址注入 Telegram parser，Telegram 下单生成的 `MarketOrder` 现在包含 `wallet.address`，满足 live swap build/broadcast 前置条件。
- `/balance` 默认使用 signer 派生地址，避免示例配置中的全 0 地址被用于余额查询。
- Telegram allowlist：
  - `TELEGRAM_DEFAULT_CHAT_ID` 自动作为允许 chat。
  - `TELEGRAM_ALLOWED_CHAT_IDS` 可增加允许 chat。
  - `TELEGRAM_ALLOWED_USER_IDS` 可限制允许 user。
  - 未授权请求返回 `Unauthorized`，不创建订单。
- 新增 `/mode`，只读显示 `execution_mode` 和 live gate 状态。
- `/status` 增强显示：
  - `execution_mode`
  - `live_enabled`
  - signer wallet address
  - DB path
  - heartbeat / Telegram offset / watcher / receipt health
- `/orders` 增强显示最近 market order 的 tx tracking reference。
- live confirm gate：
  - `execution_mode=live` 但未满足 `RUN_LIVE_TRADE_TESTS=1` 和 `CONFIRM_LIVE_TRADE_BASE=YES` 时，`/confirm ORDER_ID` 不会调用 `OrderService.confirm_order()`，不会写 approval，也不会广播。
- `scripts/start_bot_live.sh` 会在启动前检查：
  - `RUN_LIVE_TRADE_TESTS=1`
  - `CONFIRM_LIVE_TRADE_BASE=YES`
  - `LIVE_TRADE_USD_VALUE > 0`
  - `LIVE_TRADE_USD_VALUE <= 0.05`
- 新增 alpha 运行手册：[phase2_5_alpha_runbook.md](phase2_5_alpha_runbook.md)。

新增验证：

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_command_parser.py tests/test_telegram_handlers.py tests/test_bootstrap.py tests/test_config_settings.py tests/test_message_format.py
55 passed

scripts/check_env.sh
wallet.signer OK; derived address 0x8EF454c23822C5373df37e8c5E8987aC64dB96F1

scripts/start_bot_live.sh
Refusing live startup: set RUN_LIVE_TRADE_TESTS=1 and CONFIRM_LIVE_TRADE_BASE=YES.

PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot --runtime-config configs/runtime.local.yaml --db-path /private/tmp/phase2_5_startup_check.sqlite --once
tick telegram_ok=True watcher_ok=True receipt_ok=True heartbeat_ok=True

scripts/audit_live_evidence.sh
phase2 live evidence audit: OK

PYTHONDONTWRITEBYTECODE=1 pytest -q tests
154 passed, 13 skipped
```

Phase 2.5 启动建议：

```bash
scripts/check_env.sh
scripts/start_bot_dry_run.sh
```

Telegram smoke test:

```text
/status
/mode
/balance
/orders
/quote 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 1
/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 0.01
/reject ORDER_ID
/trade
```

### 2026-05-29 交互升级

已完成：

- Telegram 主要交易交互改为中文。
- 市价单创建后显示交易确认卡片，确认前不执行：
  - 订单编号
  - 方向 / route provider
  - 支付 token 和数量
  - 获得 token
  - 预计获得 / 最小接收 / 价格影响
  - 最大滑点
  - 风控结果
- 限价单创建后不再直接进入 watcher，而是先保存为 `PENDING_CONFIRMATION`。
- `/confirm LIMIT_ORDER_ID` 将限价单切到 `ACTIVE` 并开始 watcher 监控。
- `/reject LIMIT_ORDER_ID` 会拒绝并取消 pending 限价单。
- `/confirm MARKET_ORDER_ID` 返回中文交易结果摘要：
  - 订单编号
  - 状态
  - tx tracking reference
  - 提交时间
  - quote-based 预计成交量 / 最小接收 / 价格影响
  - 钱包余额摘要。
- `/balance` 兼容 DeBank `usd_value` 字段，并尽量显示 ETH / USDC 关键余额。

已验证：

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_telegram_handlers.py tests/test_message_format.py tests/test_bot_runtime.py tests/test_live_integrations.py
35 passed, 12 skipped

PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_conditional_watcher.py tests/test_guided_flow.py tests/test_order_service.py tests/test_bootstrap.py
27 passed

PYTHONDONTWRITEBYTECODE=1 pytest -q tests
154 passed, 13 skipped
```

后续问题：

- 真实成交量和成交均价需要 receipt/log 或 DeBank history 解析后才能精确返回；当前确认结果只能返回广播状态和 quote-based 估计。
- 应增加 receipt 最终状态的二次 Telegram 通知。
- Telegram 富文本排版还没有启用，后续可加入 Markdown/HTML parse mode 和安全 escaping。
- 触发限价单时应发送单独通知：触发价、目标价、触发后的 quote、是否等待确认。

### 2026-05-29 Phase 2.6 订单 UI / 管理推进

目标：把 Telegram 从“可执行命令”推进到“可初步使用的订单控制台”，优先解决中文可读性、确认前审查、当前/历史订单可见性、单订单管理、以及 `/` 命令推荐。

已完成：

- 新增 `/start` 中文首页，提供流程交易、当前订单、历史订单按钮。
- 新增 `/help` 中文命令说明。
- 新增 `/history`，与 `/orders` 分离：
  - `/orders` 只显示当前待确认、执行中、已广播未最终确认、监控中的限价单；
  - `/history` 显示完成、拒绝、取消、过期等历史记录。
- 新增 `/order ORDER_ID` 订单详情：
  - 市价单显示状态、方向、路径、最近确认、最近执行、tx tracking、事件数；
  - 限价单显示状态、方向、金额、触发条件、最近确认、事件数。
- Telegram inline keyboard 增强：
  - 首页导航；
  - 当前/历史订单切换；
  - 单订单刷新/取消/返回当前订单。
- 新增 Telegram `setMyCommands` 支持：
  - `app.bot.command_menu.BOT_COMMANDS`
  - `app.configure_bot_commands`
  - `scripts/configure_bot_commands.sh`
- `SQLiteStore` 新增当前/历史分组查询：
  - `list_current_orders()`
  - `list_history_orders()`
  - `list_current_conditional_orders()`
  - `list_history_conditional_orders()`
  - `get_conditional_order()`
- watcher 触发限价单后新增事件 `conditional_triggered_market_order`，记录触发价、生成的 market order id、market order status。

验收测试：

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_command_parser.py tests/test_sqlite_store.py tests/test_message_format.py tests/test_telegram_handlers.py tests/test_bot_runtime.py tests/test_conditional_watcher.py
67 passed

PYTHONDONTWRITEBYTECODE=1 pytest -q tests
160 passed, 13 skipped

scripts/check_env.sh
wallet.signer OK; derived address 0x8EF454c23822C5373df37e8c5E8987aC64dB96F1

scripts/configure_bot_commands.sh
configured 15 Telegram bot commands

set -a; source .env; set +a; PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot --runtime-config configs/runtime.local.yaml --db-path /private/tmp/phase2_6_startup_check.sqlite --once
tick telegram_ok=True watcher_ok=True receipt_ok=True heartbeat_ok=True
```

实际使用更新：

```bash
scripts/check_env.sh
scripts/configure_bot_commands.sh
scripts/start_bot_dry_run.sh
```

Telegram 建议 smoke test：

```text
/start
/help
/status
/balance
/orders
/history
/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 0.01
/order ORDER_ID
/reject ORDER_ID
/limit_sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 1 at 1.8
/confirm LIMIT_ORDER_ID
/orders
/cancel LIMIT_ORDER_ID
```

仍保留到后续阶段：

- receipt 最终状态二次 Telegram 通知。
- 触发限价单时的主动 Telegram 通知。
- receipt/log 或 DeBank history 解析后的真实成交量、真实成交均价。
- Telegram Markdown/HTML 富文本和安全 escaping。
