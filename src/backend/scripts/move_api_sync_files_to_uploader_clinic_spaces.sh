#!/bin/bash

# Move API-sync files into each uploader's clinic knowledge space.
# Default is dry-run. Pass --apply to write.
#
# Usage (from src/backend):
#   bash scripts/move_api_sync_files_to_uploader_clinic_spaces.sh \
#     --space-name "安全生产知识库" --folder "安全生产/消防安全"
#   bash scripts/move_api_sync_files_to_uploader_clinic_spaces.sh \
#     --space-name "安全生产知识库" --folder "安全生产/消防安全" --apply
#   bash scripts/move_api_sync_files_to_uploader_clinic_spaces.sh \
#     --space-name "安全生产知识库" --folder "安全生产/消防安全" \
#     --target-folder "归档/接口同步" --apply

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

"${PYTHON_BIN}" scripts/move_api_sync_files_to_uploader_clinic_spaces.py "$@"
