#!/bin/bash

export PYTHONPATH="./"
run_mode=${1:-execute}
step=${2:-1}

if [ "$run_mode" = "execute" ]; then
    echo "Running F006 RBAC to ReBAC permission migration..."
    python bisheng/script/permission_rbac_to_rebac_migration.py --step "${step}"
elif [ "$run_mode" = "dry_run" ]; then
    echo "Previewing F006 RBAC to ReBAC permission migration..."
    python bisheng/script/permission_rbac_to_rebac_migration.py --dry-run --step "${step}"
elif [ "$run_mode" = "verify" ]; then
    echo "Verifying F006 RBAC to ReBAC permission migration..."
    python bisheng/script/permission_rbac_to_rebac_migration.py --verify --step "${step}"
elif [ "$run_mode" = "force" ]; then
    echo "Force running F006 RBAC to ReBAC permission migration..."
    python bisheng/script/permission_rbac_to_rebac_migration.py --force --step "${step}"
else
    echo "Invalid run mode. Use 'execute', 'dry_run', 'verify', or 'force'."
    exit 1
fi
