#!/bin/bash

# Import filelib department mapping rows from CSV.
#
# Usage:
#   bash scripts/import_filelib_department_mapping.sh --csv /path/to/mapping.csv
#   bash scripts/import_filelib_department_mapping.sh --csv /path/to/mapping.csv --apply

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

"${PYTHON_BIN}" scripts/import_filelib_department_mapping.py "$@"
