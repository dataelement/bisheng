# Tasks: 租户管理与登录流程

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-04-13 审查通过（修复 2 medium + 3 low） |
| tasks.md | ✅ 已拆解 | 2026-04-13 审查通过（Round 2 LGTM，修复 3 medium + 1 low） |
| 实现 | ✅ 已完成 | 11 / 11 完成 |

---

## 任务列表

> **测试降级说明**：后端任务（T-01~T-05）将验证内嵌在实现任务中，未拆分独立测试任务。
> 理由：项目测试基础设施（F000-test-infrastructure）的 conftest + fixture 仍在搭建中，
> 当前后端缺少可复用的 TestClient fixture 和数据库 fixture，独立测试任务无法独立运行。
> 每个后端任务的"验证"部分描述了应有的测试范围，待 F000 完善后可补充正式测试用例。
> 前端任务（T-06~T-09）采用手动验证，因 Platform 前端尚无 Vitest 测试框架。

### Phase 1: 后端基础（可并行）

#### T-01: Domain Schemas + 错误码扩展

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/tenant/__init__.py`
- 新建: `src/backend/bisheng/tenant/api/__init__.py`
- 新建: `src/backend/bisheng/tenant/api/endpoints/__init__.py`
- 新建: `src/backend/bisheng/tenant/domain/__init__.py`
- 新建: `src/backend/bisheng/tenant/domain/schemas/__init__.py`
- 新建: `src/backend/bisheng/tenant/domain/schemas/tenant_schema.py`
- 新建: `src/backend/bisheng/tenant/domain/services/__init__.py`
- 修改: `src/backend/bisheng/common/errcode/tenant.py`

**内容**:
- 模块骨架：创建 `tenant/` DDD 目录结构（api/ + domain/），所有 `__init__.py`
- 请求 DTO:
  - `TenantCreate(BaseModel)`: tenant_name(str, 2-128), tenant_code(str, regex `^[a-zA-Z][a-zA-Z0-9_-]{1,63}$`), logo(Optional[str]), contact_name/phone/email(Optional), quota_config(Optional[dict]), admin_user_ids(List[int], min_length=1)
  - `TenantUpdate(BaseModel)`: tenant_name(Optional), logo, contact_name, contact_phone, contact_email — 全部 Optional
  - `TenantStatusUpdate(BaseModel)`: status(Literal['active', 'disabled', 'archived'])
  - `TenantQuotaUpdate(BaseModel)`: quota_config(dict)
  - `TenantUserAdd(BaseModel)`: user_ids(List[int], min_length=1), is_admin(bool=False)
  - `SwitchTenantRequest(BaseModel)`: tenant_id(int)
- 响应 DTO:
  - `TenantListItem(BaseModel)`: id, tenant_name, tenant_code, logo, status, user_count, storage_used_gb, storage_quota_gb, create_time
  - `TenantDetail(TenantListItem)`: root_dept_id, contact_name, contact_phone, contact_email, quota_config, storage_config, admin_users(List[dict])
  - `TenantQuotaResponse(BaseModel)`: quota_config(dict), usage(dict)
  - `UserTenantItem(BaseModel)`: tenant_id, tenant_name, tenant_code, logo, status, last_access_time, is_default
- 新增错误码（模块 200）:
  - `TenantHasUsersError(20005)`: 'Cannot delete tenant with active users'
  - `TenantAdminRequiredError(20006)`: 'Cannot remove the last admin of a tenant'
  - `TenantSwitchForbiddenError(20007)`: 'User does not belong to the target tenant'
  - `TenantCreationFailedError(20008)`: 'Tenant creation failed'
  - `NoTenantsAvailableError(20009)`: 'No available tenants for user'

**覆盖 AC**: AC-1.2(验证规则), AC-2.3(20005), AC-3.2(20006), AC-5.3(20009), AC-6.1(20007)

**验证**: import 无报错；Pydantic 验证规则单测（valid/invalid tenant_code、空 admin_user_ids 等）

---

#### T-02: 扩展 Tenant DAO

- [x] 完成

**文件**:
- 修改: `src/backend/bisheng/database/models/tenant.py`

**内容**:
- TenantDao 新增方法:
  - `alist_tenants(keyword: str = None, status: str = None, page: int = 1, page_size: int = 20)` → `Tuple[List[Tenant], int]` — 分页 + 模糊搜索 tenant_name/tenant_code + 状态过滤，使用 `bypass_tenant_filter()`
  - `aupdate_tenant(tenant_id: int, **fields)` → `Optional[Tenant]` — 部分更新，只更新传入的非 None 字段
  - `adelete_tenant(tenant_id: int)` → `None` — 物理删除 Tenant 记录
  - `acount_tenant_users(tenant_id: int)` → `int` — `SELECT COUNT(*) FROM user_tenant WHERE tenant_id=? AND status='active'`
- UserTenantDao 新增方法:
  - `aget_user_tenants_with_details(user_id: int)` → `List[dict]` — LEFT JOIN tenant 表返回 {tenant_id, tenant_name, tenant_code, logo, status, last_access_time, is_default}，按 last_access_time DESC 排序
  - `aremove_user_from_tenant(user_id: int, tenant_id: int)` → `None` — 物理删除 UserTenant 记录
  - `aupdate_last_access_time(user_id: int, tenant_id: int)` → `None` — 更新 last_access_time 为当前时间
  - `aget_tenant_users(tenant_id: int, page: int, page_size: int, keyword: str = None)` → `Tuple[List[dict], int]` — JOIN user 表返回 {user_id, user_name, avatar, join_time}，分页 + 搜索
  - `aget_user_tenant(user_id: int, tenant_id: int)` → `Optional[UserTenant]` — 单条查询
  - `adelete_by_tenant(tenant_id: int)` → `int` — 删除某租户的所有 UserTenant 记录，返回删除行数

**覆盖 AC**: AC-1.1(创建), AC-1.3(列表), AC-2.3(用户数检查), AC-2.4(级联清理), AC-3.1(添加用户), AC-3.3(移除用户), AC-5.1(租户列表), AC-6.3(last_access_time)

**验证**: 单元测试——SQLite in-memory 验证各 DAO 方法 CRUD + 分页 + 过滤逻辑

---

### Phase 2: 后端服务与 API

#### T-03: Tenant Service 层

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/tenant/domain/services/tenant_service.py`

**依赖**: T-01, T-02

**内容**:
- `TenantService` 类，所有方法 `@classmethod async`:
  - `acreate_tenant(data: TenantCreate, login_user)`:
    1. tenant_code 唯一校验 → TenantCodeDuplicateError(20003)
    2. DB 事务: Tenant 记录 → DepartmentService.acreate_root_department(tenant_id, name=tenant_name) → 回写 root_dept_id → 每个 admin_user_id 创建 UserTenant
    3. DB 提交后: PermissionService.authorize(object_type='tenant', object_id=str(id), grants=[每个 admin → relation='admin', relation='member'])
    4. OpenFGA 失败 → failed_tuples 补偿（INV-4）
  - `alist_tenants(keyword, status, page, page_size, login_user)`:
    - 调用 TenantDao.alist_tenants，enrichment: 查询每个租户的 user_count + storage_used_gb
    - storage_used_gb: 调用 MinIO 存储统计或从 quota_config 缓存读取（按实际可用性定）
  - `aget_tenant(tenant_id, login_user)`:
    - TenantDao.aget_by_id + user_count + admin_users 列表（通过 OpenFGA list_objects 查询 tenant:{id} 的 admin 关系）
  - `aupdate_tenant(tenant_id, data: TenantUpdate, login_user)`:
    - TenantDao.aupdate_tenant，不允许修改 tenant_code
  - `aupdate_tenant_status(tenant_id, data: TenantStatusUpdate, login_user)`:
    - 更新 Tenant.status
    - disabled/archived → Redis SET `disabled_tenant:{id}` = `1`（无 TTL）
    - active → Redis DEL `disabled_tenant:{id}`
  - `adelete_tenant(tenant_id, login_user)`:
    - 前置检查 acount_tenant_users > 0 → TenantHasUsersError(20005)
    - bypass_tenant_filter 下删除: Tenant + 根部门 + UserTenant 记录 + PermissionService.authorize(revokes) + Redis DEL
  - `aget_quota(tenant_id, login_user)` / `aset_quota(tenant_id, data, login_user)`:
    - 读取/更新 quota_config JSON，用量统计从各业务表 COUNT 聚合
  - `aadd_users(tenant_id, data: TenantUserAdd, login_user)`:
    - 批量创建 UserTenant + PermissionService.authorize(member 元组; is_admin=True 时追加 admin 元组)
  - `aremove_user(tenant_id, user_id, login_user)`:
    - 若 is_admin → 检查 admin 数 > 1，否则 TenantAdminRequiredError(20006)
    - 删除 UserTenant + PermissionService.authorize(revoke member + admin)
  - `aget_user_tenants(user_id)`:
    - UserTenantDao.aget_user_tenants_with_details(user_id)，不需要管理员权限
  - `aswitch_tenant(user_id, tenant_id, db_user, auth_jwt)`:
    - 校验 UserTenant 存在 → TenantSwitchForbiddenError(20007)
    - 校验 Tenant.status == 'active' → TenantDisabledError(20001)
    - 更新 last_access_time
    - LoginUser.create_access_token(user=db_user, auth_jwt=auth_jwt, tenant_id=tenant_id)
    - LoginUser.set_access_cookies + Redis session 更新
    - 返回 access_token

**覆盖 AC**: AC-1.1, AC-1.2, AC-1.3, AC-1.5, AC-2.1, AC-2.2, AC-2.3, AC-2.4, AC-3.1, AC-3.2, AC-3.3, AC-4.1, AC-4.2, AC-6.1, AC-6.2, AC-6.3

**验证**: Service 层单测（mock DAO + PermissionService），覆盖 happy path + 各 error code 场景

---

#### T-04: Tenant API Router + 端点

- [x] 完成

**文件**:
- 新建: `src/backend/bisheng/tenant/api/router.py`
- 新建: `src/backend/bisheng/tenant/api/endpoints/tenant_crud.py`
- 新建: `src/backend/bisheng/tenant/api/endpoints/tenant_users.py`
- 新建: `src/backend/bisheng/tenant/api/endpoints/user_tenant.py`
- 修改: `src/backend/bisheng/api/router.py` — 增加 `from bisheng.tenant.api.router import router as tenant_router` + `router.include_router(tenant_router)`

**依赖**: T-03

**内容**:
- `tenant/api/router.py`: 创建 APIRouter，聚合三个子模块的端点
- `tenant_crud.py`（prefix `/tenants`, tags=['Tenant Management']）:
  - `POST /` — create_tenant(data: TenantCreate, admin_user: UserPayload = Depends(get_admin_user))
  - `GET /` — list_tenants(keyword, status, page, page_size, admin_user)
  - `GET /{tenant_id}` — get_tenant(tenant_id, admin_user)
  - `PUT /{tenant_id}` — update_tenant(tenant_id, data: TenantUpdate, admin_user)
  - `PUT /{tenant_id}/status` — update_tenant_status(tenant_id, data: TenantStatusUpdate, admin_user)
  - `DELETE /{tenant_id}` — delete_tenant(tenant_id, admin_user)
  - `GET /{tenant_id}/quota` — get_quota(tenant_id, admin_user)
  - `PUT /{tenant_id}/quota` — set_quota(tenant_id, data: TenantQuotaUpdate, admin_user)
- `tenant_users.py`（prefix `/tenants`, tags=['Tenant Users']）:
  - `POST /{tenant_id}/users` — add_users(tenant_id, data: TenantUserAdd, admin_user)
  - `DELETE /{tenant_id}/users/{user_id}` — remove_user(tenant_id, user_id, admin_user)
- `user_tenant.py`（prefix `/user`, tags=['User Tenant']）:
  - `GET /tenants` — get_my_tenants(login_user: UserPayload = Depends(get_login_user))
  - `POST /switch-tenant` — switch_tenant(data: SwitchTenantRequest, login_user, auth_jwt: AuthJwt = Depends())
- 所有端点使用 `UnifiedResponseModel` 包装：`resp_200(data)` / error 返回
- 错误通过 `try/except BaseErrorCode as e: return e.return_resp_instance()`

**覆盖 AC**: AC-1.4(权限校验), 所有 API 契约（spec §6）

**验证**: TestClient 集成测试——覆盖 12 个端点的 happy path + 403 权限拒绝

---

#### T-05: 登录流程适配 + 中间件

- [x] 完成

**文件**:
- 修改: `src/backend/bisheng/user/domain/services/user.py` — `user_login()` 方法
- 修改: `src/backend/bisheng/user/domain/models/user.py` — `UserRead` 增加字段
- 修改: `src/backend/bisheng/utils/http_middleware.py` — `CustomMiddleware.__call__`
- 修改: `src/backend/bisheng/api/v1/endpoints.py` — `get_env()` 增加 multi_tenant_enabled

**依赖**: T-02（DAO 方法）, T-01（NoTenantsAvailableError）

**内容**:
1. **user_login() 改动**:
   - 认证成功后，判断 `settings.multi_tenant.enabled`:
   - True: 查询 `UserTenantDao.aget_user_tenants_with_details(user_id)`，过滤 status='active'
     - 0 活跃租户 → raise `NoTenantsAvailableError()`
     - 1 活跃租户 → `LoginUser.create_access_token(tenant_id=tenant_id)`，更新 last_access_time
     - N 活跃租户 → `LoginUser.create_access_token(tenant_id=0)` + 返回 `requires_tenant_selection=True` + `tenants` 列表
   - False: 现有行为不变（`tenant_id=DEFAULT_TENANT_ID`）

2. **UserRead 扩展**:
   - 新增可选字段: `requires_tenant_selection: Optional[bool] = None`
   - 新增可选字段: `tenants: Optional[List[dict]] = None`
   - 新增可选字段: `tenant_id: Optional[int] = None`, `tenant_name: Optional[str] = None`

3. **中间件改动**（spec §7.2）:
   - 定义 `TENANT_CHECK_EXEMPT_PATHS` 常量（豁免路径列表）
   - 在 JWT 解析后、路由前：非豁免路径检查 tenant_id==0 → 403 NoTenantContextError
   - 非豁免路径检查 Redis `disabled_tenant:{tenant_id}` → 403 TenantDisabledError

4. **get_env() 改动**:
   - 增加 `env['multi_tenant_enabled'] = settings.multi_tenant.enabled`

**覆盖 AC**: AC-5.1, AC-5.2, AC-5.3, AC-5.4, AC-2.1(中间件拦截), E-11(tenant_id=0 拦截), E-12(LDAP 适配)

**验证**: 单测——mock settings.multi_tenant.enabled=True/False，测试 0/1/N 租户场景；中间件单测——disabled 租户返回 403、tenant_id=0 非豁免路径返回 403

---

### Phase 3: 前端基础（可并行）

#### T-06: 前端 API + Types + i18n

- [x] 完成

**文件**:
- 新建: `src/frontend/platform/src/controllers/API/tenant.ts`
- 新建: `src/frontend/platform/src/types/api/tenant.ts`
- 修改: `src/frontend/platform/public/locales/zh-Hans/bs.json`
- 修改: `src/frontend/platform/public/locales/en-US/bs.json`
- 修改: `src/frontend/platform/public/locales/ja/bs.json`

**依赖**: 无（API 契约已在 spec §6 定义）

**内容**:
1. **TypeScript 类型** (`types/api/tenant.ts`):
   - `interface Tenant { id, tenant_name, tenant_code, logo, status, user_count, storage_used_gb, storage_quota_gb, create_time }`
   - `interface TenantDetail extends Tenant { root_dept_id, contact_name, contact_phone, contact_email, quota_config, storage_config, admin_users }`
   - `interface TenantQuota { quota_config, usage }`
   - `interface UserTenantItem { tenant_id, tenant_name, tenant_code, logo, status, last_access_time, is_default }`
   - `interface TenantCreateForm { tenant_name, tenant_code, logo?, contact_name?, contact_phone?, contact_email?, quota_config?, admin_user_ids }`

2. **API 函数** (`controllers/API/tenant.ts`):
   - Admin CRUD: `createTenantApi`, `getTenantsApi`(分页), `getTenantApi`, `updateTenantApi`, `updateTenantStatusApi`, `deleteTenantApi`
   - Quota: `getTenantQuotaApi`, `setTenantQuotaApi`
   - Users: `addTenantUsersApi`, `removeTenantUserApi`
   - User-facing: `getUserTenantsApi`, `switchTenantApi`
   - 使用 `@/controllers/request` 的 axios 实例

3. **i18n keys** (namespace `bs`, key prefix `tenant.`):
   - 中文: `tenant.management`="租户管理", `tenant.name`="租户名称", `tenant.code`="租户编码", `tenant.create`="创建租户", `tenant.edit`="编辑租户", `tenant.disable`="停用", `tenant.enable`="启用", `tenant.archive`="归档", `tenant.delete`="删除租户", `tenant.confirmDisable`="停用后该企业下所有成员将被强制下线，且无法再次登录系统。确认停用？", `tenant.confirmDelete`="请输入租户编码 {{code}} 以确认删除。租户内所有数据将被永久删除。", `tenant.selectTenant`="选择您的企业", `tenant.noTenants`="暂无可用企业，请联系管理员", `tenant.switchConfirm`="切换企业将刷新页面，未保存的内容将丢失。确认切换？", `tenant.switchSuccess`="切换成功", `tenant.status.active`="正常", `tenant.status.disabled`="已停用", `tenant.status.archived`="已归档", `tenant.storageUsage`="存储用量", `tenant.userCount`="用户数", `tenant.contact`="联系人", `tenant.quota`="配额设置", `tenant.adminSelect`="选择管理员", `tenant.codeRule`="仅字母开头，字母数字下划线横线，2-64字符", `tenant.codeImmutable`="编码创建后不可修改"
   - 英文 + 日文: 对应翻译

**覆盖 AC**: AC-7.1, AC-7.2, AC-7.3, AC-7.4, AC-7.5, AC-5.5(选择页文案), AC-6.4(切换器文案)

**验证**: TypeScript 编译无错误；i18n key 在三语言文件中对齐

---

### Phase 4: 前端页面

#### T-07a: 租户管理列表页 + 路由/菜单

- [x] 完成

**文件**:
- 新建: `src/frontend/platform/src/pages/TenantPage/index.tsx`
- 修改: `src/frontend/platform/src/routes/index.tsx` — 增加 `/admin/tenants` 路由
- 修改: `src/frontend/platform/src/layout/MainLayout.tsx` — 侧边栏增加「租户管理」菜单

**依赖**: T-06

**内容**:
1. **TenantPage/index.tsx** — 主列表页:
   - `useTable` hook 绑定 `getTenantsApi`
   - 搜索栏: `SearchInput` 关键字搜索
   - 状态过滤: Popover + 复选框（active/disabled/archived）
   - 表格列: 名称, 编码, 状态(Badge 颜色: active=绿, disabled=灰, archived=橙), 用户数, 存储用量(进度条 used/quota), 创建时间, 操作
   - 操作列: 编辑(link btn) / 停用|启用(link btn) / 删除(red link btn, 仅 disabled/archived)
   - `[+ 创建租户]` 按钮（打开 Dialog，T-07b 实现）
   - AutoPagination 分页
   - 停用确认: `bsConfirm({ desc: t('tenant.confirmDisable'), ... })`
   - 删除确认: 自定义 Dialog 含 Input，用户输入 tenant_code 匹配后才启用确认按钮

2. **路由注册**: `getAdminRouter()` 中添加 `{ path: 'admin/tenants', element: lazy(() => import('@/pages/TenantPage')) }`

3. **侧边栏菜单**: MainLayout 侧边栏，在"系统管理"下方增加 NavLink 到 `/admin/tenants`
   - 条件: `user.role === 'admin' && appConfig.multiTenantEnabled`
   - 图标: Building2 from lucide-react

**覆盖 AC**: AC-7.1, AC-7.2, AC-7.4, AC-7.5

**验证**: 手动验证——列表展示正确，菜单仅管理员 + multi_tenant 可见，停用/删除确认弹窗正常

---

#### T-07b: 租户 Dialog 组件（创建/编辑/配额/用户）

- [x] 完成

**文件**:
- 新建: `src/frontend/platform/src/pages/TenantPage/components/CreateTenantDialog.tsx`
- 新建: `src/frontend/platform/src/pages/TenantPage/components/TenantQuotaDialog.tsx`
- 新建: `src/frontend/platform/src/pages/TenantPage/components/TenantUserDialog.tsx`

**依赖**: T-07a

**内容**:
1. **CreateTenantDialog.tsx** — 创建/编辑 Dialog:
   - Dialog + Form: tenant_name(Input), tenant_code(Input, 编辑时 disabled + tooltip), logo(Input/上传), contact_name/phone/email(Input)
   - 管理员选择: 用户搜索下拉（调现有 getUsersApi），支持多选
   - 配额设置: 可折叠区域，storage_gb(Input type=number), user_count, knowledge_space 等
   - 校验: tenant_code 正则 + 必填项
   - 编辑模式: 传入 tenant 数据预填，tenant_code disabled

2. **TenantQuotaDialog.tsx** — 配额查看/编辑 Dialog:
   - 调 getTenantQuotaApi 展示 quota vs usage
   - 进度条展示各项用量

3. **TenantUserDialog.tsx** — 用户管理 Dialog:
   - 列表: 用户名, 头像, 加入时间, 操作(移除)
   - 添加用户: 搜索下拉 + 批量添加
   - 移除: bsConfirm 确认

**覆盖 AC**: AC-7.3

**验证**: 手动验证——创建/编辑全流程；配额展示正确；用户添加/移除正常

---

#### T-08: 登录租户选择页

- [x] 完成

**文件**:
- 新建: `src/frontend/platform/src/pages/LoginPage/TenantSelect.tsx`
- 修改: `src/frontend/platform/src/pages/LoginPage/login.tsx`
- 修改: `src/frontend/platform/src/routes/index.tsx` — 增加 `/tenant-select` 公开路由

**依赖**: T-06, T-05(后端 API)

**内容**:
1. **login.tsx 改动**:
   - `handleLogin` 的 `.then()` 回调中:
     ```
     if (res.requires_tenant_selection) {
       sessionStorage.setItem('pending_tenants', JSON.stringify(res.tenants))
       // 设置临时 token（tenant_id=0）
       if (window.self !== window.top) localStorage.setItem('ws_token', res.access_token)
       localStorage.setItem('isLogin', '1')
       location.href = __APP_ENV__.BASE_URL + '/tenant-select'
     } else {
       // 现有流程不变
     }
     ```
   - LDAP 登录同理（ldapLoginApi 共用相同的后端 user_login 逻辑，返回相同字段）

2. **TenantSelect.tsx** — 独立页面:
   - 从 sessionStorage 读取 `pending_tenants`
   - 无数据时（直接访问）调 `getUserTenantsApi()` 获取
   - 卡片布局: 每个租户一张卡片（Logo/首字母头像 + 租户名 + 编码）
   - 按 last_access_time DESC 排序
   - 点击卡片 → `switchTenantApi(tenantId)` → 成功后清除 sessionStorage + `location.href` 跳转主页
   - 底部"返回登录"按钮 → 调 logoutApi + 跳转 /login
   - 0 租户（异常）: 显示 `t('tenant.noTenants')` 提示

3. **路由**: `publicRouter` 增加 `{ path: 'tenant-select', element: <TenantSelect /> }`

**覆盖 AC**: AC-5.5, AC-5.6, E-12(LDAP)

**验证**: 手动验证——多租户用户登录后看到选择页，选择后进入正确租户；单租户用户直接进入

---

#### T-09: Header 租户切换器

- [x] 完成

**文件**:
- 修改: `src/frontend/platform/src/layout/MainLayout.tsx`
- 修改: `src/frontend/platform/src/contexts/userContext.tsx`
- 修改: `src/frontend/platform/src/contexts/locationContext.tsx`
- 修改: `src/frontend/platform/src/controllers/API/user.ts`

**依赖**: T-06, T-05(后端 API)

**内容**:
1. **userContext.tsx 改动**:
   - user 对象扩展: `tenant_id`, `tenant_name`, `tenant_code`, `tenant_logo` 字段
   - `getUserInfo()` 返回值中提取 tenant 信息（后端 UserRead 已在 T-05 扩展）

2. **locationContext.tsx 改动**:
   - `loadConfig()` 中从 `getAppConfig()` 提取 `multiTenantEnabled`: `setAppConfig(prev => ({ ...prev, multiTenantEnabled: !!res.multi_tenant_enabled }))`

3. **user.ts 改动**:
   - `getUserInfo()` 返回类型适配 tenant 字段

4. **MainLayout.tsx 改动**:
   - Header 右侧（暗色/语言切换器左侧）增加租户切换器:
     - 仅 `appConfig.multiTenantEnabled` 时渲染
     - 显示当前租户 Logo（小图标） + 租户名
     - `SelectHover` 下拉:
       - 当前租户（带 ✓ 标记）
       - 其他租户列表（调 `getUserTenantsApi()`，mount 或首次 hover 时加载）
       - 分隔线
       - 「租户管理」入口（仅 `user.role === 'admin'`），NavLink 到 `/admin/tenants`
     - 选择其他租户: `bsConfirm(t('tenant.switchConfirm'))` → `switchTenantApi(id)` → `location.reload()`

5. **路由守卫**（userContext.tsx）:
   - `multi_tenant_enabled && user.tenant_id === 0` → 重定向 `/tenant-select`

**覆盖 AC**: AC-6.4, AC-6.5, AC-7.1(菜单可见性)

**验证**: 手动验证——多租户用户看到切换器，单租户/multi_tenant=false 不显示；切换确认 + 页面刷新正确

---

#### T-10: 端到端验证 + 收尾

- [x] 完成

**依赖**: T-01 ~ T-09

**内容**:
1. **全流程验证**:
   - 系统管理员创建租户 → 列表出现 → 编辑信息 → 添加用户 → 停用 → 该用户被 403 → 启用恢复 → 删除（先移除用户）
   - 多租户用户登录 → 租户选择页 → 选择进入 → Header 切换到另一个租户 → 数据隔离验证
   - 单租户用户登录 → 直接进入
   - multi_tenant.enabled=false → 所有租户 UI 不显示

2. **Code Style**:
   - `black .` + `ruff check . --fix`（后端）
   - TypeScript 编译检查（前端）

3. **tasks.md 更新**: 标记所有任务完成，更新状态表

**覆盖 AC**: 全部 AC 端到端覆盖

**验证**: 完整 E2E 手动测试清单 + `/e2e-test` 生成 API 测试

---

## 依赖关系

```
T-01 (Schemas) ──┐
T-02 (DAO)    ───┤──→ T-03 (Service) ──→ T-04 (API Router)
                 │                         │
                 │                    T-05 (Login + Middleware)
                 │                         │
T-06 (FE API) ──────→ T-07a (List+Route) ──→ T-07b (Dialogs)
                 │                         │
                 ├────→ T-08 (Tenant Select) ←─┘
                 │
                 └────→ T-09 (Header Switcher) ←─┘
                                    │
                            T-10 (E2E + 收尾)
```

T-01, T-02, T-06 可并行。T-03 依赖 T-01+T-02。T-04 依赖 T-03。T-05 依赖 T-01+T-02。T-07a 依赖 T-06。T-07b 依赖 T-07a。T-08/T-09 依赖 T-06 + 对应后端任务。T-10 依赖全部。
