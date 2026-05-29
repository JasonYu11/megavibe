# Phase 1 Progress and Verification Matrix

Last updated: 2026-05-28

This file records verified progress against `docs/phase1_development_plan.md`.

## Verification Commands

Current verified command:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests
```

Observed result:

```text
108 passed, 12 skipped
```

Skipped tests:

```text
KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1
RUN_LIVE_DEBANK_TESTS gated test in default suite
RUN_LIVE_OKX_TESTS gated test in default suite
RUN_LIVE_OKX_SIGN_ONLY_TESTS gated test in default suite
RUN_LIVE_TRADE_TESTS + CONFIRM_LIVE_TRADE_BASE gated test in default suite
RUN_LIVE_TELEGRAM_TESTS gated test in default suite
live quote/sign_only route matrix defaults skipped unless enabled
live conditional limit sign_only defaults skipped unless enabled
live conditional limit broadcast defaults skipped unless explicitly enabled
```

DeBank live token, wallet balance, user history, and real follow-trade fixture tests were run separately with `RUN_LIVE_DEBANK_TESTS=1` and passed.
OKX live quote was run separately with `RUN_LIVE_OKX_TESTS=1` and passed for the `ETH -> USDC` and `USDC -> VIRTUAL` route matrix.
OKX live `sign_only` was run separately with `RUN_LIVE_OKX_SIGN_ONLY_TESTS=1` and passed for the `ETH -> USDC` and `USDC -> VIRTUAL` route matrix.
The local watcher limit-order live sign_only test passed using DeBank current VIRTUAL price as the trigger source.
Telegram live send/getUpdates was run separately with `RUN_LIVE_TELEGRAM_TESTS=1` and passed.
Two explicit small market live trades passed with `RUN_LIVE_TRADE_TESTS=1`, `CONFIRM_LIVE_TRADE_BASE=YES`, and `LIVE_TRADE_USD_VALUE=0.01`: `USDC_TO_VIRTUAL` and native `ETH_TO_USDC`.
One explicit local watcher limit-order live trade passed with `RUN_LIVE_TRADE_TESTS=1`, `CONFIRM_LIVE_TRADE_BASE=YES`, `CONFIRM_LIVE_LIMIT_TRADE_BASE=YES`, and `LIVE_TRADE_USD_VALUE=0.01`.
Live broadcast evidence is persisted in `var/phase1_live_evidence.sqlite`.

Environment check command:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m app.config.environment_check
```

Observed status:

```text
chain.base OK
debank.access_key OK
okx.* OK
telegram.* OK
base.rpc_url OK
wallet.keychain OK
```

## Completed With Tests

Live-service test configuration and execution order are documented in [live_test_setup.md](live_test_setup.md).

### Step 1: Project Skeleton and Config Loading

Evidence:

- `app/` package skeleton exists.
- `configs/runtime.example.yaml`
- `configs/risk_policy.example.yaml`
- `configs/strategies.example.yaml`
- `app/config/settings.py`
- `tests/test_config_settings.py`

Verified:

- Example configs parse.
- Default chain is Base (`chain_id=8453`).
- Default execution mode is `dry_run`.
- Missing `wallets` fails.
- Missing `risk.max_single_trade_usd` fails.

### Step 2: SecretProvider and LocalSigner

Evidence:

- `app/secrets/provider.py`
- `app/signing/local_signer.py`
- `tests/test_secrets_and_signer.py`

Verified:

- `EnvSecretProvider` resolves `ENV:` refs.
- Missing env secrets fail explicitly.
- `LocalSigner` signs a mock EVM transaction without broadcasting.
- `LocalSigner` can derive the configured wallet address without exposing the private key outside the signing module.
- Importing app modules does not access Keychain or secrets.

Not fully verified:

- Real Keychain item read is skipped until `KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1` exists and is accessible.

### Step 3: Order Models

Evidence:

- `app/core/order_info.py`
- `app/core/order_state.py`
- `tests/test_order_info.py`

Verified:

- `MarketOrder` validates required fields.
- `ConditionalOrder` can build a watcher-triggered `MarketOrder`.
- Amounts use `Decimal`.
- Base-unit conversion works for tested USDC values.
- Non-positive and non-finite amounts are rejected.
- Amounts that cannot be represented exactly in token base units are rejected instead of being silently truncated.
- Serialized MarketOrder and ConditionalOrder payloads do not include private keys, signer refs, secret refs, API keys, or provider secret names.

### Step 4: SQLite Storage

Evidence:

- `app/storage/sqlite_store.py`
- `tests/test_sqlite_store.py`

Verified:

- Market orders persist with `DRAFT` status.
- Status transitions write event records.
- Quote and risk decision records are queryable for order audit evidence.
- Execution records are queryable for sign/live verification evidence.
- Active conditional orders recover after reopening the DB.
- Filled conditional orders are not recovered as active.

### Step 5: DeBank Data Layer

Evidence:

- `app/data/debank_client.py`
- `tests/test_debank_client.py`

Verified with mocked HTTP:

- Token info uses DeBank `/token/list_by_ids`.
- User history parser extracts sends, receives, tx id, token dict.
- Top holders returns holder list.
- HTTP errors become explicit `DebankClientError`.
- Missing `DEBANK_ACCESS_KEY` fails explicitly without leaking a secret value.
- New `app/` flow does not depend on Basescan.

Additional live verification:

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_DEBANK_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_debank_token_info_when_enabled
```

Observed result:

```text
1 passed
```

### Step 6: OKX v6 Client

Evidence:

- `app/execution/okx_client.py`
- `tests/test_okx_client.py`

Verified with mocked HTTP:

- Quote uses `/api/v6/dex/aggregator/quote`.
- Swap uses `/api/v6/dex/aggregator/swap`.
- Swap mocked response verifies unsigned tx fields: `to`, `data`, `value`, `gas`, `gasPrice`.
- Approve transaction uses `/api/v6/dex/aggregator/approve-transaction` and does not broadcast.
- Broadcast is a separate explicit call.
- Order status uses `/api/v6/dex/post-transaction/orders`.
- Quote/swap tests do not sign or broadcast.
- Missing OKX environment keys fail before network access and do not print configured secret values.
- Live OKX swap transaction construction and sign_only are verified for native `ETH -> USDC` and `USDC -> VIRTUAL`.

### Step 7: RiskEngine

Evidence:

- `app/risk/risk_engine.py`
- `tests/test_risk_engine.py`

Verified:

- Amount over `max_single_trade_usd` is rejected.
- Daily total context over `max_daily_trade_usd` is rejected.
- Order slippage over `max_slippage_percent` is rejected.
- Unknown token is rejected when `allow_unknown_tokens=false`.
- Blocked token and blocked contract addresses are rejected.
- Insufficient wallet balance context is rejected.
- SQLite risk context provider derives daily stable-token spend from stored order statuses.
- SQLite risk context provider maps wallet balance tokens by symbol and address for balance checks.
- Excess `priceImpactPercent` is rejected.
- Natural-language source requires confirmation.

### Step 8: MarketOrder Dry-Run and Sign/Live Guard Path

Evidence:

- `app/orders/order_service.py`
- `tests/test_order_service.py`

Verified:

- Dry-run market order creates DB record.
- Quote is requested.
- Risk decision is persisted.
- Quote and risk decision evidence can be queried from SQLite after dry-run submission.
- Pending confirmation status is reached.
- Risk rejection ends in `FAILED`.
- No signing or broadcasting occurs in dry-run tests.
- `sign_only` confirmation signs a mocked OKX swap tx and does not broadcast.
- `sign_only` rejects malformed OKX swap tx responses before signing.
- `sign_only` rejects OKX swap tx responses whose `chainId` does not match Base (`8453`).
- tx build failures, signer failures, and invalid broadcast responses are marked `FAILED` and recorded in the executions table.
- live mode refuses to broadcast unless `live_enabled=True`.
- live mode broadcasts only when explicitly enabled in a mocked execution client.
- live mode requires broadcast response to include a tx hash or OKX order id before marking an order `BROADCASTED`.
- approval decisions are persisted.
- Execution records can be queried from SQLite for sign/live verification evidence.
- OrderService passes risk context providers into RiskEngine, enabling balance and daily-limit checks in the execution pipeline.
- OrderService rejects when SQLite-derived daily spend would exceed `max_daily_trade_usd`.
- A gated real OKX sign_only test exists and requires `RUN_LIVE_OKX_SIGN_ONLY_TESTS=1`, OKX env, and the configured Keychain wallet.
- A gated small live trade test exists and requires `RUN_LIVE_TRADE_TESTS=1`, `CONFIRM_LIVE_TRADE_BASE=YES`, OKX env, and the configured Keychain wallet.
- OKX receipt tracker can refresh broadcasted order status and persist `FILLED` or `FAILED` results from mocked OKX status responses.
- Real OKX sign_only passed for native `ETH -> USDC` and `USDC -> VIRTUAL`, with `LIVE_TRADE_USD_VALUE=0.01`.
- Real small live trades passed for `USDC_TO_VIRTUAL` and native `ETH_TO_USDC`, with `LIVE_TRADE_USD_VALUE=0.01`.
- OKX broadcast/status paths use current v6 endpoints.
- Durable live evidence DB `var/phase1_live_evidence.sqlite` contains 3 market orders, 1 conditional order, 3 quotes, 3 risk decisions, 3 approvals, 3 executions, and 23 events from the latest live broadcast run.
- Each live order recorded a DeBank post-trade observation event.

### Step 9: ConditionalOrderWatcher

Evidence:

- `app/orders/conditional_watcher.py`
- `app/data/price_provider.py`
- `tests/test_conditional_watcher.py`
- `tests/test_data_services.py`

Verified:

- Condition false keeps order `ACTIVE`.
- Condition true marks order `TRIGGERED`.
- Triggered conditional order generates MarketOrder through OrderService.
- Already-triggered conditional orders are not retriggered on the next watcher tick.
- Paused conditional orders are not price-polled.
- Expired conditional order becomes `EXPIRED` and is not recovered as active.
- DeBank-backed price provider returns Decimal prices through the price provider interface.
- Real local watcher limit-order sign_only passed: DeBank current VIRTUAL price triggered `USDC -> VIRTUAL`, then MarketOrder completed OKX swap tx construction and LocalSigner sign_only without broadcast.
- Real local watcher limit-order live broadcast passed: DeBank current VIRTUAL price triggered `USDC -> VIRTUAL`, then MarketOrder completed OKX v6 broadcast, receipt tracking, and DeBank post-trade observation.

### Step 10: Telegram Parameter Command Parser

Evidence:

- `app/bot/command_parser.py`
- `tests/test_command_parser.py`
- `app/bot/telegram_handlers.py`
- `app/bot/runtime.py`
- `tests/test_telegram_handlers.py`
- `tests/test_bot_runtime.py`

Verified:

- `/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 5` parses to `MarketOrder` with Base USDC as the default input token.
- `/sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 10000` parses to `MarketOrder` with Base USDC as the default output token.
- `/quote 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 5` does not create a live order.
- `/limit_buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 5 at 1.2` parses to `ConditionalOrder` with Base USDC as the default input token and `<=` USD price trigger.
- `/limit_sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 10000 at 1.8` parses to `ConditionalOrder` with Base USDC as the default output token and `>=` USD price trigger.
- `/buy` and `/sell` can override the default route token with `--with TOKEN_IN_ADDRESS` and `--to TOKEN_OUT_ADDRESS`.
- Trade command token inputs reject symbol names and require `0x...` addresses.
- `/confirm`, `/reject`, `/cancel` parse order ids.
- Unknown commands fail explicitly.
- Parser errors return safe Telegram responses and do not create orders.
- Invalid, zero, negative, or non-finite numeric command parameters fail as `CommandParseError`.
- Confirmation handler calls OrderService and persists approval decisions.
- Reject handler persists user rejection.
- Cancel handler updates order status.
- Cancel handler updates conditional order status.
- Canceling an unknown order returns explicit `NOT_FOUND` instead of a storage traceback.
- `/status`, `/orders`, and `/balance` have runtime handler skeletons with injectable services.
- Transport-agnostic Telegram runtime sends handler responses through an injected transport.
- Telegram HTTP transport uses Bot API `sendMessage` and `getUpdates` without importing the broken local `telegram` package.
- `poll_once` handles allowed-chat messages and advances update offset.
- `/quote 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 2` calls the quote client, returns a quote summary, and does not create an order.
- Quote command tests verify no order record is created and the requested amount is converted to Base token units.
- Message formatting helpers truncate addresses and format OKX router quote fields without printing secrets.

Future hardening:

- Production-grade interactive buttons and richer risk summary formatting can be added after Phase 1.

External verification:

- Real Telegram HTTP transport passed sendMessage and getUpdates with the configured private chat id.

### Step 10.5: Environment Readiness Check

Evidence:

- `app/config/environment_check.py`
- `tests/test_environment_check.py`

Verified:

- Reports Base chain id.
- Reports whether DeBank, OKX, Telegram, Base RPC, and Keychain signer references are configured.
- Derives wallet address from the configured signer without printing the private key.
- Detects wallet address mismatch if runtime config address is non-zero and differs from the derived signer address.
- Report text does not include raw secret values.

### Step 11: Legacy Migration Boundary

Evidence:

- `app/strategies/copy_trade.py`
- `app/data/token_report.py`
- `tests/test_copy_trade_strategy.py`
- `tests/test_token_report.py`

Verified:

- Mock DeBank history can produce a `copy_trade` MarketOrder.
- CopyTradeStrategy does not execute trades directly.
- Copy amount obeys `buy_ratio` and `max_copy_trade_usd`.
- Buy and sell swaps are both classified from DeBank `sends` and `receives`.
- Transfer parsing supports both list and dict shapes, root-level and item-level `token_dict`, plus inline token metadata.
- Failed transactions, approval events, and non-Base history items are skipped.
- DeBank-shaped Base swap fixture covers buy and sell conversion into `copy_trade` MarketOrders.
- Real DeBank signer wallet history can generate `copy_trade` OrderIntent records without executing trades.
- Token report covers token info, price, holders, and message formatting.
- Old OKX market-swap behavior is covered by the current `USDC_TO_VIRTUAL` live broadcast path and native `ETH_TO_USDC` live broadcast path through the new OrderService/OKX v6 executor.

## Remaining Phase 1 Work

No required Phase 1 verification item remains open in the current plan. Future hardening work can improve interactive Telegram buttons, richer risk summaries, and longer receipt polling, but these are not blocking Phase 1 completion.
