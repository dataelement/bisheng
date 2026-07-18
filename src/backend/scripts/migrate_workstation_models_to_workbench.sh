#!/bin/bash

export PYTHONPATH="./"

if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Python interpreter not found."
    exit 1
fi

run_mode=${1:-check}

if [ "$run_mode" = "check" ]; then
    echo "Dry-run migrating legacy workstation.models to Root linsight_llm.models ..."
    "${PYTHON_BIN}" scripts/migrate_workstation_models_to_workbench.py
elif [ "$run_mode" = "apply" ]; then
    echo "Applying migration from legacy workstation.models to Root linsight_llm.models ..."
    "${PYTHON_BIN}" scripts/migrate_workstation_models_to_workbench.py --apply
else
    echo "Invalid run mode. Use 'check' or 'apply'."
    exit 1
fi
