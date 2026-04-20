# Feature: 租户管理与登录流程

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 多租户需求文档 §3-5](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md)
**优先级**: P1
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 租户 CRUD API 端点（系统管理员专用）：
  - `POST /api/v1/tenants` — 创建租户
  - `GET /api/v1/tenants` — 租户列表（分页）
  - `GET /api/v1/tenants/{id}` — 租户详情
  - `PUT /api/v1/tenants/{id}` — 更新租户
  - `PUT /api/v1/tenants/{id}/status` — 启用/停用/归档
  - `DELETE /api/v1/tenants/{id}` — 物理删除
  - `GET /api/v1/tenants/{id}/quota` — 配额与用量查询
  - `PUT /api/v1/tenants/{id}/quota` — 设置配额
  - `POST /api/v1/tenants/{id}/users` — 添加用户到租户
  - `DELETE /api/v1/tenants/{id}/users/{user_id}` — 移除用户
  - `GET /api/v1/user/tenants` — 获取当前用户租户列表
  - `POST /api/v1/user/switch-tenant` — 切换租户（重发 JWT）
- 租户管理页面（独立页面，系统管理员入口）：
  - 列表：名称/编码/状态/用户数/存储用量/创建时间
  - 创建表单：名称/编码(不可变)/Logo/联系人/存储配额/管理员选择（仅现有用户）
  - 编辑：名称/Logo/联系人/状态/管理员/配额
  - 停用确认对话框 + Redis 黑名单拦截
- 登录流程变更：
  - 认证后查询 user_tenant 列表
  - 1 个租户 → 自动进入
  - 多个租户 → 显示租户选择页（按 last_access_time 排序）
  - 0 个租户 → 提示"无可用企业，请联系管理员"
- 租户切换：
  - Header 下拉显示当前租户名/Logo
  - 选择其他租户 → 重发 JWT（新 tenant_id）→ 整页刷新
  - 系统管理员额外显示"系统管理"入口
- `GET /api/v1/env` 增加 `multi_tenant_enabled` 字段供前端判断

**OUT**:
- Tenant ORM 模型定义 → F001-multi-tenant-core
- 配额执行逻辑（创建资源时校验配额） → F005-role-menu-quota
- 创建租户时内联创建新用户作为管理员 → P2
- 停用租户时暂停 Celery 队列任务 → P2
- 停用租户时暂停三方组织同步定时任务 → P2
- 跨租户使用分析仪表盘 → P2
- 首次登录无租户时强制创建租户流程 → P2
- 租户管理员密码重置功能 → P2
- LDAP 登录后端适配：LDAP 认证与密码登录共用 user_login 多租户分支，无需额外改动（已在 E-12 说明）

**关键文件（预判）**:
- 新建: `src/backend/bisheng/tenant/`（DDD 模块：api/ + domain/）
- 新建: `src/frontend/platform/src/pages/TenantPage/`
- 新建: `src/frontend/platform/src/pages/LoginPage/TenantSelect.tsx`
- 修改: `src/frontend/platform/src/pages/LoginPage/login.tsx`（登录后租户选择）
- 修改: `src/frontend/platform/src/layout/MainLayout.tsx`（租户切换下拉 + 侧边栏菜单）
- 修改: `src/backend/bisheng/user/domain/services/user.py`（登录流程适配）
- 修改: `src/backend/bisheng/utils/http_middleware.py`（停用租户中间件拦截）

**关联不变量**: INV-13, INV-14

---

## 1. 概述与用户故事

F010 将 F001 建立的多租户基础设施暴露为可操作的管理界面和登录流程。三类用户角色、三个核心场景：

**US-1 系统管理员管理租户**
> 作为系统管理员，我需要创建、编辑、停用和删除租户，以便为不同企业客户提供隔离的工作空间。

**US-2 多租户用户登录选择**
> 作为属于多个租户的用户，我在登录后需要选择要进入的租户，以便在正确的企业上下文中工作。

**US-3 用户切换租户**
> 作为属于多个租户的用户，我需要在不重新登录的情况下切换到另一个租户，以便跨企业操作。

---

## 2. 验收标准

### AC-1: 租户 CRUD

| # | 验收项 | 验证方式 |
|---|--------|---------|
| AC-1.1 | 系统管理员可创建租户，创建后租户记录、根部门、UserTenant、OpenFGA 元组（admin+member）全部正确写入 | API 测试 + DB 断言 |
| AC-1.2 | 创建租户时 tenant_code 唯一、不可变（编辑时不可修改），格式 `^[a-zA-Z][a-zA-Z0-9_-]{1,63}$` | API 测试 |
| AC-1.3 | 租户列表支持按名称/编码搜索、按状态过滤、分页返回，包含 user_count 和 storage_used_gb 字段 | API 测试 |
| AC-1.4 | 非系统管理员调用任何租户管理 API 返回 403 | API 测试 |
| AC-1.5 | 更新租户信息（名称/Logo/联系人）成功后立即生效 | API 测试 |

### AC-2: 租户状态管理

| # | 验收项 | 验证方式 |
|---|--------|---------|
| AC-2.1 | 停用租户后，写入 Redis 黑名单 key `disabled_tenant:{id}`，中间件对该租户的后续请求返回 403 | API 测试 + Redis 断言 |
| AC-2.2 | 启用租户后，删除 Redis 黑名单 key，恢复正常访问 | API 测试 |
| AC-2.3 | 删除租户前置检查：有活跃用户时拒绝删除（返回 20005 错误码） | API 测试 |
| AC-2.4 | 删除租户级联清理：UserTenant 记录 + OpenFGA 元组 + 根部门 | API 测试 + DB 断言 |

### AC-3: 租户用户管理

| # | 验收项 | 验证方式 |
|---|--------|---------|
| AC-3.1 | 系统管理员可添加已有用户到租户，同时写入 OpenFGA member 元组 | API 测试 |
| AC-3.2 | 移除用户前校验：不可移除租户最后一个 admin（返回 20006 错误码） | API 测试 |
| AC-3.3 | 移除用户后清理 UserTenant 记录 + OpenFGA member/admin 元组 | API 测试 |

### AC-4: 配额管理

| # | 验收项 | 验证方式 |
|---|--------|---------|
| AC-4.1 | 系统管理员可查看租户配额 + 当前用量（存储 GB、知识库数、用户数等） | API 测试 |
| AC-4.2 | 系统管理员可更新租户配额上限 | API 测试 |

### AC-5: 登录租户选择

| # | 验收项 | 验证方式 |
|---|--------|---------|
| AC-5.1 | `multi_tenant.enabled=true` 且用户有多个活跃租户时，登录 API 返回 `requires_tenant_selection=true` + 租户列表 + 临时 JWT（tenant_id=0） | API 测试 |
| AC-5.2 | 用户仅有 1 个活跃租户时，登录 API 直接返回含 tenant_id 的 JWT，无需选择 | API 测试 |
| AC-5.3 | 用户无活跃租户时，登录 API 返回 20009 错误码 | API 测试 |
| AC-5.4 | `multi_tenant.enabled=false` 时，登录行为与原有流程一致（JWT 含 DEFAULT_TENANT_ID=1） | API 测试 |
| AC-5.5 | 前端收到 requires_tenant_selection 后跳转租户选择页，展示租户卡片（按 last_access_time 降序） | 手动验证 |
| AC-5.6 | 用户选择租户后调 switch-tenant → 获取正式 JWT → 跳转主页 | 手动验证 |

### AC-6: 租户切换

| # | 验收项 | 验证方式 |
|---|--------|---------|
| AC-6.1 | switch-tenant API 校验用户属于目标租户、目标租户为 active 状态 | API 测试 |
| AC-6.2 | switch-tenant 成功后返回新 JWT（含新 tenant_id）并设置 Cookie | API 测试 |
| AC-6.3 | switch-tenant 更新 user_tenant.last_access_time | API 测试 |
| AC-6.4 | Header 租户切换器仅在 multi_tenant_enabled 时显示 | 手动验证 |
| AC-6.5 | 切换租户后整页刷新，所有数据加载为新租户上下文 | 手动验证 |

### AC-7: 租户管理页面

| # | 验收项 | 验证方式 |
|---|--------|---------|
| AC-7.1 | 租户管理菜单仅系统管理员且 multi_tenant_enabled 时可见 | 手动验证 |
| AC-7.2 | 租户列表展示名称/编码/状态(badge)/用户数/存储用量(进度条)/创建时间，支持搜索分页 | 手动验证 |
| AC-7.3 | 创建租户 Dialog 包含名称/编码/Logo/联系人/配额/管理员选择，提交后列表刷新 | 手动验证 |
| AC-7.4 | 停用租户显示二次确认对话框，警告文案包含"强制下线"提示 | 手动验证 |
| AC-7.5 | 删除租户显示二次确认对话框，需输入租户编码确认 | 手动验证 |

---

## 3. 边界情况

| # | 场景 | 预期行为 |
|---|------|---------|
| E-1 | 创建租户时 tenant_code 与已有重复 | 返回 20003 TenantCodeDuplicateError |
| E-2 | 删除有活跃用户的租户 | 返回 20005 TenantHasUsersError，不执行删除 |
| E-3 | 移除租户唯一管理员 | 返回 20006 TenantAdminRequiredError |
| E-4 | switch-tenant 目标租户已停用 | 返回 20001 TenantDisabledError |
| E-5 | switch-tenant 目标租户用户不属于 | 返回 20007 TenantSwitchForbiddenError |
| E-6 | 停用的租户用户发起 API 请求 | 中间件检查 Redis 黑名单，返回 403 + 20001 |
| E-7 | multi_tenant.enabled=false 时访问租户管理 API | 返回 403（非管理员）或空列表（仅默认租户） |
| E-8 | 登录时所有租户均为 disabled | 等同于 0 活跃租户，返回 20009 |
| E-9 | 租户创建过程中 OpenFGA 写入失败 | MySQL 已提交，OpenFGA 失败记入 failed_tuples 补偿表（INV-4） |
| E-10 | 并发创建同 tenant_code 的租户 | 数据库唯一约束保证仅一个成功，另一个返回 20003 |
| E-11 | 持有临时 JWT（tenant_id=0）访问非豁免 API | 中间件视 tenant_id=0 为"待选择"状态，对非豁免路径返回 403 + 20004 NoTenantContextError。豁免路径: `/user/login`, `/user/tenants`, `/user/switch-tenant`, `/env`, `/health`, `/tenant-select`（前端路由） |
| E-12 | LDAP 登录成功后的多租户选择 | LDAP 登录（ldapLoginApi）与密码登录共用同一 user_login 分支，认证后同样走多租户判断逻辑（0/1/N 租户），行为一致 |

---

## 4. 架构决策

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| AD-1 | 模块位置 | 新建 `src/backend/bisheng/tenant/` DDD 模块 | 租户管理是独立领域，不应混入 user 模块。复用 F001 的 DAO（`database/models/tenant.py`） |
| AD-2 | 页面位置 | 独立页面 `/admin/tenants`，侧边栏新顶级菜单 | 租户管理是跨租户的系统级操作，与租户内的 SystemPage 性质不同（用户确认 D1） |
| AD-3 | 登录 JWT | 多租户时先发临时 JWT（tenant_id=0）+ requires_tenant_selection | 简单直接，中间件已有 DEFAULT_TENANT_ID 兜底（用户确认 D2） |
| AD-4 | 管理员指定 | P1 仅选择现有用户 | 降低复杂度，创建新用户可在用户管理页单独完成（用户确认 D3） |
| AD-5 | 停用实现 | 状态标记 + Redis 黑名单 `disabled_tenant:{id}` + 中间件检查 | 轻量实现，覆盖核心场景。Celery 暂停为 P2（用户确认 D4） |
| AD-6 | 跨租户查询 | TenantService 使用 `bypass_tenant_filter()` | tenant 表本身无 tenant_id，但操作涉及跨租户数据查询 |
| AD-7 | 权限校验 | 系统管理员通过 `login_user.is_admin()` 校验 | 与现有 UserPayload.get_admin_user 依赖注入一致 |
| AD-8 | OpenFGA 元组 | 创建租户时通过 `PermissionService.authorize()` 写入 | 复用 F004 的双写 + 补偿机制，符合 INV-4 |

---

## 5. 数据库 & Domain 模型

### 5.1 复用模型（F001 已定义，Owner: F001）

**Tenant** (`database/models/tenant.py`)
- id, tenant_code(unique), tenant_name, logo, root_dept_id, status(active/disabled/archived)
- contact_name, contact_phone, contact_email, quota_config(JSON), storage_config(JSON)
- create_user, create_time, update_time

**UserTenant** (`database/models/tenant.py`)
- id, user_id, tenant_id, is_default, status(active/disabled), last_access_time, join_time
- 唯一约束: (user_id, tenant_id)

### 5.2 DAO 扩展（本 Feature 新增方法）

**TenantDao 新增**:
- `alist_tenants(keyword, status, page, page_size)` → `(List[Tenant], int)` — 分页列表
- `aupdate_tenant(tenant_id, **fields)` → `Tenant` — 部分更新
- `adelete_tenant(tenant_id)` → `None` — 物理删除
- `acount_tenant_users(tenant_id)` → `int` — 统计租户用户数

**UserTenantDao 新增**:
- `aget_user_tenants_with_details(user_id)` → `List[dict]` — join Tenant 表返回名称/Logo/状态
- `aremove_user_from_tenant(user_id, tenant_id)` → `None`
- `aupdate_last_access_time(user_id, tenant_id)` → `None`
- `aget_tenant_users(tenant_id, page, page_size, keyword)` → `(List, int)` — 分页用户列表
- `aget_user_tenant(user_id, tenant_id)` → `Optional[UserTenant]`
- `acount_tenant_admins(tenant_id)` → `int` — 统计租户管理员数（通过 OpenFGA check）

### 5.3 错误码扩展

在 `common/errcode/tenant.py` 新增（模块编码 200）：

| 错误码 | 类名 | 含义 |
|--------|------|------|
| 20005 | TenantHasUsersError | 租户有活跃用户，不可删除 |
| 20006 | TenantAdminRequiredError | 不可移除最后一个管理员 |
| 20007 | TenantSwitchForbiddenError | 用户不属于目标租户 |
| 20008 | TenantCreationFailedError | 租户创建失败（原子回滚） |
| 20009 | NoTenantsAvailableError | 用户无可用租户 |

---

## 6. API 契约

### 6.1 租户管理（系统管理员）

#### `POST /api/v1/tenants`
```
Auth: UserPayload.get_admin_user
Body: {
  tenant_name: str (2-128 chars),
  tenant_code: str (regex ^[a-zA-Z][a-zA-Z0-9_-]{1,63}$),
  logo?: str,
  contact_name?: str,
  contact_phone?: str,
  contact_email?: str,
  quota_config?: { storage_gb, knowledge_space, user_count, ... },
  admin_user_ids: List[int] (min 1)
}
Response 200: UnifiedResponseModel[TenantDetail]
Errors: 20003 (code duplicate), 20008 (creation failed)
Side effects: 创建 Tenant + 根部门 + UserTenant + OpenFGA 元组 (INV-14)
```

#### `GET /api/v1/tenants`
```
Auth: UserPayload.get_admin_user
Query: keyword?: str, status?: str, page: int=1, page_size: int=20
Response 200: UnifiedResponseModel[PageData[TenantListItem]]
  TenantListItem: { id, tenant_name, tenant_code, logo, status, user_count, storage_used_gb, storage_quota_gb, create_time }
```

#### `GET /api/v1/tenants/{id}`
```
Auth: UserPayload.get_admin_user
Response 200: UnifiedResponseModel[TenantDetail]
  TenantDetail: TenantListItem + { root_dept_id, contact_name, contact_phone, contact_email,
                                    quota_config, storage_config, admin_users: List[{user_id, user_name}] }
Errors: 20000 (not found)
```

#### `PUT /api/v1/tenants/{id}`
```
Auth: UserPayload.get_admin_user
Body: { tenant_name?: str, logo?: str, contact_name?: str, contact_phone?: str, contact_email?: str }
Response 200: UnifiedResponseModel[TenantDetail]
Errors: 20000
Note: tenant_code 不可修改
```

#### `PUT /api/v1/tenants/{id}/status`
```
Auth: UserPayload.get_admin_user
Body: { status: "active" | "disabled" | "archived" }
Response 200: UnifiedResponseModel[None]
Errors: 20000
Side effects:
  disabled → Redis SET disabled_tenant:{id} = 1 (no TTL)
  active → Redis DEL disabled_tenant:{id}
  archived → 同 disabled
```

#### `DELETE /api/v1/tenants/{id}`
```
Auth: UserPayload.get_admin_user
Response 200: UnifiedResponseModel[None]
Errors: 20000, 20005 (has users)
Side effects: 删除 Tenant + UserTenant 记录 + 根部门 + OpenFGA 元组 + Redis 黑名单
```

#### `GET /api/v1/tenants/{id}/quota`
```
Auth: UserPayload.get_admin_user
Response 200: UnifiedResponseModel[TenantQuotaResponse]
  TenantQuotaResponse: {
    quota_config: { storage_gb, knowledge_space, user_count, ... },
    usage: { storage_gb_used, knowledge_space_count, user_count, ... }
  }
```

#### `PUT /api/v1/tenants/{id}/quota`
```
Auth: UserPayload.get_admin_user
Body: { quota_config: dict }
Response 200: UnifiedResponseModel[None]
```

#### `POST /api/v1/tenants/{id}/users`
```
Auth: UserPayload.get_admin_user
Body: { user_ids: List[int], is_admin: bool = false }
Response 200: UnifiedResponseModel[None]
Side effects: 创建 UserTenant + OpenFGA member 元组；is_admin=true 时追加 admin 元组
```

#### `DELETE /api/v1/tenants/{id}/users/{user_id}`
```
Auth: UserPayload.get_admin_user
Response 200: UnifiedResponseModel[None]
Errors: 20006 (last admin)
Side effects: 删除 UserTenant + OpenFGA member/admin 元组
```

### 6.2 用户侧租户操作

#### `GET /api/v1/user/tenants`
```
Auth: UserPayload.get_login_user
Response 200: UnifiedResponseModel[List[UserTenantItem]]
  UserTenantItem: { tenant_id, tenant_name, tenant_code, logo, status, last_access_time, is_default }
  排序: last_access_time DESC
```

#### `POST /api/v1/user/switch-tenant`
```
Auth: UserPayload.get_login_user
Body: { tenant_id: int }
Response 200: UnifiedResponseModel[{ access_token: str }]
Errors: 20001 (disabled), 20007 (not member)
Side effects: 更新 last_access_time, 重发 JWT Cookie (新 tenant_id), Redis session 更新
```

### 6.3 环境配置（修改已有端点）

#### `GET /api/v1/env`（修改）
```
增加返回字段:
  multi_tenant_enabled: bool — 从 settings.multi_tenant.enabled 读取
```

### 6.4 登录流程变更（修改已有端点）

#### `POST /api/v1/user/login`（修改行为）
```
当 multi_tenant.enabled=true 时，认证成功后：
  0 活跃租户 → 返回 20009 NoTenantsAvailableError
  1 活跃租户 → 现有行为，JWT 含该 tenant_id
  N 活跃租户 → 返回 UserRead + {
    requires_tenant_selection: true,
    tenants: List[UserTenantItem],
    access_token: JWT(tenant_id=0)  // 临时 JWT
  }

当 multi_tenant.enabled=false 时：
  行为不变，JWT 含 DEFAULT_TENANT_ID=1
```

---

## 7. Service 层逻辑

### 7.1 TenantService (`tenant/domain/services/tenant_service.py`)

所有管理方法为 `@classmethod async`，第一行调用权限校验。

**`acreate_tenant(data, login_user)`**:
1. 校验 login_user.is_admin()
2. 校验 tenant_code 唯一（TenantDao.aget_by_code）
3. 开启 DB 事务:
   - 创建 Tenant 记录
   - 调用 `DepartmentService.acreate_root_department(tenant_id, name=tenant_name)`
   - 回写 `tenant.root_dept_id`
   - 为每个 admin_user_id 创建 UserTenant（is_default=0）
4. DB 提交后调用 `PermissionService.authorize()`:
   - 对象: `tenant:{id}`
   - grants: 每个 admin → relation=`admin`, 每个 admin → relation=`member`
5. OpenFGA 写入失败 → 记入 failed_tuples（INV-4）

**`aupdate_tenant_status(tenant_id, status, login_user)`**:
1. 校验 login_user.is_admin()
2. 更新 Tenant.status
3. `disabled`/`archived` → Redis SET `disabled_tenant:{id}` = `1`
4. `active` → Redis DEL `disabled_tenant:{id}`

**`adelete_tenant(tenant_id, login_user)`**:
1. 校验 login_user.is_admin()
2. 检查 UserTenantDao.acount_tenant_users > 0 → 拒绝
3. 使用 bypass_tenant_filter():
   - 删除 Tenant 记录
   - 删除根部门
   - 删除所有 UserTenant 记录
   - 调用 PermissionService.authorize() revoke 所有相关元组
   - Redis DEL `disabled_tenant:{id}`

**`aswitch_tenant(user_id, tenant_id, auth_jwt)`**:
1. 查询 UserTenantDao.aget_user_tenant(user_id, tenant_id) → 不存在返回 20007
2. 查询 TenantDao.aget_by_id(tenant_id) → status != 'active' 返回 20001
3. 更新 last_access_time
4. 查询 User 对象
5. 调用 LoginUser.create_access_token(user, auth_jwt, tenant_id=tenant_id)
6. LoginUser.set_access_cookies(token, auth_jwt)
7. 更新 Redis session
8. 返回 access_token

### 7.2 中间件改动 (`utils/http_middleware.py`)

在 `CustomMiddleware.__call__` 中，解析 JWT 获取 tenant_id 后、进入路由前，增加检查：

```python
# 豁免路径不检查租户状态
if path not in TENANT_CHECK_EXEMPT_PATHS:
    if not tenant_id or tenant_id == 0:
        # tenant_id=0 表示"待选择"状态（INV-13），非豁免路径拒绝访问
        return JSONResponse(status_code=403, content={...NoTenantContextError...})
    redis_client = get_redis_client_sync()
    if redis_client.get(f'disabled_tenant:{tenant_id}'):
        return JSONResponse(status_code=403, content={...TenantDisabledError...})
```

豁免路径（`TENANT_CHECK_EXEMPT_PATHS`）: `/api/v1/user/login`, `/api/v1/user/tenants`, `/api/v1/user/switch-tenant`, `/api/v1/env`, `/health`

**tenant_id=0 语义**：表示用户已认证但尚未选择租户（多租户登录中间态）。此状态下仅允许访问豁免路径（选择/切换租户相关），其他路径返回 403 + 20004。此设计与 INV-13 一致：非系统管理员端点必须有有效租户上下文。

### 7.3 登录流程改动 (`user/domain/services/user.py`)

在 `user_login()` 方法中，认证成功后、返回前：

```python
if settings.multi_tenant.enabled:
    tenants = await UserTenantDao.aget_user_tenants_with_details(db_user.user_id)
    active_tenants = [t for t in tenants if t['status'] == 'active']
    
    if len(active_tenants) == 0:
        raise NoTenantsAvailableError()
    elif len(active_tenants) == 1:
        tenant_id = active_tenants[0]['tenant_id']
        access_token = LoginUser.create_access_token(user=db_user, auth_jwt=auth_jwt, tenant_id=tenant_id)
        # update last_access_time
    else:
        access_token = LoginUser.create_access_token(user=db_user, auth_jwt=auth_jwt, tenant_id=0)
        # return with requires_tenant_selection=True and tenants list
```

---

## 8. 前端设计

### 8.1 租户管理页面 (`pages/TenantPage/`)

**路由**: `/admin/tenants`，仅系统管理员 + multi_tenant_enabled 时可见

**页面结构**:
```
┌─────────────────────────────────────────────────┐
│  租户管理                        [+ 创建租户]    │
│  [搜索框]  [状态过滤下拉]                        │
├─────────────────────────────────────────────────┤
│  租户名称 │ 编码 │ 状态 │ 用户数 │ 存储用量    │ 创建时间 │ 操作│
│  ────────┼──────┼─────┼───────┼────────────┼────────┼─────│
│  中粮集团 │ cofco│ 正常 │ 156   │ 45/100 GB  │ 2025.. │ 编辑│
│  首钢集团 │ shg  │ 停用 │ 42    │ 12/50 GB   │ 2025.. │ 编辑│
├─────────────────────────────────────────────────┤
│                              共 2 条  < 1/1 >    │
└─────────────────────────────────────────────────┘
```

**组件拆分**:
- `TenantPage/index.tsx` — 页面主体，useTable hook
- `TenantPage/components/TenantList.tsx` — 表格 + 操作列
- `TenantPage/components/CreateTenantDialog.tsx` — 创建/编辑 Dialog
- `TenantPage/components/TenantQuotaDialog.tsx` — 配额查看/编辑 Dialog
- `TenantPage/components/TenantUserDialog.tsx` — 用户管理 Dialog

**操作列**:
- 编辑（打开编辑 Dialog）
- 停用/启用（bsConfirm，停用时显示"停用后该企业所有成员将被强制下线"）
- 删除（bsConfirm + 输入编码确认，仅 disabled/archived 状态显示）

**状态 Badge**: `active` → 绿色 "正常"，`disabled` → 灰色 "已停用"，`archived` → 橙色 "已归档"

### 8.2 租户选择页 (`pages/LoginPage/TenantSelect.tsx`)

**路由**: `/tenant-select`，公开路由（不需要完整 tenant 上下文）

**页面结构**:
```
┌──────────────────────────────────────┐
│              [Logo]                   │
│          选择您的企业                  │
│                                      │
│  ┌────────────┐  ┌────────────┐      │
│  │  [Logo]    │  │  [Logo]    │      │
│  │  中粮集团   │  │  首钢集团   │      │
│  │  cofco     │  │  shougang  │      │
│  └────────────┘  └────────────┘      │
│                                      │
│           [返回登录]                  │
└──────────────────────────────────────┘
```

**行为**:
- 从 login.tsx 跳转时，tenants 通过 sessionStorage 传递
- 点击卡片 → switchTenantApi(tenantId) → 成功后 location.href 跳转主页
- 租户按 last_access_time DESC 排序
- 显示租户 Logo（无 Logo 时显示首字母头像）

### 8.3 Header 租户切换器 (`layout/MainLayout.tsx`)

在用户头像左侧增加租户切换器：

```
... [模型管理]  | 租户切换器 | [暗色] [语言] [头像▼]
                     ↓
              ┌──────────────┐
              │ ✓ 中粮集团    │
              │   首钢集团    │
              │ ──────────── │
              │ 🔧 租户管理   │  ← 仅系统管理员
              └──────────────┘
```

**行为**:
- 切换前 bsConfirm 确认："切换企业将刷新页面，未保存的内容将丢失"
- 确认后 switchTenantApi → location.reload()
- 仅 multi_tenant_enabled 时渲染

### 8.4 用户上下文变更

`userContext.tsx` 中 user 对象扩展:
```typescript
{
  ...existingFields,
  tenant_id?: number,
  tenant_name?: string,
  tenant_code?: string,
  tenant_logo?: string,
}
```

通过 `/api/v1/user/info` 返回值获取（后端 UserRead 需适配）。

### 8.5 appConfig 变更

`locationContext.tsx` 的 appConfig 从 `/api/v1/env` 获取 `multi_tenant_enabled` 字段：
```typescript
appConfig: {
  ...existing,
  multiTenantEnabled: boolean,
}
```

### 8.6 路由变更

`routes/index.tsx`:
- 新增 `{ path: "admin/tenants", element: <TenantPage /> }` 在 admin router 中
- 新增 `{ path: "tenant-select", element: <TenantSelect /> }` 在 public router 中

### 8.7 侧边栏菜单变更

`MainLayout.tsx` 侧边栏菜单新增"租户管理"项：
- 条件: `user.role === 'admin' && appConfig.multiTenantEnabled`
- 位置: 在"系统管理"下方
- 图标: Building2 (lucide-react)

---

## 9. 文件清单

### 新建文件

| 文件路径 | 说明 |
|---------|------|
| `src/backend/bisheng/tenant/__init__.py` | 模块包 |
| `src/backend/bisheng/tenant/api/__init__.py` | API 子包 |
| `src/backend/bisheng/tenant/api/router.py` | 路由聚合 |
| `src/backend/bisheng/tenant/api/endpoints/__init__.py` | 端点子包 |
| `src/backend/bisheng/tenant/api/endpoints/tenant_crud.py` | CRUD + 状态 + 配额端点 |
| `src/backend/bisheng/tenant/api/endpoints/tenant_users.py` | 租户用户管理端点 |
| `src/backend/bisheng/tenant/api/endpoints/user_tenant.py` | 用户侧端点 |
| `src/backend/bisheng/tenant/domain/__init__.py` | Domain 子包 |
| `src/backend/bisheng/tenant/domain/schemas/__init__.py` | Schema 子包 |
| `src/backend/bisheng/tenant/domain/schemas/tenant_schema.py` | Pydantic DTO |
| `src/backend/bisheng/tenant/domain/services/__init__.py` | Service 子包 |
| `src/backend/bisheng/tenant/domain/services/tenant_service.py` | 业务逻辑 |
| `src/frontend/platform/src/pages/TenantPage/index.tsx` | 租户管理页面 |
| `src/frontend/platform/src/pages/TenantPage/components/TenantList.tsx` | 列表组件 |
| `src/frontend/platform/src/pages/TenantPage/components/CreateTenantDialog.tsx` | 创建/编辑弹窗 |
| `src/frontend/platform/src/pages/TenantPage/components/TenantQuotaDialog.tsx` | 配额弹窗 |
| `src/frontend/platform/src/pages/TenantPage/components/TenantUserDialog.tsx` | 用户管理弹窗 |
| `src/frontend/platform/src/pages/LoginPage/TenantSelect.tsx` | 租户选择页 |
| `src/frontend/platform/src/controllers/API/tenant.ts` | 前端 API 函数 |
| `src/frontend/platform/src/types/api/tenant.ts` | TS 类型定义 |

### 修改文件

| 文件路径 | 改动说明 |
|---------|---------|
| `src/backend/bisheng/database/models/tenant.py` | 扩展 TenantDao/UserTenantDao 方法 |
| `src/backend/bisheng/common/errcode/tenant.py` | 新增 20005-20009 错误码 |
| `src/backend/bisheng/api/router.py` | 注册 tenant_router |
| `src/backend/bisheng/user/domain/services/user.py` | user_login() 多租户分支 |
| `src/backend/bisheng/user/domain/models/user.py` | UserRead 增加 tenant 字段 |
| `src/backend/bisheng/utils/http_middleware.py` | 停用租户中间件拦截 |
| `src/backend/bisheng/api/v1/endpoints.py` | get_env() 增加 multi_tenant_enabled |
| `src/frontend/platform/src/pages/LoginPage/login.tsx` | 登录后租户选择逻辑 |
| `src/frontend/platform/src/layout/MainLayout.tsx` | 侧边栏菜单 + Header 租户切换 |
| `src/frontend/platform/src/routes/index.tsx` | 新增路由 |
| `src/frontend/platform/src/contexts/userContext.tsx` | tenant 上下文 |
| `src/frontend/platform/src/contexts/locationContext.tsx` | appConfig.multiTenantEnabled |
| `src/frontend/platform/src/controllers/API/user.ts` | 适配 tenant 字段 |
| `src/frontend/platform/public/locales/zh-Hans/bs.json` | 中文 i18n |
| `src/frontend/platform/public/locales/en-US/bs.json` | 英文 i18n |
| `src/frontend/platform/public/locales/ja/bs.json` | 日文 i18n |

---

## 10. 非功能要求

| 类别 | 要求 |
|------|------|
| 性能 | 租户列表 API 响应 < 200ms（100 租户以内）；中间件 Redis 黑名单检查 < 5ms |
| 安全 | 所有管理 API 必须校验系统管理员权限；tenant_code 只允许字母开头的字母数字下划线横线 |
| 兼容性 | multi_tenant.enabled=false 时所有行为与改造前一致，无感知 |
| 可观测性 | 租户 CRUD 操作记入审计日志（AuditLogService） |
| 数据一致性 | 租户创建遵循 INV-14 原子性要求；OpenFGA 失败走补偿（INV-4） |
| i18n | 所有 UI 文案通过 i18next，支持中文/英文/日文三语言 |

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 多租户需求文档: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md`
- 权限改造 PRD: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 权限管理体系改造 PRD.md`
- 技术方案: `docs/PRD/2.5 权限管理体系改造 PRD/2.5 技术方案.md`
