#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

set -a
if [[ -f .env ]]; then
  source .env
fi
set +a

PYTHONDONTWRITEBYTECODE=1 python -m app.configure_bot_commands

