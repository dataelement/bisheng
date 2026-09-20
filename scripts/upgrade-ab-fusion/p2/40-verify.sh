#!/usr/bin/env bash
# B 升到 2.5.0-sg 后的本机门禁验收. 不能替代页面点检, 也不是迁入 A 的 p5/40-verify.
set -euo pipefail
STEP="p2.40-verify"
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
ledger "${STEP}" "START" ""

out="${LOG_DIR}/p2-verify-$(date +%Y%m%d%H%M%S).txt"
: >"${out}"
pass_n=0
fail_n=0

emit() {
  printf '%s\n' "$*" | tee -a "${out}"
}

# ok=1 通过, 否则失败. 三项门禁都打完再决定退出码.
print_check() {
  local title="$1" what="$2" expect="$3" actual="$4" ok="$5"
  emit ""
  emit "【${title}】"
  emit "  验证内容: ${what}"
  emit "  期望:     ${expect}"
  emit "  实际:     ${actual}"
  if [[ "${ok}" == "1" ]]; then
    emit "  判定:     通过"
    pass_n=$((pass_n + 1))
  else
    emit "  判定:     失败"
    fail_n=$((fail_n + 1))
  fi
}

emit "======== B 升级验收 ========"
emit "脚本: p2/40-verify.sh"
emit "这是什么: 检查本机 B 是否已经升到 2.5.0-sg。"
emit "这不是: 迁入 A 的验收 (那个是 p5/40-verify.sh)。"
emit "日志: ${out}"

dbv="$(mysql_scalar "SELECT version_num FROM alembic_version LIMIT 1" || true)"
head="$(docker exec -e PYTHONPATH=./ -w /app "${BACKEND_CONTAINER}" \
  bash -lc 'alembic heads' 2>/dev/null | awk '/^f[0-9]|^[0-9a-f]{12}/{print $1; exit}' || true)"
if [[ -n "${head}" && "${dbv}" == "${head}" ]]; then
  print_check "1. 库版本" \
    "alembic_version 是否等于当前 backend 镜像的 alembic head" \
    "${head}" \
    "${dbv}" \
    1
else
  print_check "1. 库版本" \
    "alembic_version 是否等于当前 backend 镜像的 alembic head" \
    "${head:-读不到镜像 head}" \
    "${dbv:-空（还没有 alembic_version，多半停在 2.4）}" \
    0
fi

left="$(mysql_scalar "SELECT COUNT(*) FROM knowledge WHERE type=2" || true)"
left="${left:-?}"
if [[ "${left}" == "0" ]]; then
  print_check "2. 旧个人库 type=2" \
    "knowledge.type=2 是否已全部转成 type=3（hop 22）" \
    "剩余 0 行" \
    "剩余 ${left} 行" \
    1
else
  print_check "2. 旧个人库 type=2" \
    "knowledge.type=2 是否已全部转成 type=3（hop 22）" \
    "剩余 0 行" \
    "剩余 ${left} 行" \
    0
fi

if table_exists failed_tuple; then
  fail_sql="SELECT COUNT(*) FROM failed_tuple WHERE status NOT IN ('succeeded','success')"
  pending="$(mysql_scalar "${fail_sql}" || true)"
  pending="${pending:-?}"
  ok_sql="SELECT COUNT(*) FROM failed_tuple WHERE status IN ('succeeded','success')"
  ok_n="$(mysql_scalar "${ok_sql}" || true)"
  if [[ "${pending}" == "0" ]]; then
    print_check "3. F006 权限写入" \
      "failed_tuple 是否还有未成功行（OpenFGA 权限迁移）" \
      "未成功 0 行" \
      "未成功 ${pending} 行；已成功 ${ok_n:-?} 行" \
      1
  else
    print_check "3. F006 权限写入" \
      "failed_tuple 是否还有未成功行（OpenFGA 权限迁移）" \
      "未成功 0 行" \
      "未成功 ${pending} 行；已成功 ${ok_n:-?} 行" \
      0
  fi
else
  print_check "3. F006 权限写入" \
    "2.5 应有 failed_tuple 表" \
    "表存在" \
    "表不存在" \
    0
fi

users="$(mysql_scalar "SELECT COUNT(*) FROM \`user\`")"
flows="$(mysql_scalar "SELECT COUNT(*) FROM flow")"
knowledge="$(mysql_scalar "SELECT COUNT(*) FROM knowledge")"
files="$(mysql_scalar "SELECT COUNT(*) FROM knowledgefile")"
sessions="$(mysql_scalar "SELECT COUNT(*) FROM message_session")"
k0="$(mysql_scalar "SELECT COUNT(*) FROM knowledge WHERE type=0")"
k1="$(mysql_scalar "SELECT COUNT(*) FROM knowledge WHERE type=1")"
k3="$(mysql_scalar "SELECT COUNT(*) FROM knowledge WHERE type=3")"

emit ""
emit "【4. 业务计数】"
emit "  验证内容: 升级后还在的用户/工作流/知识库/文件/会话数量"
emit "  判定:     本项只展示，不自动判通过/失败。"
emit "            和升级前盘点对一下即可。会话在冻结后若有人登录，数量会增加。"
emit "  用户:     ${users}"
emit "  工作流:   ${flows}"
emit "  知识库:   ${knowledge}  （传统库 type=0: ${k0}；QA type=1: ${k1}；空间/个人库 type=3: ${k3}；旧个人库 type=2: ${left}）"
emit "  文件:     ${files}"
emit "  会话:     ${sessions}"

emit ""
emit "======== 结论 ========"
emit "门禁通过 ${pass_n} 项，失败 ${fail_n} 项。（门禁=上面 1～3；第 4 项不计分）"

if [[ "${fail_n}" -gt 0 ]]; then
  emit "脚本结论: 失败。不要开始迁入 A。"
  emit "FAIL ${STEP}"
  die "门禁失败 ${fail_n} 项，见 ${out}"
fi

emit "脚本结论: 通过。本机 B 已到 2.5.0-sg。"
emit "脚本不能替代的: 在 B 页面登录，打开一条原有工作流、打开一个传统知识库。"
emit "下一步: 手册第 4 章，bash full-migrate.sh（先演练，不要一上来 APPLY=1）。"
emit "OK ${STEP}"

ledger "${STEP}" "OK" "${out}"
