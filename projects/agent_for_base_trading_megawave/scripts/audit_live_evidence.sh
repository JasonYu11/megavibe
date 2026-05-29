#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHONDONTWRITEBYTECODE=1 python -m app.verification.live_evidence_audit \
  --db-path "${LIVE_EVIDENCE_DB_PATH:-var/phase2_live_evidence.sqlite}"

