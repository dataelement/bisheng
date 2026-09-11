#!/usr/bin/env bash
# P2 预检：钉死目标构建；摸清 B 相对官方 2.2 的 schema；禁止用 Alembic 偷跳 2.3/2.4。
set -euo pipefail
STEP="p2.00-precheck"
# 默认值可被环境变量覆盖；compose 路径一律自动发现，不写死。
: "${DRILL:=0}"
: "${TARGET_GIT_COMMIT:=DRILL-SKIP}"
: "${TARGET_BACKEND_IMAGE:=dataelement/bisheng-backend:v2.4.0}"
: "${TARGET_FRONTEND_IMAGE:=dataelement/bisheng-frontend:v2.4.0}"
: "${IMAGE_OPENFGA:=unused-until-2.5}"
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
discover_deployment

ledger "${STEP}" "START" ""
if [[ "${DRILL:-0}" == "1" ]]; then
  log "DRILL=1：演练机允许跳过 git commit / 镜像 digest 钉扎。生产禁止 DRILL=1"
else
  assert_git_commit
  assert_pinned_image "${TARGET_BACKEND_IMAGE}"
  assert_pinned_image "${TARGET_FRONTEND_IMAGE}"
  if [[ "${IMAGE_OPENFGA}" == *":latest"* ]] || [[ "${IMAGE_OPENFGA}" == REPLACE* ]]; then
    die "IMAGE_OPENFGA 必须钉 digest，禁止 latest"
  fi
fi

if table_exists "alembic_version"; then
  cur="$(mysql_scalar "SELECT version_num FROM alembic_version LIMIT 1")"
  log "已有 alembic_version=${cur}。若这是未完成的 2.5 半升级，停止并走回滚，不要接着 hop。"
else
  log "无 alembic_version：符合 2.2 create_all 预期"
fi

log "=== 关键表/列（官方 2.3/2.4 将要加的，现在不该有 2.4 知识空间列）==="
for pair in "knowledge:metadata_fields" "knowledge:auth_type" "knowledgefile:user_metadata" "knowledgefile:file_level_path" "knowledgefile:extra_meta" "user:avatar" "user:source" "user:external_id" "message_session:group_ids"; do
  t="${pair%%:*}"
  c="${pair##*:}"
  if column_exists "${t}" "${c}"; then
    log "PRESENT ${t}.${c}"
  else
    log "MISSING ${t}.${c}"
  fi
done

log "=== type=2 个人知识库 ==="
mysql_exec "SELECT id, name, type, user_id, (SELECT COUNT(*) FROM knowledgefile f WHERE f.knowledge_id=knowledge.id) file_cnt FROM knowledge WHERE type=2"

log "=== 部署布局 ==="
preflight_report

ledger "${STEP}" "OK" "review schema diff before hop"
log "预检通过（仅检查）。有 PRESENT 的 2.4 列时，说明 B 已部分升级，禁止重跑对应 ALTER。"
