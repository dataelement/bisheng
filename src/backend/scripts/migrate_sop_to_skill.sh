#!/bin/bash
# One-shot migration: linsight_sop -> tenant custom skills (F035 Track G).
#
# Usage (run from src/backend/):
#   bash scripts/migrate_sop_to_skill.sh                       # dry-run, all tenants
#   bash scripts/migrate_sop_to_skill.sh apply                 # persist, all tenants
#   bash scripts/migrate_sop_to_skill.sh --no-llm apply        # persist, skip LLM summaries
#   bash scripts/migrate_sop_to_skill.sh --tenant-id 2 apply   # persist, one tenant
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

# Translate the convenience token `apply` into `--apply`; forward everything else.
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "apply" ]; then
        ARGS+=("--apply")
    else
        ARGS+=("$arg")
    fi
done

"${PYTHON_BIN}" scripts/migrate_sop_to_skill.py "${ARGS[@]}"
