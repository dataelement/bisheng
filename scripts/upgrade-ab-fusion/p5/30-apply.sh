#!/usr/bin/env bash
# dry-run + 生成各域 SQL. APPLY=1 才写入 A.
set -euo pipefail
STEP="p5.30-apply"
APPLY="${APPLY:-0}"
MIGRATE_B_SPACES="${MIGRATE_B_SPACES:-0}"
CONFIRM_POINTS="${CONFIRM_POINTS:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
resolve_batch_no

[[ -f "${PACK_ROOT}/p4/user-map.csv" ]] || die "先完成身份映射 p4/user-map.csv"

if [[ "${APPLY}" == "1" ]]; then
  require_a_25_for_apply
  require_b_25_for_apply
  assert_b_org_sync_off
  assert_a_shared_space_gate
fi

mkdir -p "${LOG_DIR}/p5" "${LOG_DIR}/p4/maps"
cp -f "${PACK_ROOT}/p4/"*.csv "${LOG_DIR}/p4/maps/" 2>/dev/null || true
# 身份 map 来自 p4/02-propose 自动安装的对照表.
# 业务 map: A 已落库的实体保留 (续跑同 ID); 未落库的清掉, 否则 dry-run 残留会跳过 INSERT.
applied_entities=""
if [[ "${APPLY}" == "1" ]]; then
  applied_entities="$(mysql_a "SELECT DISTINCT entity FROM fusion_map WHERE batch_no='${BATCH_NO}'" || true)"
fi
identity_keep='user-map.csv dept-map.csv group-map.csv role-map.csv tenant-map.csv model-map.csv server-map.csv tool-map.csv tool-key-map.csv'
declare -A map_entity=(
  [knowledge-map.csv]=knowledge
  [file-map.csv]=file
  [qa-map.csv]=qa
  [dictionary-map.csv]=dictionary
  [tag-map.csv]=review_tag
  [tag-link-map.csv]=review_tag_link
  [flow-map.csv]=flow
  [flowversion-map.csv]=flowversion
  [assistant-map.csv]=assistant
  [chat-map.csv]=chat
  [message-map.csv]=message
  [citation-map.csv]=citation
  [citation-relation-map.csv]=citation_relation
  [mark-task-map.csv]=mark_task
  [mark-record-map.csv]=mark_record
  [mark-app-user-map.csv]=mark_app_user
  [report-map.csv]=report
  [report-version-key-map.csv]=report
  [tool-type-map.csv]=tool_type
  [role-access-map.csv]=role_access
  [group-resource-map.csv]=group_resource
  [share-link-map.csv]=share_link
  [audit-map.csv]=audit
)
for f in "${LOG_DIR}/p4/maps/"*.csv; do
  [[ -f "${f}" ]] || continue
  base="$(basename "${f}")"
  keep=0
  for k in ${identity_keep}; do
    if [[ "${base}" == "${k}" ]]; then
      keep=1
      break
    fi
  done
  entity="${map_entity[${base}]:-}"
  if [[ -n "${entity}" && -n "${applied_entities}" ]] && printf '%s\n' "${applied_entities}" | grep -qx "${entity}"; then
    keep=1
  fi
  if [[ "${keep}" != "1" ]]; then
    rm -f "${f}"
  fi
done
rm -f "${LOG_DIR}/p5/minio-jobs.tsv"

if [[ "${APPLY}" == "1" ]]; then
  # A 在导出后可能继续写消息. 主键从 MAX+100000 起, 躲开并发 AUTO_INCREMENT.
  mx="$(mysql_a "SELECT COALESCE(MAX(id),0) FROM chatmessage" || echo 0)"
  mx="$(printf '%s' "${mx}" | tr -d '[:space:]')"
  echo "$((mx + 100000))" > "${LOG_DIR}/p5/next-message-id.txt"
  mysql_a_tsv "SELECT id FROM chatmessage" > "${LOG_DIR}/p5/a-message-ids.tsv" || true
  mysql_a_tsv "SELECT chat_id FROM message_session" > "${LOG_DIR}/p5/a-chat-ids.tsv"
  log "chatmessage next_id=$((mx + 100000)) (A max=${mx})"
fi

python3 "${PACK_ROOT}/p5/assemble_dump.py" "${LOG_DIR}/p5"
dry_space=(--no-migrate-b-spaces)
if [[ "${MIGRATE_B_SPACES}" == "1" ]]; then
  dry_space=(--migrate-b-spaces)
fi
python3 "${PACK_ROOT}/fusion/cli.py" dry-run \
  --input "${LOG_DIR}/p5/dump.json" \
  --user-map "${PACK_ROOT}/p4/user-map.csv" \
  --out "${LOG_DIR}/p5/dry-run.json" \
  "${dry_space[@]}"

# 字典可先于业务; 模型/工具须在 knowledge/flow 之前落 map, 否则工作流引用会失败
for kind in dictionary llm tool_types knowledge qa tags flow assistant session citations marks reports relations group_resource role_access audit openfga; do
  python3 "${PACK_ROOT}/p5/build_sql.py" --kind "${kind}" \
    --dump "${LOG_DIR}/p5/dump.json" \
    --maps "${LOG_DIR}/p4/maps" \
    --out "${LOG_DIR}/p5/${kind}.sql" \
    --batch "${BATCH_NO}"
done
chmod 600 "${LOG_DIR}/p5/llm.sql" "${LOG_DIR}/p5/tool_types.sql" 2>/dev/null || true

python3 "${PACK_ROOT}/fusion/cli.py" gaps \
  --maps "${LOG_DIR}/p4/maps" \
  --propose-dir "${LOG_DIR}/p4" \
  --out "${LOG_DIR}/p5/gaps-model-tool.tsv"
cp -f "${LOG_DIR}/p4/maps/"model-map.csv "${PACK_ROOT}/p4/" 2>/dev/null || true
cp -f "${LOG_DIR}/p4/maps/"server-map.csv "${PACK_ROOT}/p4/" 2>/dev/null || true
cp -f "${LOG_DIR}/p4/maps/"tool-map.csv "${PACK_ROOT}/p4/" 2>/dev/null || true
cp -f "${LOG_DIR}/p4/maps/"tool-key-map.csv "${PACK_ROOT}/p4/" 2>/dev/null || true

if [[ "${CONFIRM_POINTS}" == "1" ]]; then
  log "积分迁移未实现自动 APPLY, 见方案 D16; 本包跳过积分, 审计已在上面 APPLY"
fi

if [[ "${APPLY}" == "1" ]]; then
  declare -A kind_entity=(
    [dictionary]=dictionary
    [llm]=llm_server
    [tool_types]=tool_type
    [knowledge]=knowledge
    [qa]=qa
    [tags]=review_tag
    [flow]=flow
    [assistant]=assistant
    [session]=chat
    [citations]=citation
    [marks]=mark_task
    [reports]=report
    [relations]=citation_relation
    [group_resource]=group_resource
    [role_access]=role_access
    [audit]=audit
  )
  for kind in dictionary llm tool_types knowledge qa tags flow assistant session citations marks reports relations group_resource role_access audit; do
    entity="${kind_entity[${kind}]}"
    n="$(mysql_a "SELECT COUNT(*) FROM fusion_map WHERE batch_no='${BATCH_NO}' AND entity='${entity}'" || echo 0)"
    n="$(printf '%s' "${n}" | tr -d '[:space:]')"
    if [[ "${n}" != "0" ]]; then
      log "skip APPLY ${kind}: fusion_map 已有 ${entity}=${n}"
      continue
    fi
    apply_sql_on_a "${LOG_DIR}/p5/${kind}.sql"
  done
fi

ledger "${STEP}" "OK" "APPLY=${APPLY}"
echo "OK ${STEP}. MinIO 任务 logs/p5/minio-jobs.tsv; OpenFGA logs/p5/openfga.tuples.json; 缺口 logs/p5/gaps-model-tool.tsv"
echo "下一步: bash p5/20-copy-minio.sh ; bash p5/22-copy-vectors.sh ; bash p5/35-apply-openfga.sh"
