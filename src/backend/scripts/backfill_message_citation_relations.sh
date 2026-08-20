#!/bin/bash
# Backfill message_citation_relation after deploying the shared-citation hotfix.
#
# Usage (run from src/backend/):
#   bash scripts/backfill_message_citation_relations.sh
#   bash scripts/backfill_message_citation_relations.sh --recover-markers apply
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

ARGS=()
for arg in "$@"; do
    if [ "$arg" = "apply" ]; then
        ARGS+=("--apply")
    else
        ARGS+=("$arg")
    fi
done

"${PYTHON_BIN}" scripts/backfill_message_citation_relations.py "${ARGS[@]}"
