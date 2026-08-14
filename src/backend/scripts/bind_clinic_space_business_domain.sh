#!/bin/bash

# Bind clinic knowledge spaces to portal business domains (bidirectional).
#
# Usage:
#   bash scripts/bind_clinic_space_business_domain.sh --space-id 3689 --domain-code HR --department-id 2359
#   bash scripts/bind_clinic_space_business_domain.sh --file scripts/examples/clinic_business_domain_bindings.example.json --apply

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

"${PYTHON_BIN}" scripts/bind_clinic_space_business_domain.py "$@"
