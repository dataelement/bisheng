#!/usr/bin/env bash
# 按批次生成回滚 SQL. APPLY=1 才在 A 执行. 不会删除 A 原 type=3 空间.
set -euo pipefail
STEP="p5.90-rollback"
APPLY="${APPLY:-0}"
BATCH_NO="${BATCH_NO:?set BATCH_NO}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

mkdir -p "${LOG_DIR}/p5"
# 从 A fusion_map 拉本批映射
mysql_a_tsv "SELECT entity,src_id,dst_id,action FROM fusion_map WHERE batch_no='${BATCH_NO}'" \
  > "${LOG_DIR}/p5/rollback-map.tsv"

python3 - <<PY
import json, sys
from pathlib import Path
from collections import defaultdict
pack = Path("${PACK_ROOT}")
sys.path.insert(0, str(pack))
from fusion.sql import load_table
from fusion.maps import SKIP_ROLLBACK_ACTIONS
rows = load_table(Path("${LOG_DIR}/p5/rollback-map.tsv"))
maps = defaultdict(list)
user_create = []
for r in rows:
    ent, src, dst, act = r.get("entity"), r.get("src_id"), r.get("dst_id"), r.get("action")
    if not ent or not dst:
        continue
    if act in SKIP_ROLLBACK_ACTIONS:
        continue
    if ent == "user" and act == "create":
        user_create.append((src, dst))
        continue
    maps[ent].append((src, dst))
maps["user_create"] = user_create
maps["user"] = user_create
spaces = []
p = Path("${LOG_DIR}/p5/a-space-ids.txt")
if p.exists():
    for ln in p.read_text().split():
        try:
            spaces.append(int(ln))
        except ValueError:
            pass
dump = {"maps": {k: v for k, v in maps.items()}, "a_space_ids": spaces}
Path("${LOG_DIR}/p5/rollback-dump.json").write_text(json.dumps(dump), encoding="utf-8")
PY

python3 "${PACK_ROOT}/p5/build_sql.py" --kind rollback \
  --dump "${LOG_DIR}/p5/rollback-dump.json" \
  --maps "${LOG_DIR}/p4/maps" \
  --out "${LOG_DIR}/p5/rollback.sql" \
  --batch "${BATCH_NO}"

apply_sql_on_a "${LOG_DIR}/p5/rollback.sql"
if [[ -f "${LOG_DIR}/p5/openfga.tuples.json" ]]; then
  ACTION=delete APPLY="${APPLY}" bash "${PACK_ROOT}/p5/35-apply-openfga.sh"
fi
if [[ -f "${LOG_DIR}/p5/vector-created.tsv" ]]; then
  ACTION=drop APPLY="${APPLY}" bash "${PACK_ROOT}/p5/22-copy-vectors.sh"
fi
ledger "${STEP}" "OK" "APPLY=${APPLY} batch=${BATCH_NO}"
echo "OK ${STEP} SQL=${LOG_DIR}/p5/rollback.sql"
