#!/bin/bash
# Backfill OpenFGA department#parent inheritance edges from the DB tree
# (additive / idempotent). Run AFTER backfill_departments_under_single_root.sh
# so parent_id is finalised first.
#
# Usage (run from src/backend/):
#   bash scripts/backfill_department_parent_tuples.sh          # dry-run (default, no writes)
#   bash scripts/backfill_department_parent_tuples.sh apply    # persist
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

# Translate the convenience token `apply` into `--apply`; forward everything else.
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "apply" ]; then
        ARGS+=("--apply")
    else
        ARGS+=("$arg")
    fi
done

"${PYTHON_BIN}" scripts/backfill_department_parent_tuples.py "${ARGS[@]}"
