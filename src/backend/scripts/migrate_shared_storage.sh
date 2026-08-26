#!/bin/bash
set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <migrate|reverse|status> [args...]" >&2
    echo "" >&2
    echo "  Forward migration:  $0 migrate --tenant-id <ID> [--dry-run]" >&2
    echo "  Reverse migration:  $0 reverse --tenant-id <ID> [--dry-run]" >&2
    echo "  Status:             $0 status  --tenant-id <ID>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BACKEND_DIR"

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

exec "${PYTHON_BIN}" scripts/migrate_shared_storage.py "$@"