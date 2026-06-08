#!/usr/bin/env bash
# Wrapper for the unified MySQL -> DaMeng (DM8) data migration.
#
# Runs migrate_mysql_to_dm.py inside the bisheng backend venv so that the
# dmPython driver and the DM dialect patches (bisheng.core.database.
# dialect_helpers) are importable. All arguments are forwarded verbatim, e.g.:
#
#   bash scripts/migrate_mysql_to_dm.sh --config scripts/migrate_dm.yaml --dry-run
#   bash scripts/migrate_mysql_to_dm.sh --config scripts/migrate_dm.yaml --truncate
#   bash scripts/migrate_mysql_to_dm.sh --config scripts/migrate_dm.yaml --verify
#   bash scripts/migrate_mysql_to_dm.sh --config scripts/migrate_dm.yaml --db bisheng --resume-from t_report
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_ROOT="${REPO_ROOT}/src/backend"

# Prefer the bisheng backend venv (has dmPython on Linux); fall back to PATH.
if [ -x "${BACKEND_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${BACKEND_ROOT}/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Python interpreter not found." >&2
    exit 1
fi

# Make `import bisheng.*` resolve against the backend source tree.
export PYTHONPATH="${BACKEND_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/migrate_mysql_to_dm.py" "$@"
