#!/usr/bin/env bash
# type=2 → 个人知识空间。已并入 21-hop-2.4.sh; 本脚本给 2.4 schema 已完成、只补转换时用。
# 没有 type=2 则直接成功。有行时 CONFIRM_TYPE2=1 才 UPDATE。
set -euo pipefail
STEP="p2.22-type2"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${CONFIRM_TYPE2:=0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
require_complete_p2_freeze
ledger "${STEP}" "START" ""

left="$(mysql_scalar "SELECT COUNT(*) FROM knowledge WHERE type=2")"
log "当前 type=2 行数=${left}："
mysql_exec "SELECT k.id, k.name, k.user_id, (SELECT COUNT(*) FROM knowledgefile f WHERE f.knowledge_id=k.id) file_cnt FROM knowledge k WHERE k.type=2"

if [[ "${left}" == "0" ]]; then
  ledger "${STEP}" "OK" "no type=2"
  log "没有 type=2, 跳过转换。下一步 30-hop-2.5.sh"
  echo "OK ${STEP}"
  exit 0
fi

if [[ "${CONFIRM_TYPE2}" != "1" ]]; then
  ledger "${STEP}" "BLOCK" "CONFIRM_TYPE2!=1"
  die "上面是待转换的个人知识库。确认后: CONFIRM_TYPE2=1 bash p2/21-hop-2.4.sh （只补转也可: CONFIRM_TYPE2=1 bash p2/22-hop-2.4-type2.sh）"
fi

table_exists space_channel_member || die "先完成 21-hop-2.4.sh 的 schema 段"

mysql_file "$(dirname "$0")/sql/22-type2.sql"
left="$(mysql_scalar "SELECT COUNT(*) FROM knowledge WHERE type=2")"
[[ "${left}" == "0" ]] || die "仍有 type=2 行: ${left}"
ledger "${STEP}" "OK" "converted"
log "下一步 30-hop-2.5.sh"
echo "OK ${STEP}"
