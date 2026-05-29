# Phase 2 Completion Audit

Audit date: 2026-05-28

This document records current evidence against the Phase 2 objective. It is not a replacement for tests; it is a checklist for deciding whether the active goal can be marked complete.

## Requirement Evidence

### 1. Telegram Direct Commands

Status: implemented and default-tested.

Evidence:

- `app/bot/command_parser.py`
- `app/bot/telegram_handlers.py`
- `tests/test_command_parser.py`
- `tests/test_telegram_handlers.py`

Verified behavior:

- `/buy TOKEN_OUT_ADDRESS AMOUNT`
- `/sell TOKEN_IN_ADDRESS AMOUNT`
- `/limit_buy TOKEN_OUT_ADDRESS AMOUNT at TARGET_PRICE`
- `/limit_sell TOKEN_IN_ADDRESS AMOUNT at TARGET_PRICE`
- `/quote`, `/balance`, `/orders`, `/status`, `/confirm`, `/reject`, `/cancel`
- Token arguments reject symbols and require `0x...` addresses.
- Default route token is Base USDC.

### 2. Telegram Guided Flow

Status: implemented and default-tested.

Evidence:

- `app/bot/guided_flow.py`
- `app/storage/sqlite_store.py`
- `tests/test_guided_flow.py`
- `tests/test_telegram_handlers.py`

Verified behavior:

- `/trade` starts a guided trade.
- Buy, Sell, Limit Buy, and Limit Sell are supported.
- The flow collects token address, amount, and limit price where needed.
- The flow enters a review step first.
- `Confirm` is required before creating a `MarketOrder` or `ConditionalOrder`.
- `/cancel` clears the draft.
- SQLite restores draft state after process restart.

### 3. Limit Order Review Price Distance

Status: implemented and default-tested.

Evidence:

- `app/bot/message_format.py`
- `app/bot/telegram_handlers.py`
- `tests/test_telegram_handlers.py`

Verified behavior:

- Conditional order review shows current USD price when `price_provider` is available.
- Review shows target USD price and `distance +N%` or `distance -N%`.
- Price lookup failure does not block order creation and reports `current price unavailable`.

### 4. Runtime Orchestrator

Status: implemented and default-tested.

Evidence:

- `app/bot/orchestrator.py`
- `app/run_bot.py`
- `app/bootstrap.py`
- `tests/test_runtime_orchestrator.py`
- `tests/test_bootstrap.py`

Verified behavior:

- One tick runs Telegram polling, ConditionalOrder watcher, receipt tracker, and heartbeat.
- `telegram_offset`, `heartbeat_at`, `watcher_last_ok`, and `receipt_last_ok` persist to SQLite.
- Submodule exceptions are isolated and recorded as runtime events.
- `python -m app.run_bot --once` exits after one tick.
- `python -m app.run_bot` is the long-running entrypoint and uses a stop event for graceful shutdown.

### 5. TokenResolver

Status: implemented and default-tested.

Evidence:

- `app/data/token_resolver.py`
- `app/bot/command_parser.py`
- `app/orders/order_service.py`
- `tests/test_data_services.py`
- `tests/test_order_service.py`

Verified behavior:

- Base USDC, native ETH, WETH, and VIRTUAL use local fallback metadata.
- Unknown `0x...` token addresses require DeBank metadata when a resolver is configured.
- Missing decimals fail explicitly.
- Live mode rejects unresolved parser fallback metadata before quote or broadcast.
- No Basescan API is used in the current Phase 2 path.

### 6. Telegram Query Capability

Status: implemented and default-tested.

Evidence:

- `app/bot/telegram_handlers.py`
- `app/bot/message_format.py`
- `app/data/balance_service.py`
- `tests/test_telegram_handlers.py`
- `tests/test_message_format.py`

Verified behavior:

- `/balance` uses injected DeBank balance service and formats total USD value.
- `/orders` lists market and conditional orders with id, status, side, amount, tokens, and trigger price.
- `/status` shows execution mode, DB path, heartbeat, Telegram offset, watcher health, and receipt tracker health.

### 7. Security Requirements

Status: implemented for default and dry-run paths; live proof is pending.

Evidence:

- `app/secrets/provider.py`
- `app/signing/local_signer.py`
- `app/orders/order_service.py`
- `tests/test_secrets_and_signer.py`
- `tests/test_order_info.py`
- `tests/test_telegram_handlers.py`
- `tests/test_environment_check.py`

Verified behavior:

- Private key is read only by `LocalSigner`.
- Order payload serialization excludes private key, signer refs, secret refs, API keys, and provider secret names.
- Telegram text and inline button markup do not include private key, signer ref, API key names, DeBank key names, or Telegram token names in tested paths.
- Environment check reports whether keys exist without printing values.
- Live broadcast remains gated by explicit env flags.
- Live trade value cap remains `<= 0.05`.

## Current Verification Commands

Passed:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_telegram_handlers.py tests/test_bot_runtime.py tests/test_message_format.py tests/test_runtime_orchestrator.py
PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot --once --db-path /private/tmp/phase2_runtime_check.sqlite
PYTHONDONTWRITEBYTECODE=1 python -m app.config.environment_check
PYTHONDONTWRITEBYTECODE=1 pytest -q tests
```

Latest default result:

```text
145 passed, 13 skipped
```

Latest runtime smoke result:

```text
PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot --once --db-path /private/tmp/phase2_runtime_check.sqlite
tick telegram_ok=True watcher_ok=True receipt_ok=True heartbeat_ok=True
```

Live evidence audit command to run after both live regressions:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m app.verification.live_evidence_audit --db-path var/phase2_live_evidence.sqlite
```

The audit requires at least one direct market live order, one watcher-triggered limit live order, one triggered conditional order, and per-order quote, risk decision, approval, live execution, receipt payload, and post-trade observation evidence.

Current audit result after live regression:

```text
phase2 live evidence audit: OK
db_path: var/phase2_live_evidence.sqlite
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
```

## Completion Status

Status: complete.

The Phase 2 completion evidence is now present in `var/phase2_live_evidence.sqlite`.

Live evidence summary:

```text
direct market order: ord_b5099081f50447838c4593b2cf7f0914
direct market tx: 0x103163b5f2a2965b02b0fb7b876a205a3363adbc2fb2d9a5336805f73d56f8c6
watcher-triggered market order: ord_258ecd99182f410186569dc9cc09da43
watcher-triggered tx: 0x389407085a27197222f628b90af2f55574f134dfde7d286899c33c0fab6b145e
```

Current environment check in sandbox-external execution:

```text
debank.access_key OK
okx.* OK
telegram.* OK
base.rpc_url OK
wallet.signer OK
```

The normal sandboxed Codex process cannot read the Keychain signer, but sandbox-external execution can. Live tests were executed sandbox-external with explicit live flags and `LIVE_TRADE_USD_VALUE=0.01`.

Default live flags remain disabled:

```text
RUN_LIVE_TRADE_TESTS=0
CONFIRM_LIVE_TRADE_BASE=NO
```

Live completion was run with:

```bash
LIVE_WALLET_SECRET_REF=<local signer ref>
RUN_LIVE_TRADE_TESTS=1
CONFIRM_LIVE_TRADE_BASE=YES
LIVE_TRADE_USD_VALUE=0.01
LIVE_EVIDENCE_DB_PATH=var/phase2_live_evidence.sqlite
```

And for watcher limit live regression:

```bash
CONFIRM_LIVE_LIMIT_TRADE_BASE=YES
```

No remaining Phase 2 completion blocker is known after the live evidence audit and default test suite pass.
