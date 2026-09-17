#!/usr/bin/env bash
# 记录 A 保护基线到 fusion_a_baseline (APPLY=1) 或只打印 (APPLY=0).
set -euo pipefail
STEP="p5.00-baseline"
APPLY="${APPLY:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
mkdir -p "${LOG_DIR}/p5"
{
  echo "metric	value"
  echo -n "a_space_cnt	"; mysql_a "SELECT COUNT(*) FROM knowledge WHERE type=3"
  echo -n "a_space_file_cnt	"; mysql_a "SELECT COUNT(*) FROM knowledgefile f JOIN knowledge k ON f.knowledge_id=k.id WHERE k.type=3"
  echo -n "a_session_cnt	"; mysql_a "SELECT COUNT(*) FROM message_session"
  echo -n "a_message_cnt	"; mysql_a "SELECT COUNT(*) FROM chatmessage"
  echo -n "a_flow_cnt	"; mysql_a "SELECT COUNT(*) FROM flow"
  echo -n "a_user_cnt	"; mysql_a "SELECT COUNT(*) FROM \`user\`"
} | tee "${LOG_DIR}/p5/a-baseline.tsv"

mysql_a_tsv "SELECT id,name,description,user_id,tenant_id,DATE_FORMAT(update_time,'%Y-%m-%d %H:%i:%s') AS update_time FROM knowledge WHERE type=3 ORDER BY id" \
  | tee "${LOG_DIR}/p5/a-space-meta.tsv" >/dev/null
mysql_a_tsv "SELECT f.id FROM knowledgefile f JOIN knowledge k ON f.knowledge_id=k.id WHERE k.type=3 ORDER BY f.id" \
  | tee "${LOG_DIR}/p5/a-space-file-ids.tsv" >/dev/null
mysql_a_tsv "SELECT chat_id FROM message_session" \
  | tee "${LOG_DIR}/p5/a-pre-chat-ids.tsv" >/dev/null

if [[ "${APPLY}" == "1" ]]; then
  require_a_25_for_apply
  mysql_a "INSERT INTO fusion_a_baseline (metric, value_num) SELECT 'a_space_cnt', COUNT(*) FROM knowledge WHERE type=3"
  mysql_a "INSERT INTO fusion_a_baseline (metric, value_num) SELECT 'a_space_file_cnt', COUNT(*) FROM knowledgefile f JOIN knowledge k ON f.knowledge_id=k.id WHERE k.type=3"
  mysql_a "INSERT INTO fusion_a_baseline (metric, value_num) SELECT 'a_session_cnt', COUNT(*) FROM message_session"
  mysql_a "INSERT INTO fusion_a_baseline (metric, value_num) SELECT 'a_message_cnt', COUNT(*) FROM chatmessage"
fi
ledger "${STEP}" "OK" "${LOG_DIR}/p5/a-baseline.tsv"
echo "OK ${STEP}"
