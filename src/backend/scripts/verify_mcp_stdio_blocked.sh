#!/bin/bash
# Probe a remote BiSheng: /mcp/test and /mcp/refresh must refuse STDIO (15025).
#
# Usage (from src/backend/):
#   bash scripts/verify_mcp_stdio_blocked.sh --base-url http://HOST:7860 \
#       --username admin --password '***'

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

"${PYTHON_BIN}" scripts/verify_mcp_stdio_blocked.py "$@"
