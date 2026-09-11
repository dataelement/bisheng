#!/usr/bin/env bash
set -euo pipefail
STEP="p2.20-2.4-beta1"
# 测试机 B 10.168.24.121
IMAGE_2_4_BETA1="dataelement/bisheng-backend:v2.4.0-beta1"
IMAGE_FRONTEND_2_4_BETA1="dataelement/bisheng-frontend:v2.4.0-beta1"
COMPOSE_FILE="/data/bisheng-main/docker/docker-compose.yml"
MYSQL_CONTAINER="bisheng-mysql"
MYSQL_DB="bisheng"
APPLY=1
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" ""

if require_apply; then
  add_column_if_missing message_session group_ids "ADD COLUMN group_ids json NULL COMMENT '会话所属用户组'"
  mysql_file "$(dirname "$0")/sql/20-2.4-beta1-group-ids.sql"
  left="$(mysql_scalar "SELECT COUNT(*) FROM message_session WHERE group_ids IS NULL")"
  log "group_ids 仍为 NULL 的会话: ${left}（无用户组的会话可以为 NULL）"
  switch_compose_images "${IMAGE_2_4_BETA1}" "${IMAGE_FRONTEND_2_4_BETA1}"
  compose up -d backend backend_worker frontend
  ledger "${STEP}" "OK" "null_group_ids=${left}"
else
  ledger "${STEP}" "DRY" "APPLY=0"
fi
log "下一步 21-hop-2.4.sh"
