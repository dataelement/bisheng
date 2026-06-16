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
#
# CONNECTION SETTINGS (account / password / ip / port)
# ----------------------------------------------------
# The YAML config expands ${VAR} placeholders for every connection field. Set
# them either by exporting before calling the script, or by editing the defaults
# block below. A value the caller already exported always wins over the default.
#
#   export MYSQL_HOST=10.0.0.5 MYSQL_PASSWORD=xxx DM_HOST=192.168.107.9 \
#          DM_BISHENG_PASSWORD=yyy
#   bash scripts/migrate_mysql_to_dm.sh --config scripts/migrate_dm.yaml --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_ROOT="${REPO_ROOT}/src/backend"

# --- Connection settings ----------------------------------------------------
# Defaults / inline overrides. Anything already exported by the caller's shell
# is kept; only unset values fall back to these. Edit here if you prefer
# hard-coding over exporting env vars.
#
# MySQL source:
export MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
export MYSQL_PORT="${MYSQL_PORT:-3306}"
export MYSQL_USER="${MYSQL_USER:-root}"
export MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"
# DaMeng (DM8) target (account doubles as the DM schema name):
export DM_HOST="${DM_HOST:-127.0.0.1}"
export DM_PORT="${DM_PORT:-5236}"
export DM_BISHENG_USER="${DM_BISHENG_USER:-BISHENG}"
export DM_BISHENG_PASSWORD="${DM_BISHENG_PASSWORD:-}"
export DM_GATEWAY_USER="${DM_GATEWAY_USER:-BISHENG_GATEWAY}"
export DM_GATEWAY_PASSWORD="${DM_GATEWAY_PASSWORD:-}"
export DM_OPENFGA_USER="${DM_OPENFGA_USER:-OPENFGA}"
export DM_OPENFGA_PASSWORD="${DM_OPENFGA_PASSWORD:-}"

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
