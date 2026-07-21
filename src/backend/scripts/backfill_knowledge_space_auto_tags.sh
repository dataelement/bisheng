#!/bin/bash

# Backfill AI auto tags for knowledge-space files with too few tags.
#
# Usage:
#   bash scripts/backfill_knowledge_space_auto_tags.sh
#   bash scripts/backfill_knowledge_space_auto_tags.sh --apply --batch-size 20

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

"${PYTHON_BIN}" scripts/backfill_knowledge_space_auto_tags.py "$@"
