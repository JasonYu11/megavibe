# 跟单功能两段式落地计划

目标：把跟单拆成两个独立可测试部分，再做集成。

- Part A：DeBank 轮询到提交交易。
- Part B：Telegram 用户机器人端配置、确认、管理、通知。

第一版默认：

```text
chain = base
target_address = 0x138ab382c889add23de09a78fd7a75b9b4fe5c25
max_age_seconds = 300
copy_ratio = 0.00001
max_copy_trade_usd = 0.01
execution_mode = dry_run
```

## Part A: DeBank 轮询到提交交易

### A1. 目标

这一部分不关心 Telegram 输入，只负责：

```text
读取跟单地址 DeBank history
-> 过滤 Base 最近 5 分钟交易
-> 识别 swap 交易
-> 解析交易细节
-> 构造跟单动作
-> 调用现有 OrderService
-> 记录结果
```

核心问题：

```text
DeBank 能不能轮询到新交易？
交易细节能不能被正确解析？
解析后的动作能不能提交给现有交易系统？
提交后 dry-run / sign_only / live 是否走同一套交易基础设施？
```

### A2. DeBank 交易过滤

只处理：

```text
chain = base
time_at >= now - 300 seconds
cate_id = swap 或可识别为双边 token exchange
tx.status != 0
sends >= 1
receives >= 1
```

忽略：

```text
非 Base
超过 5 分钟
approve / transfer / deploy / cancel
失败交易
单边发送
单边接收
无法识别 token metadata
重复 history_id / tx_hash
```

### A3. 交易细节检查

每条候选交易需要形成标准结构：

```text
history_id
tx_hash
time_at
chain
sent_token
sent_amount
received_token
received_amount
sent_token_price_usd
received_token_price_usd
estimated_usd_value
trade_kind
```

`trade_kind`：

```text
USDC_OR_ETH_TO_TOKEN
TOKEN_TO_USDC_OR_ETH
TOKEN_TO_TOKEN
IGNORED
COMPLEX
```

### A4. 跟单动作构造

#### A4.1 USDC 买入

源交易：

```text
100 USDC -> C
```

跟单：

```text
copy_amount = min(100 * 0.00001, 0.01)
USDC -> C
```

#### A4.2 ETH 买入

源交易：

```text
0.05 ETH -> C
ETH price = 3000
source_usd_value = 150
```

跟单：

```text
copy_amount = min(150 * 0.00001, 0.01)
USDC -> C
```

也就是说，即使源地址用 ETH 买入，本地默认仍用 USDC 跟单。

#### A4.3 卖出

源交易：

```text
C -> USDC
```

跟单：

```text
读取本地 C 余额
sell_amount = local_C_balance * 0.00001
```

如果余额为 0：

```text
记录动作失败: balance_zero
不提交卖出订单
```

#### A4.4 双代币交易

源交易：

```text
B -> C
```

跟单动作组：

```text
1. 买入 C: 使用 estimated_usd_value * ratio 的 USDC
2. 卖出 B: 卖出本地 B 余额 * ratio
```

如果本地 B 余额为 0：

```text
买入 C 可以继续
卖出 B 记录失败: balance_zero
```

### A5. 提交交易

第一版只接入现有 `OrderService`：

```text
MarketOrder
source = copy_trade
trade.execution_mode = copy_watcher
approval.require_confirmation = false
```

执行规则：

```text
dry_run:
  submit_market_order()
  如果 PENDING_CONFIRMATION，则 confirm_order(actor="copy_watcher")
  期望 DRY_RUN_COMPLETED

sign_only:
  submit_market_order()
  confirm_order(actor="copy_watcher")
  期望 SIGNED_NOT_BROADCASTED

live:
  第一版不自动打开
  后续必须要求 live gates 和 copy live gates 双确认
```

### A6. Part A 测试

新增测试：

```text
tests/test_copy_trade_history_parser.py
tests/test_copy_trade_classifier.py
tests/test_copy_trade_action_builder.py
tests/test_copy_trade_watcher.py
tests/test_live_copy_trade_debank_analysis.py
```

测试矩阵：

```text
Base 2 分钟内 USDC -> C: 接受
Base 10 分钟前 USDC -> C: 忽略
ETH chain USDC -> C: 忽略
approve: 忽略
transfer 单边 send: 忽略
失败 tx: 忽略
重复 history_id: 第二次忽略
100 USDC -> C, ratio 0.00001: 生成 0.001 USDC 买入 C
0.05 ETH -> C, ETH=3000: 生成 0.0015 USDC 买入 C
C -> USDC, 本地 C=0: 卖出失败 balance_zero
B -> C, 本地 B=0: 买 C 成功, 卖 B 失败
dry_run 提交: DRY_RUN_COMPLETED
```

验收命令：

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q \
  tests/test_copy_trade_history_parser.py \
  tests/test_copy_trade_classifier.py \
  tests/test_copy_trade_action_builder.py \
  tests/test_copy_trade_watcher.py
```

真实 DeBank 只读测试：

```bash
PYTHONDONTWRITEBYTECODE=1 \
RUN_LIVE_DEBANK_TESTS=1 \
COPY_TRADE_TEST_ADDRESS=0x138ab382c889add23de09a78fd7a75b9b4fe5c25 \
pytest -q tests/test_live_copy_trade_debank_analysis.py
```

这个测试只读 DeBank，不创建订单，不提交交易。

## Part B: Telegram 用户机器人端

### B1. 目标

这一部分不直接负责交易识别，只负责用户配置和展示：

```text
添加跟单地址
确认是否跟单
设置跟单参数
查看跟单状态
暂停/恢复/删除
接收跟单触发报告
```

### B2. Telegram 命令

建议命令：

```text
/copy_add ADDRESS
/copy_confirm ADDRESS
/copy_set ADDRESS ratio 0.00001 max 0.01
/copy_list
/copy_status
/copy_pause ADDRESS
/copy_resume ADDRESS
/copy_remove ADDRESS
```

### B3. 用户添加流程

用户输入：

```text
/copy_add 0x138ab382c889add23de09a78fd7a75b9b4fe5c25
```

机器人返回确认卡片：

```text
跟单地址确认
━━━━━━━━━━━━
地址: 0x138ab3...5c25
公链: Base
安全窗口: 5 分钟
默认比例: 0.00001
最大单笔: 0.01 USDC

规则:
- 只跟 Base 交易
- 只跟 5 分钟内新交易
- 忽略单边转账
- 忽略 approve/transfer
- 默认 dry-run

[确认跟单] [取消]
```

确认后：

```text
跟单已启用
━━━━━━━━━━━━
地址: 0x138ab3...5c25
比例: 0.00001
最大单笔: 0.01 USDC
状态: ACTIVE
```

### B4. 参数修改

用户输入：

```text
/copy_set 0x138ab382c889add23de09a78fd7a75b9b4fe5c25 ratio 0.00001 max 0.01
```

机器人返回：

```text
跟单参数已更新
━━━━━━━━━━━━
地址: 0x138ab3...5c25
比例: 0.00001
最大单笔: 0.01 USDC
安全窗口: 5 分钟
```

### B5. 跟单触发通知

当 Part A watcher 生成结果后，Telegram 接收一条系统通知。

单币买入：

```text
跟单触发
━━━━━━━━━━━━
源地址: 0x138ab3...5c25
源交易: 100 USDC -> C
时间: 2 分钟前
比例: 0.00001

执行动作
────────────
🟢 买入: 使用 0.001 USDC 买入 C
状态: DRY_RUN_COMPLETED
订单: ord_xxx
```

双代币：

```text
跟单触发
━━━━━━━━━━━━
源地址: 0x138ab3...5c25
源交易: B -> C
时间: 1 分钟前
比例: 0.00001

执行动作
────────────
🟢 买入: 使用 0.001 USDC 买入 C
状态: DRY_RUN_COMPLETED

🔴 卖出: 卖出 B
状态: FAILED
原因: B 余额为 0
```

### B6. Part B 测试

新增测试：

```text
tests/test_copy_trade_telegram_handlers.py
tests/test_simulated_telegram_copy_trade_flow.py
```

模拟输入：

```text
/copy_add 0x138ab382c889add23de09a78fd7a75b9b4fe5c25
callback: copy_confirm
/copy_set 0x138ab382c889add23de09a78fd7a75b9b4fe5c25 ratio 0.00001 max 0.01
/copy_list
/copy_status
fake DeBank history: 100 USDC -> C
orchestrator tick
```

期望：

```text
copy target created
copy target active
ratio = 0.00001
max = 0.01
watcher generated dry-run order
Telegram received 跟单触发 report
```

验收命令：

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q \
  tests/test_copy_trade_telegram_handlers.py \
  tests/test_simulated_telegram_copy_trade_flow.py
```

## Part A 与 Part B 的结合

### 集成方式

`RuntimeOrchestrator` 增加 copy watcher：

```text
tick_once()
  1. Telegram poll
  2. Conditional order watcher
  3. Copy trade watcher
  4. Receipt tracker
  5. Heartbeat
```

原因：

```text
先处理用户命令，再处理自动策略。
用户刚 /copy_pause 后，下一轮 copy watcher 不应再执行该地址。
```

### 集成数据流

```text
Telegram /copy_add
-> SQLite copy_targets

Runtime tick
-> CopyTradeWatcher reads active copy_targets
-> DeBank get_user_history(address, chain_id=base)
-> parser/filter/classifier/action_builder
-> OrderService dry-run execution
-> SQLite orders / copy_trade_events / seen_transactions
-> Telegram system notification
```

### 集成测试

新增：

```text
tests/test_runtime_orchestrator_copy_trade.py
```

测试用例：

```text
orchestrator 有 copy watcher 时每 tick 调用一次
copy watcher 失败不影响 telegram/conditional/receipt/heartbeat
copy watcher 成功后写 copy_watcher_ok=true
copy watcher 生成通知后 Telegram 收到消息
copy_pause 后下一 tick 不处理该地址
```

验收：

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_runtime_orchestrator_copy_trade.py
```

## 总体验收

开发完成后必须通过：

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q \
  tests/test_copy_trade_history_parser.py \
  tests/test_copy_trade_classifier.py \
  tests/test_sqlite_store_copy_trade.py \
  tests/test_copy_trade_action_builder.py \
  tests/test_copy_trade_watcher.py \
  tests/test_copy_trade_telegram_handlers.py \
  tests/test_simulated_telegram_copy_trade_flow.py \
  tests/test_runtime_orchestrator_copy_trade.py
```

最后跑全量：

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests
```

## 第一版完成标准

```text
Base-only 生效
5 分钟窗口生效
ratio=0.00001 生效
max_copy_trade_usd=0.01 生效
DeBank 只读分析可运行
单边转账被忽略
approve/transfer 被忽略
重复 tx 不重复处理
USDC/ETH 单币交易可识别
双代币 B-C 可生成动作组
余额为 0 时返回失败动作，不崩溃
dry-run 能提交到现有 OrderService
Telegram 能配置、查看、暂停、恢复、删除跟单地址
Telegram 能收到跟单触发报告
模拟 Telegram 流程完整通过
```

## 第一版不做

```text
live 自动跟单广播
跨链跟单
LP/借贷/复杂 DeFi 跟单
多跳路径精确还原
真实成交均价精确解析
自然语言跟单
```

live 自动跟单应作为下一阶段，在 dry-run 和只读 DeBank 测试稳定后再开启。
