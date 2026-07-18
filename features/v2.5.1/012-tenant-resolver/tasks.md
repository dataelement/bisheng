# Tasks: F012-tenant-resolver (叶子派生 + 归属自动维护 + JWT)

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**分支**: `feat/v2.5.1/012-tenant-resolver`（base=`2.5.0-PM`）
**前置**: F011 已合入 `2.5.0-PM`（commit `8a111ad2a`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已定稿 | 2026-04-21 Round 2 Review + 2026-04-19 深度排查 |
| tasks.md | ✅ 已拆解 | 2026-04-19 12 任务 |
| 实现 | ✅ 已完成 | 12 / 12；F012 新增 77 tests passed；F011 回归 85 passed 无损；v2.5.0 基线维持（16 pre-existing failures 无关 F012） |

---

## 开发模式

**后端 Test-Alongside（对齐 F011）**：
- ORM + DAO 扩展 + 测试合并同一任务
- Service/API 测试与实现合并
- 迁移脚本通过"手工 DDL + alembic upgrade/downgrade 往返"保证
- Redis 操作通过 `mock_redis` fixture 隔离

**决策锁定**（plan 阶段确认）：
- 错误码模块 MMM=191（spec §9 已声明）
- ContextVar 扩展 F012 一次性落地（含 F019 预留）
- `CustomMiddleware` 原地增强，**不拆新 middleware**
- `token_version` 校验走 Redis 缓存（TTL 300s）
- `sync_user` 三处调用：登录后 / 主部门变更钩子 / Celery 6h 兜底

---

## 依赖图

```
T01 (errcode + UserTenantSyncConf)
  │
  ├─→ T02 (User.token_version ORM + DAO)
  │    │
  │    └─→ T03 (Alembic 迁移)
  │
  └─→ T04 (ContextVar 扩展)
       │
       └─→ T05 (TenantResolver)
            │
            └─→ T06 (UserTenantSyncService)
                 │
                 ├─→ T07 (JWT payload + login)
                 │    │
                 │    └─→ T08 (CustomMiddleware 增强)
                 │
                 └─→ T09 (主部门变更钩子)
                      │
                      └─→ T10 (current-tenant API)
                           │
                           └─→ T11 (Celery reconcile)
                                │
                                └─→ T12 (AC 对照 + 手工 QA)
```

---

## Tasks

### 基础：errcode + 配置类

- [x] **T01**: 错误码 `tenant_resolver.py` + `UserTenantSyncConf` + Settings 注册 + CLAUDE.md 同步
  **文件（新建）**:
  - `src/backend/bisheng/common/errcode/tenant_resolver.py` — 4 个 `BaseErrorCode` 子类（19101-19104）
  - `src/backend/bisheng/core/config/user_tenant_sync.py` — Pydantic `UserTenantSyncConf(enforce_transfer_before_relocate: bool = False)`
  **文件（修改）**:
  - `src/backend/bisheng/core/config/settings.py` — 注册 `user_tenant_sync: UserTenantSyncConf`
  - `CLAUDE.md` — 错误码编码表 "MMM" 清单补 `191=tenant_resolver (F012)`
  **错误码清单**:
  ```python
  TenantRelocateBlockedError       Code=19101  # 阻断主部门变更（enforce_transfer=True）
  TenantResolveFailedError          Code=19102  # 派生失败（无主部门且无默认 Tenant）
  TokenVersionMismatchError         Code=19103  # JWT token_version 与 DB 不一致
  TenantCycleDetectedError          Code=19104  # Tenant 循环（主部门指向自身 Tenant 祖先）
  ```
  **测试**: 无（纯常量 + Pydantic 类）
  **覆盖 AC**: AC-06（19101）、§5.2 配置项
  **依赖**: 无

---

### 数据层：User.token_version

- [x] **T02**: `User` ORM 追加 `token_version` + DAO 方法 + DAO 测试
  **文件（修改）**:
  - `src/backend/bisheng/user/domain/models/user.py` — `User` 加字段 + `UserDao` 加方法
  **文件（新建）**:
  - `src/backend/test/test_user_token_version_dao.py`
  **逻辑**:
  - **`User` 字段**（追加在 `delete` 字段附近）:
    ```python
    token_version: int = Field(
        default=0,
        sa_column=Column(
            'token_version',
            Integer,
            nullable=False, server_default=text('0'),
            comment='v2.5.1 F012: JWT invalidation counter; incremented on leaf tenant change',
        ),
    )
    ```
  - **`UserDao` 新增 classmethods**:
    - `aget_token_version(user_id: int) -> int` — Redis cache first (`user:{id}:token_version` TTL 300s), fallback DB
    - `aincrement_token_version(user_id: int) -> int` — `UPDATE user SET token_version = token_version + 1 WHERE user_id = X`; DEL Redis key after commit; return new version
  **测试**（4 条）:
  - `test_token_version_default_zero` — 新建 User，token_version=0
  - `test_aincrement_token_version_atomic` — 先 0 → call 3 次 → 3
  - `test_aget_token_version_reads_from_db_when_no_cache` — mock redis 无缓存时走 DB
  - `test_aincrement_invalidates_redis_cache` — 调用后 DEL key 被调用
  **覆盖 AC**: AC-02（token_version 字段）、AC-09（中间件比对数据源）
  **依赖**: T01

---

- [x] **T03**: Alembic 迁移 + SQLite table_definitions 同步
  **文件（新建）**:
  - `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f012_user_token_version.py`
  **文件（修改）**:
  - `src/backend/test/fixtures/table_definitions.py` — `TABLE_USER` 追加 `token_version INTEGER DEFAULT 0`
  **逻辑**:
  - **revision**: `revision='f012_user_token_version', down_revision='f011_tenant_tree'`
  - **upgrade()**（参照 F011 `v2_5_1_f011_tenant_tree.py` 幂等模式）:
    ```python
    if not _column_exists('user', 'token_version'):
        op.add_column(
            'user',
            sa.Column('token_version', sa.Integer, nullable=False,
                      server_default='0',
                      comment='v2.5.1 F012: JWT invalidation counter'),
        )
    ```
  - **downgrade()**: `op.drop_column('user', 'token_version')` 包幂等 check
  - **helper**: 复用 F011 T06 新增的 `_column_exists(table, column)`（若 F011 迁移中已定义为模块级 helper；否则在本迁移内重复定义）
  **测试**: SQLite 测试（T02）绿灯即为 table_definitions 同步佐证；MySQL 手工 `alembic upgrade head` / `downgrade -1` 往返
  **覆盖 AC**: AC-02（DDL 已执行）
  **依赖**: T02

---

### ContextVar 扩展

- [x] **T04**: `core/context/tenant.py` 扩展 4 个 ContextVar + `strict_tenant_filter()` + `get_current_tenant_id()` 优先级
  **文件（修改）**:
  - `src/backend/bisheng/core/context/tenant.py`
  **文件（新建）**:
  - `src/backend/test/test_tenant_context_vars.py`
  **逻辑**（spec §5.4 签名严格对齐）:
  - 新增 ContextVars:
    ```python
    visible_tenant_ids: ContextVar[Optional[frozenset[int]]] = ContextVar('visible_tenant_ids', default=None)
    _strict_tenant_filter: ContextVar[bool] = ContextVar('_strict_tenant_filter', default=False)
    _admin_scope_tenant_id: ContextVar[Optional[int]] = ContextVar('_admin_scope_tenant_id', default=None)
    _is_management_api: ContextVar[bool] = ContextVar('_is_management_api', default=False)
    ```
  - 新增 setter/getter helper: `set_visible_tenant_ids`, `get_visible_tenant_ids`, `set_admin_scope_tenant_id`, `get_admin_scope_tenant_id`, `set_is_management_api`, `get_is_management_api`
  - 新增 `strict_tenant_filter()` context manager
  - **改写 `get_current_tenant_id()`**（签名保留）:
    ```python
    def get_current_tenant_id() -> Optional[int]:
        scope = _admin_scope_tenant_id.get()
        if scope is not None:
            return scope
        return current_tenant_id.get()
    ```
  - v2.5.0 既有 `current_tenant_id` / `set_current_tenant_id` / `_bypass_tenant_filter` / `bypass_tenant_filter` / `is_tenant_filter_bypassed` **签名完全保留**
  **测试**（8 条）:
  - `test_visible_tenant_ids_default_none`
  - `test_visible_tenant_ids_set_reset`
  - `test_strict_tenant_filter_cm_entry_exit`
  - `test_admin_scope_overrides_current_tenant_id` — set current=5 + admin_scope=7 → get returns 7
  - `test_admin_scope_none_returns_current` — set current=5 + admin_scope=None → get returns 5
  - `test_admin_scope_zero_valid` — admin_scope=0 区分于 None（但 0 非合法 tenant_id；仅验证 get 正常处理）
  - `test_v25_signatures_preserved` — `set_current_tenant_id(5)` / `bypass_tenant_filter()` 与 v2.5.0 调用一致
  - `test_is_management_api_default_false`
  **覆盖 AC**: spec §5.4（ContextVar 契约）
  **依赖**: T01

---

### 核心服务层

- [x] **T05**: `TenantResolver` 服务 + 单元测试
  **文件（新建）**:
  - `src/backend/bisheng/tenant/domain/services/tenant_resolver.py`
  - `src/backend/test/test_tenant_resolver.py`
  **逻辑**（spec §5.1 + 计划 §6.1）:
  ```python
  class TenantResolver:
      @classmethod
      async def resolve_user_leaf_tenant(cls, user_id: int) -> Tenant:
          with bypass_tenant_filter():
              primary = await UserDepartmentDao.aget_user_primary_department(user_id)
              if not primary:
                  return await TenantDao.aget_by_id(ROOT_TENANT_ID)

              dept = await DepartmentDao.aget_ancestors_with_mount(primary.department_id)
              visited = set()  # 循环保护
              while dept is not None:
                  if dept.id in visited:
                      raise TenantCycleDetectedError()
                  visited.add(dept.id)

                  tenant = await TenantDao.aget_by_id(dept.mounted_tenant_id)
                  if tenant and tenant.status == 'active':
                      return tenant
                  # 非 active → 往父部门再找
                  parent_id = _parse_parent_from_path(dept.path, dept.id)
                  if parent_id is None:
                      break
                  dept = await DepartmentDao.aget_ancestors_with_mount(parent_id)

              return await TenantDao.aget_by_id(ROOT_TENANT_ID)
  ```
  - helper `_parse_parent_from_path(path: str, current_id: int) -> Optional[int]`：从物化路径 `/1/5/12/` 解析 current 的 parent
  **测试**（7 条）:
  - `test_happy_path_mounted_child` — 部门 A 挂 Tenant 5（active），用户主部门在 A 下 → 返回 Tenant 5
  - `test_no_primary_department_returns_root` — 用户无 UserDepartment（主） → 返回 Root(1)
  - `test_skips_disabled_mounted_tenant` — A 挂 Tenant 5（disabled）、祖 B 挂 Tenant 6（active） → 返回 6
  - `test_nested_returns_nearest` — 3 层挂载 → 返回最近的那个
  - `test_root_department_no_mount_returns_root` — 主部门 path 上无挂载 → Root(1)
  - `test_cycle_detection_raises_19104` — 构造循环 path → raise `TenantCycleDetectedError`
  - `test_tenant_deleted_returns_root` — 挂载的 Tenant 记录不存在 → 退回 Root(1)
  **覆盖 AC**: AC-01（派生）、边界"Tenant 禁用"
  **依赖**: T04

---

- [x] **T06**: `UserTenantSyncService.sync_user` + 单元测试
  **文件（新建）**:
  - `src/backend/bisheng/tenant/domain/services/user_tenant_sync_service.py`
  - `src/backend/test/test_user_tenant_sync_service.py`
  **逻辑**（spec §5.2 + 计划 §3 Q4-Q6）:
  ```python
  class UserTenantSyncService:
      RESOURCE_TYPES = {'knowledge', 'flow', 'assistant', 'channel', 't_gpts_tools'}

      @classmethod
      async def sync_user(cls, user_id: int, *, trigger: str = 'manual') -> Tenant:
          """
          trigger: 'login' | 'dept_change' | 'celery_reconcile' | 'manual'
          """
          new_leaf = await TenantResolver.resolve_user_leaf_tenant(user_id)
          current = await UserTenantDao.aget_active_user_tenant(user_id)

          if current and current.tenant_id == new_leaf.id:
              return new_leaf  # 无变化

          old_tenant_id = current.tenant_id if current else None

          # 资源计数 + 阻断判定
          owned_count = 0
          if old_tenant_id:
              owned_count = await cls._count_owned_resources(user_id, old_tenant_id)

          if owned_count > 0 and settings.user_tenant_sync.enforce_transfer_before_relocate:
              await AuditLogDao.ainsert_v2(
                  tenant_id=old_tenant_id, operator_id=user_id,
                  operator_tenant_id=old_tenant_id,
                  action='user.tenant_relocate_blocked',
                  target_type='user', target_id=str(user_id),
                  metadata={'owned_count': owned_count, 'new_tenant_id': new_leaf.id, 'trigger': trigger},
              )
              raise TenantRelocateBlockedError(owned_count=owned_count)

          # 告警（有资源但不阻断）
          if owned_count > 0:
              await cls._notify_resource_owner_relocation(user_id, old_tenant_id, new_leaf.id, owned_count)

          # 归属切换
          await UserTenantDao.aactivate_user_tenant(user_id, new_leaf.id)
          await UserDao.aincrement_token_version(user_id)
          await cls._rewrite_fga_member_tuples(user_id, old_tenant_id, new_leaf.id)
          await cls._invalidate_redis_caches(user_id)

          reason = 'no_primary_department' if old_tenant_id is None and new_leaf.id == 1 else None
          await AuditLogDao.ainsert_v2(
              tenant_id=new_leaf.id, operator_id=user_id,
              operator_tenant_id=new_leaf.id,
              action='user.tenant_relocated',
              target_type='user', target_id=str(user_id),
              reason=reason,
              metadata={'old_tenant_id': old_tenant_id, 'new_tenant_id': new_leaf.id,
                        'owned_count': owned_count, 'trigger': trigger},
          )
          return new_leaf

      @classmethod
      async def _count_owned_resources(cls, user_id, tenant_id) -> int:
          """5 类表严格匹配 + bypass 自动过滤 + strict_tenant_filter 确保非 IN list"""
          total = 0
          with bypass_tenant_filter(), strict_tenant_filter():
              # select count from knowledge where user_id=X and tenant_id=Y
              # ... 5 个 table 各 count ...
          return total

      @classmethod
      async def _rewrite_fga_member_tuples(cls, user_id, old_tenant_id, new_tenant_id):
          operations = []
          if old_tenant_id and old_tenant_id != new_tenant_id:
              operations.append(TupleOperation(action='delete',
                  user=f'user:{user_id}', relation='member', object=f'tenant:{old_tenant_id}'))
          operations.append(TupleOperation(action='write',
              user=f'user:{user_id}', relation='member', object=f'tenant:{new_tenant_id}'))
          await PermissionService.batch_write_tuples(operations, crash_safe=True)

      @classmethod
      async def _invalidate_redis_caches(cls, user_id):
          redis = await get_redis_client()
          await redis.adelete(f'user:{user_id}:leaf_tenant')
          await redis.adelete(f'user:{user_id}:token_version')
          await redis.adelete(f'user:{user_id}:is_super')
  ```
  **测试**（10 条）:
  - `test_sync_no_change_returns_early`
  - `test_sync_blocked_when_owned_and_enforce_true` — 抛 19101 + audit blocked
  - `test_sync_warns_when_owned_and_enforce_false` — 继续 + audit relocated + notify called
  - `test_sync_rewrites_fga_member_tuples` — mock PermissionService 验证 delete old + write new
  - `test_sync_increments_token_version`
  - `test_sync_invalidates_redis_caches`
  - `test_sync_writes_audit_relocated` — metadata 含 old/new/owned_count/trigger
  - `test_sync_first_time_no_old_tenant` — current=None 时不 count / 不 delete FGA
  - `test_sync_fga_failure_does_not_rollback` — mock batch_write_tuples 抛 FGA error → 主事务仍成功，失败由 failed_tuples 补偿
  - `test_sync_reason_no_primary_department` — 无主部门用户 sync → audit reason=no_primary_department
  **覆盖 AC**: AC-03（no_primary_department audit）、AC-04（切换）、AC-05（告警）、AC-06（阻断）、AC-07（兼职不 sync 由 T09 入口保证）
  **依赖**: T02, T05

---

### JWT + Middleware

- [x] **T07**: JWT payload + `LoginUser` 扩展 + 登录流程调用 TenantResolver
  **文件（修改）**:
  - `src/backend/bisheng/user/domain/services/auth.py`
    - `create_access_token` 接受扩展 subject（增加 `token_version` field）
    - `login` / `sso_login`（如存在）流程：先 `TenantResolver.resolve_user_leaf_tenant(user.user_id)` 替代 `tenant_id = DEFAULT_TENANT_ID`
    - `LoginUser` BaseModel 追加 `token_version: int = 0`
  **文件（新建）**:
  - `src/backend/test/test_auth_jwt_token_version.py`
  **逻辑**:
  - 登录成功后 subject = `{'user_id': X, 'user_name': Y, 'tenant_id': leaf.id, 'token_version': user.token_version}`
  - 解码 JWT 后 `LoginUser.model_validate(payload)` 自然带回 token_version
  **测试**（4 条）:
  - `test_jwt_payload_contains_token_version` — 创建 token 后解码验证
  - `test_login_resolves_leaf_tenant` — mock TenantResolver → tenant_id 为返回的 leaf.id
  - `test_login_user_has_token_version_field` — LoginUser(token_version=5).token_version == 5
  - `test_old_token_without_token_version_defaults_zero` — 解码无 token_version 字段的旧 JWT → LoginUser.token_version == 0
  **覆盖 AC**: AC-08（payload 字段）
  **依赖**: T02, T05

---

- [x] **T08**: `CustomMiddleware` 增强：token_version 401 + `visible_tenant_ids` 计算
  **文件（修改）**:
  - `src/backend/bisheng/utils/http_middleware.py`
  **文件（新建）**:
  - `src/backend/test/test_middleware_token_version.py`
  **逻辑**（计划 §6.3 骨架）:
  - 在 `_set_tenant_context` 内或 `dispatch` 内部解码 JWT 后：
    1. 提取 `payload_token_version` + `user_id`
    2. `_validate_token_version(user_id, payload_token_version)`：调 `UserDao.aget_token_version`（内部 Redis 缓存）；不等则 `return JSONResponse(status_code=401, content={'detail': 'token_version mismatch'})`
    3. `is_super = await _check_is_global_super(user_id)`：FGA check `user:{id} super_admin system:global`，缓存 `user:{id}:is_super` TTL=300s
    4. `visible = None if is_super else (frozenset({1}) if tenant_id == 1 else frozenset({tenant_id, 1}))`
    5. `set_visible_tenant_ids(visible)`
  - 豁免路径（`TENANT_CHECK_EXEMPT_PATHS`）跳过 token_version 校验
  **测试**（6 条）:
  - `test_token_version_match_allows_request`
  - `test_token_version_mismatch_returns_401`
  - `test_no_token_path_exempt` — `/health` 等豁免路径无 401
  - `test_global_super_visible_none`
  - `test_child_user_visible_set` — tenant_id=5 → visible={5,1}
  - `test_root_user_visible_root_only` — tenant_id=1 → visible={1}
  **覆盖 AC**: AC-09（旧 JWT 拒绝）、§5.5 Middleware 语义
  **依赖**: T02, T04, T07

---

### 主部门变更钩子

- [x] **T09**: `UserDepartmentService.change_primary_department` + sync 入口 + 测试
  **文件（新建）**:
  - `src/backend/bisheng/user/domain/services/user_department_service.py`
  - `src/backend/test/test_user_department_service.py`
  **逻辑**:
  - `change_primary_department(user_id, new_dept_id, operator)`:
    1. 读当前主 dept（UserDepartmentDao.aget_user_primary_department）
    2. 若新旧相同 → 直接返回
    3. 事务内：原主 `is_primary=0`；新 dept `is_primary=1`（若不存在 user_department 记录先 insert）
    4. 调 `UserTenantSyncService.sync_user(user_id, trigger='dept_change')`
    5. 返回 `{'leaf_tenant_id': new_leaf.id, 'token_version': new_version}`
  - **兼职部门**（`is_primary=0`）变更通过其他 API，不进入此入口 → 自然不触发 sync
  **测试**（5 条）:
  - `test_change_primary_cross_tenant_triggers_sync` — mock sync_user 被调用 1 次
  - `test_change_primary_same_dept_noop` — 新旧同 → sync_user 未调
  - `test_secondary_dept_change_not_handled_here` — 调用 UserDepartmentDao.aadd_member 直接加兼职 → sync_user 未调（行为约定，非本 service 代码）
  - `test_change_primary_blocked_raises_19101` — mock sync_user raise TenantRelocateBlockedError → 事务回滚（原主 is_primary=1 保留）
  - `test_change_primary_transactional` — DB 断开 mock 测事务一致性
  **覆盖 AC**: AC-04（跨 Tenant 调岗）、AC-06（阻断）、AC-07（兼职不 sync）
  **依赖**: T06

---

### API 层

- [x] **T10**: `GET /api/v1/user/current-tenant` + F011 switch-tenant 410 回归 + 集成测试
  **文件（新建）**:
  - `src/backend/bisheng/user/api/endpoints/current_tenant.py`
  - `src/backend/test/test_current_tenant_api.py`
  **文件（修改）**:
  - `src/backend/bisheng/user/api/router.py` — 注册 current_tenant 路由
  **逻辑**:
  - `GET /api/v1/user/current-tenant`（需登录）:
    - 调 `TenantResolver.resolve_user_leaf_tenant(login_user.user_id)` → leaf Tenant
    - 若 `leaf.parent_tenant_id IS NULL`（Root） → `is_child=False, mounted_department_id=None, root_tenant_id=leaf.id`
    - 否则 → `is_child=True`; 用 `DepartmentDao.aget_by_mounted_tenant(leaf.id)` 反查挂载部门 ID；`root_tenant_id=leaf.parent_tenant_id`
    - 响应:
      ```json
      {
        "status_code": 200,
        "data": {
          "leaf_tenant_id": 5,
          "is_child": true,
          "mounted_department_id": 42,
          "root_tenant_id": 1
        }
      }
      ```
  - 若 `DepartmentDao.aget_by_mounted_tenant` 不存在（F011 T04 未提供），则新增 DAO 方法（`select(Department).where(mounted_tenant_id == X).limit(1)`）
  **测试**（4 条）:
  - `test_current_tenant_root_user` — user.tenant_id=1 → is_child=False
  - `test_current_tenant_child_user` — user.tenant_id=5 → is_child=True + mounted_department_id
  - `test_current_tenant_unauthenticated_returns_401` — 无 JWT → 401
  - `test_switch_tenant_still_returns_410` — AC-11 回归：`POST /user/switch-tenant` → 410
  **覆盖 AC**: AC-10, AC-11
  **依赖**: T05, T08

---

### Celery 兜底

- [x] **T11**: 6h reconcile Celery 任务 + beat 注册 + 测试
  **文件（新建）**:
  - `src/backend/bisheng/worker/tenant_reconcile/__init__.py`
  - `src/backend/bisheng/worker/tenant_reconcile/tasks.py`
  - `src/backend/test/test_tenant_reconcile_task.py`
  **文件（修改）**:
  - `src/backend/bisheng/core/config/settings.py` — `CeleryConf.validate` 注册任务:
    ```python
    if 'reconcile_user_tenant_assignments' not in self.beat_schedule:
        self.beat_schedule['reconcile_user_tenant_assignments'] = {
            'task': 'bisheng.worker.tenant_reconcile.tasks.reconcile_user_tenant_assignments',
            'schedule': crontab.from_string('0 */6 * * *'),  # 每 6h（00:00/06:00/12:00/18:00）
        }
    ```
  **逻辑**（计划 §3 Q8）:
  ```python
  @bisheng_celery.task(acks_late=True, time_limit=1800)
  def reconcile_user_tenant_assignments():
      loop = asyncio.new_event_loop()
      try:
          loop.run_until_complete(_reconcile_async())
      finally:
          loop.close()

  async def _reconcile_async():
      with bypass_tenant_filter():
          offset = 0
          batch = 500
          while True:
              users = await UserDao.alist_users(offset=offset, limit=batch)
              if not users:
                  break
              for u in users:
                  try:
                      await UserTenantSyncService.sync_user(u.user_id, trigger='celery_reconcile')
                  except TenantRelocateBlockedError:
                      pass  # 阻断已记 audit_log，继续下一人
                  except Exception as e:
                      logger.error(f'reconcile user {u.user_id} failed: {e}')
              offset += batch
  ```
  **测试**（3 条）:
  - `test_reconcile_scans_all_users` — 10 users 分 2 batch（batch=5）→ sync_user mock 被调 10 次
  - `test_reconcile_calls_sync_with_celery_trigger` — trigger='celery_reconcile' 参数传递
  - `test_reconcile_swallows_blocked_errors` — 第 3 人抛 19101 → 继续第 4+，总计 10 次调用
  **覆盖 AC**: §8.4 Celery 兜底清单（手工验证配合）
  **依赖**: T06

---

### 验收

- [x] **T12**: AC 对照 + spec §8 手工 QA + 本地回归
  **文件（新建）**:
  - `features/v2.5.1/012-tenant-resolver/ac-verification.md`
  **逻辑**:
  - AC→测试映射表（AC-01 ~ AC-11 共 11 条）
  - 执行 spec §8 手工 QA 清单（8.1 派生 4 条 + 8.2 主部门变更 5 条 + 8.3 JWT 4 条 + 8.4 Celery 2 条 = 15 条）
  - 回归命令:
    ```bash
    .venv/bin/pytest src/backend/test/ -q  # 全量（F011 69 + v2.5.0 401 + F012 新增 ≥ 45）
    ```
  - F012 专项:
    ```bash
    .venv/bin/pytest src/backend/test/test_user_token_version_dao.py \
                     src/backend/test/test_tenant_context_vars.py \
                     src/backend/test/test_tenant_resolver.py \
                     src/backend/test/test_user_tenant_sync_service.py \
                     src/backend/test/test_auth_jwt_token_version.py \
                     src/backend/test/test_middleware_token_version.py \
                     src/backend/test/test_user_department_service.py \
                     src/backend/test/test_current_tenant_api.py \
                     src/backend/test/test_tenant_reconcile_task.py -v
    ```
  **覆盖 AC**: 全部 AC-01 ~ AC-11
  **依赖**: T01-T11

---

## 实际偏差记录

> 详见 [ac-verification.md §"开发实际偏差"](./ac-verification.md#开发实际偏差)。

主要偏差：
- **T02 DAO-method 测试精简**：6 条 SQL 级行为测试 替代原 4 条 async+Redis mock（conftest `premock_import_chain` + SQLModel metadata 双重注册冲突不可解；DAO 方法的 Redis 缓存路径由 T06 集成调用链间接覆盖）。
- **T10 endpoint 抽离**：handler 独立到 `user/api/current_tenant.py`，原 `user.py` 仅作路由薄包装（`user.py` 导入链过重单测不可用）。
- **T11 测试 importlib 旁路**：通过 `importlib.util.spec_from_file_location` 直接加载 `tasks.py`，绕过 `bisheng.worker/__init__.py` 的 eager-import。
- **T08 Middleware 原地增强**：未拆 `TenantContextMiddleware`，直接在 `CustomMiddleware.dispatch` 内集成（plan §3 Q2 决策）。
- **T07 登录流程扩展**：`user/domain/services/user.py::user_login` 增加 `UserTenantSyncService.sync_user(trigger=LOGIN)` 并用 `UserDao.aget_token_version` 刷新版本，保证 JWT 携带最新 token_version。

---

## 工时预估

| Task | 预估 | 备注 |
|------|------|------|
| T01 | 1h | errcode + config + 文档 |
| T02 | 1.5h | ORM 字段 + 2 DAO 方法 + 4 测试（含 Redis mock） |
| T03 | 1h | Alembic + SQLite 同步 |
| T04 | 1.5h | 4 ContextVar + cm + priority + 8 测试 |
| T05 | 3h | 派生算法 + 循环保护 + 7 测试 |
| T06 | 5h | sync_user 主流程 + FGA + audit + Redis + 10 测试 |
| T07 | 2h | JWT + LoginUser + login hook + 4 测试 |
| T08 | 3h | Middleware token_version + visible + 6 测试 |
| T09 | 2h | 主部门钩子 + 事务 + 5 测试 |
| T10 | 2h | current-tenant + 410 回归 + 4 测试 |
| T11 | 2h | Celery task + beat + 3 测试 |
| T12 | 3h | AC 对照 + 手工 QA + 回归 |
| **合计** | **27h** | ~3.5 人日 |
