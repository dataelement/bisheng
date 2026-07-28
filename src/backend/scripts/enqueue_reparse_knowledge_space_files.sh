#!/bin/bash

# Enqueue knowledge-space files for worker-based reparse.
#
# Usage:
#   bash scripts/enqueue_reparse_knowledge_space_files.sh
#   bash scripts/enqueue_reparse_knowledge_space_files.sh --apply
#   bash scripts/enqueue_reparse_knowledge_space_files.sh --apply --space-id 10

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

"${PYTHON_BIN}" scripts/enqueue_reparse_knowledge_space_files.py "$@"
