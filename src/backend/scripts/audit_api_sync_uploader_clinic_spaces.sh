#!/bin/bash

# Audit API-sync files and whether each uploader has a clinic knowledge space.
#
# Usage (from src/backend):
#   bash scripts/audit_api_sync_uploader_clinic_spaces.sh \
#     --space-name "安全生产知识库" --folder "安全生产/消防安全"
#   bash scripts/audit_api_sync_uploader_clinic_spaces.sh \
#     --space-name "安全生产知识库" --folder / --format json

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

"${PYTHON_BIN}" scripts/audit_api_sync_uploader_clinic_spaces.py "$@"
