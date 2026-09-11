#!/usr/bin/env bash
# 从 A 只读导出用户，并从本机 B 导出用户，供 propose-map 使用。不改库。
set -euo pipefail
STEP="p4.export-users"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" ""

mkdir -p "${LOG_DIR}/p4"
a_out="${LOG_DIR}/p4/a-users.csv"
b_out="${LOG_DIR}/p4/b-users.csv"

sql_a="SELECT CONCAT_WS(',', user_id, REPLACE(REPLACE(IFNULL(user_name,''), ',', ' '), CHAR(10), ' '), IFNULL(source,''), IFNULL(external_id,''), IFNULL(\`delete\`,0)) FROM \`user\`"
sql_b="${sql_a}"
if ! column_exists user source; then
  sql_b="SELECT CONCAT_WS(',', user_id, REPLACE(REPLACE(IFNULL(user_name,''), ',', ' '), CHAR(10), ' '), '', '', IFNULL(\`delete\`,0)) FROM \`user\`"
  log "B 无 user.source，B 导出 source/external_id 列留空"
elif ! column_exists user external_id; then
  sql_b="SELECT CONCAT_WS(',', user_id, REPLACE(REPLACE(IFNULL(user_name,''), ',', ' '), CHAR(10), ' '), IFNULL(source,''), '', IFNULL(\`delete\`,0)) FROM \`user\`"
fi

log "从 A ${A_SSH_USER}@${A_SSH_HOST}:${A_SSH_PORT} 导出 user（只读）"
{
  printf 'user_id,user_name,source,external_id,delete\n'
  mysql_a "${sql_a}"
} >"${a_out}"

log "从本机 B 导出 user（只读）"
{
  printf 'user_id,user_name,source,external_id,delete\n'
  mysql_scalar "${sql_b}"
} >"${b_out}"

a_n=$(($(wc -l <"${a_out}") - 1))
b_n=$(($(wc -l <"${b_out}") - 1))
ledger "${STEP}" "OK" "a=${a_n} b=${b_n}"
log "已写 ${a_out} (${a_n}) 与 ${b_out} (${b_n})。下一步: python3 p4/01-propose-map.py logs/p4/a-users.csv logs/p4/b-users.csv --out-dir logs/p4"
