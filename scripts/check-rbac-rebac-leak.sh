#!/usr/bin/env bash
# check-rbac-rebac-leak.sh — INV-T19 全仓守卫
#
# 用途：CI 步骤或 pre-commit 钩子，扫描整个后端代码库，
# 检测 DAO/Model 层是否存在直读 `RoleAccessDao.{find|judge|afind|ajudge}_role_access`
# 或 `RoleAccessDao.get_role_access(...)` 做权限过滤的漏网。
#
# arch-guard.sh 是 per-file PostToolUse 钩子（开发期同步检查）；
# 本脚本是仓库级 one-shot 扫描，覆盖未被编辑过的存量代码。
#
# 退出码：
#   0 — 无违规
#   1 — 发现违规（CI 应失败）
#
# 例外白名单参考 release-contract.md INV-T19。

set -uo pipefail

# 仓库根（脚本一般在 scripts/ 下）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="${ROOT}/src/backend/bisheng"

if [ ! -d "${BACKEND}" ]; then
    echo "ERROR: backend dir not found: ${BACKEND}" >&2
    exit 2
fi

# 违规命中模式：
#   1. RoleAccessDao.find_role_access(  / judge_role_access(  / afind_role_access(  / ajudge_role_access(
#   2. RoleAccessDao.get_role_access(  （列表型，被 flow.py 历史漏网用过）
PATTERN='RoleAccessDao\.(find|judge|afind|ajudge)_role_access\(|RoleAccessDao\.get_role_access\('

# 例外白名单（允许文件路径片段）。任何匹配以下任一片段的文件都被豁免。
ALLOWLIST=(
    'bisheng/user/domain/services/auth.py'
    'bisheng/user/api/user.py'
    'bisheng/role/domain/services/role_service.py'
    'bisheng/permission/migration/'
    'bisheng/database/models/role_access.py'
)

# 收集所有命中行（path:line:content 形式）
hits="$(grep -rnE "${PATTERN}" "${BACKEND}" --include='*.py' 2>/dev/null || true)"

if [ -z "${hits}" ]; then
    echo "[check-rbac-rebac-leak] OK — no RoleAccessDao consumer-side calls found."
    exit 0
fi

# 过滤白名单
violations=""
while IFS= read -r line; do
    [ -z "${line}" ] && continue
    file="${line%%:*}"
    skip=0
    for allow in "${ALLOWLIST[@]}"; do
        if echo "${file}" | grep -q "${allow}"; then
            skip=1
            break
        fi
    done
    if [ "${skip}" -eq 0 ]; then
        violations="${violations}${line}"$'\n'
    fi
done <<< "${hits}"

if [ -z "${violations}" ]; then
    echo "[check-rbac-rebac-leak] OK — all RoleAccessDao calls are within the INV-T19 allowlist."
    exit 0
fi

echo "❌ [check-rbac-rebac-leak] INV-T19 VIOLATION — DAO/Model 层禁止直读 RoleAccessDao 做权限过滤"
echo ""
echo "请改走 PermissionService.list_accessible_ids / PermissionService.check（参考 KnowledgeDao.ajudge_knowledge_permission / FlowDao.get_user_access_online_flows 迁移模板）。"
echo ""
echo "命中行："
printf "%s" "${violations}" | sed 's/^/  /'
exit 1
