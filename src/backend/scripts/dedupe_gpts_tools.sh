#!/bin/bash
# Dedupe redundant preset tools/tool-types sharing the same (tool_key, tenant_id).
# See module docstring in dedupe_gpts_tools.py for the full root-cause writeup.
#
# Usage (run from src/backend/; BACK UP THE DB before apply):
#   bash scripts/dedupe_gpts_tools.sh            # dry-run (no writes)
#   bash scripts/dedupe_gpts_tools.sh --apply    # perform cleanup
#   bash scripts/dedupe_gpts_tools.sh apply      # same as --apply
set -e

export PYTHONPATH="./"
: "${config:=config.yaml}"
export config

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

# Translate the convenience token `apply` into `--apply`; forward everything else.
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "apply" ]; then
        ARGS+=("--apply")
    else
        ARGS+=("$arg")
    fi
done

"${PYTHON_BIN}" scripts/dedupe_gpts_tools.py "${ARGS[@]}"
