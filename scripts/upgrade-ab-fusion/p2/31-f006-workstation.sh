#!/usr/bin/env bash
# F006 RBAC→ReBAC + 工作台模型迁移。导入 A 空间之后禁止再跑全局 F006。
set -euo pipefail
STEP="p2.31-f006"
# 测试机 B。看完 dry_run 把 CONFIRM_F006 改成 1。
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${CONFIRM_F006:=0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
require_complete_p2_freeze
ledger "${STEP}" "START" ""

f006() {
  local mode="$1"
  # 不用 bash -lc "bash ... ${mode}": 外层双引号套内层脚本, CentOS 7 bash
  # 报错时会把 line 47 算到本 hop 头上. 参数直接传给 docker exec.
  docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" \
    bash scripts/permission_migration.sh "${mode}"
}

log "dry_run"
f006 dry_run

if [[ "${CONFIRM_F006}" != "1" ]]; then
  ledger "${STEP}" "OK" "dry_run only CONFIRM_F006=0"
  log "dry_run 结束, 未写入 OpenFGA / 工作台."
  log "核对上面清单后执行: CONFIRM_F006=1 bash p2/31-f006-workstation.sh"
  echo "NEXT CONFIRM_F006=1 bash p2/31-f006-workstation.sh"
  echo "OK ${STEP} dry_run"
  exit 0
fi

f006 execute
f006 verify
docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" \
  bash scripts/migrate_workstation_models_to_workbench.sh apply

# SQL 先放变量, 避免 pending="$(mysql_scalar "...")" 套双引号.
fail_sql="SELECT COUNT(*) FROM failed_tuple WHERE status NOT IN ('succeeded','success')"
pending="$(mysql_scalar "${fail_sql}")"
log "failed_tuple 非成功行=${pending}"
[[ "${pending}" == "0" ]] || die "failed_tuple 仍有未成功记录，禁止当升级完成"

ledger "${STEP}" "OK" "f006+workstation"
log "下一步 40-verify.sh。此后不要全局重跑 F006。"
