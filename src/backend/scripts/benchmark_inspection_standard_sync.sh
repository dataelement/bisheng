#!/bin/bash

# HTTP benchmark for POST /api/v2/filelib/inspection-standard/sync.
#
# Usage (from repo root or src/backend):
#   bash src/backend/scripts/benchmark_inspection_standard_sync.sh --mode per-dept
#   bash scripts/benchmark_inspection_standard_sync.sh --mode single-request --dept-count 10 --records-per-dept 2000 --timeout 900
#   bash run_inspection_standard_sync_bulk.sh
#
# Optional:
#   --base-url http://127.0.0.1:7860
#   --token bst_xxx
#   --timeout 600

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_ROOT}"

# Local dev defaults (override via env or --base-url / --token).
export INSPECTION_STANDARD_SYNC_BASE_URL="${INSPECTION_STANDARD_SYNC_BASE_URL:-http://127.0.0.1:7860}"
export INSPECTION_STANDARD_SYNC_TOKEN="${INSPECTION_STANDARD_SYNC_TOKEN:-bst_esyapps0hfUIyHFzG52BkGNoA59KW0mpyVDYw4AuIKw}"

export PYTHONPATH="${BACKEND_ROOT}:${BACKEND_ROOT}/scripts"

if [ -x "${BACKEND_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${BACKEND_ROOT}/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Python interpreter not found." >&2
    exit 1
fi

"${PYTHON_BIN}" "${SCRIPT_DIR}/benchmark_inspection_standard_sync.py" "$@"
