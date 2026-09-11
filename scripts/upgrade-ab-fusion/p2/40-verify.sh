#!/usr/bin/env bash
# B 升级验收计数。不能替代业务 UAT。
set -euo pipefail
STEP="p2.40-verify"
# 测试机 B。2.4 阶段还没有 alembic，不要跑本脚本。
TARGET_ALEMBIC_HEAD="f058_dashboard_dataset_flags"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" ""

out="${LOG_DIR}/p2-verify-$(date +%Y%m%d%H%M%S).txt"
{
  echo "alembic_version"
  mysql_exec "SELECT version_num FROM alembic_version"
  echo "users/flows/knowledge/files/sessions"
  mysql_exec "SELECT
    (SELECT COUNT(*) FROM \`user\`) users,
    (SELECT COUNT(*) FROM flow) flows,
    (SELECT COUNT(*) FROM knowledge) knowledge,
    (SELECT COUNT(*) FROM knowledgefile) files,
    (SELECT COUNT(*) FROM message_session) sessions"
  echo "knowledge.type"
  mysql_exec "SELECT type, COUNT(*) cnt FROM knowledge GROUP BY type"
  echo "type=2 leftover"
  mysql_exec "SELECT COUNT(*) leftover_type2 FROM knowledge WHERE type=2"
  if table_exists failed_tuple; then
    echo "failed_tuple"
    mysql_exec "SELECT status, COUNT(*) cnt FROM failed_tuple GROUP BY status"
  fi
} | tee "${out}"

dbv="$(mysql_scalar "SELECT version_num FROM alembic_version")"
[[ "${dbv}" == "${TARGET_ALEMBIC_HEAD}" ]] || die "head mismatch ${dbv}"

ledger "${STEP}" "OK" "${out}"
log "把本文件与升级前 P1 计数对比。差异必须能解释并签字。然后做工作流打开/跑通、知识库上传解析检索。"
