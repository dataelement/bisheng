#!/bin/bash
# Move public tag-library tags into 「通用标签库」 and bind every knowledge space.
#
# Usage (from src/backend):
#   bash scripts/migrate_tags_to_general_library.sh
#   bash scripts/migrate_tags_to_general_library.sh --apply

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

"${PYTHON_BIN}" scripts/migrate_tags_to_general_library.py "$@"
