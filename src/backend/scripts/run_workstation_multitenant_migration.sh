#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT_DIR"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/src/backend/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

DRY_RUN_FLAG=""
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN_FLAG="--dry-run"
fi

echo "[info] root_dir=$ROOT_DIR"
echo "[info] python_bin=$PYTHON_BIN"
echo "[info] checking tenant_workstation_config table exists"

"$PYTHON_BIN" - <<'PY'
import sys
from pathlib import Path
ROOT = Path.cwd()
BACKEND_SRC = ROOT / "src" / "backend"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))
from sqlmodel import select
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.workstation.domain.models import TenantWorkstationConfig
with bypass_tenant_filter():
    with get_sync_db_session() as session:
        session.exec(select(TenantWorkstationConfig.id).limit(1))
print("tenant_workstation_config check ok")
PY

echo "[step] migrate workstation config rows to root tenant"
"$PYTHON_BIN" "$ROOT_DIR/src/backend/scripts/migrate_workstation_config_to_root.py" $DRY_RUN_FLAG

echo "[step] backfill builtin tools for child tenants"
"$PYTHON_BIN" "$ROOT_DIR/src/backend/scripts/backfill_child_builtin_tools.py" $DRY_RUN_FLAG

echo "[done] workstation multitenant migration completed"
