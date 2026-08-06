#!/bin/bash

# Verify POST /api/v2/filelib/file/sync with a developer token.
#
# Usage:
#   bash scripts/verify_filelib_sync.sh \
#     --token bst_xxx \
#     --file /path/to/report.pdf \
#     --params /path/to/sync_params.json
#
# Optional:
#   --base-url http://127.0.0.1:7860
#   --timeout 120

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

"${PYTHON_BIN}" scripts/verify_filelib_sync.py "$@"
