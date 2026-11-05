#!/bin/bash

# Inspect, grant or revoke a platform Super Admin.
#
# Usage:
#   bash scripts/set_admin.sh <user_id>
#   sh   scripts/set_admin.sh <user_id>
#
# Example:
#   bash scripts/set_admin.sh 1   # promote user_id=1 to Super Admin
#   bash scripts/set_admin.sh 7 --action status
#   bash scripts/set_admin.sh 7 --action revoke          # preview only
#   bash scripts/set_admin.sh 7 --action revoke --apply

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <user_id> [--action status|grant|revoke] [--dry-run|--apply]" >&2
    exit 1
fi

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

"${PYTHON_BIN}" scripts/set_admin.py "$@"
