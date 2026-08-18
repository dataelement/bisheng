#!/bin/bash

# Verify POST /api/v2/filelib/inspection-standard/sync with a developer token.
#
# Usage:
#   bash scripts/verify_inspection_standard_sync.sh \
#     --token bst_xxx \
#     --payload scripts/examples/inspection_standard_sync_payload.example.json
#
# Optional:
#   --base-url http://10.171.0.50:7860
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

"${PYTHON_BIN}" scripts/verify_inspection_standard_sync.py "$@"
