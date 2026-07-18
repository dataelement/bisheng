#!/bin/bash
# Backfill ReBAC viewer/manager grants for already-active channel subscribers
# whose grant was never written (activated before commit c530bf375).
#
# Usage (run from src/backend/):
#   bash scripts/backfill_channel_member_rebac_grants.sh                         # dry-run, all channels
#   bash scripts/backfill_channel_member_rebac_grants.sh apply                   # persist, all channels
#   bash scripts/backfill_channel_member_rebac_grants.sh --channel-id <id>       # dry-run, one channel
#   bash scripts/backfill_channel_member_rebac_grants.sh --channel-id <id> apply # persist, one channel
set -e

export PYTHONPATH="./"

if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Python interpreter not found." >&2
    exit 1
fi

# Translate the convenience token `apply` into `--apply`; forward everything else.
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "apply" ]; then
        ARGS+=("--apply")
    else
        ARGS+=("$arg")
    fi
done

"${PYTHON_BIN}" scripts/backfill_channel_member_rebac_grants.py "${ARGS[@]}"
