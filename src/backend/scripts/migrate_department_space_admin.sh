#!/bin/bash
# F045 — normalize department knowledge spaces to the single-space-admin model.
# Run from src/backend/. Dry-run by default; pass --apply to write.
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

"${PYTHON_BIN}" scripts/migrate_department_space_admin.py "$@"
