#!/usr/bin/env bash
# 按已签字 CSV 接管或在 B 新建身份。不按姓名合并。执行前 B 上 SG 同步必须关闭。
set -euo pipefail
STEP="p4.takeover"
# 测试机 B。有签字 CSV 并复核 SQL 后再把 APPLY 改成 1。
MYSQL_CONTAINER="bisheng-mysql"
MYSQL_DB="bisheng"
APPLY=0
BATCH_NO="${BATCH_NO:-p4-manual}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" "APPLY=${APPLY}"

csv="${1:-${PACK_ROOT}/p4/user-map.csv}"
[[ -f "${csv}" ]] || die "缺少映射文件 ${csv}（从 user-map.csv.example / user-map.proposed.csv 复制并经客户签字）"

sql_out="${LOG_DIR}/p4-takeover-$(date +%Y%m%d%H%M%S).sql"
python3 "$(dirname "$0")/csv_to_sql.py" "${csv}" "${BATCH_NO}" >"${sql_out}"
log "已生成 ${sql_out}，请复核后再 APPLY=1"

if [[ "${APPLY}" != "1" ]]; then
  ledger "${STEP}" "DRY" "${sql_out}"
  log "APPLY=0，未落库。"
  exit 0
fi

require_b_25_for_apply
assert_b_org_sync_off
mysql_file "$(dirname "$0")/sql/mapping-tables.sql"
mysql_file "${sql_out}"
dups="$(mysql_scalar "SELECT COUNT(*) FROM (SELECT external_id FROM \`user\` WHERE external_id IS NOT NULL AND external_id<>'' GROUP BY external_id HAVING COUNT(*)>1) t")"
[[ "${dups}" == "0" ]] || die "接管后 B 仍有重复 external_id 组=${dups}，P0 阻断"
split="$(mysql_scalar "SELECT COUNT(*) FROM (SELECT employee_code FROM fusion_user_map WHERE employee_code IS NOT NULL AND employee_code<>'' GROUP BY employee_code HAVING COUNT(DISTINCT b_user_id)>1) t")"
[[ "${split}" == "0" ]] || die "同一员工编码映到多个 B user_id，组数=${split}"
ledger "${STEP}" "OK" "${sql_out}"
log "身份映射完成。不要在这一步打开 SG 同步。"
