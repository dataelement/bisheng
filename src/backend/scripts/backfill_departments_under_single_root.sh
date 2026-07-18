#!/bin/bash
# Collapse all mis-rooted departments under the single default-org root so the
# whole platform has exactly one root (DB-only: parent_id + cascade path).
#
# Usage (run from src/backend/):
#   bash scripts/backfill_departments_under_single_root.sh          # dry-run (default, no writes)
#   bash scripts/backfill_departments_under_single_root.sh apply    # persist
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

"${PYTHON_BIN}" scripts/backfill_departments_under_single_root.py "${ARGS[@]}"
