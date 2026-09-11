#!/usr/bin/env bash
# 根据已导出的 JSON 做数量盘点, 并抽出 B 现有同名空间供 dry-run。不改库。
set -euo pipefail
STEP="p5.inventory"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" ""

mkdir -p "${LOG_DIR}/p5"
inv="${LOG_DIR}/p5/inventory-$(date +%Y%m%d%H%M%S).tsv"
printf 'a_space_id\tname\towner_a_user_id\tfiles\tdirs\tsuccess\tfailed\ttimeout\tviolation\tmembers\tobjects\n' >"${inv}"

shopt -s nullglob
jsons=("${LOG_DIR}/p5"/a-space-*.json)
[[ ${#jsons[@]} -gt 0 ]] || die "没有 ${LOG_DIR}/p5/a-space-*.json，先跑 00-export-a-space.sh"

python3 - "${inv}" "${jsons[@]}" <<'PY'
import json, sys
from pathlib import Path

inv = Path(sys.argv[1])
rows = []
for path in sys.argv[2:]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    space = data["space"]
    files = data.get("files") or []
    real = [f for f in files if int(f.get("file_type") or 1) == 1]
    dirs = [f for f in files if int(f.get("file_type") or 1) == 0]
    status = {}
    for f in real:
        status[int(f.get("status") or 0)] = status.get(int(f.get("status") or 0), 0) + 1
    objects = sum(1 for f in real if f.get("object_name"))
    rows.append(
        "\t".join(
            str(x)
            for x in [
                space["id"],
                (space.get("name") or "").replace("\t", " "),
                space.get("user_id") or "",
                len(real),
                len(dirs),
                status.get(2, 0),
                status.get(3, 0),
                status.get(6, 0),
                status.get(7, 0),
                len(data.get("members") or []),
                objects,
            ]
        )
    )
with inv.open("a", encoding="utf-8") as f:
    f.write("\n".join(rows) + ("\n" if rows else ""))
print(f"spaces={len(rows)}")
PY

b_names="${LOG_DIR}/p5/b-space-names.tsv"
if table_exists knowledge; then
  {
    printf 'id\tname\tuser_id\n'
    mysql_scalar "SELECT CONCAT_WS('\t', id, REPLACE(IFNULL(name,''), '\t', ' '), IFNULL(user_id,'')) FROM knowledge WHERE type=3"
  } >"${b_names}" || true
else
  printf 'id\tname\tuser_id\n' >"${b_names}"
fi

if table_exists fusion_user_map; then
  mysql_scalar "SELECT CONCAT_WS(',', a_user_id, b_user_id, IFNULL(employee_code,''), action) FROM fusion_user_map" \
    >"${LOG_DIR}/p5/fusion_user_map.csv.raw" || true
  {
    printf 'a_user_id,b_user_id,employee_code,action\n'
    cat "${LOG_DIR}/p5/fusion_user_map.csv.raw"
  } >"${LOG_DIR}/p5/fusion_user_map.csv"
else
  log "B 还没有 fusion_user_map（P4 未 APPLY）。dry-run 仍可用签字 CSV。"
fi

if table_exists fusion_dept_map; then
  {
    printf 'a_dept_pk,b_dept_pk,external_id,action\n'
    mysql_scalar "SELECT CONCAT_WS(',', a_dept_pk, IFNULL(b_dept_pk,''), IFNULL(external_id,''), action) FROM fusion_dept_map" || true
  } >"${LOG_DIR}/p5/fusion_dept_map.csv"
fi

ledger "${STEP}" "OK" "${inv}"
log "盘点 ${inv}；B 同名 ${b_names}"
