# Tasks: 策略角色、菜单权限与配额管理

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 30 条 AC，9 个 AD，5 处审查修复 |
| tasks.md | ✅ 已拆解 | 13 个任务，30 条 AC 全覆盖 |
| 实现 | ✅ 已完成 | 13 / 13 完成，34 测试全通过 |

---

## 开发模式

**后端 Test-First（务实版）**：
- 理想流程：先写测试（红），再写实现（绿）
- 务实适配：F000 已搭建 pytest 基础设施（conftest.py、db fixture），直接使用
- 如果某任务的测试编写成本极高，可标注 `**测试降级**: 手动验证 + TODO 标记`

**前端**：F005 为纯后端 Feature（AD），无前端任务。前端改造归 F010。

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## Tasks

### 基础设施（无测试配对）

- [x] **T01**: Alembic 迁移 — Role 表扩展
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v2_5_0_f005_role_menu_quota.py`
  **逻辑**:
  - `down_revision` = F004 系列最后一个迁移
  - `ADD COLUMN department_id INT NULL`，添加索引 `idx_role_department_id`
  - `ADD COLUMN quota_config JSON NULL`
  - `ADD COLUMN role_type VARCHAR(16) NOT NULL DEFAULT 'tenant'`
  - `DROP INDEX group_role_name_uniq`（旧唯一约束）
  - `CREATE UNIQUE INDEX uk_tenant_roletype_rolename ON role(tenant_id, role_type, role_name)`
  - 数据回填：`UPDATE role SET role_type='global' WHERE id IN (1, 2)`
  - 数据迁移：将 `knowledge_space_file_limit > 0` 的旧值写入 `quota_config` JSON
  - downgrade: 逆操作（删新列、恢复旧约束）
  **验证**: `alembic upgrade head` 成功；检查 role 表结构包含新字段；AdminRole/DefaultRole 的 role_type='global'
  **依赖**: 无

- [x] **T02**: Role ORM 模型更新
  **文件**: `src/backend/bisheng/database/models/role.py`
  **逻辑**:
  - `RoleBase` 新增字段：`role_type`（String(16), default='tenant'）、`department_id`（Optional[int]）、`quota_config`（Optional[dict], JSON 列）
  - `group_id` 和 `knowledge_space_file_limit` 添加 `# deprecated` 注释（AD-07, AD-08）
  - `Role.__table_args__` 唯一约束从 `(group_id, role_name)` 改为 `(tenant_id, role_type, role_name)`
  - 新增 DAO 方法：
    - `get_visible_roles(tenant_id, keyword, page, limit, department_path=None)` — 合并全局+租户角色查询，支持部门子树过滤（AC-03, AC-04, AC-04b）
    - `count_visible_roles(tenant_id, keyword, department_path=None)` — 对应计数
    - `aget_visible_roles(...)` / `acount_visible_roles(...)` — 异步版本
  - 查询逻辑：`WHERE id > 1 AND ((role_type='global') OR (tenant_id=:tid AND role_type='tenant')) AND (:dept_path IS NULL OR department_id IN (SELECT id FROM department WHERE path LIKE :dept_path||'%'))`
  **验证**: 导入无报错；DAO 方法可被 Service 调用
  **依赖**: T01

- [x] **T03**: 错误码定义
  **文件**: `src/backend/bisheng/common/errcode/role.py`
  **逻辑**:
  - 定义 6 个错误码类，继承 `BaseErrorCode`：
    ```
    24000 RoleNotFoundError        — 角色不存在
    24001 QuotaExceededError       — 资源配额超限
    24002 RoleNameDuplicateError   — 角色名重复
    24003 RolePermissionDeniedError — 无权操作此角色
    24004 RoleBuiltinProtectedError — 内置角色不可删改
    24005 QuotaConfigInvalidError  — quota_config 值非法
    ```
  - 更新 `features/v2.5.0/release-contract.md`「已分配模块编码」表，注册 `240 | role | common/errcode/role.py`
  **覆盖 AC**: AC-06, AC-07, AC-09, AC-10b, AC-10c, AC-20, AC-22
  **依赖**: 无

- [x] **T04**: role/ DDD 模块骨架 + Router 注册
  **文件**:
  - `src/backend/bisheng/role/__init__.py`
  - `src/backend/bisheng/role/api/__init__.py`
  - `src/backend/bisheng/role/api/router.py`
  - `src/backend/bisheng/role/api/endpoints/__init__.py`
  - `src/backend/bisheng/role/domain/__init__.py`
  - `src/backend/bisheng/role/domain/schemas/__init__.py`
  - `src/backend/bisheng/role/domain/schemas/role_schema.py`
  - `src/backend/bisheng/role/domain/services/__init__.py`
  - `src/backend/bisheng/api/router.py`（修改，注册 role 模块路由）
  **逻辑**:
  - 创建空模块骨架（`__init__.py` 文件）
  - `role/api/router.py` 创建 `role_router` APIRouter，注册到全局 `api/router.py`
  - `role_schema.py` 定义 Pydantic DTO（spec §5.5）：
    ```python
    RoleCreateRequest(role_name: str, department_id: Optional[int], quota_config: Optional[dict], remark: Optional[str])
    RoleUpdateRequest(role_name: Optional[str], department_id: Optional[int], quota_config: Optional[dict], remark: Optional[str])
    RoleListResponse(id, role_name, role_type, department_id, department_name, quota_config, remark, user_count, is_readonly, create_time, update_time)
    EffectiveQuotaItem(resource_type, role_quota, tenant_quota, tenant_used, user_used, effective)
    MenuUpdateRequest(menu_ids: list[str])
    ```
  **验证**: `from bisheng.role.api.router import role_router` 成功
  **依赖**: 无（可与 T01-T03 并行）

- [x] **T05**: WebMenuResource 枚举更新 + init_data 调整
  **文件**:
  - `src/backend/bisheng/database/models/role_access.py`（修改 WebMenuResource 枚举）
  - `src/backend/bisheng/common/init_data.py`（修改默认角色初始化）
  **逻辑**:
  - 更新 `WebMenuResource` 枚举（spec §5.2）：
    - 新增：WORKSTATION, ADMIN, TOOL, MCP, CHANNEL, DATASET, MARK_TASK
    - 保留：BUILD, KNOWLEDGE, KNOWLEDGE_SPACE, MODEL, EVALUATION, BOARD, SUBSCRIPTION
    - Deprecated 保留：FRONTEND, BACKEND, CREATE_DASHBOARD
  - `init_data.py` 中：
    - AdminRole(id=1) 初始化时设置 `role_type='global'`（如果 init_data 创建角色时可设置）
    - DefaultRole(id=2) 初始化时设置 `role_type='global'`
    - DefaultRole 的默认 WEB_MENU 权限更新为新枚举值（保持兼容：BUILD, KNOWLEDGE, MODEL, KNOWLEDGE_SPACE, WORKSTATION）
  - `auth.py` 的 `get_roles_web_menu()` 方法中：管理员全集更新为新 WebMenuResource 全部值
  **覆盖 AC**: AC-13, AC-14
  **依赖**: T02（Role 模型需有 role_type 字段）

### 后端 Domain Service（Test-First 配对）

- [x] **T06**: QuotaService 单元测试
  **文件**: `src/backend/test/test_quota_service.py`
  **逻辑**: Mock DAO 层（RoleDao, UserRoleDao, TenantDao），测试 QuotaService 核心方法：
  - `test_admin_always_unlimited` → AC-19：管理员返回 -1
  - `test_multi_role_take_max` → AC-17：多角色取最大值（5, 10 → 10）
  - `test_any_role_unlimited_returns_unlimited` → AC-16：任一角色 -1 → 返回 -1
  - `test_missing_key_uses_default` → AC-18：quota_config 缺失 key → 用 DEFAULT_ROLE_QUOTA
  - `test_null_quota_config_uses_default` → AC-18 变体：quota_config=NULL → 全部用默认值
  - `test_no_roles_uses_default` → §3 边界：无角色 → 用默认值
  - `test_tenant_limit_caps_role_quota` → AC-22：租户上限 50，已用 45，角色配额 10 → effective=5
  - `test_tenant_null_means_unlimited` → §3 边界：租户 quota_config=NULL → 不限制
  - `test_check_quota_raises_on_exceed` → AC-20：超限抛 QuotaExceededError
  - `test_check_quota_passes_when_available` → AC-21：配额充足 → True
  - `test_quota_config_validation` → AC-10c：非法值（非整数、负数非-1）校验
  **覆盖 AC**: AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-10c
  **依赖**: T03（错误码）, T04（Schema）

- [x] **T07**: QuotaService 实现
  **文件**: `src/backend/bisheng/role/domain/services/quota_service.py`
  **逻辑**:
  - 定义 `DEFAULT_ROLE_QUOTA` 常量（8 个资源类型，spec §5.3）
  - 定义 `QuotaResourceType` 常量类
  - 实现 `QuotaService`（@classmethod，无实例状态）：
    - `get_effective_quota(user_id, resource_type, tenant_id, login_user)` → int
      1. 管理员短路 → -1
      2. 获取用户角色列表 → 多角色取 max（遇 -1 立即返回 -1）
      3. 无角色 → DEFAULT_ROLE_QUOTA
      4. 获取租户 quota_config → 租户不限制（-1 或 NULL）→ 仅看角色
      5. 租户剩余 = 租户上限 - 已用
      6. effective = min(max(tenant_remaining, 0), role_quota)
    - `check_quota(user_id, resource_type, tenant_id, login_user)` → bool / raise QuotaExceededError
    - `get_all_effective_quotas(user_id, tenant_id, login_user)` → List[EffectiveQuotaItem]
    - `get_tenant_resource_count(tenant_id, resource_type)` → int（按资源类型 dispatch 到不同 DAO 的 COUNT 查询）
    - `get_user_resource_count(user_id, resource_type)` → int
    - `validate_quota_config(config: dict)` → None / raise QuotaConfigInvalidError
  - 实现 `@require_quota(resource_type)` 装饰器：
    - 从 kwargs 提取 `login_user`（LoginUser 类型）
    - 调用 `QuotaService.check_quota(login_user.user_id, resource_type, login_user.tenant_id, login_user)`
    - 注：装饰器定义在 F005，实际应用在 F008
  **测试**: T06 全部通过
  **覆盖 AC**: AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-10c
  **依赖**: T02, T03, T04, T06

- [x] **T08**: RoleService 单元测试
  **文件**: `src/backend/test/test_role_service.py`
  **逻辑**: Mock DAO 层 + PermissionService，测试 RoleService：
  - `test_create_role_as_tenant_admin` → AC-01：租户管理员创建角色
  - `test_create_global_role_as_admin` → AC-02：系统管理员创建全局角色
  - `test_create_role_duplicate_name` → AC-09：重名返回 24002
  - `test_create_role_invalid_quota` → AC-10c：非法 quota_config 返回 24005
  - `test_create_role_as_regular_user_denied` → AC-10b：普通用户拒绝
  - `test_list_roles_tenant_admin_sees_global_and_tenant` → AC-03：租户管理员可见范围
  - `test_list_roles_admin_sees_all_except_adminrole` → AC-04：系统管理员看全部（AdminRole 除外）
  - `test_list_roles_dept_admin_sees_subtree_only` → AC-04b：部门管理员仅看子树
  - `test_update_global_role_by_tenant_admin_denied` → AC-06：租户管理员改全局角色被拒
  - `test_delete_builtin_role_denied` → AC-07：删除内置角色被拒
  - `test_delete_role_cascades` → AC-08：级联删除 UserRole + RoleAccess
  - `test_update_menu` → AC-11：更新菜单权限
  - `test_get_menu` → AC-12：查询菜单权限
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-04b, AC-06, AC-07, AC-08, AC-09, AC-10b, AC-10c, AC-11, AC-12
  **依赖**: T02, T03, T04

- [x] **T09**: RoleService 实现
  **文件**: `src/backend/bisheng/role/domain/services/role_service.py`
  **逻辑**:
  - `RoleService`（@classmethod，无实例状态）：
    - `create_role(req: RoleCreateRequest, login_user: LoginUser)` → Role
      1. 权限检查四级短路（admin → tenant admin → dept admin → reject 24003）
      2. 系统管理员创建 → role_type='global'；其他 → role_type='tenant'
      3. 校验 department_id（如有）→ 查 Department 是否存在且 active
      4. 校验 quota_config（如有）→ QuotaService.validate_quota_config()
      5. 唯一性检查（tenant_id + role_type + role_name）→ 24002
      6. 调用 RoleDao 创建
      7. 审计日志（AuditLogService.create_role）
    - `list_roles(keyword, page, limit, login_user)` → PageData[RoleListResponse]
      1. admin → 全部（无 dept 过滤）；tenant admin → 全部（无 dept 过滤）；dept admin → 子树过滤
      2. 调用 RoleDao.get_visible_roles
      3. 关联查询 department_name（批量 DepartmentDao）
      4. 统计 user_count（批量 UserRoleDao）
      5. 标记 is_readonly（全局角色对非系统管理员只读）
    - `get_role(role_id, login_user)` → RoleListResponse
    - `update_role(role_id, req, login_user)` → Role
      1. 权限检查 + 全局角色对租户管理员只读（24003）
      2. 内置角色保护：AdminRole/DefaultRole 不可修改 role_name（24004）
      3. quota_config 校验 + role_name 去重
      4. 更新 + 审计日志
    - `delete_role(role_id, login_user)` → None
      1. 权限检查 + 内置角色保护（24004）
      2. 级联删除：UserRole + RoleAccess
      3. 审计日志
    - `update_menu(role_id, menu_ids, login_user)` → None
      1. 权限检查 + AdminRole 不可改菜单
      2. 委托 RoleAccessDao.update_role_access_all(role_id, AccessType.WEB_MENU, menu_ids)
    - `get_menu(role_id, login_user)` → List[str]
  **测试**: T08 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-04b, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-10b, AC-10c, AC-11, AC-12
  **依赖**: T02, T03, T04, T05, T08

### 后端 API 层（Test-First 配对）

- [x] **T10**: API 端点集成测试
  **文件**: `src/backend/test/test_role_api.py`
  **逻辑**: 使用 TestClient（httpx），测试 HTTP 端点 happy path + error path：
  - `test_create_role_success` → AC-01：POST /api/v1/roles → 201
  - `test_create_role_duplicate_name` → AC-09：POST /api/v1/roles → 24002
  - `test_list_roles` → AC-03：GET /api/v1/roles → 分页响应
  - `test_get_role_detail` → AC-10：GET /api/v1/roles/{id} → 含 department_name + user_count
  - `test_update_role` → AC-05：PUT /api/v1/roles/{id} → 成功
  - `test_delete_builtin_denied` → AC-07：DELETE /api/v1/roles/2 → 24004
  - `test_update_menu` → AC-11：POST /api/v1/roles/{id}/menu → 成功
  - `test_get_effective_quota` → AC-15：GET /api/v1/quota/effective → 配额列表
  - `test_list_roles_as_admin` → AC-04：GET /api/v1/roles（系统管理员）→ AdminRole 除外的全部角色
  - `test_legacy_role_add` → AC-24：POST /role/add → 兼容成功
  - `test_legacy_role_list` → AC-25：GET /role/list → 兼容成功
  - `test_legacy_role_access_refresh` → AC-26：POST /role_access/refresh → 兼容成功
  - `test_legacy_role_access_list` → AC-27：GET /role_access/list → 兼容成功
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-07, AC-09, AC-10, AC-11, AC-15, AC-24, AC-25, AC-26, AC-27
  **依赖**: T07, T09

- [x] **T11**: API 端点 + Router 注册
  **文件**:
  - `src/backend/bisheng/role/api/endpoints/role.py`
  - `src/backend/bisheng/role/api/endpoints/role_access.py`
  - `src/backend/bisheng/role/api/endpoints/quota.py`
  - `src/backend/bisheng/role/api/router.py`（更新注册）
  **逻辑**:
  - `role.py`（5 个端点）：
    - `POST /roles` → `RoleService.create_role()`
    - `GET /roles` → `RoleService.list_roles()`，query params: keyword, page, limit
    - `GET /roles/{role_id}` → `RoleService.get_role()`
    - `PUT /roles/{role_id}` → `RoleService.update_role()`
    - `DELETE /roles/{role_id}` → `RoleService.delete_role()`
    - 认证：`login_user: LoginUser = Depends(LoginUser.get_login_user)`
    - 响应：`UnifiedResponseModel`（resp_200 / errcode.return_resp）
  - `role_access.py`（2 个端点）：
    - `POST /roles/{role_id}/menu` → `RoleService.update_menu()`
    - `GET /roles/{role_id}/menu` → `RoleService.get_menu()`
  - `quota.py`（2 个端点）：
    - `GET /quota/effective` → `QuotaService.get_all_effective_quotas()`
    - `GET /quota/usage` → 各资源类型用量统计
  - `router.py` 注册所有子路由
  **测试**: T10 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-04b, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-10b, AC-10c, AC-11, AC-12, AC-15
  **依赖**: T07, T09, T10

### 集成适配

- [x] **T12**: 旧 API 向后兼容适配
  **文件**: `src/backend/bisheng/user/api/user.py`
  **逻辑**:
  - 修改 5 个旧端点，内部委托 RoleService：
    - `POST /role/add`（L318）→ 调用 `RoleService.create_role()`，将旧 RoleCreate 参数转换为 RoleCreateRequest
    - `PATCH /role/{role_id}`（L349）→ 调用 `RoleService.update_role()`
    - `GET /role/list`（L378）→ 调用 `RoleService.list_roles()`，响应格式保持原有结构 `{"data": [...], "total": N}`
    - `DELETE /role/{role_id}`（L408）→ 调用 `RoleService.delete_role()`
    - `POST /role_access/refresh`（L500）→ 调用 `RoleService.update_menu()`
    - `GET /role_access/list`（L520）→ 保持原有逻辑（直接查 RoleAccessDao），因为旧 API 支持查询非 WEB_MENU 类型
  - 保持旧端点的 URL 路径和 HTTP 方法不变
  - 旧参数 `group_id` 在新 Service 中可忽略（deprecated）
  **覆盖 AC**: AC-24, AC-25, AC-26, AC-27
  **测试降级**: 手动验证 + T10 中的 legacy API 测试用例覆盖
  **依赖**: T09, T11

- [x] **T13**: LoginUser 集成 + init_data 更新
  **文件**:
  - `src/backend/bisheng/user/domain/services/auth.py`（修改 get_roles_web_menu）
  - `src/backend/bisheng/common/init_data.py`（修改默认角色初始化）
  **逻辑**:
  - `auth.py` 的 `get_roles_web_menu(user)`（L364-386）：
    - 管理员分支：`web_menu = [one.value for one in WebMenuResource]` — 已自动包含新增枚举值（AC-14）
    - 非管理员分支：无需改动，通过 RoleAccessDao 查询 WEB_MENU 类型记录（AC-13）
    - 确认 `WebMenuResource` 导入路径无误
  - `init_data.py`：
    - AdminRole 初始化时添加 `role_type='global'`（如 ORM 支持则直接设置）
    - DefaultRole 初始化时添加 `role_type='global'`
    - DefaultRole 的默认 WEB_MENU 权限：
      - 保留：BUILD, KNOWLEDGE, MODEL, KNOWLEDGE_SPACE
      - 新增：WORKSTATION（用户端入口应默认可见）
      - 移除：BACKEND, FRONTEND（deprecated，由新菜单项替代）
    - 注意：init_data 仅在首次无角色时执行，已有数据不受影响
  **覆盖 AC**: AC-13, AC-14
  **测试降级**: 手动验证 — 登录 admin 检查 web_menu 包含所有新枚举值；登录普通用户检查 web_menu 正确
  **依赖**: T05, T09

---

## 依赖关系图

```
T01 (migration) ──→ T02 (ORM) ──→ T05 (enum+init) ──→ T13 (LoginUser)
                        │
T03 (errcode)  ─┐      ├──→ T08 (service test) ──→ T09 (service impl) ──→ T12 (legacy)
                │      │                                    │
T04 (skeleton) ─┤      └──→ T06 (quota test) ──→ T07 (quota impl)──┐
                │                                                     │
                └──────────────────────────────→ T10 (api test) ──→ T11 (api impl)
```

**关键路径**: T01 → T02 → T09 → T11 → T12
**并行轨道**: T03 + T04（立即开始）; T06→T07 与 T08 并行; T05 与 T06/T08 并行

---

## AC 覆盖矩阵

| AC | T01 | T02 | T03 | T04 | T05 | T06 | T07 | T08 | T09 | T10 | T11 | T12 | T13 |
|----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|
| AC-01 | | | | | | | | ✓ | ✓ | ✓ | ✓ | | |
| AC-02 | | | | | | | | ✓ | ✓ | | ✓ | | |
| AC-03 | | | | | | | | ✓ | ✓ | ✓ | ✓ | | |
| AC-04 | | | | | | | | ✓ | ✓ | ✓ | ✓ | | |
| AC-04b | | ✓ | | | | | | ✓ | ✓ | | ✓ | | |
| AC-05 | | | | | | | | | ✓ | ✓ | ✓ | | |
| AC-06 | | | ✓ | | | | | ✓ | ✓ | | ✓ | | |
| AC-07 | | | ✓ | | | | | ✓ | ✓ | ✓ | ✓ | | |
| AC-08 | | | | | | | | ✓ | ✓ | | ✓ | | |
| AC-09 | | | ✓ | | | | | ✓ | ✓ | ✓ | ✓ | | |
| AC-10 | | | | | | | | | ✓ | ✓ | ✓ | | |
| AC-10b | | | ✓ | | | | | ✓ | ✓ | | ✓ | | |
| AC-10c | | | ✓ | | | ✓ | ✓ | ✓ | ✓ | | ✓ | | |
| AC-11 | | | | | | | | ✓ | ✓ | ✓ | ✓ | | |
| AC-12 | | | | | | | | ✓ | ✓ | | ✓ | | |
| AC-13 | | | | | ✓ | | | | | | | | ✓ |
| AC-14 | | | | | ✓ | | | | | | | | ✓ |
| AC-15 | | | | | | | ✓ | | | ✓ | ✓ | | |
| AC-16 | | | | | | ✓ | ✓ | | | | | | |
| AC-17 | | | | | | ✓ | ✓ | | | | | | |
| AC-18 | | | | | | ✓ | ✓ | | | | | | |
| AC-19 | | | | | | ✓ | ✓ | | | | | | |
| AC-20 | | | ✓ | | | ✓ | ✓ | | | | | | |
| AC-21 | | | | | | ✓ | ✓ | | | | | | |
| AC-22 | | | ✓ | | | ✓ | ✓ | | | | | | |
| AC-23 | | | | | | | ✓ | | | | | | |
| AC-24 | | | | | | | | | | ✓ | | ✓ | |
| AC-25 | | | | | | | | | | ✓ | | ✓ | |
| AC-26 | | | | | | | | | | ✓ | | ✓ | |
| AC-27 | | | | | | | | | | ✓ | | ✓ | |

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

_(实现阶段填写)_
