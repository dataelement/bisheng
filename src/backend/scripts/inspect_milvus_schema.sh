#!/bin/bash

# Inspect the schema of Milvus collections used by knowledge bases.
#
# Useful when online inserts fail with errors like:
#   <DataNotMatchException: (code=1, message=Insert missed an field `abstract`
#    to collection without set nullable==true or set default_value)>
# but brand-new knowledge spaces work fine — an old collection carries a
# not-nullable, no-default field that the current insert path no longer fills.
#
# Usage (run from src/backend):
#   bash scripts/inspect_milvus_schema.sh --knowledge-id 123
#   bash scripts/inspect_milvus_schema.sh --collection col_xxxx
#   bash scripts/inspect_milvus_schema.sh --all --only-risky
#   bash scripts/inspect_milvus_schema.sh --diff new_col old_col

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

"${PYTHON_BIN}" scripts/inspect_milvus_schema.py "$@"
