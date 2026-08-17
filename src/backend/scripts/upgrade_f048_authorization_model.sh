#!/bin/bash
# Make the F054 `app` resource type effective on an environment that already ran
# the F048 permission migration (publish model -> re-point release -> backfill
# action resource scopes). Default is a dry run.
#
# Usage (run from src/backend/):
#   bash scripts/upgrade_f048_authorization_model.sh              # plan (default, no writes)
#   bash scripts/upgrade_f048_authorization_model.sh apply
#   bash scripts/upgrade_f048_authorization_model.sh apply --allow-live
#   bash scripts/upgrade_f048_authorization_model.sh verify
#   bash scripts/upgrade_f048_authorization_model.sh rollback
#
# AFTER `apply` OR `rollback`: restart EVERY process (API, celery x3, beat,
# linsight worker). Heartbeats are re-checked every 15s with a 45s TTL, so a
# process left running does not keep working — it fails closed.
set -e

export PYTHONPATH="./"
export config="${config:-config.yaml}"

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

"${PYTHON_BIN}" scripts/upgrade_f048_authorization_model.py "$@"
