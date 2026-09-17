#!/usr/bin/env bash
# 生成身份 SQL 并按 APPLY 写入 A. 需要已签字 p4/*.csv.
set -euo pipefail
STEP="p4.10-apply-identity"
APPLY="${APPLY:-0}"
BATCH_NO="${BATCH_NO:-fusion-$(date +%Y%m%d)}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

[[ -f "${PACK_ROOT}/p4/user-map.csv" ]] || die "缺少签字 ${PACK_ROOT}/p4/user-map.csv"
[[ -f "${PACK_ROOT}/p4/tenant-map.csv" ]] || die "缺少 ${PACK_ROOT}/p4/tenant-map.csv"

if [[ "${APPLY}" == "1" ]]; then
  require_a_25_for_apply
  require_b_25_for_apply
  assert_b_org_sync_off
fi

mkdir -p "${LOG_DIR}/p4/maps"
cp -f "${PACK_ROOT}/p4/"*.csv "${LOG_DIR}/p4/maps/"

python3 - <<PY
import json
from pathlib import Path
import sys
pack = Path("${PACK_ROOT}")
log = Path("${LOG_DIR}")
sys.path.insert(0, str(pack))
from fusion.sql import load_table

def next_id(rows, key):
    vals = []
    for r in rows:
        try:
            vals.append(int(r.get(key) or 0))
        except ValueError:
            pass
    return (max(vals) + 1) if vals else 1

a_users = load_table(log / "p4" / "a-users.tsv")
a_groups = load_table(log / "p4" / "a-groups.tsv")
a_roles = load_table(log / "p4" / "a-roles.tsv")
dump = {
    "b_users": load_table(log / "p4" / "b-users.tsv"),
    "b_groups": load_table(log / "p4" / "b-groups.tsv"),
    "b_usergroups": load_table(log / "p4" / "b-usergroups.tsv"),
    "b_user_departments": load_table(log / "p4" / "b-user-departments.tsv"),
    "b_roles": load_table(log / "p4" / "b-roles.tsv"),
    "b_userroles": load_table(log / "p4" / "b-userroles.tsv"),
    "a_user_names": [r.get("user_name", "") for r in a_users],
    "a_external_ids": [r.get("external_id", "") for r in a_users if r.get("external_id")],
    "next_user_id": next_id(a_users, "user_id"),
    "next_group_id": next_id(a_groups, "id"),
    "next_role_id": next_id(a_roles, "id"),
}
(log / "p4" / "identity-dump.json").write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
print(log / "p4" / "identity-dump.json")
PY
chmod 600 "${LOG_DIR}/p4/identity-dump.json" || true

python3 "${PACK_ROOT}/p5/build_sql.py" --kind identity \
  --dump "${LOG_DIR}/p4/identity-dump.json" \
  --maps "${LOG_DIR}/p4/maps" \
  --out "${LOG_DIR}/p4/identity.sql" \
  --batch "${BATCH_NO}"
chmod 600 "${LOG_DIR}/p4/identity.sql" || true

python3 - <<PY
import json
from pathlib import Path
import sys
pack = Path("${PACK_ROOT}")
sys.path.insert(0, str(pack))
from fusion.maps import persist_runtime_maps
meta = Path("${LOG_DIR}/p4/identity.sql.meta.json")
if meta.exists():
    extra = json.loads(meta.read_text(encoding="utf-8"))
    persist_runtime_maps(Path("${PACK_ROOT}/p4"), extra)
    persist_runtime_maps(Path("${LOG_DIR}/p4/maps"), extra)
PY

apply_sql_on_a "${LOG_DIR}/p4/identity.sql"
ledger "${STEP}" "OK" "APPLY=${APPLY} ${LOG_DIR}/p4/identity.sql"
echo "OK ${STEP}"
