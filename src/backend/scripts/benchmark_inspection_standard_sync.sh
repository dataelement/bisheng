#!/bin/bash

# HTTP benchmark for POST /api/v2/filelib/inspection-standard/sync.
#
# Usage:
#   bash scripts/benchmark_inspection_standard_sync.sh --mode per-dept
#   bash scripts/benchmark_inspection_standard_sync.sh --mode single-request --timeout 900
#   bash scripts/benchmark_inspection_standard_sync.sh --dry-run --dept-count 10 --records-per-dept 10000
#
# Optional:
#   --base-url http://127.0.0.1:7860
#   --token bst_xxx
#   --timeout 600

set -e

export PYTHONPATH="./:./scripts"

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

"${PYTHON_BIN}" scripts/benchmark_inspection_standard_sync.py "$@"
