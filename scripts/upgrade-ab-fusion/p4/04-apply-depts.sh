#!/usr/bin/env bash
# 按已签字 dept-map.csv 在 B bind 或新建部门, 并补 user_department。默认 APPLY=0。
# 不按部门名合并。层级冲突未关闭时拒绝 APPLY=1。
set -euo pipefail
STEP="p4.apply-depts"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
APPLY="${APPLY:-0}"
BATCH_NO="${BATCH_NO:-p4-dept}"
CONFIRM_DEPT_HIERARCHY="${CONFIRM_DEPT_HIERARCHY:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" "APPLY=${APPLY}"

csv="${1:-${PACK_ROOT}/p4/dept-map.csv}"
[[ -f "${csv}" ]] || die "缺少映射文件 ${csv} (从 logs/p4/dept-map.proposed.csv 复制并签字)"

conflicts="${LOG_DIR}/p4/dept-conflicts.tsv"
if [[ -f "${conflicts}" ]]; then
  conflict_n=$(($(wc -l <"${conflicts}") - 1))
  if [[ "${conflict_n}" -gt 0 && "${APPLY}" == "1" && "${CONFIRM_DEPT_HIERARCHY}" != "1" ]]; then
    die "部门冲突 ${conflict_n} 条未关闭, 见 ${conflicts}。确认后才能 CONFIRM_DEPT_HIERARCHY=1 APPLY=1"
  fi
fi

ud="${LOG_DIR}/p4/a-user-department.tsv"
sql_out="${LOG_DIR}/p4-depts-$(date +%Y%m%d%H%M%S).sql"
if [[ -f "${ud}" ]]; then
  python3 "$(dirname "$0")/dept_to_sql.py" "${csv}" "${BATCH_NO}" "${ud}" >"${sql_out}"
else
  python3 "$(dirname "$0")/dept_to_sql.py" "${csv}" "${BATCH_NO}" >"${sql_out}"
  log "没有 ${ud}, SQL 不含 user_department"
fi
log "已生成 ${sql_out}, 请复核后再 APPLY=1"

if [[ "${APPLY}" != "1" ]]; then
  ledger "${STEP}" "DRY" "${sql_out}"
  log "APPLY=0, 未落库。"
  exit 0
fi

require_b_25_for_apply
assert_b_org_sync_off
table_exists department || die "B 无 department 表"
table_exists fusion_user_map || die "B 无 fusion_user_map, 先 APPLY P4 用户"
mysql_file "$(dirname "$0")/sql/mapping-tables.sql"
mysql_file "${sql_out}"
unbound="$(mysql_scalar "SELECT COUNT(*) FROM fusion_dept_map WHERE batch_no='${BATCH_NO}' AND action='create' AND b_dept_pk IS NULL")"
[[ "${unbound}" == "0" ]] || die "仍有 create 行未拿到 b_dept_pk: ${unbound}"

mkdir -p "${LOG_DIR}/p5"
{
  printf 'a_dept_pk,b_dept_pk,external_id,action\n'
  mysql_scalar "SELECT CONCAT_WS(',', a_dept_pk, IFNULL(b_dept_pk,''), IFNULL(external_id,''), action) FROM fusion_dept_map"
} >"${LOG_DIR}/p5/fusion_dept_map.csv"

ledger "${STEP}" "OK" "${sql_out}"
log "部门映射完成。P5 dry-run 将读 ${LOG_DIR}/p5/fusion_dept_map.csv"
