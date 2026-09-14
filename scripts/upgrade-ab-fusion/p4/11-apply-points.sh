#!/usr/bin/env bash
# 用 A 的 point_rule 覆盖 B, 并按用户映射迁账户+流水。默认 APPLY=0。
# 不迁 point_copy / 榜单快照 / outbox。B 已有账户则余额相加, 不抹掉 B 现网积分。
set -euo pipefail
STEP="p4.apply-points"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
APPLY="${APPLY:-0}"
BATCH_NO="${BATCH_NO:-p4-points}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" "APPLY=${APPLY}"

export_json="${LOG_DIR}/p4/a-points.json"
[[ -f "${export_json}" ]] || die "缺少 ${export_json}, 先跑 p4/10-export-a-points.sh"
user_map="${USER_MAP:-${PACK_ROOT}/p4/user-map.csv}"
if [[ ! -f "${user_map}" ]]; then
  user_map="${LOG_DIR}/p4/user-map.proposed.csv"
fi
[[ -f "${user_map}" ]] || die "缺少用户映射 ${user_map}"

sql_out="${LOG_DIR}/p4-points-$(date +%Y%m%d%H%M%S).sql"
skip_out="${LOG_DIR}/p4/points-skipped.json"
python3 "$(dirname "$0")/points_to_sql.py" "${export_json}" "${user_map}" \
  --batch-no "${BATCH_NO}" --skip-out "${skip_out}" >"${sql_out}"
log "已生成 ${sql_out}, 跳过清单 ${skip_out}"

if [[ "${APPLY}" != "1" ]]; then
  ledger "${STEP}" "DRY" "${sql_out}"
  log "APPLY=0, 未落库。"
  exit 0
fi

require_b_25_for_apply
table_exists point_rule || die "B 无 point_rule, 积分迁移需要 B 已有积分表"
table_exists user_point_account || die "B 无 user_point_account"
table_exists user_point_log || die "B 无 user_point_log"
table_exists fusion_user_map || die "B 无 fusion_user_map, 先 APPLY P4 用户"
mysql_file "$(dirname "$0")/sql/mapping-tables.sql"
mysql_file "${sql_out}"
ledger "${STEP}" "OK" "${sql_out}"
log "积分规则已按 A 覆盖, 账户+流水已按映射写入。跳过 ${skip_out}"
