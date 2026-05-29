# Simulated Telegram Test Plan

This test plan verifies the Telegram trading bot without sending real Telegram messages and without broadcasting live trades.

## Purpose

- Validate the same command path used by the long-running bot:
  - `TelegramRuntime.poll_once()`
  - `TelegramCommandHandler`
  - SQLite order store
  - conditional watcher
  - runtime notifications
- Avoid manual Telegram input during regression tests.
- Keep all tests in `dry_run` unless live gates are explicitly enabled elsewhere.

## Runtime Config Audit

The main program and dry-run script now use the same local runtime config:

```text
python -m app.run_bot
scripts/start_bot_dry_run.sh
```

Both resolve to:

```text
configs/runtime.local.yaml
configs/risk_policy.example.yaml
configs/strategies.example.yaml
var/orders.sqlite
```

The dry-run script additionally forces:

```text
APP_EXECUTION_MODE=dry_run
```

This is intentional. It prevents accidental live mode if `runtime.local.yaml` is edited later.

Covered by:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_runtime_entrypoints.py
```

## Simulated Telegram Flow

The simulated test constructs fake Telegram updates and feeds them into the real runtime poller.

Covered by:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_simulated_telegram_flow.py
```

### Flow 1: Normal Trading And Management

Simulated inputs:

```text
/start
/status
/balance
/quote USDC VIRTUAL 0.01
/buy VIRTUAL 0.01
callback: confirm market order
/limit_buy VIRTUAL 0.01 at 1
callback: confirm limit order
/orders
/history
```

Expected behavior:

- `/start` returns a Chinese home panel and navigation buttons.
- `/status` reports `execution_mode=dry_run`.
- `/balance` returns wallet balance formatting.
- `/quote` does not create an order.
- `/buy` creates a pending market order and asks for confirmation.
- confirming the market order returns `DRY_RUN_COMPLETED`.
- `/limit_buy` creates a pending limit order and asks for confirmation.
- confirming the limit order activates watcher.
- watcher sees current price below target and automatically executes the generated market order.
- Telegram receives a system notification: `限价单已自动执行`.
- `/orders` no longer shows the filled limit order as current.
- `/history` shows completed market and limit order history.

### Flow 2: Safety And Error Handling

Simulated inputs:

```text
unauthorized user: /buy VIRTUAL 0.01
authorized user: /buy VIRTUAL
```

Expected behavior:

- unauthorized user receives `Unauthorized`.
- malformed command returns `Command error`.
- neither path creates an order.

## Recommended Regression Command

Run this before restarting the bot after interaction changes:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q \
  tests/test_runtime_entrypoints.py \
  tests/test_simulated_telegram_flow.py \
  tests/test_message_format.py \
  tests/test_telegram_handlers.py \
  tests/test_bot_runtime.py \
  tests/test_runtime_orchestrator.py
```

Expected current result:

```text
50 passed
```
