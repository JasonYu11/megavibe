# Phase 2.5 Alpha Runbook

## Goal

Phase 2.5 turns the verified Phase 2 trading framework into a local alpha Telegram bot. The default mode is safe: dry-run execution, read-only DeBank queries, persistent SQLite state, and no live broadcast unless live mode and live env gates are both enabled.

## Runtime Files

- `configs/runtime.local.yaml`: local runtime config for this machine.
- `.env`: API keys, Telegram token/chat id, RPC URL, and live flags.
- macOS Keychain: wallet private key under `KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1`.
- `var/orders.sqlite`: long-running bot state.
- `var/phase2_live_evidence.sqlite`: explicit live regression evidence DB.

## Safety Gates

Dry-run startup is the default:

```bash
scripts/start_bot_dry_run.sh
```

Live startup requires all of:

```text
APP_EXECUTION_MODE=live
RUN_LIVE_TRADE_TESTS=1
CONFIRM_LIVE_TRADE_BASE=YES
LIVE_TRADE_USD_VALUE<=0.05
```

Use:

```bash
scripts/start_bot_live.sh
```

The script refuses to start if the live flags are missing or if `LIVE_TRADE_USD_VALUE` is above the safety cap.

## Telegram Access Control

Set these in `.env`:

```bash
TELEGRAM_DEFAULT_CHAT_ID=7433362014
TELEGRAM_ALLOWED_USER_IDS=7433362014
```

`TELEGRAM_DEFAULT_CHAT_ID` is always treated as an allowed chat. If `TELEGRAM_ALLOWED_USER_IDS` is set, only those Telegram user ids can issue commands.

Unauthorized requests return:

```text
Unauthorized
```

## Commands

Direct commands:

```text
/status
/mode
/balance
/orders
/history
/order ORDER_ID
/quote TOKEN_IN_ADDRESS TOKEN_OUT_ADDRESS AMOUNT
/buy TOKEN_OUT_ADDRESS AMOUNT
/sell TOKEN_IN_ADDRESS AMOUNT
/limit_buy TOKEN_OUT_ADDRESS AMOUNT at TARGET_PRICE
/limit_sell TOKEN_IN_ADDRESS AMOUNT at TARGET_PRICE
/confirm ORDER_ID
/reject ORDER_ID
/cancel ORDER_ID
```

Guided flow:

```text
/trade
```

The bot then asks for Buy / Sell / Limit Buy / Limit Sell, token address, amount, limit price where needed, and review confirmation.

## Startup Verification

Environment:

```bash
scripts/check_env.sh
```

Single tick smoke test:

```bash
set -a; source .env; set +a
PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot \
  --runtime-config configs/runtime.local.yaml \
  --db-path /private/tmp/phase2_5_startup_check.sqlite \
  --once
```

Expected:

```text
tick telegram_ok=True watcher_ok=True receipt_ok=True heartbeat_ok=True
```

Default tests:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests
```

Live evidence audit:

```bash
scripts/audit_live_evidence.sh
```

## Alpha Operating Rules

- Keep `configs/runtime.local.yaml` in `dry_run` unless deliberately testing live.
- Do not allow live startup without `TELEGRAM_ALLOWED_USER_IDS`.
- Rotate Telegram bot token if it has appeared in any terminal output.
- Keep test wallet funded with only small amounts.
- Prefer `/reject` when testing order creation.
- Use `/cancel` for active conditional orders that should not remain watched.

## 2026-05-29 Interaction Upgrade

Implemented:

- Telegram user-facing messages now use Chinese for the main trading surfaces.
- Market order creation returns a confirmation card before execution, including:
  - order id
  - side/provider
  - pay token and amount
  - receive token
  - estimated receive when quote provides it
  - min receive when quote provides it
  - price impact
  - max slippage
  - risk decision
- Limit order creation no longer enters watcher immediately. It is first stored as `PENDING_CONFIRMATION`.
- `/confirm LIMIT_ORDER_ID` activates the limit order and starts watcher monitoring.
- `/reject LIMIT_ORDER_ID` rejects and cancels the pending limit order.
- `/confirm MARKET_ORDER_ID` returns a Chinese execution result summary with:
  - order id
  - execution status
  - tx tracking reference when available
  - submission time when available
  - estimated fill/min receive/price impact when quote evidence is available
  - wallet balance summary when balance service is available
- `/balance` displays DeBank `usd_value` and key token balances for ETH/USDC when available.

Verified:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests
# 154 passed, 13 skipped
```

Known product gaps for later hardening:

- Real filled amount and average execution price require receipt/log or DeBank history parsing after the transaction is mined; current live confirmation can only report broadcast/tracking plus quote-based estimates.
- Telegram Markdown/HTML formatting is not enabled yet, so current layout is plain text. Rich formatting should be added carefully with escaping.
- Conditional order trigger notifications should include trigger price, quote at trigger, and whether the market order is waiting for confirmation.
- A background post-trade notifier should send a second message after receipt reaches final `FILLED` or `FAILED`.
- Balance display should eventually show token contract, token amount, USD value, and last refresh time.

## 2026-05-29 Order UI / Management Upgrade

Implemented:

- `/start` returns a Chinese home panel with quick buttons for guided trade, current orders, and history.
- `/help` returns concise Chinese command examples.
- `/orders` now shows only current actionable orders:
  - market orders in `PENDING_CONFIRMATION`, `SIGNING`, or `BROADCASTED`;
  - limit orders in `PENDING_CONFIRMATION`, `ACTIVE`, `TRIGGERED`, `EXECUTING`, or `PAUSED`.
- `/history` shows recent completed/rejected/cancelled/expired orders separately from current orders.
- `/order ORDER_ID` shows a single market or limit order detail panel, including status, route/condition, latest approval, latest execution, tx tracking reference, and event count when available.
- Inline navigation buttons were added for:
  - home panel to guided trade / current orders / history;
  - current/history panels;
  - individual order refresh/cancel/current-orders.
- Telegram slash command recommendations are now represented in `app.bot.command_menu.BOT_COMMANDS`.
- `scripts/configure_bot_commands.sh` can publish the command menu to Telegram with `setMyCommands`.
- Conditional watcher now records a `conditional_triggered_market_order` event containing trigger price, market order id, and market order status.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_command_parser.py tests/test_sqlite_store.py tests/test_message_format.py tests/test_telegram_handlers.py tests/test_bot_runtime.py tests/test_conditional_watcher.py
# 67 passed

PYTHONDONTWRITEBYTECODE=1 pytest -q tests
# 160 passed, 13 skipped

scripts/check_env.sh
# wallet.signer OK; derived address 0x8EF454c23822C5373df37e8c5E8987aC64dB96F1

set -a; source .env; set +a
PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot \
  --runtime-config configs/runtime.local.yaml \
  --db-path /private/tmp/phase2_6_startup_check.sqlite \
  --once
# tick telegram_ok=True watcher_ok=True receipt_ok=True heartbeat_ok=True
```

To configure Telegram `/` command recommendations:

```bash
scripts/configure_bot_commands.sh
# configured 15 Telegram bot commands
```
