#!/bin/bash
# Backfill channel-module default permissions into legacy custom relation models.
#
# Usage (run from src/backend/):
#   bash scripts/migrate_channel_permissions_for_relation_models.sh         # dry-run
#   bash scripts/migrate_channel_permissions_for_relation_models.sh apply   # persist
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

ARGS=()
if [ "$1" = "apply" ]; then
    ARGS+=("--apply")
fi

"${PYTHON_BIN}" scripts/migrate_channel_permissions_for_relation_models.py "${ARGS[@]}"
