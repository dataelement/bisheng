#!/usr/bin/env bash
# 从 A 按空间只读导出 JSON 到 logs/p5/。不改库。
# 用法: bash p5/00-export-a-space.sh --space-id 123
#       bash p5/00-export-a-space.sh --all
#       bash p5/00-export-a-space.sh          # 读 logs/p5/batch.txt
set -euo pipefail
STEP="p5.export"
MYSQL_CONTAINER="${MYSQL_CONTAINER:-bisheng-mysql}"
MYSQL_DB="${MYSQL_DB:-bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
ledger "${STEP}" "START" ""

mkdir -p "${LOG_DIR}/p5"
ids=()
export_all=0
batch_file="${LOG_DIR}/p5/batch.txt"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --space-id)
      ids+=("$2")
      shift 2
      ;;
    --batch-file)
      batch_file="$2"
      shift 2
      ;;
    --all)
      export_all=1
      mapfile -t ids < <(mysql_a "SELECT id FROM knowledge WHERE type=3 AND IFNULL(state,0)<>5 ORDER BY id")
      shift
      ;;
    *)
      die "未知参数 $1"
      ;;
  esac
done
if [[ ${#ids[@]} -eq 0 ]]; then
  [[ -f "${batch_file}" ]] || die "未给 --space-id 且缺少 ${batch_file}"
  while read -r line; do
    [[ -z "${line}" || "${line}" =~ ^# ]] && continue
    ids+=("${line}")
  done <"${batch_file}"
fi
[[ ${#ids[@]} -gt 0 ]] || die "没有要导出的空间"

export_one() {
  local sid="$1"
  local dump="${LOG_DIR}/p5/a-space-${sid}.dump"
  local json="${LOG_DIR}/p5/a-space-${sid}.json"
  log "导出 A space_id=${sid}"
  {
    echo "===SPACE==="
    mysql_a "SELECT id, name, IFNULL(description,''), user_id, type, IFNULL(state,0), IFNULL(is_released,0), IFNULL(auth_type,'public'), IFNULL(icon,''), IFNULL(is_favorite,0) FROM knowledge WHERE id=${sid} AND type=3"
    echo "===SCOPE==="
    mysql_a "SELECT space_id, level, owner_type, owner_id FROM knowledge_space_scope WHERE space_id=${sid}" || true
    echo "===FILES==="
    mysql_a "SELECT id, user_id, IFNULL(user_name,''), knowledge_id, file_name, IFNULL(file_type,1), IFNULL(file_source,''), IFNULL(level,0), IFNULL(file_level_path,''), file_size, IFNULL(md5,''), status, IFNULL(object_name,''), IFNULL(parse_type,''), IFNULL(remark,''), updater_id, IFNULL(updater_name,''), original_uploader_id, reference_document_id, predecessor_logic_file_id, IFNULL(entry_type,''), IFNULL(entry_status,''), IFNULL(preview_file_object_name,''), IFNULL(thumbnails,'') FROM knowledgefile WHERE knowledge_id=${sid} AND deleted_at IS NULL"
    echo "===DOCS==="
    mysql_a "SELECT id, knowledge_id, IFNULL(file_level_path,''), IFNULL(level,0), primary_version_id, predecessor_logic_file_id, IFNULL(content_generation,0), IFNULL(lifecycle_status,'active') FROM knowledge_document WHERE knowledge_id=${sid}" || true
    echo "===VERSIONS==="
    mysql_a "SELECT v.id, v.document_id, v.knowledge_file_id, v.version_no, v.is_primary FROM knowledge_document_version v JOIN knowledge_document d ON d.id=v.document_id WHERE d.knowledge_id=${sid}" || true
    echo "===MEMBERS==="
    mysql_a "SELECT user_id, user_role, IFNULL(status,'ACTIVE'), IFNULL(grant_subject_type,''), grant_subject_id, IFNULL(grant_relation,''), IFNULL(is_pinned,0) FROM space_channel_member WHERE business_id='${sid}' AND business_type='space'" || true
    echo "===TAGS==="
    mysql_a "SELECT id, name, IFNULL(description,''), CAST(tags AS CHAR), IFNULL(is_builtin,0), IFNULL(owner_knowledge_id,''), IFNULL(user_id,0) FROM knowledge_space_tag_library WHERE owner_knowledge_id=${sid} OR id IN (SELECT tag_library_id FROM knowledge_tag_library_link WHERE knowledge_id=${sid})" || true
    echo "===TAG_LINKS==="
    mysql_a "SELECT knowledge_id, tag_library_id, IFNULL(sort_order,0) FROM knowledge_tag_library_link WHERE knowledge_id=${sid}" || true
  } >"${dump}"
  python3 "${PACK_ROOT}/p5/export_to_json.py" "${dump}" "${json}"
}

for sid in "${ids[@]}"; do
  export_one "${sid}"
done

if [[ "${export_all}" == "1" ]]; then
  printf '%s\n' "${ids[@]}" >"${LOG_DIR}/p5/batch.txt"
  log "已写 ${LOG_DIR}/p5/batch.txt (${#ids[@]} 个空间)"
fi

ledger "${STEP}" "OK" "count=${#ids[@]}"
log "JSON 在 ${LOG_DIR}/p5/a-space-*.json"
