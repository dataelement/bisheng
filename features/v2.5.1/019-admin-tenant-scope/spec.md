# Feature: F019-admin-tenant-scope (管理视图切换 / Admin Scope)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §5.1.5
**优先级**: P1
**所属版本**: v2.5.1
**模块编码**: 197 (`admin_scope`)
**依赖**: F013（`LoginUser.is_global_super()` 权限识别）

---

## 1. 概述与用户故事

作为 **集团 IT 的全局超管**，
我希望 **临时切换到某个 Child Tenant 的管理视角**（查看/配置该 Child 专属的 LLM 模型、角色、配额、审计日志），
以便 **跨 Child 管理时有明确的上下文，而不需要登出/重登或改动自己的用户归属**。

**背景**：v2.5.1 Tenant 树形架构下，全局超管需要跨 Child 管理资源（尤其 LLM 模型、角色、配额）。原 `POST /api/v1/user/switch-tenant` 在 2026-04-20 收窄中已废弃（返 410 Gone，理由：用户归属跟主部门派生，不应由 JWT 切换）。本 Feature 提供语义完全不同的"**管理视图切换**"机制：Redis 驻留、非 JWT、仅超管、仅对管理类 API 生效，与用户归属解耦。

**对应 2026-04-19 决策 1**。

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 全局超管 | `POST /api/v1/admin/tenant-scope` body `{tenant_id: 5}` | HTTP 200；响应含 `{scope_tenant_id: 5, expires_at: ...}`；Redis `admin_scope:{user_id} = "5"`，TTL ≈ 14400s |
| AC-02 | 全局超管（已设 scope=5） | `GET /api/v1/admin/tenant-scope` | HTTP 200；返回 `{scope_tenant_id: 5, expires_at: ...}` |
| AC-03 | 全局超管（已设 scope=5） | `POST /api/v1/admin/tenant-scope` body `{tenant_id: null}` | HTTP 200；Redis 对应 key 被 DEL；后续 `GET` 返回 `{scope_tenant_id: null, expires_at: null}` |
| AC-04 | Child Admin | `POST /api/v1/admin/tenant-scope` body `{tenant_id: 5}` | HTTP 403 + 错误码 `19701` `admin_scope_forbidden` |
| AC-05 | 普通用户（非超管非 Child Admin） | `POST /api/v1/admin/tenant-scope` | HTTP 403 + 错误码 `19701` |
| AC-06 | 全局超管（已设 scope=5） | 调用管理类 API（如 `GET /api/v1/llm`） | 返回结果按 `tenant_id IN (5, 1)` 过滤（仅 Child 5 本地 + Root 共享） |
| AC-07 | 全局超管（已设 scope=5） | 调用普通业务 API（如 `POST /api/v1/chat/...`） | **不受 scope 影响**；按 JWT leaf_tenant_id 执行 |
| AC-08 | 全局超管（已设 scope=5） | 连续 4h 内每隔 < 14400s 调用管理类 API | Redis TTL 滑动刷新；scope 不过期 |
| AC-09 | 全局超管（已设 scope=5） | 超过 14400s 未调用 | Redis 自然过期；再调管理类 API 时回退到"看全树"（可见集合 = None） |
| AC-10 | 全局超管（已设 scope=5） | 调用 `POST /api/v1/auth/logout` | AuthService 钩子 DEL Redis key；再登录后无 scope |
| AC-11 | 全局超管（已设 scope=5） | `user.token_version` +1（主部门变更触发） | 钩子 DEL Redis key（旧 JWT 已失效，scope 同步清理） |
| AC-12 | 全局超管（已设 scope=5）| 超管角色被撤销 | Role 变更钩子 DEL Redis key |
| AC-13 | 全局超管（已设 scope=5）| Child Tenant 5 被禁用/归档/删除 | Celery 每 10 分钟巡检 `admin_scope:*` 值命中非 active Tenant 的 key → DEL（频率来自 AD-07 决策折衷，非 INV-T14 硬约束；最大不一致窗口 ≤ 10 分钟） |
| AC-14 | 开发 | 每次 POST `/admin/tenant-scope` | 写 `audit_log`，action=`admin.scope_switch`，payload 含 `from_scope / to_scope / ip / user_agent / operator_id` |
| AC-15 | 全局超管 | `POST` body tenant_id 指向不存在的 Tenant | HTTP 400 + 错误码 `19702` `tenant_not_found` |
| AC-16 | 全局超管 | `POST` body tenant_id 指向 Root（tenant_id=1） | 允许；等价于"显式锁定看 Root 视图"（与不设 scope 行为差异：前者 IN 列表 = `{1}`，后者 None 见全部） |

---

## 3. 边界情况

- **普通 API 不读 Redis**：热路径零额外开销，由 `AdminScopeMiddleware` 根据 URL 白名单决定是否命中
- **管理类 API 白名单**：`/api/v1/llm`（含子路径）、`/api/v1/roles`、`/api/v1/tenants/{id}/quota`、`/api/v1/audit_log`、`/api/v1/admin/*`（后续 Feature 按需追加）
- **非超管误设 scope**：Redis key 虽写入但中间件**仅为超管读取**，避免非超管角色被提权后在 scope 下越权
- **scope 不影响 JWT**：登出、重登、`user.token_version +1` 都会清理，但 JWT 本身的签名逻辑不变
- **禁用的 Child 作为 scope**：若 Child 5 被禁用但 scope 仍未清理（Celery 巡检前），管理类 API 会查到空数据；AC-13 限制最大不一致窗口 ≤ 10 分钟
- **scope 与 switch-tenant 并存不冲突**：`POST /api/v1/user/switch-tenant` 仍 410 Gone（INV-T14 + §10.4）
- **admin-scope Redis 竞态**：TTL 临界点两个并发请求可能看到不同状态（一个读到 scope、一个读到 None）；不做跨请求事务，用户 UI 下次刷新即恢复

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 |
|----|------|------|------|
| AD-01 | 存储介质 | A: JWT / B: Redis / C: MySQL | B（Redis，不重签 JWT，不影响用户归属） |
| AD-02 | TTL 策略 | A: 固定 / B: 滑动刷新 | B（4h 滑动，用户不用频繁重设） |
| AD-03 | TTL 长度 | A: 1h / B: 4h / C: 8h | B（兼顾安全与用户体验） |
| AD-04 | scope 作用域 | A: 所有 API / B: 管理类 API 白名单 | B（避免超管 scope 错配导致业务查询混乱） |
| AD-05 | 适用角色 | A: 所有用户 / B: 全局超管 + Child Admin / C: 仅全局超管 | C（Child Admin 登录即在自己 Child，无切换需求） |
| AD-06 | 非超管调用处理 | A: 静默忽略 / B: 403 拒绝 | B（明确语义，便于前端提示）|
| AD-07 | Child 禁用后 scope 清理 | A: 实时钩子 / B: Celery 巡检 | B（避免 Tenant 禁用操作热路径多一次 Redis 扫描；10 分钟不一致窗口可接受）|

---

## 5. 核心实现

### 5.1 API 端点

```python
# src/backend/bisheng/admin/api/endpoints/tenant_scope.py

from fastapi import APIRouter, Depends, HTTPException
from bisheng.common.dependencies import UserPayload
from bisheng.common.schemas import resp_200
from bisheng.admin.domain.services.tenant_scope import TenantScopeService

router = APIRouter(prefix="/admin", tags=["admin-scope"])


@router.post("/tenant-scope")
async def set_tenant_scope(
    body: SetScopeRequest,  # {tenant_id: int | None}
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not user.is_global_super:
        raise HTTPException(status_code=403, detail={"code": 19701, "msg": "admin_scope_forbidden"})

    result = await TenantScopeService.set_scope(
        user_id=user.user_id,
        tenant_id=body.tenant_id,
        request_context=get_request_context(),  # IP, UA
    )
    return resp_200(data=result)  # {scope_tenant_id, expires_at}


@router.get("/tenant-scope")
async def get_tenant_scope(
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not user.is_global_super:
        raise HTTPException(status_code=403, detail={"code": 19701})
    return resp_200(data=await TenantScopeService.get_scope(user.user_id))
```

### 5.2 Service 层

```python
# src/backend/bisheng/admin/domain/services/tenant_scope.py

class TenantScopeService:

    REDIS_KEY_TEMPLATE = "admin_scope:{user_id}"

    @classmethod
    async def set_scope(cls, user_id: int, tenant_id: int | None, request_context: dict):
        key = cls.REDIS_KEY_TEMPLATE.format(user_id=user_id)
        old_scope = await RedisManager.get(key)
        old_scope_int = int(old_scope) if old_scope else None

        if tenant_id is None:
            await RedisManager.delete(key)
            expires_at = None
        else:
            # 校验 Tenant 存在
            if not await TenantDao.aexists(tenant_id):
                raise BusinessError(19702, "tenant_not_found")
            ttl = settings.multi_tenant.admin_scope_ttl_seconds
            await RedisManager.set(key, str(tenant_id), ex=ttl)
            expires_at = datetime.utcnow() + timedelta(seconds=ttl)

        # 写 audit_log
        await AuditLogDao.acreate(
            tenant_id=tenant_id or ROOT_TENANT_ID,
            operator_id=user_id,
            operator_tenant_id=ROOT_TENANT_ID,  # 超管 leaf_tenant_id 始终为 Root（INV-T11：Root 不可删/禁，且本实例唯一 Root）；硬编码 1 避免查库
            action="admin.scope_switch",
            metadata={
                "from_scope": old_scope_int,
                "to_scope": tenant_id,
                "ip": request_context.get("ip"),
                "user_agent": request_context.get("ua"),
            },
        )
        return {"scope_tenant_id": tenant_id, "expires_at": expires_at}

    @classmethod
    async def get_scope(cls, user_id: int) -> dict:
        key = cls.REDIS_KEY_TEMPLATE.format(user_id=user_id)
        value = await RedisManager.get(key)
        if not value:
            return {"scope_tenant_id": None, "expires_at": None}
        ttl = await RedisManager.ttl(key)
        return {
            "scope_tenant_id": int(value),
            "expires_at": datetime.utcnow() + timedelta(seconds=ttl),
        }

    @classmethod
    async def clear_on_logout(cls, user_id: int):
        """AuthService.logout 钩子调用"""
        await RedisManager.delete(cls.REDIS_KEY_TEMPLATE.format(user_id=user_id))

    @classmethod
    async def clear_on_token_version_bump(cls, user_id: int):
        """UserTenantSyncService.sync_user 主部门变更时钩子调用"""
        await RedisManager.delete(cls.REDIS_KEY_TEMPLATE.format(user_id=user_id))

    @classmethod
    async def clear_on_role_revoke(cls, user_id: int):
        """RoleService.revoke_global_super 钩子调用"""
        await RedisManager.delete(cls.REDIS_KEY_TEMPLATE.format(user_id=user_id))
```

### 5.3 中间件

```python
# src/backend/bisheng/common/middleware/admin_scope.py

MANAGEMENT_API_PREFIXES = (
    "/api/v1/llm",
    "/api/v1/roles",
    "/api/v1/audit_log",
    "/api/v1/admin",
    # /api/v1/tenants/{id}/quota 等精细路径由业务内部显式判定
)


class AdminScopeMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        is_mgmt = any(request.url.path.startswith(p) for p in MANAGEMENT_API_PREFIXES)
        _is_management_api.set(is_mgmt)

        user: UserPayload | None = request.state.user if hasattr(request.state, "user") else None
        if user and user.is_global_super and is_mgmt:
            scope = await RedisManager.get(f"admin_scope:{user.user_id}")
            if scope:
                _admin_scope_tenant_id.set(int(scope))
                # 滑动刷新
                await RedisManager.expire(
                    f"admin_scope:{user.user_id}",
                    settings.multi_tenant.admin_scope_ttl_seconds,
                )
        return await call_next(request)
```

### 5.4 Celery 巡检任务

```python
# src/backend/bisheng/worker/tenant/tasks.py

from bisheng.core.context.tenant import bypass_tenant_filter


@celery_app.task(queue="celery", name="tasks.admin_scope_cleanup")
async def admin_scope_cleanup():
    """每 10 分钟巡检，清理指向非 active Tenant 的 scope。

    **Celery 上下文注意**：本任务在 Celery worker 进程执行，**无 HTTP 请求上下文**，
    `current_tenant_id` ContextVar 为 None。必须 `with bypass_tenant_filter()` 包裹
    DAO 查询，否则 SQLAlchemy tenant_filter event 在 current_tenant_id=None 时的
    行为未定义（可能过滤为空结果或抛 TenantContextMissing）。
    """
    keys = await RedisManager.keys("admin_scope:*")

    with bypass_tenant_filter():
        non_active_ids = set(await TenantDao.aget_non_active_ids())
        # status IN (disabled, archived, orphaned)；tenant 表跨 Tenant 查询，必须 bypass

    for key in keys:
        value = await RedisManager.get(key)
        if value and int(value) in non_active_ids:
            await RedisManager.delete(key)

# beat schedule: every 10min
```

---

## 6. 配置项

```yaml
# config.yaml
multi_tenant:
  admin_scope_ttl_seconds: 14400   # 默认 4h 滑动
```

---

## 7. 测试清单（对应 AC）

| Test | AC | 类型 |
|------|----|----|
| `test_set_scope_super_admin_success` | AC-01 | API 集成测试 |
| `test_get_scope_success` | AC-02 | API 集成测试 |
| `test_clear_scope` | AC-03 | API 集成测试 |
| `test_child_admin_forbidden` | AC-04 | API 集成测试 |
| `test_normal_user_forbidden` | AC-05 | API 集成测试 |
| `test_mgmt_api_uses_scope` | AC-06 | 集成测试（结合 F020 LLM 端点） |
| `test_business_api_ignores_scope` | AC-07 | 集成测试 |
| `test_sliding_ttl` | AC-08 | 时间相关单元测试 |
| `test_ttl_expiry` | AC-09 | 时间相关单元测试 |
| `test_logout_clears_scope` | AC-10 | 钩子集成测试 |
| `test_token_version_clears_scope` | AC-11 | 钩子集成测试 |
| `test_role_revoke_clears_scope` | AC-12 | 钩子集成测试 |
| `test_celery_cleanup_non_active_tenant` | AC-13 | Celery 单元测试 |
| `test_audit_log_on_switch` | AC-14 | 集成测试 |
| `test_invalid_tenant_id` | AC-15 | API 集成测试 |
| `test_root_as_scope_locks_to_root` | AC-16 | 集成测试 |

---

## 8. 关键文件

| 类别 | 文件 | 改动 |
|------|------|------|
| API | `src/backend/bisheng/admin/api/endpoints/tenant_scope.py` | 新建；POST/GET 两个端点 |
| API 注册 | `src/backend/bisheng/admin/api/router.py` | 新建（或挂到现有 admin 路由） |
| Service | `src/backend/bisheng/admin/domain/services/tenant_scope.py` | 新建 |
| 中间件 | `src/backend/bisheng/common/middleware/admin_scope.py` | 新建 |
| 中间件注册 | `src/backend/bisheng/main.py` | 在 `TenantContextMiddleware` 之后注册 `AdminScopeMiddleware` |
| ContextVar | `src/backend/bisheng/core/context/tenant.py` | **由 F012 §5.4 负责定义** `_admin_scope_tenant_id` / `_is_management_api` 两个 ContextVar（统一在 tenant-resolver feature 集中管理）；本 Feature 中间件**消费**而非定义 |
| 钩子 | `src/backend/bisheng/user/domain/services/auth.py` | logout 钩子调 `TenantScopeService.clear_on_logout` |
| 钩子 | `src/backend/bisheng/tenant/domain/services/user_tenant_sync.py` | `sync_user` 中 `token_version` +1 后调 `clear_on_token_version_bump` |
| 钩子 | `src/backend/bisheng/permission/domain/services/role.py` | 撤销 super_admin 角色时调 `clear_on_role_revoke` |
| Celery | `src/backend/bisheng/worker/tenant/tasks.py` | 新增 `admin_scope_cleanup` 任务 |
| 配置 | `src/backend/bisheng/core/config/settings.py` | 新增 `multi_tenant.admin_scope_ttl_seconds` |
| 错误码 | `src/backend/bisheng/common/errcode/admin_scope.py` | 新建；19701 `admin_scope_forbidden` / 19702 `tenant_not_found` |
| 前端 API 封装（本 Feature） | `src/frontend/platform/src/controllers/API/admin.ts` | 新增 `setTenantScope / getTenantScope` axios 调用；本 Feature 负责，供 F020 的 `useAdminScope` hook 依赖 |
| 前端组件（F020 拥有） | `src/frontend/platform/src/components/AdminScopeSelector.tsx` | **不在本 Feature 范围**（见 §9）；本 Feature 仅声明组件存在的契约，源码由 F020 实施 |

---

## 9. 不做的事（Out of Scope）

- **前端 Scope 切换器组件本身**：由 F020 抽取为 `src/frontend/platform/src/components/AdminScopeSelector.tsx` 公共组件，供 ModelPage / 未来 RolesPage / QuotaPage / AuditLogPage 等管理页复用；本 Feature **仅提供后端 API**（POST/GET `/admin/tenant-scope`）+ `useAdminScope` hook（由 F020 编写在 `src/frontend/platform/src/hooks/useAdminScope.ts` 供复用）。**归属明确**：组件源码在 F020 分支实施；本 Feature 不包含任何 `.tsx` 代码
- Redis key 的可观测性仪表盘
- Scope 历史查询 API（audit_log 已含，MVP 不单独建表）
- 跨实例的 scope 同步（bisheng 仅私有化部署，单实例即可）
- 自动根据"用户上次操作的 Child"预置 scope（避免魔法行为）

---

## 10. 依赖清单

| 依赖 | 说明 |
|------|------|
| F011 | Tenant 树数据模型；需查询 Tenant 是否存在、status |
| F013 | `LoginUser.is_global_super()` 超管识别；Celery 巡检读取 Tenant status |
| INV-T14 | 本 Feature 落地的不变量 |

---

## 11. 相关文档

- PRD §5.1.5 管理视图切换（Admin-Scope）
- PRD §4.1 查询层自动过滤（admin-scope 覆盖规则）
- PRD 附录 B API 清单（新增 2 行）
- PRD 附录 C 决策汇总
- 技术方案 §11.2 权限检查链路 Admin-scope 扩展
- 技术方案 §11.7 关键修改文件清单（4 行新增）
- 技术方案 §11.8 新增测试用例
- release-contract INV-T14 / 模块编码 197
