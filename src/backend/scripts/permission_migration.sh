#!/bin/bash

# Step map:
#   1 = Super Admin
#   2 = User Group Membership
#   3 = Role Access Expansion
#   4 = Space/Channel Members
#   5 = Resource Owners
#   6 = Folder Hierarchy
#   7 = Department Membership
#   8 = Group Resources

export PYTHONPATH="./"
run_mode=${1:-execute}
step=${2:-1}
if [ "$#" -ge 2 ]; then
    shift 2
elif [ "$#" -ge 1 ]; then
    shift 1
fi
extra_args=("$@")

if [ "$run_mode" = "execute" ]; then
    echo "Running F006 RBAC to ReBAC permission migration..."
    python scripts/permission_rbac_to_rebac_migration.py --step "${step}" "${extra_args[@]}"
elif [ "$run_mode" = "dry_run" ]; then
    echo "Previewing F006 RBAC to ReBAC permission migration..."
    python scripts/permission_rbac_to_rebac_migration.py --dry-run --step "${step}" "${extra_args[@]}"
elif [ "$run_mode" = "only_step" ]; then
    echo "Running only F006 migration step ${step}..."
    python scripts/permission_rbac_to_rebac_migration.py --only-step "${step}" "${extra_args[@]}"
elif [ "$run_mode" = "dry_run_only_step" ]; then
    echo "Previewing only F006 migration step ${step}..."
    python scripts/permission_rbac_to_rebac_migration.py --dry-run --only-step "${step}" "${extra_args[@]}"
elif [ "$run_mode" = "verify" ]; then
    echo "Verifying F006 RBAC to ReBAC permission migration..."
    python scripts/permission_rbac_to_rebac_migration.py --verify --step "${step}" "${extra_args[@]}"
elif [ "$run_mode" = "replay" ]; then
    echo "Replaying F006 RBAC to ReBAC permission migration from scratch..."
    python scripts/permission_rbac_to_rebac_migration.py --force --step "${step}" "${extra_args[@]}"
elif [ "$run_mode" = "force" ]; then
    echo "Force running F006 RBAC to ReBAC permission migration..."
    python scripts/permission_rbac_to_rebac_migration.py --force --step "${step}" "${extra_args[@]}"
else
    echo "Invalid run mode. Use 'execute', 'dry_run', 'only_step', 'dry_run_only_step', 'verify', 'replay', or 'force'."
    echo "Step values: 1=Super Admin, 2=User Group Membership, 3=Role Access Expansion, 4=Space/Channel Members, 5=Resource Owners, 6=Folder Hierarchy, 7=Department Membership, 8=Group Resources."
    exit 1
fi
