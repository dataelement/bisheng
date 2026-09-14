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
ledger "${STEP}" "START" ""

f006() {
  local mode="$1"
  docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" bash -lc "bash scripts/permission_migration.sh ${mode}"
}

log "dry_run"
f006 dry_run

if [[ "${CONFIRM_F006}" != "1" ]]; then
  ledger "${STEP}" "BLOCK" "CONFIRM_F006!=1"
  die "阅读 dry_run 输出后 export CONFIRM_F006=1 再执行"
fi

f006 execute
f006 verify
docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" bash -lc \
  'bash scripts/migrate_workstation_models_to_workbench.sh apply'

pending="$(mysql_scalar "SELECT COUNT(*) FROM failed_tuple WHERE status NOT IN ('succeeded','success')")"
log "failed_tuple 非成功行=${pending}"
[[ "${pending}" == "0" ]] || die "failed_tuple 仍有未成功记录，禁止当升级完成"

ledger "${STEP}" "OK" "f006+workstation"
log "下一步 40-verify.sh。此后不要全局重跑 F006。"
