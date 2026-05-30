#!/usr/bin/env bash
set -euo pipefail

cd /Users/macbot/Documents/tele_get
exec /usr/bin/env python3 -m tg_web_recorder.service \
  --config /Users/macbot/Documents/tele_get/config.yaml \
  --env /Users/macbot/Documents/tele_get/.env \
  --profile /Users/macbot/Documents/tele_get/profiles/telegram-web \
  --once

