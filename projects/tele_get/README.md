# tele_get

Telegram Web collector with LLM summaries and Telegram Bot pushes.

## What Runs

- Collects selected Telegram topics from `config.yaml`.
- Stores raw messages in SQLite with fingerprint deduplication.
- Sends new messages to the configured LLM API for Markdown summaries.
- Pushes immediate Telegram cards only when the newest message range has not already been pushed.
- Sends digest summaries at UTC `08:00` and `20:00`.

## One-Time Requirements

1. Fill `.env`:

```env
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_PUSH_CHAT_ID=...
```

2. Log in once using the dedicated Chrome profile:

```bash
cd /Users/macbot/Documents/tele_get
python3 tg_standalone_test.py --keep-open
```

Log in to Telegram Web in the opened Chrome window, then close it.

## Manual Commands

Run one full cycle:

```bash
/Users/macbot/Documents/tele_get/scripts/run_once.sh
```

Run long term in the foreground:

```bash
/Users/macbot/Documents/tele_get/scripts/run_service.sh
```

Logs:

```bash
tail -f /Users/macbot/Documents/tele_get/logs/service.log
```

## macOS launchd

Install:

```bash
mkdir -p ~/Library/LaunchAgents
cp /Users/macbot/Documents/tele_get/launchd/com.tele-get.recorder.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.tele-get.recorder.plist
```

Stop:

```bash
launchctl unload ~/Library/LaunchAgents/com.tele-get.recorder.plist
```

Restart:

```bash
launchctl unload ~/Library/LaunchAgents/com.tele-get.recorder.plist
launchctl load ~/Library/LaunchAgents/com.tele-get.recorder.plist
```

## Stability Notes

- `tg_web_recorder.service` catches per-cycle exceptions and continues after the next interval.
- Config and `.env` are reloaded each cycle.
- Digest pushes are persisted with a dedup key, so restart should not duplicate the same UTC slot.
- Immediate pushes are skipped if the latest message id for the target was already covered by a successful push.

