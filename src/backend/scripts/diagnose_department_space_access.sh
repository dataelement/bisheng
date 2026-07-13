#!/bin/bash
set -euo pipefail

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

export PYTHONPATH="./"
exec "${PYTHON_BIN}" scripts/diagnose_department_space_access.py "$@"
