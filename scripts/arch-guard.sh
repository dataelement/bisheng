#!/bin/bash
# arch-guard.sh — BiSheng 架构守卫
# 无违规时零输出. RULE-1/2/4/5/8/9/10/11 命中时退出码 1.
# RULE-3/6/7 只警告, 退出码仍为 0.
# RULE-9/10/11 只看新增行: 存量 LONGTEXT / axios 一碰整文件就会误伤.
#
# 用法: bash scripts/arch-guard.sh <file> [file...]
# CI 可设 ARCH_GUARD_BASE 为对比提交, 用它和 HEAD 的新增行做 RULE-9/10/11.

# 领域模块列表 (用于 RULE-1 检查)
DOMAIN_MODULES="knowledge|workflow|permission|linsight|llm|chat_session|tool|channel|message|user|finetune|share_link|telemetry_search|workstation|open_endpoints|mcp_manage"

violation() {
    printf '%s\n' "⚠️  [arch-guard] $1"
    FILE_HAS_VIOLATION=1
}

warning() {
    printf '%s\n' "⚠️  [arch-guard] $1"
}

# 不在 git 里的文件视为全新内容. 已跟踪文件只取相对 HEAD (或 ARCH_GUARD_BASE) 的新增行.
added_lines_of() {
    local file="$1"
    local root diff_out

    if ! root=$(git -C "$(dirname "$file")" rev-parse --show-toplevel 2>/dev/null); then
        cat "$file"
        return 0
    fi
    if ! git -C "$root" ls-files --error-unmatch -- "$file" >/dev/null 2>&1; then
        cat "$file"
        return 0
    fi
    if [ -n "${ARCH_GUARD_BASE:-}" ]; then
        diff_out=$(git -C "$root" diff -U0 "${ARCH_GUARD_BASE}" HEAD -- "$file" 2>/dev/null) || true
    else
        diff_out=$(git -C "$root" diff -U0 HEAD -- "$file" 2>/dev/null) || true
    fi
    printf '%s\n' "$diff_out" | grep -E '^\+[^+]' | sed 's/^+//' || true
}

is_comment_line() {
    [[ "$1" =~ ^[[:space:]]*(#|//|\*|/\*) ]]
}

check_rule_9() {
    case "$FILE" in
        *"/src/backend/test/"*|*"dialect_helpers.py") return 0 ;;
    esac
    echo "$FILE" | grep -q '\.py$' || return 0
    local line
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        is_comment_line "$line" && continue
        if echo "$line" | grep -qE 'sqlalchemy\.JSON|mysql\.JSON\b|from sqlalchemy import [^#]*\bJSON\b|from sqlalchemy\.dialects\.mysql import [^#]*\bJSON\b|\bLONGTEXT\b|\bMEDIUMTEXT\b|information_schema|JSON_EXTRACT|JSON_CONTAINS|JSON_SEARCH'; then
            violation "RULE-9 VIOLATION: $(basename "$FILE") — 新增行使用了禁用的数据库写法。改用 dialect_helpers.JsonType / LargeText，不要写 sqlalchemy.JSON、mysql.JSON、LONGTEXT、MEDIUMTEXT、information_schema、JSON_EXTRACT、JSON_CONTAINS、JSON_SEARCH。命中: ${line}"
            return 0
        fi
    done < <(added_lines_of "$FILE")
}

check_rule_10() {
    echo "$FILE" | grep -qE '\.(ts|tsx)$' || return 0
    case "$FILE" in
        *"src/frontend/platform/src/controllers/request.ts"|*"src/frontend/client/src/api/request.ts") return 0 ;;
    esac
    local line
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        is_comment_line "$line" && continue
        echo "$line" | grep -qE '^[[:space:]]*import[[:space:]]+type[[:space:]]' && continue
        if echo "$line" | grep -qE "from[[:space:]]+['\"]axios['\"]"; then
            violation "RULE-10 VIOLATION: $(basename "$FILE") — 新增行直接 import 了 axios 包。Platform 改走 @/controllers/request，Client 改走 ~/api/request。命中: ${line}"
            return 0
        fi
    done < <(added_lines_of "$FILE")
}

check_rule_11() {
    echo "$FILE" | grep -qE '\.(ts|tsx)$' || return 0
    local other=""
    case "$FILE" in
        *"/src/frontend/platform/"*) other="src/frontend/client" ;;
        *"/src/frontend/client/"*) other="src/frontend/platform" ;;
        *) return 0 ;;
    esac
    local line
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        is_comment_line "$line" && continue
        echo "$line" | grep -qE '^[[:space:]]*(import|export)[[:space:]]' || continue
        if echo "$line" | grep -q "$other"; then
            violation "RULE-11 VIOLATION: $(basename "$FILE") — Platform 与 Client 禁止互相引用。命中: ${line}"
            return 0
        fi
    done < <(added_lines_of "$FILE")
}

check_file() {
    case "$FILE" in
        *"/node_modules/"*) return 0 ;;
    esac

    # ── RULE-1：common/core 不导入 domain/api ──────────────────────────
    if echo "$FILE" | grep -q "/common/\|/core/"; then
        if echo "$FILE" | grep -q "\.py$"; then
            if grep -qE "^(from|import) bisheng\.(${DOMAIN_MODULES})\." "$FILE" 2>/dev/null; then
                violation "RULE-1 VIOLATION: $(basename "$FILE") — common/core 禁止导入领域模块"
            fi
            if grep -qE "^(from|import) bisheng\.api\.(v1|services|endpoints)" "$FILE" 2>/dev/null; then
                violation "RULE-1 VIOLATION: $(basename "$FILE") — common/core 禁止导入 api 层"
            fi
        fi
    fi

    # ── RULE-2：database/models 不导入 domain ──────────────────────────
    if echo "$FILE" | grep -q "/database/models/"; then
        if echo "$FILE" | grep -q "\.py$"; then
            if grep -qE "^(from|import) bisheng\.[a-z_]+\.domain\." "$FILE" 2>/dev/null; then
                violation "RULE-2 VIOLATION: $(basename "$FILE") — database/models 禁止导入 domain 层"
            fi
        fi
    fi

    # ── RULE-3：Endpoint 不直接导入 database/models（WARNING）──────────
    if echo "$FILE" | grep -q "/api/endpoints/\|/api/v1/"; then
        if echo "$FILE" | grep -q "\.py$"; then
            if grep -qE "^(from|import) bisheng\.database\.models\." "$FILE" 2>/dev/null; then
                warning "RULE-3 WARNING: $(basename "$FILE") — Endpoint 直接导入 database/models（应通过 Domain 层）"
            fi
        fi
    fi

    # ── RULE-4：domain.models 不导入 domain.services ───────────────────
    if echo "$FILE" | grep -q "/domain/models/"; then
        if echo "$FILE" | grep -q "\.py$"; then
            if grep -qE "^(from|import) bisheng\.[a-z_]+\.domain\.services\." "$FILE" 2>/dev/null; then
                violation "RULE-4 VIOLATION: $(basename "$FILE") — domain.models 禁止导入 domain.services"
            fi
        fi
    fi

    # ── RULE-5：API 层不跨模块互相导入 ─────────────────────────────────
    if echo "$FILE" | grep -q "/api/endpoints/\|/api/router.py"; then
        if echo "$FILE" | grep -q "\.py$"; then
            MODULE=$(echo "$FILE" | sed -n 's|.*bisheng/\([a-z_]*\)/api/.*|\1|p')
            if [ -n "$MODULE" ]; then
                OTHER_IMPORT=$(grep -E "^(from|import) bisheng\.[a-z_]+\.api\." "$FILE" 2>/dev/null | grep -v "bisheng\.${MODULE}\.api\." | grep -v "bisheng\.api\." | head -1)
                if [ -n "$OTHER_IMPORT" ]; then
                    violation "RULE-5 VIOLATION: $(basename "$FILE") — 禁止跨模块 API 层互相导入"
                fi
            fi
        fi
    fi

    # ── RULE-6：前端 store 不直接调 HTTP（WARNING，.get( 误报高）────────
    if echo "$FILE" | grep -q "/store/"; then
        if echo "$FILE" | grep -qE "\.(ts|tsx)$"; then
            if grep -qE "(axios\.|fetch\(|\.get\(|\.post\(|\.put\(|\.delete\()" "$FILE" 2>/dev/null; then
                warning "RULE-6 WARNING: $(basename "$FILE") — store 疑似直接调用 HTTP 方法（应通过 API 封装层）"
            fi
        fi
    fi

    # ── RULE-7：硬编码敏感信息检测（WARNING）────────────────────────────
    if echo "$FILE" | grep -qE "\.(py|ts|tsx|js|json)$"; then
        if grep -qE "(password|secret_key|api_key|access_token)\s*=\s*['\"][^'\"]{8,}['\"]" "$FILE" 2>/dev/null; then
            warning "RULE-7 WARNING: $(basename "$FILE") — 疑似硬编码敏感信息"
        fi
    fi

    # ── RULE-8：DAO/Model 层不得直读 RoleAccessDao 做权限过滤 ───────────
    if echo "$FILE" | grep -q "/bisheng/" && echo "$FILE" | grep -q "\.py$"; then
        if ! echo "$FILE" | grep -qE "/(user/domain/services/auth\.py|user/api/user\.py|role/domain/services/role_service\.py|permission/migration/|database/models/role_access\.py)$"; then
            if grep -qE "RoleAccessDao\.(find|judge|afind|ajudge)_role_access\(|RoleAccessDao\.get_role_access\(" "$FILE" 2>/dev/null; then
                violation "RULE-8 VIOLATION: $(basename "$FILE") — DAO/Model 层禁止直读 RoleAccessDao 做权限过滤（INV-T19，请改走 PermissionService.list_accessible_ids/check）"
            fi
        fi
    fi

    check_rule_9
    check_rule_10
    check_rule_11
}

[ "$#" -eq 0 ] && exit 0

status=0
for FILE in "$@"; do
    [ -f "$FILE" ] || continue
    FILE_HAS_VIOLATION=0
    check_file
    if [ "$FILE_HAS_VIOLATION" -ne 0 ]; then
        status=1
    fi
done
exit "$status"
