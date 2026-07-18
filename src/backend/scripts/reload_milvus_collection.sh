#!/bin/bash

# Release and reload Milvus collections to recover a stuck query delegator.
#
# Use when search/query/retry fail with:
#   <MilvusException: (code=65535, message=failed to search/query delegator NNNN
#    for channel ...-dml_X_...: Timestamp lag too large)>
# but fresh uploads (insert-only) into the same collection still succeed.
# Release+load forces query nodes to rebuild the channel delegator and replay
# to the latest checkpoint, which clears the timestamp-lag condition.
#
# WARNING: the collection cannot serve search/query while released. Run in a
# maintenance window or when a brief search outage is acceptable.
#
# Usage (run from src/backend):
#   bash scripts/reload_milvus_collection.sh --knowledge-id 123
#   bash scripts/reload_milvus_collection.sh --collection col_xxxx
#   bash scripts/reload_milvus_collection.sh --collection col_xxxx --dry-run

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

"${PYTHON_BIN}" scripts/reload_milvus_collection.py "$@"
