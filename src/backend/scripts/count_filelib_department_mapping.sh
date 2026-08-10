#!/bin/bash

# Print total row count in filelib_department_mapping.
#
# Usage:
#   export config=/path/to/config.yaml
#   bash scripts/count_filelib_department_mapping.sh

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

"${PYTHON_BIN}" scripts/count_filelib_department_mapping.py "$@"
