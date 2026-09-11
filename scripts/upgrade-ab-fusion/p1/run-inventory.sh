#!/usr/bin/env bash
# P1 只读盘点。在 A、B 主机上分别执行，或改 MYSQL_CONTAINER 指向对应库。
set -euo pipefail
STEP="p1.inventory"
# 测试机 B 10.168.24.121
MYSQL_CONTAINER="bisheng-mysql"
MYSQL_DB="bisheng"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" ""

mkdir -p "${LOG_DIR}/p1"
out="${LOG_DIR}/p1/${MYSQL_DB}-$(date +%Y%m%d%H%M%S).txt"

if table_exists "alembic_version"; then
  log "检测到 alembic_version，按 A 清单盘点"
  mysql_file "$(cd "$(dirname "$0")" && pwd)/inventory-A.sql" | tee "${out}"
else
  log "无 alembic_version，按 B 2.2 清单盘点"
  mysql_file "$(cd "$(dirname "$0")" && pwd)/inventory-B.sql" | tee "${out}"
fi

if table_exists "user_point_account"; then
  log "追加积分盘点"
  mysql_file "$(cd "$(dirname "$0")" && pwd)/inventory-points.sql" | tee -a "${out}"
else
  log "无 user_point_account，跳过积分盘点（2.2 或未 hop 完 2.5）"
fi

ledger "${STEP}" "OK" "${out}"
log "输出 ${out}。整理成四份清单：用户映射、部门映射、资源/ID、冲突。"
