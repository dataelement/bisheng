#!/bin/bash

# List platform Super Admin users (full JSON by default).
#
# Usage:
#   bash scripts/list_admin_users.sh
#   bash scripts/list_admin_users.sh --brief
#   bash scripts/list_admin_users.sh --include-deleted

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

"${PYTHON_BIN}" scripts/list_admin_users.py "$@"
