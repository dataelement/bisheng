#!/bin/bash
# Swap live tables with <table>_bak (live -> _ori, _bak -> live).
#
# Usage (from src/backend):
#   bash scripts/rollback_tag_library_migration.sh
#   bash scripts/rollback_tag_library_migration.sh --apply

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

"${PYTHON_BIN}" scripts/rollback_tag_library_migration.py "$@"
