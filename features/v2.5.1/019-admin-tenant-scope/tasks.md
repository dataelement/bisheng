# Tasks: F019-admin-tenant-scope (管理视图切换 / Admin Scope)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/019-admin-tenant-scope`（base=`2.5.0-PM`，commit `81e597690`）
**Worktree**: `/Users/lilu/Projects/bisheng-worktrees/019-admin-tenant-scope`
**前置**: F011/F012/F013 已合入 `2.5.0-PM`（F012 的 ContextVar `_admin_scope_tenant_id` / `_is_management_api` 与 getter/setter 已就位；本 Feature **消费而非定义**）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已定稿 | 2026-04-21 Round 3 深度排查通过；16 AC + 7 AD + 完整代码骨架 |
| tasks.md | ✅ 已拆解 | 2026-04-21 `/sdd-review tasks` 第 2 轮通过（修复 2 medium + 3 low） |
| 实现 | 🔲 未开始 | 0 / 13 |

---

## 开发模式

**后端 Test-Alongside（对齐 F012 / F017 模式）**：
- 基础（errcode / config / action enum）无测试配对
- Service 层：单测与实现合并同一任务（`test_xxx.py` 与实现文件同 PR）
- API / Middleware / 钩子：集成测试紧随实现
- Celery 任务用 `importlib` 旁路绕过 `bisheng.worker/__init__.py` eager-import（沿 F012 T11 范式）

**前端 Platform 手动验证**：
- 本 Feature 仅提供纯 axios 封装 `src/frontend/platform/src/controllers/API/admin.ts`
- `AdminScopeSelector.tsx` 组件 + `useAdminScope` hook **归 F020 拥有**，本 Feature 不做
- Platform 前端无 Vitest；axios 封装通过 F020 联调时回归

**自包含任务**：每个任务内联文件路径、代码片段、测试用例、依赖说明；实现阶段无需回读 spec.md。

---

## 决策锁定（plan 阶段确认）

| ID | 决策 | 结论 |
|----|------|------|
| D1 | 模块编码 | MMM=197（release-contract 表已登记）；错误码 19701 `admin_scope_forbidden` / 19702 `tenant_not_found` |
| D2 | ContextVar 归属 | F012 已定义 `_admin_scope_tenant_id` + `_is_management_api` + getter/setter，本 Feature 仅消费 |
| D3 | Redis key 格式 | `admin_scope:{user_id}`，value=`str(tenant_id)`，TTL=`settings.multi_tenant.admin_scope_ttl_seconds`（默认 14400s） |
| D4 | 管理类 API 白名单 | 代码常量 `MANAGEMENT_API_PREFIXES = ('/api/v1/llm', '/api/v1/roles', '/api/v1/audit_log', '/api/v1/admin')`；未来 Feature 追加靠 PR |
| D5 | `clear_on_role_revoke` 挂接点 | OpenFGA `system:global#super_admin` 元组删除处若未集中，**保留公开 Service 方法但挂接点标 `TODO(#F019-role-revoke)`**；不阻塞本 Feature 合并 |
| D6 | audit_log action 扩展 | 在 F011 `TenantAuditAction` 枚举增 1 行 `ADMIN_SCOPE_SWITCH = 'admin.scope_switch'`；属 F011 owner 对象的 pure-additive 扩展 |
| D7 | Celery 巡检频率 | 10 分钟（spec AD-07；不一致窗口 ≤ 10min） |
| D8 | `operator_tenant_id` 填值 | 硬编码 `ROOT_TENANT_ID=1`（INV-T11：本实例单 Root 且不可删/禁，超管 leaf 恒为 Root） |
| D9 | scope 作用域与 JWT 解耦 | admin-scope 仅影响管理类 API 的 `get_current_tenant_id()` 优先级（F012 已实现），JWT 签名/验证完全不变 |

---

## 依赖图

```
T01 (errcode 197xx) ──┐
T02 (config + action enum) ─┤
                            ├──→ T03 (admin 模块骨架)
                            │         │
                            │         └──→ T04 (TenantScopeService + 单测)  ← T01, T02
                            │                │
                            │                ├──→ T05 (POST/GET endpoints + 集成测试)
                            │                │         │
                            │                │         └──→ T06 (路由注册)
                            │                │
                            │                ├──→ T07 (AdminScopeMiddleware + 注册 + 测试)
                            │                │
                            │                ├──→ T08 (logout 钩子)
                            │                ├──→ T09 (sync_user token_version +1 钩子)
                            │                ├──→ T10 (role_revoke 钩子定位 / TODO)
                            │                │
                            │                └──→ T11 (Celery admin_scope_cleanup + beat)
                            │
                            └──→ T12 (前端 axios 封装)

T13 (AC 对照 + 本地回归) ← T01~T12
```

---

## Tasks

### 基础：errcode + config + action enum

- [ ] **T01**: 错误码 `admin_scope.py`
  **文件（新建）**:
  - `src/backend/bisheng/common/errcode/admin_scope.py`
  **逻辑**（参照 `common/errcode/tenant_resolver.py` 模式）:
  ```python
  from bisheng.common.errcode.base import BaseErrorCode

  class AdminScopeForbiddenError(BaseErrorCode):
      Code: int = 19701
      Msg: str = '仅全局超管可切换管理视图 scope'

  class AdminScopeTenantNotFoundError(BaseErrorCode):
      Code: int = 19702
      Msg: str = 'scope 指向的 Tenant 不存在'
  ```
  **测试**: 无（纯常量类；错误码返回行为由 T05 的 `test_child_admin_forbidden_19701` / `test_normal_user_forbidden_19701` / `test_invalid_tenant_id_returns_19702` 覆盖 AC-04/05/15）
  **覆盖 AC**: —（基础设施任务，AC 由 T05 测试覆盖）
  **依赖**: 无

---

- [ ] **T02**: `MultiTenantConf` 扩展 `admin_scope_ttl_seconds` + F011 `TenantAuditAction` 枚举扩展 + CLAUDE.md 同步
  **文件（修改）**:
  - `src/backend/bisheng/core/config/multi_tenant.py` — 新增字段:
    ```python
    admin_scope_ttl_seconds: int = Field(
        default=14400,
        description='v2.5.1 F019 管理视图切换 Redis TTL（秒）；默认 4h 滑动',
    )
    ```
  - `src/backend/bisheng/tenant/domain/constants.py` — `TenantAuditAction` 追加 1 行（放在 RESOURCE_SHARE_DISABLE 之后）:
    ```python
    # v2.5.1 F019 — admin tenant-scope switch (Redis)
    ADMIN_SCOPE_SWITCH = 'admin.scope_switch'
    ```
  - `CLAUDE.md` — 验证「模块编码」表已含 `197=admin_scope (F019)`（若未含则补）；无需新增章节
  **测试**: 无（Pydantic 字段 + 枚举扩展）
  **覆盖 AC**: AC-08（TTL 可配置）、AC-14（audit action 名落地）
  **依赖**: 无

---

### admin 模块骨架

- [ ] **T03**: 新建 `bisheng.admin` 模块目录与空 `__init__.py`
  **文件（新建）**:
  - `src/backend/bisheng/admin/__init__.py`（空）
  - `src/backend/bisheng/admin/api/__init__.py`（空）
  - `src/backend/bisheng/admin/api/endpoints/__init__.py`（空）
  - `src/backend/bisheng/admin/domain/__init__.py`（空）
  - `src/backend/bisheng/admin/domain/services/__init__.py`（空）
  **逻辑**: 沿 `bisheng.tenant` 模块骨架（api/ + domain/services）；不引入额外子目录（无 models/ 无 schemas/，DTO 直接内联在 endpoint）
  **测试**: 无
  **覆盖 AC**: 无（结构性任务）
  **依赖**: 无

---

### 核心 Service

- [ ] **T04**: `TenantScopeService` + 单元测试
  **文件（新建）**:
  - `src/backend/bisheng/admin/domain/services/tenant_scope.py`
  - `src/backend/test/test_admin_tenant_scope_service.py`
  **逻辑**（spec §5.2 签名严格对齐）:
  ```python
  from bisheng.core.cache.redis_manager import get_redis_client
  from bisheng.database.models.tenant import TenantDao, ROOT_TENANT_ID
  from bisheng.database.models.audit_log import AuditLogDao
  from bisheng.tenant.domain.constants import TenantAuditAction
  from bisheng.common.errcode.admin_scope import AdminScopeTenantNotFoundError
  from bisheng.core.config.settings import settings

  class TenantScopeService:
      REDIS_KEY_TEMPLATE = 'admin_scope:{user_id}'

      @classmethod
      async def set_scope(cls, user_id: int, tenant_id: int | None, request_context: dict) -> dict:
          key = cls.REDIS_KEY_TEMPLATE.format(user_id=user_id)
          redis = await get_redis_client()
          old_raw = await redis.aget(key)
          old_scope = int(old_raw) if old_raw else None

          if tenant_id is None:
              await redis.adelete(key)
              expires_at = None
          else:
              if not await TenantDao.aexists(tenant_id):
                  raise AdminScopeTenantNotFoundError.http_exception()
              ttl = settings.multi_tenant.admin_scope_ttl_seconds
              await redis.aset(key, str(tenant_id), expiration=ttl)
              expires_at = (datetime.utcnow() + timedelta(seconds=ttl)).isoformat() + 'Z'

          # audit_log（D8: operator_tenant_id 硬编码 ROOT_TENANT_ID=1）
          await AuditLogDao.ainsert_v2(
              tenant_id=tenant_id or ROOT_TENANT_ID,
              operator_id=user_id,
              operator_tenant_id=ROOT_TENANT_ID,
              action=TenantAuditAction.ADMIN_SCOPE_SWITCH.value,
              metadata={
                  'from_scope': old_scope,
                  'to_scope': tenant_id,
                  'ip': request_context.get('ip'),
                  'user_agent': request_context.get('ua'),
              },
              ip_address=request_context.get('ip'),
          )
          return {'scope_tenant_id': tenant_id, 'expires_at': expires_at}

      @classmethod
      async def get_scope(cls, user_id: int) -> dict:
          key = cls.REDIS_KEY_TEMPLATE.format(user_id=user_id)
          redis = await get_redis_client()
          raw = await redis.aget(key)
          if not raw:
              return {'scope_tenant_id': None, 'expires_at': None}
          ttl = await redis.attl(key)  # 需用 RedisClient.attl；若缺则降级用 redis.ttl 同步封装
          return {
              'scope_tenant_id': int(raw),
              'expires_at': (datetime.utcnow() + timedelta(seconds=ttl)).isoformat() + 'Z',
          }

      @classmethod
      async def clear_on_logout(cls, user_id: int) -> None:
          redis = await get_redis_client()
          await redis.adelete(cls.REDIS_KEY_TEMPLATE.format(user_id=user_id))

      @classmethod
      async def clear_on_token_version_bump(cls, user_id: int) -> None:
          """UserTenantSyncService.sync_user 中 token_version +1 后调用。"""
          await cls.clear_on_logout(user_id)

      @classmethod
      async def clear_on_role_revoke(cls, user_id: int) -> None:
          """RoleService 撤销 super_admin 时调用（T10 定位挂接点）。"""
          await cls.clear_on_logout(user_id)
  ```
  **注意**:
  - `RedisClient` 的 TTL 读方法需先核对（`redis_conn.py` 现有 `attl` / `ttl`）；若无 `attl`，用 `redis.ttl(key)` 同步方法或在 T04 补一个 helper；不要为此新建 DAO
  - `ROOT_TENANT_ID` 从 `database.models.tenant` 导入（已定义为 `1`）
  - `AuditLogDao.ainsert_v2` 已有 `metadata` 与 `ip_address` 双通道；遵循 F012 / F018 的现有调用样式

  **测试**（10 条）:
  - `test_set_scope_first_time` — 无旧值 → Redis key 写入 + audit_log from_scope=None / to_scope=5
  - `test_set_scope_override_existing` — 旧值=3 → 新值=5 → audit from_scope=3 / to_scope=5
  - `test_set_scope_clear_with_none` — body tenant_id=null → Redis DEL + audit from_scope=5 / to_scope=None
  - `test_set_scope_tenant_not_found_raises_19702` — mock `TenantDao.aexists` return False → 抛 `AdminScopeTenantNotFoundError`
  - `test_set_scope_ttl_applied` — mock redis.aset 被调且 expiration=14400
  - `test_set_scope_audit_uses_root_operator_tenant_id` — operator_tenant_id 恒为 1
  - `test_get_scope_empty` — Redis 无值 → `{scope_tenant_id: None, expires_at: None}`
  - `test_get_scope_with_value` — Redis 有值 + TTL → `scope_tenant_id=5` + `expires_at` is ISO datetime
  - `test_clear_on_logout_deletes_key`
  - `test_clear_on_token_version_bump_delegates_to_clear`
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-14, AC-15（AC-16 "Root 作为 scope" 由 T05 `test_root_as_scope_accepted` 集成测试覆盖）
  **依赖**: T01, T02

---

### API 层

- [ ] **T05**: POST/GET `/api/v1/admin/tenant-scope` endpoint + 集成测试
  **文件（新建）**:
  - `src/backend/bisheng/admin/api/endpoints/tenant_scope.py`
  - `src/backend/bisheng/admin/api/router.py`
  - `src/backend/test/test_admin_tenant_scope_api.py`
  **逻辑**（spec §5.1 严格对齐）:
  ```python
  # tenant_scope.py
  from typing import Optional
  from fastapi import APIRouter, Depends, Request
  from pydantic import BaseModel

  from bisheng.common.dependencies.user_deps import UserPayload
  from bisheng.common.schemas.api import resp_200
  from bisheng.common.errcode.admin_scope import AdminScopeForbiddenError
  from bisheng.admin.domain.services.tenant_scope import TenantScopeService

  router = APIRouter(prefix='/admin', tags=['admin-scope'])


  class SetScopeRequest(BaseModel):
      tenant_id: Optional[int] = None


  def _request_context(request: Request) -> dict:
      return {
          'ip': request.client.host if request.client else None,
          'ua': request.headers.get('user-agent'),
      }


  @router.post('/tenant-scope')
  async def set_tenant_scope(
      body: SetScopeRequest,
      request: Request,
      user: UserPayload = Depends(UserPayload.get_login_user),
  ):
      if not await user.is_global_super():
          raise AdminScopeForbiddenError.http_exception()
      result = await TenantScopeService.set_scope(
          user_id=user.user_id,
          tenant_id=body.tenant_id,
          request_context=_request_context(request),
      )
      return resp_200(data=result)


  @router.get('/tenant-scope')
  async def get_tenant_scope(
      user: UserPayload = Depends(UserPayload.get_login_user),
  ):
      if not await user.is_global_super():
          raise AdminScopeForbiddenError.http_exception()
      return resp_200(data=await TenantScopeService.get_scope(user.user_id))
  ```
  ```python
  # admin/api/router.py
  from fastapi import APIRouter
  from bisheng.admin.api.endpoints import tenant_scope

  router = APIRouter()
  router.include_router(tenant_scope.router)
  ```
  **注意**:
  - `is_global_super()` 是 LoginUser 上的 async 方法（`utils/http_middleware.py:117 _check_is_global_super` 为 FGA 调用）；调用前确认其实际签名
  - `AdminScopeForbiddenError.http_exception()` 假设 `BaseErrorCode` 提供此工厂；如无，改为 `raise HTTPException(status_code=403, detail={'code': 19701, 'msg': ...})` 或新增 helper
  - 先读 `common/errcode/base.py` 确认 `http_exception()` 存在再写 endpoint
  **测试**（6 条，用 TestClient）:
  - `test_set_scope_super_admin_success` — AC-01
  - `test_get_scope_returns_current` — AC-02
  - `test_clear_scope_via_null` — AC-03
  - `test_child_admin_forbidden_19701` — AC-04
  - `test_normal_user_forbidden_19701` — AC-05
  - `test_invalid_tenant_id_returns_19702` — AC-15
  - `test_root_as_scope_accepted` — AC-16（tenant_id=1 通过）
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-14, AC-15, AC-16
  **依赖**: T04

---

- [ ] **T06**: 全局路由注册
  **文件（修改）**:
  - `src/backend/bisheng/api/router.py` — 加 2 行:
    ```python
    from bisheng.admin.api.router import router as admin_router
    router.include_router(admin_router)
    ```
  **测试**: 在 T05 集成测试的 TestClient 中隐式覆盖（endpoint URL 可达 = 路由注册成功）
  **覆盖 AC**: 结构性任务
  **依赖**: T05

---

### 中间件

- [ ] **T07**: `AdminScopeMiddleware` + 注册 + 单元 & 集成测试
  **文件（新建）**:
  - `src/backend/bisheng/common/middleware/admin_scope.py`
  - `src/backend/test/test_admin_scope_middleware.py`
  **文件（修改）**:
  - `src/backend/bisheng/main.py` — 在 `CustomMiddleware` 之后（即第 99 行之后）注册 `AdminScopeMiddleware`
  **逻辑**（spec §5.3 严格对齐 + F012 ContextVar 消费）:
  ```python
  # common/middleware/admin_scope.py
  from starlette.middleware.base import BaseHTTPMiddleware
  from starlette.requests import Request

  from bisheng.core.cache.redis_manager import get_redis_client
  from bisheng.core.config.settings import settings
  from bisheng.core.context.tenant import (
      set_admin_scope_tenant_id,
      set_is_management_api,
  )

  MANAGEMENT_API_PREFIXES = (
      '/api/v1/llm',
      '/api/v1/roles',
      '/api/v1/audit_log',
      '/api/v1/admin',
  )


  def _is_management_api_path(path: str) -> bool:
      return any(path.startswith(p) for p in MANAGEMENT_API_PREFIXES)


  class AdminScopeMiddleware(BaseHTTPMiddleware):

      async def dispatch(self, request: Request, call_next):
          is_mgmt = _is_management_api_path(request.url.path)
          set_is_management_api(is_mgmt)

          user = getattr(request.state, 'user', None)
          if (
              is_mgmt
              and user is not None
              and hasattr(user, 'is_global_super_cached')  # CustomMiddleware 已注入
              and user.is_global_super_cached
          ):
              key = f'admin_scope:{user.user_id}'
              redis = await get_redis_client()
              raw = await redis.aget(key)
              if raw:
                  set_admin_scope_tenant_id(int(raw))
                  # 滑动刷新
                  await redis.expire_key(key, settings.multi_tenant.admin_scope_ttl_seconds)

          return await call_next(request)
  ```
  **注意**:
  - `request.state.user` 的挂载时机：`CustomMiddleware`（`utils/http_middleware.py:224-250`）在 dispatch 中设置；AdminScopeMiddleware 必须**之后**注册才能读到
  - `is_global_super_cached` 属性**若 CustomMiddleware 未缓存**，退化为 `await user.is_global_super()`（异步 FGA 查询）；T07 实施前先确认
  - ContextVar `set_is_management_api` / `set_admin_scope_tenant_id` 由 F012 导出；不要重定义
  - Starlette 中间件注册顺序：`app.add_middleware` 按"后注册先执行"入站；spec 要求 AdminScope 位于 CustomMiddleware 之后（入站更晚，出站更早）—— 即 `add_middleware(AdminScope)` 写在 `add_middleware(Custom)` **之前**
  **测试**（7 条）:
  - `test_middleware_no_scope_on_non_mgmt_path` — path=`/api/v1/chat/xxx` → admin_scope ContextVar=None
  - `test_middleware_reads_scope_for_super_admin_on_mgmt_path` — path=`/api/v1/llm`, Redis=5 → ContextVar=5
  - `test_middleware_skips_non_super_admin` — Redis=5, user 非超管 → ContextVar=None（防被提权后滥用）
  - `test_middleware_refreshes_ttl_on_hit` — mock redis.expire_key 被调用 1 次
  - `test_middleware_no_redis_entry_leaves_context_none` — Redis 无值（key 从未存在 **或** TTL 自然过期后 GET 返 None 语义等价）→ ContextVar=None；**同时覆盖 AC-09**（过期后回退"看全树" = ContextVar=None）
  - `test_middleware_sets_is_management_api_true_false`
  - `test_middleware_business_api_ignores_scope_even_for_super_admin` — AC-07：`/api/v1/chat` + Redis=5 + 超管 → ContextVar=None（因 is_mgmt=False）
  **覆盖 AC**: AC-06, AC-07, AC-08, AC-09
  **依赖**: T04

---

### 钩子接入

- [ ] **T08**: logout 钩子接入 `clear_on_logout`
  **文件（修改）**:
  - `src/backend/bisheng/user/api/user.py:156-159` — `logout` endpoint
  **逻辑**:
  ```python
  @router.post('/user/logout', status_code=201)
  async def logout(
      auth_jwt: AuthJwt = Depends(),
      user: UserPayload = Depends(UserPayload.get_login_user_optional),  # optional 若已失效
  ):
      if user:
          from bisheng.admin.domain.services.tenant_scope import TenantScopeService
          await TenantScopeService.clear_on_logout(user.user_id)
      auth_jwt.unset_access_token()
      return resp_200()
  ```
  **注意**:
  - `get_login_user_optional` 依赖若不存在，用 try/except 包 `get_login_user` 调用或读 JWT raw payload
  - import 放在函数内以避免 `user` 模块顶层反向依赖 `admin` 模块（模块层架构守卫）
  **测试**（2 条）:
  - `test_logout_clears_admin_scope` — 超管已设 scope=5 → POST logout → Redis key DEL
  - `test_logout_no_scope_noop` — 无 scope → logout 正常返回
  **覆盖 AC**: AC-10
  **依赖**: T04

---

- [ ] **T09**: `UserTenantSyncService.sync_user` token_version+1 后清理 scope
  **文件（修改）**:
  - `src/backend/bisheng/tenant/domain/services/user_tenant_sync_service.py` —— 在 `_invalidate_redis_caches()` 或 token_version +1 的事务提交点**之后**加一行:
    ```python
    from bisheng.admin.domain.services.tenant_scope import TenantScopeService
    await TenantScopeService.clear_on_token_version_bump(user_id)
    ```
  **注意**:
  - 当前文件行号为 `~120`（plan 探索确认），具体插入点以"token_version 提交后 + `_invalidate_redis_caches` 附近"为准
  - 同样用函数内 import 避免 `tenant` 模块顶层依赖 `admin`
  **测试**（2 条）:
  - `test_sync_user_cross_tenant_clears_scope` — mock TenantScopeService.clear_on_token_version_bump 被调 1 次
  - `test_sync_user_same_tenant_no_scope_clear` — 无 token_version 变更 → 未调
  **覆盖 AC**: AC-11
  **依赖**: T04

---

- [ ] **T10**: `clear_on_role_revoke` 挂接点定位 + 最佳努力接入
  **文件（调研）**:
  - 搜 `src/backend/bisheng/permission/` 以下模式:
    - `super_admin` write/delete
    - `system:global` tuple write/delete
    - `FGAClient.write` / `FGAClient.delete`
  **文件（可能修改）**:
  - 定位到的 RoleService / PermissionService / FGA adapter 方法
  **逻辑**:
  1. 若找到集中的 `revoke_super_admin(user_id)` 方法 → 在其事务提交后加 `await TenantScopeService.clear_on_role_revoke(user_id)`
  2. 若分散在多处 `FGAClient.delete(...)` 调用 → **不内联调用**，改为在本任务写一份 `docs/F019-role-revoke-hook.md` 说明挂接点清单 + `TODO(#F019-role-revoke)` 注释；`TenantScopeService.clear_on_role_revoke` 公开方法保留供未来集中化后接入
  3. 无论走 1 还是 2，**`clear_on_role_revoke` 方法本身 + 单元测试已在 T04 实现**，本任务只做挂接
  **测试**（按落地方案调整）:
  - 方案 1：`test_revoke_super_admin_clears_scope` — mock clear_on_role_revoke 被调用
  - 方案 2：仅写调研笔记 + 确保 T04 的 `test_clear_on_role_revoke_deletes_key` 覆盖方法本体
  **覆盖 AC**:
  - 方案 1 → AC-12（完整覆盖：方法本体 + 钩子挂接）
  - 方案 2 → AC-12 **部分覆盖**（仅方法本体；挂接点落到文档 TODO 移交至未来集中化 RoleService 落地时挂钩）；D5 决策已锁定方案 2 可接受
  **依赖**: T04
  **验收门槛**: 方案 2 合并前需用户确认"AC-12 钩子挂接延迟 + 文档化 TODO"可接受

---

### Celery 巡检

- [ ] **T11**: `admin_scope_cleanup` Celery 任务 + beat 注册 + 测试
  **租户上下文**: **跨租户巡检任务**（扫全部 `admin_scope:*`，不走 tenant_id → ContextVar 注入路径）；Celery headers 不携带 tenant_id，进程内 `current_tenant_id` ContextVar 为 None；对 `TenantDao.aget_non_active_ids()` 的跨 Tenant 查询必须用 `bypass_tenant_filter()` 包裹（spec §5.4 AD-07）
  **文件（新建）**:
  - `src/backend/bisheng/worker/admin_scope/__init__.py`
  - `src/backend/bisheng/worker/admin_scope/tasks.py`
  - `src/backend/test/test_admin_scope_cleanup_task.py`
  **文件（修改）**:
  - `src/backend/bisheng/core/config/settings.py` — `CeleryConf.validate` 注册:
    ```python
    if 'admin_scope_cleanup' not in self.beat_schedule:
        self.beat_schedule['admin_scope_cleanup'] = {
            'task': 'bisheng.worker.admin_scope.tasks.admin_scope_cleanup',
            'schedule': crontab.from_string('*/10 * * * *'),  # 每 10 分钟
        }
    ```
  **逻辑**（spec §5.4 严格对齐 + `bypass_tenant_filter` 必须包裹）:
  ```python
  import asyncio
  from bisheng.worker.celery_app import bisheng_celery
  from bisheng.core.cache.redis_manager import get_redis_client
  from bisheng.core.context.tenant import bypass_tenant_filter
  from bisheng.database.models.tenant import TenantDao

  @bisheng_celery.task(acks_late=True, time_limit=600, name='bisheng.worker.admin_scope.tasks.admin_scope_cleanup')
  def admin_scope_cleanup():
      loop = asyncio.new_event_loop()
      try:
          loop.run_until_complete(_cleanup_async())
      finally:
          loop.close()

  async def _cleanup_async():
      redis = await get_redis_client()
      keys = await redis.akeys('admin_scope:*')
      if not keys:
          return

      with bypass_tenant_filter():  # Celery 无 request context，ContextVar=None，必须 bypass
          non_active = set(await TenantDao.aget_non_active_ids())

      for key in keys:
          raw = await redis.aget(key)
          if raw and int(raw) in non_active:
              await redis.adelete(key)
  ```
  **注意**:
  - 任务注册的 `name=` 必须与 beat_schedule 的 `task` 字符串一致
  - 测试用 `importlib.util.spec_from_file_location` 直接加载 `tasks.py`，绕过 `bisheng.worker/__init__.py` eager-import（沿 F012 T11 范式）
  **测试**（4 条）:
  - `test_cleanup_removes_non_active_scopes` — Redis: `admin_scope:1=5, admin_scope:2=6, admin_scope:3=7`；TenantDao 返 `[5, 7]` → key 1 + 3 被 DEL，key 2 保留
  - `test_cleanup_noop_when_no_keys` — akeys 返 [] → 未调 aget_non_active_ids（fast-path）
  - `test_cleanup_noop_when_all_active` — 全 active → 无 DEL
  - `test_cleanup_uses_bypass_tenant_filter` — mock bypass_tenant_filter 进出
  **覆盖 AC**: AC-13
  **依赖**: T04

---

### 前端

- [ ] **T12**: 前端 axios 封装 `admin.ts`
  **文件（新建）**:
  - `src/frontend/platform/src/controllers/API/admin.ts`
  **逻辑**:
  ```typescript
  import axios from '@/controllers/request'

  export interface AdminScopeResponse {
    scope_tenant_id: number | null
    expires_at: string | null
  }

  export async function setTenantScope(tenantId: number | null): Promise<AdminScopeResponse> {
    return await axios.post('/api/v1/admin/tenant-scope', { tenant_id: tenantId })
  }

  export async function getTenantScope(): Promise<AdminScopeResponse> {
    return await axios.get('/api/v1/admin/tenant-scope')
  }
  ```
  **手动验证**（本 Feature 阶段无 UI；F020 联调时补）:
  - F020 `useAdminScope` hook 预期 import `setTenantScope` / `getTenantScope` 且返回类型匹配
  - 本 Feature 合入后触发 Platform dev server `npm start`，浏览器 devtools 手动调用 `await (await import('/src/controllers/API/admin.ts')).getTenantScope()` 返 200
  **覆盖 AC**: 无（spec §9 明确：前端组件归 F020）
  **依赖**: T05

---

### 验收

- [ ] **T13**: AC 对照 + 本地回归 + 手工 QA
  **文件（新建）**:
  - `features/v2.5.1/019-admin-tenant-scope/ac-verification.md`
  **逻辑**:
  - AC → 测试映射表（AC-01 ~ AC-16 共 16 条）
  - 执行 spec §7 测试清单（16 项全覆盖）
  - F019 专项回归:
    ```bash
    cd src/backend
    .venv/bin/pytest test/test_admin_tenant_scope_service.py \
                     test/test_admin_tenant_scope_api.py \
                     test/test_admin_scope_middleware.py \
                     test/test_admin_scope_cleanup_task.py \
                     -v
    ```
  - 全量回归:
    ```bash
    .venv/bin/pytest src/backend/test/ -q
    ```
  - 手工 QA（114 服务器）:
    1. 超管登录 → `POST /api/v1/admin/tenant-scope {tenant_id: 5}` → 200
    2. `GET /api/v1/admin/tenant-scope` → `scope_tenant_id=5, expires_at=ISO`
    3. `GET /api/v1/llm` → 结果仅含 Child 5 本地 + Root 共享（需 F020 联调）
    4. `POST /api/v1/chat/...` → 不受 scope 影响
    5. `POST /api/v1/admin/tenant-scope {tenant_id: null}` → Redis DEL
    6. Child Admin → POST → 403 + 19701
    7. 检查 `audit_log` 表 `action='admin.scope_switch'` 记录正确
  **覆盖 AC**: 全部 AC-01 ~ AC-16
  **依赖**: T01 ~ T12

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- _待填_

---

## 工时预估

| Task | 预估 | 备注 |
|------|------|------|
| T01 | 0.5h | errcode 2 类 |
| T02 | 0.5h | 配置字段 + 枚举扩展 + CLAUDE.md |
| T03 | 0.2h | 空 `__init__.py` × 5 |
| T04 | 3h | Service 实现 + 10 测试（含 Redis mock） |
| T05 | 2.5h | 2 endpoints + 7 集成测试（TestClient + 超管/Child Admin fixture） |
| T06 | 0.2h | 路由注册 |
| T07 | 3h | Middleware + 注册顺序验证 + 7 测试 |
| T08 | 1h | logout 钩子 + 2 测试 |
| T09 | 1h | sync_user 挂钩 + 2 测试 |
| T10 | 1~3h | 视挂接点定位难度（方案 1 实挂 ~3h / 方案 2 文档化 ~1h） |
| T11 | 2h | Celery task + beat + 4 测试（importlib 旁路） |
| T12 | 0.5h | 2 个 axios 函数 |
| T13 | 2h | ac-verification.md + 本地回归 + 手工 QA |
| **合计** | **17~19h** | 约 2~2.5 工作日 |

---

## 变更历史

| 日期 | 变更 |
|------|------|
| 2026-04-21 | 初始化 tasks.md；13 任务；决策锁定 D1~D9；依赖图 |
