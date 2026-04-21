#!/bin/bash
# arch-guard.sh — BiSheng 架构守卫脚本
# 触发：Claude Code PostToolUse hook（同步）
# 原则：无违规时零输出，不阻塞正常开发
#
# 规则清单：
#   RULE-1: common/core 不导入 domain/api（VIOLATION）
#   RULE-2: database/models 不导入 domain（VIOLATION）
#   RULE-3: Endpoint 不直接导入 database/models（WARNING，迁移期）
#   RULE-4: domain.models 不导入 domain.services（VIOLATION）
#   RULE-5: API 层不跨模块互相导入（VIOLATION）
#   RULE-6: 前端 store 不直接调 HTTP（WARNING）
#   RULE-7: 硬编码敏感信息检测（WARNING）

FILE="$1"
[ -z "$FILE" ] && exit 0
[ ! -f "$FILE" ] && exit 0

# 领域模块列表（用于 RULE-1 检查）
DOMAIN_MODULES="knowledge|workflow|permission|linsight|llm|chat_session|tool|channel|message|user|finetune|share_link|telemetry_search|workstation|open_endpoints|mcp_manage"

# ── RULE-1：common/core 不导入 domain/api ──────────────────────────
# 基础设施层不应反向依赖领域层或 API 层
if echo "$FILE" | grep -q "/common/\|/core/"; then
    if echo "$FILE" | grep -q "\.py$"; then
        if grep -qE "^(from|import) bisheng\.(${DOMAIN_MODULES})\." "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-1 VIOLATION: $(basename "$FILE") — common/core 禁止导入领域模块"
        fi
        if grep -qE "^(from|import) bisheng\.api\.(v1|services|endpoints)" "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-1 VIOLATION: $(basename "$FILE") — common/core 禁止导入 api 层"
        fi
    fi
fi

# ── RULE-2：database/models 不导入 domain ──────────────────────────
# database/models/ 是纯 ORM 定义，不应知道任何领域逻辑
if echo "$FILE" | grep -q "/database/models/"; then
    if echo "$FILE" | grep -q "\.py$"; then
        if grep -qE "^(from|import) bisheng\.[a-z_]+\.domain\." "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-2 VIOLATION: $(basename "$FILE") — database/models 禁止导入 domain 层"
        fi
    fi
fi

# ── RULE-3：Endpoint 不直接导入 database/models ────────────────────
# 应通过 Domain Service/DAO 间接访问
# 迁移期设为 WARNING，待 DDD 迁移完成后升级为 VIOLATION
if echo "$FILE" | grep -q "/api/endpoints/\|/api/v1/"; then
    if echo "$FILE" | grep -q "\.py$"; then
        if grep -qE "^(from|import) bisheng\.database\.models\." "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-3 WARNING: $(basename "$FILE") — Endpoint 直接导入 database/models（应通过 Domain 层）"
        fi
    fi
fi

# ── RULE-4：domain.models 不导入 domain.services ───────────────────
# 防止模型层反向依赖服务层
if echo "$FILE" | grep -q "/domain/models/"; then
    if echo "$FILE" | grep -q "\.py$"; then
        if grep -qE "^(from|import) bisheng\.[a-z_]+\.domain\.services\." "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-4 VIOLATION: $(basename "$FILE") — domain.models 禁止导入 domain.services"
        fi
    fi
fi

# ── RULE-5：API 层不跨模块互相导入 ─────────────────────────────────
# 各模块的 api/ 层应独立，不导入其他模块的 api/
if echo "$FILE" | grep -q "/api/endpoints/\|/api/router.py"; then
    if echo "$FILE" | grep -q "\.py$"; then
        # 提取当前模块名：bisheng/{module}/api/...
        MODULE=$(echo "$FILE" | sed -n 's|.*bisheng/\([a-z_]*\)/api/.*|\1|p')
        if [ -n "$MODULE" ]; then
            # 检查是否导入了其他领域模块的 api 层（排除 bisheng.api. 全局路由和自身模块）
            OTHER_IMPORT=$(grep -E "^(from|import) bisheng\.[a-z_]+\.api\." "$FILE" 2>/dev/null | grep -v "bisheng\.${MODULE}\.api\." | grep -v "bisheng\.api\." | head -1)
            if [ -n "$OTHER_IMPORT" ]; then
                echo "⚠️  [arch-guard] RULE-5 VIOLATION: $(basename "$FILE") — 禁止跨模块 API 层互相导入"
            fi
        fi
    fi
fi

# ── RULE-6：前端 store 不直接调 HTTP ───────────────────────────────
# store 应通过 controllers/API 或 api/ 封装函数调用后端
if echo "$FILE" | grep -q "/store/"; then
    if echo "$FILE" | grep -qE "\.(ts|tsx)$"; then
        if grep -qE "(axios\.|fetch\(|\.get\(|\.post\(|\.put\(|\.delete\()" "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-6 WARNING: $(basename "$FILE") — store 疑似直接调用 HTTP 方法（应通过 API 封装层）"
        fi
    fi
fi

# ── RULE-7：硬编码敏感信息检测 ─────────────────────────────────────
if echo "$FILE" | grep -qE "\.(py|ts|tsx|js|json)$"; then
    # 检测 password/secret/token/api_key 赋值为字面字符串（≥8 字符）
    if grep -qE "(password|secret_key|api_key|access_token)\s*=\s*['\"][^'\"]{8,}['\"]" "$FILE" 2>/dev/null; then
        echo "⚠️  [arch-guard] RULE-7 WARNING: $(basename "$FILE") — 疑似硬编码敏感信息"
    fi
fi

exit 0
