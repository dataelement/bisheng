#!/bin/bash

# Reparse knowledge-space files with bounded local concurrency.
#
# Usage:
#   bash scripts/reparse_knowledge_space_files.sh
#   bash scripts/reparse_knowledge_space_files.sh --apply --concurrency 4
#   bash scripts/reparse_knowledge_space_files.sh --apply --space-id 10 --folder-id 20

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

"${PYTHON_BIN}" scripts/reparse_knowledge_space_files.py "$@"
