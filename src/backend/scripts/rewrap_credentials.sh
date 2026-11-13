#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="./"
if [[ -x .venv/bin/python ]]; then PYTHON_BIN=.venv/bin/python
elif command -v python >/dev/null 2>&1; then PYTHON_BIN=$(command -v python)
elif command -v python3 >/dev/null 2>&1; then PYTHON_BIN=$(command -v python3)
else printf 'Python interpreter not found\n' >&2; exit 1; fi
exec "$PYTHON_BIN" scripts/rewrap_credentials.py "$@"
