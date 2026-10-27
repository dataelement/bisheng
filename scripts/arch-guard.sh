#!/bin/bash
# arch-guard.sh — BiSheng 架构守卫脚本
# 触发：Claude Code PostToolUse hook（同步）
# 原则：无违规时零输出，不阻塞正常开发
#
# 规则清单（每条对应 docs/constitution.md 的条款 Cx — 改 RULE 须同步宪法）：
#   RULE-1: common/core 不导入 domain/api（C1，VIOLATION）
#   RULE-2: database/models 不导入 domain（C1，VIOLATION）
#   RULE-3: Endpoint 不直接导入 database/models（C1，WARNING，迁移期）
#   RULE-4: domain.models 不导入 domain.services（C1，VIOLATION）
#   RULE-5: API 层不跨模块互相导入（C1，VIOLATION）
#   RULE-6: 前端 store 不直接调 HTTP（C7，WARNING）
#   RULE-7: 硬编码敏感信息检测（C6，WARNING）
#   RULE-8: DAO/Model 层不得直读 RoleAccessDao 做权限过滤（C4，INV-T19，VIOLATION）
#   RULE-9: 业务模块不得导入 OpenFGA 基础设施（C4，VIOLATION）
#   RULE-10: backend 不得依赖容器/编排 SDK 与 docker socket（C1/K1，VIOLATION）

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

# ── RULE-8：DAO/Model 层不得直读 RoleAccessDao 做权限过滤（INV-T19）──
# F008 已把 5 对 10 类资源 AccessType 迁到 ReBAC（PermissionService）。
# 资源消费侧若想"按用户过滤可见 ID"，必须经 PermissionService 委托。
# 直接调 RoleAccessDao.{find,judge,afind,ajudge}_role_access 或
# RoleAccessDao.get_role_access(*, AccessType.X) 视为漏网。
#
# 例外白名单（允许文件路径）：
#   - bisheng/user/domain/services/auth.py     LoginUser legacy fallback
#   - bisheng/user/api/user.py                 /role_access CRUD 端点
#   - bisheng/role/domain/services/role_service.py  WEB_MENU 读取
#   - bisheng/permission/migration/            F006 迁移工具
#   - bisheng/database/models/role_access.py   DAO 自身定义
if echo "$FILE" | grep -q "/bisheng/" && echo "$FILE" | grep -q "\.py$"; then
    if ! echo "$FILE" | grep -qE "/(user/domain/services/auth\.py|user/api/user\.py|role/domain/services/role_service\.py|permission/migration/|database/models/role_access\.py)$"; then
        if grep -qE "RoleAccessDao\.(find|judge|afind|ajudge)_role_access\(|RoleAccessDao\.get_role_access\(" "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-8 VIOLATION: $(basename "$FILE") — DAO/Model 层禁止直读 RoleAccessDao 做权限过滤（INV-T19，请改走 permission.application 协议）"
        fi
    fi
fi

# ── RULE-9：业务模块不得感知 OpenFGA 基础设施（C4）───────────────
# OpenFGA client/manager/tuple APIs 只允许由 core/openfga 和 permission
# 模块使用；其他模块必须依赖 permission.application 暴露的应用协议。
if echo "$FILE" | grep -q "/bisheng/" && echo "$FILE" | grep -q "\.py$"; then
    if ! echo "$FILE" | grep -qE "/bisheng/(core/openfga|core/context/manager\.py|permission/).*\.py$"; then
        if grep -qE "^(from|import) bisheng\.core\.openfga" "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-9 VIOLATION: $(basename "$FILE") — 业务模块禁止依赖 OpenFGA 基础设施（请改走 permission.application 协议）"
        fi
        if grep -qE "bisheng\.permission\.domain\.schemas\.tuple_operation|PermissionService\.batch_write_tuples\(" "$FILE" 2>/dev/null; then
            echo "⚠️  [arch-guard] RULE-9 VIOLATION: $(basename "$FILE") — 业务模块禁止构造或写入 transport tuple（请使用 PermissionRelationChange/apply_changes）"
        fi
    fi
fi

# ── RULE-10：backend 禁编排依赖（F054 K1）─────────────────────────
# 「安全来自笼子」的前提是 backend 自己不在笼子外面：它编译期与运行期都不得
# 持有容器编排后端的访问面——不 import docker/kubernetes 客户端、不出现
# /var/run/docker.sock 字面量、不读 DOCKER_HOST。编排一律经 runtime-manager
# （独立包、独立进程、意图式 HTTP RPC）下发期望态。
#
# 只扫 src/backend/bisheng/** 的 .py：
#   - .drone.yml 挂 docker.sock 是 CI 的正当用法（全仓唯一出现处），扫进来
#     就是假阳性，而假阳性最终会让人把整条规则关掉；
#   - src/runtime-manager/ 是唯一被允许持有该访问面的地方，它不在此路径下。
# ⚠️ 路径前缀不带前导 `/`：hook 传的是绝对路径，但 CI / 手工以相对路径调用同样要生效。
# 写成 "/src/backend/bisheng/" 会让相对路径静默不匹配 —— 守卫看着在跑、实则不设防
# （SDD-Guide §0 记载过同类失效：永远验证"是否真的在拦"，而不是"应该在拦"）。
if echo "$FILE" | grep -q "src/backend/bisheng/" && echo "$FILE" | grep -q "\.py$"; then
    if grep -qE "^[[:space:]]*(from|import)[[:space:]]+(docker|aiodocker|kubernetes|kubernetes_asyncio)\b" "$FILE" 2>/dev/null; then
        echo "⚠️  [arch-guard] RULE-10 VIOLATION: $(basename "$FILE") — backend 禁止导入容器/编排 SDK（docker/kubernetes），编排请经 runtime-manager 的意图 RPC"
    fi
    if grep -q "/var/run/docker.sock" "$FILE" 2>/dev/null; then
        echo "⚠️  [arch-guard] RULE-10 VIOLATION: $(basename "$FILE") — backend 禁止出现 docker socket 路径（编排特权只属于 runtime-manager）"
    fi
    if grep -qE "\bDOCKER_HOST\b" "$FILE" 2>/dev/null; then
        echo "⚠️  [arch-guard] RULE-10 VIOLATION: $(basename "$FILE") — backend 禁止读取 DOCKER_HOST（编排特权只属于 runtime-manager）"
    fi
fi

exit 0
