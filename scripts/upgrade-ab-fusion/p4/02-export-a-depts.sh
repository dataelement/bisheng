#!/usr/bin/env bash
# 从 A 只读导出部门树和 user_department, 并从本机 B 导出部门。不改库。
set -euo pipefail
STEP="p4.export-depts"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" ""

mkdir -p "${LOG_DIR}/p4"
a_out="${LOG_DIR}/p4/a-depts.tsv"
b_out="${LOG_DIR}/p4/b-depts.tsv"
ud_out="${LOG_DIR}/p4/a-user-department.tsv"

dept_sql="SELECT CONCAT_WS('\t', id, IFNULL(dept_id,''), REPLACE(IFNULL(name,''), '\t', ' '), REPLACE(IFNULL(short_name,''), '\t', ' '), IFNULL(parent_id,''), IFNULL(tenant_id,1), IFNULL(sort_order,0), IFNULL(source,'local'), IFNULL(external_id,''), IFNULL(status,'active'), IFNULL(is_deleted,0)) FROM department"

log "从 A ${A_SSH_USER}@${A_SSH_HOST}:${A_SSH_PORT} 导出 department / user_department (只读)"
{
  printf 'id\tdept_id\tname\tshort_name\tparent_id\ttenant_id\tsort_order\tsource\texternal_id\tstatus\tis_deleted\n'
  mysql_a "${dept_sql}"
} >"${a_out}"

{
  printf 'user_id\tdepartment_id\tis_primary\tsource\n'
  mysql_a "SELECT CONCAT_WS('\t', user_id, department_id, IFNULL(is_primary,1), IFNULL(source,'local')) FROM user_department" || true
} >"${ud_out}"

log "从本机 B 导出 department (只读)"
if table_exists department; then
  {
    printf 'id\tdept_id\tname\tshort_name\tparent_id\ttenant_id\tsort_order\tsource\texternal_id\tstatus\tis_deleted\n'
    mysql_scalar "${dept_sql}"
  } >"${b_out}"
else
  printf 'id\tdept_id\tname\tshort_name\tparent_id\ttenant_id\tsort_order\tsource\texternal_id\tstatus\tis_deleted\n' >"${b_out}"
  log "B 无 department 表, B 导出为空"
fi

a_n=$(($(wc -l <"${a_out}") - 1))
b_n=$(($(wc -l <"${b_out}") - 1))
ud_n=$(($(wc -l <"${ud_out}") - 1))
ledger "${STEP}" "OK" "a=${a_n} b=${b_n} user_department=${ud_n}"
log "已写 ${a_out} (${a_n}) ${b_out} (${b_n}) ${ud_out} (${ud_n})"
log "下一步: python3 p4/03-propose-dept-map.py logs/p4/a-depts.tsv logs/p4/b-depts.tsv --out-dir logs/p4"
