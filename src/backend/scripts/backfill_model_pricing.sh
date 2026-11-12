#!/bin/bash
# F015: give every existing LLM model a price, then gate the upgrade (run AFTER `alembic upgrade head`,
# while the service is still stopped; see features/v3.1.0-beta1/015-credit-pricing/runbook.md).
#
# Usage (run from src/backend/):
#   bash scripts/backfill_model_pricing.sh           # dry run (default, no writes)
#   bash scripts/backfill_model_pricing.sh apply     # write prices for models that have none
#   bash scripts/backfill_model_pricing.sh check     # gate: exit 0 only when nothing is missing
set -e

export PYTHONPATH="./"
export config="${config:-config.yaml}"

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

# Translate the convenience tokens `apply` / `check`; forward everything else.
ARGS=()
for arg in "$@"; do
    case "$arg" in
        apply) ARGS+=("--apply") ;;
        check) ARGS+=("--check") ;;
        *) ARGS+=("$arg") ;;
    esac
done

"${PYTHON_BIN}" scripts/backfill_model_pricing.py "${ARGS[@]}"
