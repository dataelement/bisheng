#!/usr/bin/env bash
# 按批次生成回滚 SQL. APPLY=1 才在 A 执行. 不会删除 A 原 type=3 空间.
# 向量: 删表前快照本批 knowledge 的 collection/index, 并合并 skip 留下的旧 Collection,
# 不只依赖 vector-created.tsv.
# MinIO: 按 minio-jobs dst / fusion_map file note / file-map 还原的键 mc rm, 不递归删桶.
# 连 A: 与 full-migrate.sh 相同, 会问地址/账号/端口(写入 env.sh)和密码(只进当前窗口).
set -euo pipefail
STEP="p5.90-rollback"
APPLY="${APPLY:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
prompt_a_ssh_target
if ! resolve_batch_no existing; then
  fusion_pick_open_batch_from_a || die "找不到批次名. 看 ${LOG_DIR}/current-batch.txt 或 logs/ledger.tsv. 多批次才需要 export BATCH_NO=..."
fi

mkdir -p "${LOG_DIR}/p5"
# 从 A fusion_map 拉本批映射
mysql_a_tsv "SELECT entity,src_id,dst_id,action,note FROM fusion_map WHERE batch_no='${BATCH_NO}'" \
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

# 必须在 DELETE knowledge 之前把 A 上的 collection/index 记下来.
python3 - <<PY
from pathlib import Path
import sys
sys.path.insert(0, "${PACK_ROOT}")
from fusion.maps import SKIP_ROLLBACK_ACTIONS
from fusion.sql import load_table
rows = load_table(Path("${LOG_DIR}/p5/rollback-map.tsv"))
spaces = set()
p = Path("${LOG_DIR}/p5/a-space-ids.txt")
if p.exists():
    for ln in p.read_text().split():
        try:
            spaces.add(int(ln))
        except ValueError:
            pass
ids = []
for r in rows:
    if (r.get("entity") or "") != "knowledge":
        continue
    if (r.get("action") or "").strip() in SKIP_ROLLBACK_ACTIONS:
        continue
    dst = (r.get("dst_id") or "").strip()
    if not dst.isdigit() or int(dst) in spaces:
        continue
    ids.append(dst)
Path("${LOG_DIR}/p5/rollback-knowledge-ids.txt").write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
print("knowledge_dsts=%d" % len(ids))
PY
: > "${LOG_DIR}/p5/rollback-knowledge-stores.tsv"
if [[ -s "${LOG_DIR}/p5/rollback-knowledge-ids.txt" ]]; then
  ids="$(paste -sd, "${LOG_DIR}/p5/rollback-knowledge-ids.txt")"
  mysql_a_tsv "SELECT id, collection_name, index_name FROM knowledge WHERE id IN (${ids})" \
    > "${LOG_DIR}/p5/rollback-knowledge-stores.tsv"
fi
PYTHONPATH="${PACK_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" python3 "${PACK_ROOT}/fusion/rollback_vectors.py" \
  --out "${LOG_DIR}/p5/rollback-vector-stores.tsv" \
  --knowledge-stores "${LOG_DIR}/p5/rollback-knowledge-stores.tsv" \
  --vector-jobs "${LOG_DIR}/p5/vector-jobs.tsv" \
  --vector-created "${LOG_DIR}/p5/vector-created.tsv" \
  --knowledge-map "${LOG_DIR}/p4/maps/knowledge-map.csv" \
  --b-knowledge "${LOG_DIR}/p5/b-knowledge.tsv" \
  --forbid "${LOG_DIR}/p5/a-space-store-names.txt"
log "向量删除名单 ${LOG_DIR}/p5/rollback-vector-stores.tsv"
if [[ -f "${LOG_DIR}/p5/rollback-vector-stores.tsv" ]]; then
  cat "${LOG_DIR}/p5/rollback-vector-stores.tsv" >&2
fi

PYTHONPATH="${PACK_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" python3 "${PACK_ROOT}/fusion/rollback_minio.py" \
  --out "${LOG_DIR}/p5/rollback-minio-keys.tsv" \
  --jobs "${LOG_DIR}/p5/minio-jobs.tsv" \
  --rollback-map "${LOG_DIR}/p5/rollback-map.tsv" \
  --file-map "${LOG_DIR}/p4/maps/file-map.csv" \
  --b-files "${LOG_DIR}/p5/b-files.tsv" \
  --dump "${LOG_DIR}/p5/dump.json"
log "MinIO 删除名单 ${LOG_DIR}/p5/rollback-minio-keys.tsv"
if [[ -f "${LOG_DIR}/p5/rollback-minio-keys.tsv" ]]; then
  cat "${LOG_DIR}/p5/rollback-minio-keys.tsv" >&2
fi

python3 "${PACK_ROOT}/p5/build_sql.py" --kind rollback \
  --dump "${LOG_DIR}/p5/rollback-dump.json" \
  --maps "${LOG_DIR}/p4/maps" \
  --out "${LOG_DIR}/p5/rollback.sql" \
  --batch "${BATCH_NO}"

apply_sql_on_a "${LOG_DIR}/p5/rollback.sql"
if [[ -f "${LOG_DIR}/p5/openfga.tuples.json" ]]; then
  ACTION=delete APPLY="${APPLY}" bash "${PACK_ROOT}/p5/35-apply-openfga.sh"
fi
if [[ -s "${LOG_DIR}/p5/rollback-vector-stores.tsv" ]] && awk -F'\t' 'NR>1 && $2!="" {found=1} END{exit found?0:1}' "${LOG_DIR}/p5/rollback-vector-stores.tsv"; then
  VECTOR_DROP_LIST="${LOG_DIR}/p5/rollback-vector-stores.tsv" ACTION=drop APPLY="${APPLY}" \
    bash "${PACK_ROOT}/p5/22-copy-vectors.sh"
fi
if [[ -s "${LOG_DIR}/p5/rollback-minio-keys.tsv" ]] && awk -F'\t' 'NR>1 && $1!="" {found=1} END{exit found?0:1}' "${LOG_DIR}/p5/rollback-minio-keys.tsv"; then
  MINIO_DROP_LIST="${LOG_DIR}/p5/rollback-minio-keys.tsv" ACTION=delete APPLY="${APPLY}" \
    bash "${PACK_ROOT}/p5/20-copy-minio.sh"
fi
ledger "${STEP}" "OK" "APPLY=${APPLY} batch=${BATCH_NO}"
echo "OK ${STEP} SQL=${LOG_DIR}/p5/rollback.sql"
