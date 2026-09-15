#!/usr/bin/env bash
# 在 A 安装 fusion_* 控制表. 默认可重复执行.
set -euo pipefail
STEP="p4.00-control"
APPLY="${APPLY:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" "APPLY=${APPLY}"
apply_sql_on_a "${PACK_ROOT}/fusion/control.sql"
ledger "${STEP}" "OK" "control tables"
echo "OK ${STEP}"
