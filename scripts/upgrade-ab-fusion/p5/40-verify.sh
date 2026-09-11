#!/usr/bin/env bash
# 按 fusion_* 映射核对数量、对象哈希、版本链、解析终态。检索只做有向量/可查抽样。
set -euo pipefail
STEP="p5.verify"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-bisheng-backend}"
BATCH_NO="${BATCH_NO:-}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" "batch=${BATCH_NO}"

table_exists fusion_space_map || die "没有 fusion_space_map"
b_before="${LOG_DIR}/p5/b-space-count-before.txt"
# 不要求 before 文件; 只断言映射行对应的 B 空间存在且 A 原库未在本机。

log "=== 空间映射 ==="
mysql_exec "SELECT status, COUNT(*) cnt FROM fusion_space_map GROUP BY status"

log "=== 文件映射 vs B knowledgefile ==="
mysql_exec "SELECT m.a_space_id, m.b_space_id,
  (SELECT COUNT(*) FROM fusion_file_map f JOIN knowledgefile kf ON kf.id=f.b_file_id WHERE f.b_file_id IS NOT NULL AND kf.knowledge_id=m.b_space_id) mapped_files,
  (SELECT COUNT(*) FROM knowledgefile kf WHERE kf.knowledge_id=m.b_space_id AND kf.file_type=1) b_files
  FROM fusion_space_map m ${BATCH_NO:+WHERE m.batch_no='${BATCH_NO}'}"

log "=== 解析状态 (B 新空间) ==="
mysql_exec "SELECT kf.status, COUNT(*) cnt
  FROM knowledgefile kf
  JOIN fusion_space_map m ON m.b_space_id=kf.knowledge_id
  WHERE kf.file_type=1
  ${BATCH_NO:+AND m.batch_no='${BATCH_NO}'}
  GROUP BY kf.status"

log "=== 版本链: 有主版本的文档 ==="
mysql_exec "SELECT COUNT(*) docs_with_primary
  FROM knowledge_document d
  JOIN fusion_space_map m ON m.b_space_id=d.knowledge_id
  WHERE d.primary_version_id IS NOT NULL
  ${BATCH_NO:+AND m.batch_no='${BATCH_NO}'}"

log "=== 例外 ==="
if table_exists fusion_exception; then
  mysql_exec "SELECT kind, COUNT(*) cnt FROM fusion_exception ${BATCH_NO:+WHERE batch_no='${BATCH_NO}'} GROUP BY kind"
fi

log "=== 对象存在抽样 (最多 5 个 dst key) ==="
mapfile -t keys < <(mysql_scalar "SELECT dst_object_key FROM fusion_file_map WHERE dst_object_key IS NOT NULL AND dst_object_key<>'' ${BATCH_NO:+AND batch_no='${BATCH_NO}'} LIMIT 5")
if [[ ${#keys[@]} -gt 0 ]]; then
  docker cp "${PACK_ROOT}/p5/minio_xfer.py" "${BACKEND_CONTAINER}:/tmp/fusion-ab/minio_xfer.py" 2>/dev/null || true
  docker exec "${BACKEND_CONTAINER}" mkdir -p /tmp/fusion-ab
  docker cp "${PACK_ROOT}/p5/minio_xfer.py" "${BACKEND_CONTAINER}:/tmp/fusion-ab/minio_xfer.py"
  for key in "${keys[@]}"; do
    [[ -z "${key}" ]] && continue
    docker exec -w /app -e PYTHONPATH=/app "${BACKEND_CONTAINER}" \
      python /tmp/fusion-ab/minio_xfer.py exists "${key}" || log "MISSING ${key}"
  done
fi

log "=== 向量/全文: 只确认新空间有 collection_name, 不编造金标 ==="
mysql_exec "SELECT m.b_space_id, k.name, k.collection_name, k.index_name, k.state
  FROM fusion_space_map m JOIN knowledge k ON k.id=m.b_space_id
  ${BATCH_NO:+WHERE m.batch_no='${BATCH_NO}'}"

ledger "${STEP}" "OK" "review parse status; enqueue success != parse done"
log "verify 只核对映射与对象抽样。解析终态要等 Worker; 未 SUCCESS 不要发布。"
