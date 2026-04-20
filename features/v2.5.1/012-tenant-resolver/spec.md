# Feature: F012-tenant-resolver (叶子派生 + 归属自动维护 + JWT)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §5.6
**优先级**: P0
**所属版本**: v2.5.1

---

## 1. 概述与用户故事

作为 **集团用户**，
我希望 **登录后系统自动按我的主部门派生叶子 Tenant，不需要手工选择"进入哪个租户"**，
以便 **主部门变更时（调岗）归属自动跟随，兼职不改变归属**。

核心能力：
- `TenantResolver.resolve_user_leaf_tenant(user_id)`：沿部门 path 反向找最近挂载点 → 取其 Child Tenant；无挂载点 → 回到 Root
- `UserTenantSyncService.sync_user(user_id)`：主部门变更时更新 `UserTenant` 快照、FGA 元组、JWT token_version
- JWT payload 扩展：含 `tenant_id`（叶子）+ `token_version`（2026-04-20 简化：去 tenant_path，2 层下可见集合直接由 tenant_id 与 Root id=1 推导）
- `user.token_version` 字段新增（DDL 在本 Feature 落地）
- 主部门变更时**告警且不迁移资源**（PRD Review P0-C）

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 集团用户 | SSO 首次登录 | 沿主部门 path 反向查找 `is_tenant_root=true` 的最近部门，派生 Child Tenant；若无 → Root（id=1） |
| AC-02 | 开发 | 部署本 feature 后 | `user` 表含 `token_version INT NOT NULL DEFAULT 0` 字段（DDL 已执行） |
| AC-03 | 开发 | 用户无主部门 | 默认归属 tenant_id=1（Root） + 告警 audit_log（action=`user.tenant_relocated`，metadata=`{reason: 'no_primary_department'}`；见 F011 §5.4.2） |
| AC-04 | 集团用户 | 主部门从集团→子公司 X | `user_tenant` 旧 active 置为 inactive，写入新 tenant_id；Redis 缓存失效；`user.token_version +1` |
| AC-05 | 集团用户 | 主部门变更且名下有资源 > 0 | audit_log 记录 + 站内消息 + 邮件告警给原/新 Tenant Child Admin（或全局超管） |
| AC-06 | 集团用户 | 开启 `user_tenant_sync.enforce_transfer_before_relocate=true`（config key 路径）主部门变更 | HTTP 409 `19101` 阻断；要求先交接资源 |
| AC-07 | 集团用户 | 兼职部门增加 | 不触发 UserTenantSync（不改归属） |
| AC-08 | 开发 | JWT payload 检查 | 含 `tenant_id`（叶子）+ `token_version` 两个新字段（不含 tenant_path） |
| AC-09 | 业务用户 | 归属切换后用旧 JWT 请求 | 中间件比对 `payload.token_version != user.token_version` → 返回 401，强制重新登录 |
| AC-10 | 运维 | 查询 `GET /api/v1/user/current-tenant` | 返回 `{leaf_tenant_id, is_child, mounted_department_id, root_tenant_id}` |
| AC-11 | 开发 | `POST /api/v1/user/switch-tenant` 请求 | HTTP 410 Gone；响应体说明"用户无切换概念，归属由主部门自动派生（见 §5.6）" |

---

## 3. 边界情况

- **主部门被删除**：该用户进入 `pending_relocation` 状态，下次登录时重新派生
- **部门挂载点变更**：子树下所有用户需重新派生叶子；通过 Celery 异步批量处理
- **Tenant 禁用**：派生算法跳过 disabled Tenant，继续向上找
- **并发主部门变更**：使用 `FOR UPDATE` 锁 + 乐观锁 token_version
- **不支持**：
  - 单用户多叶子 Tenant（仅私有化单实例，2026-04-20 收窄）
  - 用户手工选择归属（违反唯一叶子原则）
  - SaaS 多客户 Gateway 路由（仅私有化）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 派生触发点 | A: 登录时 / B: 主部门变更钩子 / C: Celery 定时 | **三者并用** | 登录做源头拦截；钩子做实时；Celery 做兜底 |
| AD-02 | JWT 失效策略 | A: 主动吊销列表 / B: token_version 单调递增 | 选 B | 简化实现；无需维护吊销列表 |
| AD-03 | 告警 vs 阻断 | A: 仅告警 / B: 默认阻断 / C: 配置项 | 选 C | MVP 默认告警；客户可按需阻断 |
| AD-04 | 资源是否随人迁 | A: 自动迁移 / B: 留原处 | 选 B | PRD Review P0-C；避免带走集团核心资源 |

---

## 5. 核心服务设计

### 5.1 TenantResolver

```python
class TenantResolver:
    @classmethod
    async def resolve_user_leaf_tenant(cls, user_id: int) -> Tenant:
        """沿主部门 path 反向找最近挂载点"""
        primary_dept = await UserDepartmentDao.aget_primary(user_id)
        if not primary_dept:
            return await TenantDao.aget(DEFAULT_TENANT_ID)

        # 沿 path 反向查 is_tenant_root=true 的部门
        ancestors = _parse_path(primary_dept.path)  # [1, 5, 12]
        for dept_id in reversed(ancestors):
            dept = await DepartmentDao.aget(dept_id)
            if dept.is_tenant_root and dept.mounted_tenant_id:
                return await TenantDao.aget(dept.mounted_tenant_id)

        return await TenantDao.aget(1)  # 无挂载点 → 回 Root（硬编码 tenant_id=1，仅私有化单实例；PRD §1.5 收窄）
```

### 5.2 UserTenantSyncService

见《2.5 技术方案.md》§11.5 的 `sync_user` 实现。

**阻断逻辑伪代码**（2026-04-21 明确 config key 路径）：

```python
class UserTenantSyncService:
    @classmethod
    async def sync_user(cls, user_id: int) -> None:
        new_leaf = await TenantResolver.resolve_user_leaf_tenant(user_id)
        current_active = await UserTenantDao.aget_active(user_id)

        if current_active and current_active.tenant_id == new_leaf.id:
            return  # 无变化

        # 2026-04-21：阻断判断 —— config key 路径明确为 user_tenant_sync.enforce_transfer_before_relocate
        if settings.user_tenant_sync.enforce_transfer_before_relocate:
            owned_count = await ResourceDao.acount_owned_by_user(user_id, tenant_id=current_active.tenant_id)
            if owned_count > 0:
                # 写入 audit_log.action = 'user.tenant_relocate_blocked'
                await AuditLogDao.acreate(..., action='user.tenant_relocate_blocked')
                raise RelocateBlockedError(code=19101, owned_count=owned_count)

        # 告警但不阻断（默认行为）
        if owned_count > 0:
            await NotificationService.notify_admins(...)
            await AuditLogDao.acreate(..., action='user.tenant_relocated')

        # 正常切换归属
        await UserTenantDao.aupsert_active(user_id, new_leaf.id)
        await UserDao.aincrement_token_version(user_id)
        await fga.replace_member_tuple(user_id, from_tenant=current_active.tenant_id, to_tenant=new_leaf.id)
        await redis.delete(f'user:{user_id}:leaf_tenant')
```

**配置示例**（`src/backend/bisheng/config.yaml`）：

```yaml
user_tenant_sync:
  enforce_transfer_before_relocate: false   # 默认 false=仅 audit_log 告警 + 站内消息，不阻断
                                            # 合规客户可改 true：用户名下有资源时主部门变更返 409+19101
```

### 5.3 JWT Payload

```python
class JWTPayload:
    user_id: int
    user_name: str
    tenant_id: int          # 叶子 Tenant ID（Root=1 或 Child=N）
    token_version: int      # 主部门变更时 +1，强制旧 JWT 失效
    exp: int
```

**说明**（2026-04-20 简化）：去掉 `tenant_path` 字段——MVP 锁 2 层下，可见集合 `{leaf, Root=1}` 直接由 `tenant_id` 推导，无需 payload 承载物化路径。

### 5.4 ContextVar 扩展与 get_current_tenant_id() 优先级

**背景**：v2.5.0/F001 已在 `src/backend/bisheng/core/context/tenant.py` 定义 `current_tenant_id` ContextVar + `get_current_tenant_id()` getter + `bypass_tenant_filter()` context manager。v2.5.1 在此基础上扩展 4 个新 ContextVar 以支撑 IN 列表过滤、严格匹配、admin-scope、管理类 API 标识：

```python
# src/backend/bisheng/core/context/tenant.py（本 Feature 扩展）

from contextlib import contextmanager
from contextvars import ContextVar

# v2.5.0 既有
# current_tenant_id: ContextVar[Optional[int]]
# _bypass_tenant_filter: ContextVar[bool]

# v2.5.1 新增（本 Feature 负责定义 + tenant_filter.py event listener 消费）
visible_tenant_ids: ContextVar[Optional[frozenset[int]]] = ContextVar(
    'visible_tenant_ids', default=None,
)
"""由 TenantContextMiddleware 计算并设置；IN 列表过滤事件消费。
2 层下典型值：
  Root 用户:        frozenset({1})
  Child 5 用户:     frozenset({5, 1})（叶子 + Root）
  全局超管无 scope: None（event listener 不注入过滤）
  全局超管 scope=5: frozenset({5, 1})
"""

_strict_tenant_filter: ContextVar[bool] = ContextVar(
    '_strict_tenant_filter', default=False,
)
"""启用后，SQLAlchemy event 从 IN 列表改为严格相等 (`tenant_id = current_tenant_id`)。
供 F016 配额精确计数使用。通过 strict_tenant_filter() context manager 切换。
"""

_admin_scope_tenant_id: ContextVar[Optional[int]] = ContextVar(
    '_admin_scope_tenant_id', default=None,
)
"""F019 AdminScopeMiddleware 设置；仅全局超管 + 管理类 API 场景下非 None。
优先级高于 JWT leaf_tenant_id（见 get_current_tenant_id 下方规则）。
"""

_is_management_api: ContextVar[bool] = ContextVar(
    '_is_management_api', default=False,
)
"""F019 AdminScopeMiddleware 根据 URL 白名单设置；业务 API 请求时为 False。
tenant_filter event 可据此决定是否读取 _admin_scope_tenant_id。
"""


@contextmanager
def strict_tenant_filter():
    """配额计数等场景使用严格匹配（仅 current_tenant_id，不含 IN 列表）。"""
    token = _strict_tenant_filter.set(True)
    try:
        yield
    finally:
        _strict_tenant_filter.reset(token)


def get_current_tenant_id() -> Optional[int]:
    """**2026-04-19 扩展**：优先级规则（v2.5.1 高于 v2.5.0 基线版）：

    1. 若 `_admin_scope_tenant_id` 非 None（F019 超管已设管理视图），返回它；
    2. 否则返回 `current_tenant_id` ContextVar（来自 JWT leaf_tenant_id）；
    3. 若均未设置，返回 None（调用方据情况处理 —— 如 F017/F020 衍生数据写入点
       应抛 `TenantContextMissing` 异常，见 F017 AC-11）。

    **关键**：v2.5.0 已有的 `get_current_tenant_id` 签名保留不变；本 Feature 仅在实现
    内部增加 admin-scope 查找。所有 v2.5.0 调用方无需修改。
    """
    scope = _admin_scope_tenant_id.get()
    if scope is not None:
        return scope
    return current_tenant_id.get()
```

### 5.5 Middleware 注册顺序（F012 / F019 / 业务路由依赖）

```python
# src/backend/bisheng/main.py 中间件注册顺序（按 FastAPI 执行从下到上）：
#
# 1. AuthenticationMiddleware（v2.5.0 既有）
#    - 解析 JWT Cookie / Header
#    - 校验 payload.token_version == user.token_version（本 Feature AC-09，否则 401）
#    - 填充 request.state.user = UserPayload(...)
#
# 2. TenantContextMiddleware（v2.5.0 既有，本 Feature 扩展）
#    - 读 request.state.user.tenant_id → set_current_tenant_id
#    - 新增：计算 visible_tenant_ids = {leaf} 或 {leaf, Root=1}（本 Feature 5.4）
#    - 新增：若 request.state.user.is_global_super，visible_tenant_ids = None（不注入过滤）
#
# 3. AdminScopeMiddleware（F019 新增）
#    - 仅当 user.is_global_super + URL 命中管理类 API 前缀白名单时工作
#    - 读 Redis admin_scope:{user_id}，若存在则 set _admin_scope_tenant_id + _is_management_api=True
#    - 注：本中间件**必须位于 TenantContextMiddleware 之后**，否则 get_current_tenant_id 返回值
#      不含 scope 覆盖
#
# 4. 业务路由
```

---

## 6. 依赖

### 6.1 前置依赖

| 依赖 | 原因 |
|------|------|
| F011-tenant-tree-model | Tenant/UserTenant 模型 + 部门挂载字段 |
| v2.5.0/F002-department-tree | `Department.path` 物化路径 |
| v2.5.0/F004-rebac-core | OpenFGA 元组写入（tenant#member 重建） |

### 6.2 本 Feature 阻塞

- F013-tenant-fga-tree（需用户叶子 Tenant 派生 + JWT token_version）
- F014-sso-org-realtime-sync（复用 UserTenantSyncService）
- F018-resource-owner-transfer（Owner 交接前需确认归属）

---

## 7. 业务表改造清单

| 表 | 改造点 | Checklist |
|----|--------|----------|
| user_tenant | 语义变更为唯一叶子快照；加 uk_user_active 约束 | ☐ 数据迁移：同一 user 多条记录按 last_access_time 保留最新 ☐ 新增 `is_primary` 字段冗余标识 |
| user | **新增 token_version 字段** | DDL：`ALTER TABLE user ADD COLUMN token_version INT NOT NULL DEFAULT 0`；每次 sync_user 递增；中间件读取并比对 JWT payload.token_version |
| audit_log | 新增操作类型 `user.tenant_relocated` / `user.tenant_relocate_blocked` | ☐ 日志字段含 from_tenant/to_tenant/resource_count（audit_log 表本身在 F011 创建） |
| user_department | is_primary 变更钩子触发 sync | ☐ 加 SQLAlchemy before_update event |

---

## 8. 手工 QA 清单

### 8.1 派生逻辑

- [ ] SSO 登录时自动派生正确叶子 Tenant
- [ ] 无主部门用户默认 tenant_id=1
- [ ] 部门树多层挂载（集团→事业部→子公司挂载点）返回最近挂载点
- [ ] Tenant disabled 时派生跳过

### 8.2 主部门变更

- [ ] 跨 Tenant 调岗：user_tenant 旧 inactive、新 active
- [ ] 同 Tenant 调部门：不触发 UserTenantSync
- [ ] 兼职部门增减：无 sync
- [ ] 名下有资源时触发告警，站内消息 + 邮件
- [ ] `enforce_transfer_before_relocate=true` 时阻断主部门变更

### 8.3 JWT

- [ ] 新登录 token 含 `tenant_id` + `token_version`（不含 tenant_path）
- [ ] 主部门变更后 `user.token_version` 自增
- [ ] 旧 token 被拒绝（401）：中间件比对 payload.token_version vs user.token_version
- [ ] IN 列表过滤直接从 tenant_id 推导（leaf + Root=1），无需读 payload 其他字段

### 8.4 Celery 兜底

- [ ] 每 6h 定时任务批量校对所有 active 用户的归属
- [ ] 不一致时自动 sync 并写 audit_log

---

## 9. 错误码

- **MMM=191** (tenant_resolver)
- 19101: 阻断主部门变更（enforce_transfer_before_relocate）
- 19102: 派生失败（用户无主部门且无默认 Tenant）
- 19103: token_version 版本冲突
- 19104: Tenant 循环（主部门指向自身 Tenant 的祖先）

---

## 10. 不在本 Feature 范围

- 所有者交接 API → F018
- SSO 实时同步协议 → F014
- Celery 定时校对具体实现 → F015
- Gateway 域名路由 → 由 Gateway 侧配置，不在 bisheng 范围
