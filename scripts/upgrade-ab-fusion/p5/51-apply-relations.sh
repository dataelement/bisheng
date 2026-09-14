#!/usr/bin/env bash
# 按映射迁置顶/订阅置顶/收藏引用。映不上跳过。默认 APPLY=0。
set -euo pipefail
STEP="p5.apply-relations"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
APPLY="${APPLY:-0}"
BATCH_NO="${BATCH_NO:-p5-relations}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" "APPLY=${APPLY}"

export_json="${LOG_DIR}/p5/a-relations.json"
[[ -f "${export_json}" ]] || die "缺少 ${export_json}, 先跑 p5/50-export-a-relations.sh"
user_map="${USER_MAP:-${PACK_ROOT}/p4/user-map.csv}"
if [[ ! -f "${user_map}" ]]; then
  user_map="${LOG_DIR}/p5/fusion_user_map.csv"
fi
[[ -f "${user_map}" ]] || die "缺少用户映射"

mkdir -p "${LOG_DIR}/p5"
space_map="${LOG_DIR}/p5/fusion_space_map.csv"
file_map="${LOG_DIR}/p5/fusion_file_map.csv"
doc_map="${LOG_DIR}/p5/fusion_document_map.csv"

if table_exists fusion_space_map; then
  {
    printf 'a_space_id,b_space_id\n'
    mysql_scalar "SELECT CONCAT_WS(',', a_space_id, b_space_id) FROM fusion_space_map WHERE b_space_id IS NOT NULL" || true
  } >"${space_map}"
fi
if table_exists fusion_file_map; then
  {
    printf 'a_file_id,b_file_id\n'
    mysql_scalar "SELECT CONCAT_WS(',', a_file_id, b_file_id) FROM fusion_file_map WHERE b_file_id IS NOT NULL" || true
  } >"${file_map}"
fi
if table_exists fusion_document_map; then
  {
    printf 'a_doc_id,b_doc_id\n'
    mysql_scalar "SELECT CONCAT_WS(',', a_doc_id, b_doc_id) FROM fusion_document_map WHERE b_doc_id IS NOT NULL" || true
  } >"${doc_map}"
fi
[[ -f "${space_map}" ]] || die "缺少 ${space_map}, 先 APPLY P5 空间"

sql_out="${LOG_DIR}/p5-relations-$(date +%Y%m%d%H%M%S).sql"
skip_out="${LOG_DIR}/p5/relations-skipped.json"
rel_args=(
  "${export_json}"
  --user-map "${user_map}"
  --space-map "${space_map}"
  --batch-no "${BATCH_NO}"
  --skip-out "${skip_out}"
)
[[ -f "${file_map}" ]] && rel_args+=(--file-map "${file_map}")
[[ -f "${doc_map}" ]] && rel_args+=(--doc-map "${doc_map}")
python3 "${PACK_ROOT}/p5/relations_to_sql.py" "${rel_args[@]}" >"${sql_out}"
log "已生成 ${sql_out}, 跳过清单 ${skip_out}"

if [[ "${APPLY}" != "1" ]]; then
  ledger "${STEP}" "DRY" "${sql_out}"
  log "APPLY=0, 未落库。"
  exit 0
fi

require_b_25_for_apply
mysql_file "${PACK_ROOT}/p4/sql/mapping-tables.sql"
mysql_file "${PACK_ROOT}/p5/sql/space-map.sql"
mysql_file "${sql_out}"
ledger "${STEP}" "OK" "${sql_out}"
log "关系迁移完成。跳过 ${skip_out}"
