#!/usr/bin/env bash
# 从 A 按空间只读导出 JSON 到 logs/p5/。不改库。
# 用法: bash p5/00-export-a-space.sh --space-id 123
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
    mysql_a "SELECT id, name, IFNULL(description,''), user_id, type, IFNULL(state,0), IFNULL(is_released,0), IFNULL(auth_type,'public'), IFNULL(icon,'') FROM knowledge WHERE id=${sid} AND type=3"
    echo "===SCOPE==="
    mysql_a "SELECT space_id, level, owner_type, owner_id FROM knowledge_space_scope WHERE space_id=${sid}" || true
    echo "===FILES==="
    mysql_a "SELECT id, user_id, IFNULL(user_name,''), knowledge_id, file_name, IFNULL(file_type,1), IFNULL(file_source,''), IFNULL(level,0), IFNULL(file_level_path,''), file_size, IFNULL(md5,''), status, IFNULL(object_name,''), IFNULL(parse_type,''), IFNULL(remark,''), updater_id, IFNULL(updater_name,''), original_uploader_id, reference_document_id, predecessor_logic_file_id, IFNULL(entry_type,''), IFNULL(entry_status,'') FROM knowledgefile WHERE knowledge_id=${sid} AND deleted_at IS NULL"
    echo "===DOCS==="
    mysql_a "SELECT id, knowledge_id, IFNULL(file_level_path,''), IFNULL(level,0), primary_version_id, predecessor_logic_file_id, IFNULL(content_generation,0), IFNULL(lifecycle_status,'active') FROM knowledge_document WHERE knowledge_id=${sid}" || true
    echo "===VERSIONS==="
    mysql_a "SELECT v.id, v.document_id, v.knowledge_file_id, v.version_no, v.is_primary FROM knowledge_document_version v JOIN knowledge_document d ON d.id=v.document_id WHERE d.knowledge_id=${sid}" || true
    echo "===MEMBERS==="
    mysql_a "SELECT user_id, user_role, IFNULL(status,'ACTIVE'), IFNULL(grant_subject_type,''), grant_subject_id, IFNULL(grant_relation,'') FROM space_channel_member WHERE business_id='${sid}' AND business_type='space'" || true
  } >"${dump}"
  python3 "${PACK_ROOT}/p5/export_to_json.py" "${dump}" "${json}"
}

for sid in "${ids[@]}"; do
  export_one "${sid}"
done

ledger "${STEP}" "OK" "count=${#ids[@]}"
log "JSON 在 ${LOG_DIR}/p5/a-space-*.json"
