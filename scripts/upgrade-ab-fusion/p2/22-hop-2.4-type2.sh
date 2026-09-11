#!/usr/bin/env bash
# type=2 → 个人知识空间。默认只打印。CONFIRM_TYPE2=1 且 APPLY=1 才 UPDATE。
set -euo pipefail
STEP="p2.22-type2"
# 测试机 B 10.168.24.121。确认清单后把 CONFIRM_TYPE2 改成 1。
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${APPLY:=0}"
: "${CONFIRM_TYPE2:=0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" ""

log "当前 type=2："
mysql_exec "SELECT k.id, k.name, k.user_id, (SELECT COUNT(*) FROM knowledgefile f WHERE f.knowledge_id=k.id) file_cnt FROM knowledge k WHERE k.type=2"

if [[ "${CONFIRM_TYPE2}" != "1" ]]; then
  ledger "${STEP}" "BLOCK" "CONFIRM_TYPE2!=1"
  die "上面是待转换的个人知识库。确认无误后执行: CONFIRM_TYPE2=1 bash p2/22-hop-2.4-type2.sh"
fi

table_exists space_channel_member || die "先完成 21-hop-2.4.sh"

if require_apply; then
  mysql_file "$(dirname "$0")/sql/22-type2.sql"
  left="$(mysql_scalar "SELECT COUNT(*) FROM knowledge WHERE type=2")"
  [[ "${left}" == "0" ]] || die "仍有 type=2 行: ${left}"
  ledger "${STEP}" "OK" "converted"
else
  ledger "${STEP}" "DRY" "APPLY=0"
fi
log "下一步 30-hop-2.5.sh"
