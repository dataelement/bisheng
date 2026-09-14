#!/usr/bin/env bash
# 从 A 只读导出积分规则/账户/流水为 JSON。不改库。A 无表则写空 JSON。
set -euo pipefail
STEP="p4.export-points"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" ""

mkdir -p "${LOG_DIR}/p4"
out="${LOG_DIR}/p4/a-points.json"
dump="${LOG_DIR}/p4/a-points.dump"

a_has_rules="$(mysql_a "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='${A_MYSQL_DB}' AND TABLE_NAME='point_rule'" || echo 0)"
if [[ "${a_has_rules}" == "0" ]]; then
  printf '{"rules":[],"accounts":[],"logs":[]}\n' >"${out}"
  ledger "${STEP}" "SKIP" "A 无 point_rule"
  log "A 无积分表, 已写空 ${out}"
  exit 0
fi

{
  echo "===RULES==="
  mysql_a "SELECT JSON_OBJECT('id',id,'tenant_id',tenant_id,'rule_code',rule_code,'rule_type',rule_type,'name',name,'display_name',display_name,'score_expr',score_expr,'daily_cap',daily_cap,'beneficiary',beneficiary,'status',status,'remark',remark,'sort_order',sort_order) FROM point_rule"
  echo "===ACCOUNTS==="
  mysql_a "SELECT JSON_OBJECT('id',id,'tenant_id',tenant_id,'user_id',user_id,'balance',balance,'lifetime_earned',lifetime_earned,'lifetime_deducted',lifetime_deducted,'version',version,'last_earned_at',DATE_FORMAT(last_earned_at,'%Y-%m-%d %H:%i:%s')) FROM user_point_account"
  echo "===LOGS==="
  mysql_a "SELECT JSON_OBJECT('id',id,'tenant_id',tenant_id,'user_id',user_id,'delta',delta,'balance_after',balance_after,'direction',direction,'rule_code',rule_code,'title',title,'source',source,'biz_type',biz_type,'biz_id',biz_id,'idempotency_key',idempotency_key,'operator_id',operator_id,'remark',remark,'score_snapshot',score_snapshot,'beneficiary_role',beneficiary_role,'occurred_at',DATE_FORMAT(occurred_at,'%Y-%m-%d %H:%i:%s')) FROM user_point_log"
} >"${dump}"

python3 - "${dump}" "${out}" <<'PY'
import json, sys
from pathlib import Path

dump, out = Path(sys.argv[1]), Path(sys.argv[2])
parts: dict[str, list] = {"RULES": [], "ACCOUNTS": [], "LOGS": []}
current = None
for line in dump.read_text(encoding="utf-8").splitlines():
    if line.startswith("===") and line.endswith("==="):
        current = line.strip("=").strip()
        continue
    if current is None or not line.strip():
        continue
    parts[current].append(json.loads(line))
payload = {"rules": parts["RULES"], "accounts": parts["ACCOUNTS"], "logs": parts["LOGS"]}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(
    f"rules={len(payload['rules'])} accounts={len(payload['accounts'])} "
    f"logs={len(payload['logs'])} -> {out}"
)
PY

ledger "${STEP}" "OK" "${out}"
log "已写 ${out}"
