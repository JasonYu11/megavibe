#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

set -a
if [[ -f .env ]]; then
  source .env
fi
set +a

APP_EXECUTION_MODE=dry_run \
PYTHONDONTWRITEBYTECODE=1 \
python -m app.run_bot \
  --runtime-config "${RUNTIME_CONFIG:-configs/runtime.local.yaml}" \
  --risk-config "${RISK_CONFIG:-configs/risk_policy.example.yaml}" \
  --strategies-config "${STRATEGIES_CONFIG:-configs/strategies.example.yaml}" \
  --db-path "${ORDER_DB_PATH:-var/orders.sqlite}"

