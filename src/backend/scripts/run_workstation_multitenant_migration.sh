#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="./"
DRY_RUN_FLAG=""
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN_FLAG="--dry-run"
fi



echo "[step] migrate workstation config rows to root tenant"
python3 ./scripts/migrate_workstation_config_to_root.py $DRY_RUN_FLAG

echo "[step] backfill builtin tools for child tenants"
python3 ./scripts/backfill_child_builtin_tools.py $DRY_RUN_FLAG

echo "[done] workstation multitenant migration completed"
