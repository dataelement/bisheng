#!/bin/bash

# Probe Milvus collections and report which have a broken query delegator.
#
# Sends a minimal strong-consistency probe query to each collection; any that
# raise "Timestamp lag too large" (or similar delegator errors) have a stuck
# query delegator and need recovery (see reload_milvus_collection.sh).
#
# Usage (run from src/backend):
#   bash scripts/diagnose_milvus_collections.sh --all
#   bash scripts/diagnose_milvus_collections.sh --knowledge-id 123
#   bash scripts/diagnose_milvus_collections.sh --collection col_xxxx
#   bash scripts/diagnose_milvus_collections.sh --all --load-unloaded

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

"${PYTHON_BIN}" scripts/diagnose_milvus_collections.py "$@"
