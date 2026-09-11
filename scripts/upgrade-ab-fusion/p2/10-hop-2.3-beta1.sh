#!/usr/bin/env bash
# 2.3-beta1：补列 + 用 2.3-beta1 镜像跑 convert_all（评审稿 §5.2 步骤 2）。
set -euo pipefail
STEP="p2.10-2.3-beta1"
# 默认值可被环境变量覆盖；compose 路径一律自动发现，不写死。
: "${IMAGE_2_3_BETA1:=dataelement/bisheng-backend:v2.3.0-beta1}"
: "${IMAGE_FRONTEND_2_3_BETA1:=dataelement/bisheng-frontend:v2.3.0-beta1}"
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${APPLY:=0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
discover_deployment
ledger "${STEP}" "START" "$(sha256_file "$(dirname "$0")/sql/10-2.3-beta1-backfill.sql")"

if require_apply; then
  add_column_if_missing knowledge metadata_fields "ADD COLUMN metadata_fields json DEFAULT NULL COMMENT '知识库元数据字段配置'"
  add_column_if_missing knowledgefile user_name "ADD COLUMN user_name varchar(255) NULL COMMENT '上传者用户名' AFTER user_id"
  add_column_if_missing knowledgefile updater_id "ADD COLUMN updater_id int NULL COMMENT '更新者ID'"
  add_column_if_missing knowledgefile updater_name "ADD COLUMN updater_name varchar(255) NULL COMMENT '更新者用户名' AFTER updater_id"
  add_column_if_missing knowledgefile user_metadata "ADD COLUMN user_metadata json DEFAULT NULL COMMENT '用户自定义元数据'"

  mysql_file "$(dirname "$0")/sql/10-2.3-beta1-backfill.sql"

  if column_exists knowledgefile extra_meta; then
    log "DROP extra_meta（官方 2.3-beta1）"
    mysql_exec "ALTER TABLE knowledgefile DROP COLUMN extra_meta"
  fi

  switch_compose_images "${IMAGE_2_3_BETA1}" "${IMAGE_FRONTEND_2_3_BETA1}"
  log "启动 2.3-beta1 容器（不必对用户开放）"
  compose up -d backend backend_worker frontend

  log "convert_all：必须 2.3 代码，工作目录视镜像而定"
  docker exec -e PYTHONPATH=./ "${BACKEND_CONTAINER}" bash -lc \
    'if [ -f bisheng/script/knowledge.sh ]; then sh bisheng/script/knowledge.sh convert_all;
     elif [ -f scripts/knowledge.sh ]; then sh scripts/knowledge.sh convert_all;
     else echo "knowledge.sh not found"; exit 1; fi'
fi

if [[ "${APPLY}" == "1" ]]; then
  column_exists knowledge metadata_fields || die "knowledge.metadata_fields 不存在"
  column_exists knowledgefile extra_meta && die "extra_meta 仍在，DROP 未完成"
  ledger "${STEP}" "OK" "convert_all done"
else
  ledger "${STEP}" "DRY" "APPLY=0"
fi
log "下一步 11-hop-2.3-release.sh"
