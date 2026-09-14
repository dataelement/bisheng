#!/usr/bin/env bash
# 从 A 只读导出置顶 / 成员置顶 / 收藏引用。不改库。
set -euo pipefail
STEP="p5.export-relations"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" ""

mkdir -p "${LOG_DIR}/p5"
dump="${LOG_DIR}/p5/a-relations.dump"
out="${LOG_DIR}/p5/a-relations.json"

{
  echo "===PINS==="
  mysql_a "SELECT user_id, type_detail FROM user_link WHERE type='knowledge_space_pin'" || true
  echo "===MEMBER_PINS==="
  mysql_a "SELECT business_id, user_id FROM space_channel_member WHERE business_type='space' AND IFNULL(is_pinned,0)=1" || true
  echo "===FAVORITE_REFS==="
  mysql_a "SELECT kf.id, kf.knowledge_id, kf.user_id, kf.file_name, kf.reference_document_id FROM knowledgefile kf JOIN knowledge k ON k.id=kf.knowledge_id WHERE k.type=3 AND IFNULL(k.is_favorite,0)=1 AND kf.deleted_at IS NULL AND kf.reference_document_id IS NOT NULL" || true
} >"${dump}"

python3 - "${dump}" "${out}" <<'PY'
import json, sys
from pathlib import Path

dump, out = Path(sys.argv[1]), Path(sys.argv[2])
parts: dict[str, list[str]] = {}
current = None
buf: list[str] = []
for line in dump.read_text(encoding="utf-8").splitlines():
    if line.startswith("===") and line.endswith("==="):
        if current is not None:
            parts[current] = buf
        current = line.strip("=").strip()
        buf = []
        continue
    if current is not None:
        buf.append(line)
if current is not None:
    parts[current] = buf

def rows(section: str) -> list[list[str]]:
    out_rows = []
    for line in parts.get(section, []):
        if not line.strip():
            continue
        out_rows.append(line.split("\t"))
    return out_rows

pins = [{"user_id": r[0], "type_detail": r[1]} for r in rows("PINS") if len(r) >= 2]
member_pins = [{"business_id": r[0], "user_id": r[1]} for r in rows("MEMBER_PINS") if len(r) >= 2]
favs = []
for r in rows("FAVORITE_REFS"):
    if len(r) < 5:
        continue
    favs.append(
        {
            "id": r[0],
            "knowledge_id": r[1],
            "user_id": r[2],
            "file_name": r[3],
            "reference_document_id": r[4],
        }
    )
payload = {"pins": pins, "member_pins": member_pins, "favorite_refs": favs}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"pins={len(pins)} member_pins={len(member_pins)} favorite_refs={len(favs)} -> {out}")
PY

ledger "${STEP}" "OK" "${out}"
log "已写 ${out}"
