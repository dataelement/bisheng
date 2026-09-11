#!/usr/bin/env bash
# 2.4 正式版：知识空间相关列。新表 space_channel_member 由本 hop SQL 建, 不依赖 2.4 启动 create_all.
set -euo pipefail
STEP="p2.21-2.4"
# 默认值可被环境变量覆盖；compose 路径一律自动发现，不写死。
: "${IMAGE_2_4:=dataelement/bisheng-backend:v2.4.0}"
: "${IMAGE_FRONTEND_2_4:=dataelement/bisheng-frontend:v2.4.0}"
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${APPLY:=0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
discover_deployment
ledger "${STEP}" "START" ""

if require_apply; then
  mysql_exec "ALTER TABLE config MODIFY value longtext NULL"

  add_column_if_missing user avatar "ADD COLUMN avatar varchar(255) NULL COMMENT '头像'"
  add_column_if_missing role knowledge_space_file_limit "ADD COLUMN knowledge_space_file_limit int DEFAULT 40 NULL COMMENT '知识空间文件大小限制'"
  add_column_if_missing knowledge auth_type "ADD COLUMN auth_type ENUM('PUBLIC','PRIVATE','APPROVAL') DEFAULT 'PUBLIC' COMMENT '知识空间授权类型'"
  add_column_if_missing knowledge is_released "ADD COLUMN is_released tinyint DEFAULT 0 COMMENT '是否发布'"

  add_column_if_missing knowledgefile preview_file_object_name "ADD COLUMN preview_file_object_name varchar(255) DEFAULT NULL"
  add_column_if_missing knowledgefile abstract "ADD COLUMN abstract text DEFAULT NULL"
  add_column_if_missing knowledgefile thumbnails "ADD COLUMN thumbnails varchar(255) DEFAULT NULL"
  add_column_if_missing knowledgefile file_type "ADD COLUMN file_type tinyint DEFAULT 1"
  add_column_if_missing knowledgefile file_source "ADD COLUMN file_source varchar(32) DEFAULT 'upload'"
  add_column_if_missing knowledgefile level "ADD COLUMN level int DEFAULT 0"
  add_column_if_missing knowledgefile file_level_path "ADD COLUMN file_level_path varchar(255) DEFAULT ''"

  add_column_if_missing tag business_type "ADD COLUMN business_type enum('KNOWLEDGE_SPACE','APPLICATION') NOT NULL DEFAULT 'APPLICATION'"
  add_column_if_missing tag business_id "ADD COLUMN business_id char(32) NOT NULL DEFAULT 'application'"
  add_column_if_missing message_session name "ADD COLUMN name varchar(255) DEFAULT NULL COMMENT '会话名称'"

  idx="$(mysql_scalar "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='${MYSQL_DB}' AND TABLE_NAME='tag' AND INDEX_NAME='ix_tag_name'")"
  if [[ "${idx}" != "0" ]]; then
    mysql_exec "ALTER TABLE tag DROP INDEX ix_tag_name"
  fi

  mysql_exec "ALTER TABLE t_gpts_tools MODIFY \`desc\` longtext NULL"

  mysql_file "$(dirname "$0")/sql/21-2.4-dml.sql"
  table_exists space_channel_member || die "space_channel_member 未建成功，不要跑 type=2"

  switch_compose_images "${IMAGE_2_4}" "${IMAGE_FRONTEND_2_4}"
  log "启动 2.4 镜像"
  compose up -d backend backend_worker frontend
  ledger "${STEP}" "OK" "2.4 schema"
else
  ledger "${STEP}" "DRY" "APPLY=0"
fi
log "下一步 22-hop-2.4-type2.sh（先看 type=2 清单，对齐 D07）"
