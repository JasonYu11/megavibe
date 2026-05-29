# Live Broadcast Test Setup

This document defines the real broadcast tests used by Phase 1 and Phase 2 verification. Defaults must stay safe: no live network or broadcast test runs unless its explicit `RUN_*` flag is enabled.

## Current Goal

Phase live verification closes on real broadcast evidence, not only dry-run or sign-only evidence. The live test goal is:

- Broadcast 0.01 USD value market swaps on Base with the local Keychain test wallet.
- Cover native `ETH -> USDC` and `USDC -> VIRTUAL`.
- Persist order, quote, risk, approval, execution, receipt, and post-trade evidence.
- Prove the local watcher limit-order path can trigger from real DeBank price data and then proceed through the same market-order infrastructure.
- Keep every real broadcast behind `RUN_LIVE_TRADE_TESTS=1` and `CONFIRM_LIVE_TRADE_BASE=YES`.

## Required Keys and Local Secrets

Do not print or commit real values. Put API credentials in `.env`; put wallet private keys in macOS Keychain.

| Name | Where | Used for | Required for |
| --- | --- | --- | --- |
| `DEBANK_ACCESS_KEY` | `.env` | DeBank read-only API | DeBank token/history/balance tests |
| `OKX_API_KEY` | `.env` | OKX Web3 API auth | OKX quote/swap/broadcast/status tests |
| `OKX_SECRET_KEY` | `.env` | OKX request signing | OKX quote/swap/broadcast/status tests |
| `OKX_API_PASSPHRASE` | `.env` | OKX request signing | OKX quote/swap/broadcast/status tests |
| `OKX_PROJECT_ID` | `.env` | OKX Web3 project header | OKX quote/swap/broadcast/status tests |
| `TELEGRAM_BOT_TOKEN` | `.env` | Telegram Bot HTTP API | Telegram send/poll tests |
| `TELEGRAM_DEFAULT_CHAT_ID` | `.env` | target chat for bot messages | Telegram live send tests |
| `BASE_RPC_URL` | `.env` | Base RPC endpoint | later receipt/RPC balance checks |
| `AGENT_WALLET_PRIVATE_KEY_BASE_TEST1` | macOS Keychain | local EVM signer | sign_only/live trade tests |
| `LIVE_WALLET_SECRET_REF` | `.env` optional | signer ref override, for example `KEYCHAIN:...` or `ENV:...` | sign_only/live trade tests |
| `DEBANK_TEST_ADDRESS` | `.env` | stable public wallet fixture | live DeBank history tests |
| `LIVE_EVIDENCE_DB_PATH` | `.env` | durable SQLite evidence DB | live broadcast evidence |

Current Keychain reference:

```text
KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1
```

Create or update it with:

```bash
security add-generic-password -U -a base_main_test -s AGENT_WALLET_PRIVATE_KEY_BASE_TEST1 -w 'YOUR_TEST_WALLET_PRIVATE_KEY'
```

If the signer secret is intentionally stored somewhere else, set a signer ref override instead of changing test code:

```bash
LIVE_WALLET_SECRET_REF=KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1
# or, only for local test wallets:
LIVE_WALLET_SECRET_REF=ENV:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1
```

Do not print the private key value and do not commit it to the repository.

The test wallet must be a small Base wallet funded only for testing. For live swap tests it needs:

- Base ETH for gas.
- USDC on Base for the test amount.
- Recommended `LIVE_TRADE_USD_VALUE=0.01`.
- Hard test cap: `LIVE_TRADE_USD_VALUE <= 0.05`.

## `.env` Template

```bash
DEBANK_ACCESS_KEY=...

OKX_API_KEY=...
OKX_SECRET_KEY=...
OKX_API_PASSPHRASE=...
OKX_PROJECT_ID=...

TELEGRAM_BOT_TOKEN=...
TELEGRAM_DEFAULT_CHAT_ID=...

BASE_RPC_URL=https://mainnet.base.org
LIVE_WALLET_SECRET_REF=KEYCHAIN:base_main_test:AGENT_WALLET_PRIVATE_KEY_BASE_TEST1

RUN_LIVE_DEBANK_TESTS=0
RUN_LIVE_OKX_TESTS=0
RUN_LIVE_OKX_SIGN_ONLY_TESTS=0
RUN_LIVE_TELEGRAM_TESTS=0
RUN_LIVE_TRADE_TESTS=0
CONFIRM_LIVE_TRADE_BASE=NO
CONFIRM_LIVE_LIMIT_TRADE_BASE=NO
LIVE_TRADE_USD_VALUE=0.01
LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL
LIVE_EVIDENCE_DB_PATH=var/phase2_live_evidence.sqlite

DEBANK_TEST_ADDRESS=...
```

## Test Matrix

### 0. Environment Readiness

Purpose: confirm which keys are available without printing secret values.

```bash
PYTHONDONTWRITEBYTECODE=1 python -m app.config.environment_check
```

Passing condition:

- `chain.base OK`
- `debank.access_key OK`
- OKX keys `OK`
- Telegram token/chat `OK`
- `base.rpc_url OK`
- `wallet.signer OK`

### 1. DeBank Real Read Tests

Implemented:

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_DEBANK_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_debank_token_info_when_enabled
```

Verifies:

- DeBank API key works.
- Base USDC token info returns symbol and decimals.
- No Basescan dependency.

Recommended additions:

- `test_live_debank_user_history_when_enabled`
  - Input: `DEBANK_TEST_ADDRESS`.
  - Verify `get_user_history()` returns `history_list` and `token_dict` shape.
- `test_live_debank_wallet_balance_for_signer_when_enabled`
  - Input: Keychain signer-derived address.
  - Verify `get_user_chain_balance()` returns a dict and does not print wallet secret.
- `test_live_debank_observes_trade_after_live_swap_when_enabled`
  - Input: live swap tracking id or signer address.
  - Verify DeBank history eventually includes the post-trade wallet activity.

### 2. OKX Quote Test

Implemented:

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_okx_quote_when_enabled
```

Requires:

- `OKX_API_KEY`
- `OKX_SECRET_KEY`
- `OKX_API_PASSPHRASE`
- `OKX_PROJECT_ID`

Verifies:

- OKX v6 quote endpoint works for Base USDC -> VIRTUAL.
- No signing.
- No broadcast.

### 3. OKX Swap `sign_only` Test

Implemented:

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_okx_swap_sign_only_when_enabled
```

Requires:

- All OKX keys.
- Keychain test wallet.
- Test wallet address derivable from private key.
- Optional `LIVE_TRADE_USD_VALUE=0.01`.
- sign_only route matrix covers `ETH -> USDC` and `USDC -> VIRTUAL`.

Verifies:

- OKX returns a real swap unsigned tx.
- LocalSigner signs locally.
- No broadcast occurs.
- SQLite records `SIGNED_NOT_BROADCASTED` and tx hash.

### 4. Explicit Small Live Swap Test

Implemented and intentionally dangerous unless explicitly enabled:

```bash
PYTHONDONTWRITEBYTECODE=1 \
RUN_LIVE_TRADE_TESTS=1 \
CONFIRM_LIVE_TRADE_BASE=YES \
LIVE_TRADE_USD_VALUE=0.01 \
LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL \
pytest -q tests/test_live_integrations.py::test_live_small_trade_when_explicitly_enabled
```

Requires:

- All OKX keys.
- Keychain test wallet.
- Base ETH gas.
- Base USDC for `USDC -> VIRTUAL`, and Base native ETH for `ETH -> USDC`.
- Explicit `CONFIRM_LIVE_TRADE_BASE=YES`.

Verifies:

- Real OKX swap tx is signed locally; sign_only covers `ETH -> USDC` and `USDC -> VIRTUAL`.
- Signed tx is broadcast through OKX.
- Durable SQLite records `BROADCASTED`.
- Execution row has tx hash or OKX order id.
- Receipt and post-trade observation evidence are recorded in `LIVE_EVIDENCE_DB_PATH`.

Recommended addition:

- `test_live_conditional_limit_sign_only_when_enabled`
  - Use DeBank current VIRTUAL price and an immediately triggerable local watcher condition.
  - Verify watcher trigger -> MarketOrder -> quote/risk/approval -> sign_only without broadcast.
- `test_live_conditional_limit_trade_when_explicitly_enabled`
  - Requires `RUN_LIVE_TRADE_TESTS=1`, `CONFIRM_LIVE_TRADE_BASE=YES`, and `CONFIRM_LIVE_LIMIT_TRADE_BASE=YES`.
  - Uses DeBank current VIRTUAL price and an immediately triggerable local watcher condition.
  - Verifies watcher trigger -> MarketOrder -> quote/risk/approval -> OKX v6 broadcast.
  - Persists conditional event, market order, execution, receipt, and post-trade observation in `LIVE_EVIDENCE_DB_PATH`.
- `test_live_okx_receipt_tracking_after_small_trade`
  - Verify OKX/RPC status after broadcast and persist evidence.
  - Input: broadcast tracking id.
  - Verify `OkxReceiptTracker` reaches `FILLED`, `FAILED`, or remains `BROADCASTED` with status evidence.

### 5. Telegram Bot Tests

Implemented send test:

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TELEGRAM_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_telegram_send_message_when_enabled
```

Requires:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_DEFAULT_CHAT_ID`

Verifies:

- Bot token works.
- Bot can send to the configured chat.

Recommended additions:

- `test_live_telegram_get_updates_when_enabled`
  - Verify `getUpdates` works without `python-telegram-bot`.
- Manual command test in Telegram:
  - `/status`
  - `/quote 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 1`
  - `/buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 1`
  - `/reject ORDER_ID`
  - `/limit_buy 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 1 at 1.2`
  - `/limit_sell 0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b 10000 at 1.8`
  - `/cancel ORDER_ID`
- Optional confirmation flow:
  - Create a dry-run order.
  - `/confirm ORDER_ID`.
  - Verify SQLite approval and execution rows.

## Safe Verification Order

Run in this order:

1. Environment readiness.
2. Full local tests.
3. DeBank token live test.
4. OKX quote live test.
5. Telegram send live test.
6. Keychain signer test.
7. OKX `sign_only` test.
8. Small live swap test.
9. Receipt tracking and DeBank post-trade observation.

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 pytest -q tests
PYTHONDONTWRITEBYTECODE=1 python -m app.config.environment_check
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_DEBANK_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_debank_token_info_when_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_okx_quote_when_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TELEGRAM_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_telegram_send_message_when_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_OKX_SIGN_ONLY_TESTS=1 pytest -q tests/test_live_integrations.py::test_live_okx_swap_sign_only_when_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL LIVE_EVIDENCE_DB_PATH=var/phase2_live_evidence.sqlite pytest -q tests/test_live_integrations.py::test_live_small_trade_when_explicitly_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES CONFIRM_LIVE_LIMIT_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_EVIDENCE_DB_PATH=var/phase2_live_evidence.sqlite pytest -q tests/test_live_integrations.py::test_live_conditional_limit_trade_when_explicitly_enabled
```

## Phase 2 Runtime Regression

After Phase 2 runtime wiring, verify the local Telegram runtime without live broadcast first:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m app.run_bot --once --db-path var/phase2_runtime_check.sqlite
```

Expected:

- Command exits after one orchestrator tick.
- SQLite stores `heartbeat_at`.
- If Telegram chat id is configured, `telegram_offset` is updated after polling.
- If watcher or receipt tracker fails, an event is written instead of crashing the process.

Manual Telegram dry-run smoke test:

```text
/status
/balance
/orders
/trade
Buy
0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b
0.01
Confirm
/reject ORDER_ID
```

Expected:

- `/trade` can also use inline buttons for Buy / Sell / Limit Buy / Limit Sell.
- Market order reaches `PENDING_CONFIRMATION` before any execution.
- Confirm/reject/cancel inline callbacks are equivalent to text commands.
- `/status` shows execution mode, DB path, heartbeat, Telegram offset, watcher health, and receipt tracker health.
- `/orders` shows id/status plus amount/token/trigger summaries.

Phase 2 live regression still uses the same explicit live gates as Phase 1:

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_TRADE_ROUTE=USDC_TO_VIRTUAL LIVE_EVIDENCE_DB_PATH=var/phase2_live_evidence.sqlite pytest -q tests/test_live_integrations.py::test_live_small_trade_when_explicitly_enabled
PYTHONDONTWRITEBYTECODE=1 RUN_LIVE_TRADE_TESTS=1 CONFIRM_LIVE_TRADE_BASE=YES CONFIRM_LIVE_LIMIT_TRADE_BASE=YES LIVE_TRADE_USD_VALUE=0.01 LIVE_EVIDENCE_DB_PATH=var/phase2_live_evidence.sqlite pytest -q tests/test_live_integrations.py::test_live_conditional_limit_trade_when_explicitly_enabled
```

Do not increase `LIVE_TRADE_USD_VALUE` above the configured safety cap, and do not run these commands without the explicit confirmation flags.

After both Phase 2 live regressions finish, audit the durable evidence DB:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m app.verification.live_evidence_audit --db-path var/phase2_live_evidence.sqlite
```

Expected:

- The command exits with status `0`.
- At least one direct market live order is present.
- At least one watcher-triggered limit live order is present.
- At least one conditional order is triggered.
- Every live order has quote, risk decision, confirmed approval, live execution with tx hash, receipt payload, and post-trade observation event.
- No private key, signer ref, API key ref, DeBank key ref, OKX secret ref, or Telegram bot token ref appears in SQLite payloads.

## Future Hardening

These are useful after Phase 1 but are not blocking current completion:

- Longer-running receipt polling that waits for final `FILLED` or `FAILED` instead of accepting immediate `BROADCASTED`.
- Optional CLI/manual Telegram command script for repeated full-flow smoke tests.
- Richer per-order PnL and receipt summaries.
