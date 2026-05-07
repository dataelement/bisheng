# Tasks: 租户用户管理 UI 与 F012 派生模型对齐（F024）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**基线依赖**: F010（被修订）+ F011（Tenant 树）+ F012（leaf 派生）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已草 + 3 项采访决策对齐（AD-06=A / AD-03=C / 节奏=A） | 301 行 |
| tasks.md | ✅ 已拆解 | 6 个任务 |
| 实现 | ✅ 完成（2026-05-07） | 6 / 6 完成；后端 15 新增单测 + 40 既有单测全绿；前端 TS 编译无新错误 |

---

## 开发模式

- **后端 Test-First**：DAO 新方法 + API 410 端点都先写测试再写实现。沿用 P0 / G1 / G2 修复期的 Mock 模式（`monkeypatch` + `_FakeSession`）。
- **前端手动验证**：Platform 前端无自动化测试框架，手动验证 + 联调 114 / 120 真实环境。
- **零 schema 变更**：AD-03 决策 C 之后无 DB migration，无启动钩子，回滚零数据风险。

---

## Tasks

### 后端：DAO 层（Test-First 配对）

- [x] **T001**: `UserDepartmentDao.aget_users_by_tenant_subtree` 单元测试
  **文件**: `src/backend/test/test_tenant_users_query_source.py`
  **逻辑**: 用 sqlite + SQLModel ORM 起内存库，建 Tenant + Department + UserDepartment + UserTenant + User 五张表，构造场景：
  - 用户 A 主部门在 Tenant 5 子树 → 应返回
  - 用户 B 主部门在 Tenant 5 子树外 → 不应返回
  - 用户 C 兼职部门在 Tenant 5 子树（is_primary=0），主部门在外 → 不应返回（与 F012 一致）
  - 用户 D 既无主部门也无 UserTenant 行 → 不返回
  - 用户 E 主部门在 Tenant 5 子树 + UserTenant 行（last_access_time=...）→ 返回时 join_time 字段 = UserTenant.last_access_time
  - 用户 F 主部门在 Tenant 5 子树但**没有** UserTenant 行 → 仍返回（LEFT JOIN）, join_time=NULL
  - **关键**: 用户 G 仅有 UserTenant(tenant_id=5) 行但主部门在别处（v2.5.0 残留幽灵行）→ 不应返回（AC-12 验证）
  - keyword 过滤、分页、total 计数
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-12
  **依赖**: 无

- [x] **T002**: `UserDepartmentDao.aget_users_by_tenant_subtree` 实现
  **文件**: `src/backend/bisheng/database/models/department.py`
  **逻辑**: 新增 classmethod，签名 `aget_users_by_tenant_subtree(tenant_id, page, page_size, keyword) -> tuple[list[dict], int]`
  - 解析 `tenant.root_dept_id` → 取得 root dept 的 path（若 tenant 无 root_dept 配置，回退到 `WHERE department.tenant_id == tenant_id` —— 兼容 v2.5.0 / v2.5.1 早期数据）
  - SQL 形态见 spec §7 伪代码：`User → UserDepartment(is_primary=1) → Department(path LIKE root_path || '%')`，UserTenant 仅 LEFT JOIN 取 last_access_time
  - 返回格式与现有 `UserTenantDao.aget_tenant_users` 完全一致：`[{user_id, user_name, avatar, join_time}], total`
  - 用 `bypass_tenant_filter()` 包裹（管理路径）
  **测试**: T001 全部通过
  **覆盖 AC**: AC-01~04, AC-12
  **依赖**: T001

### 后端：Service 层

- [x] **T003**: `TenantService.aget_tenant_users` 切源 + `aadd_users`/`aremove_user` 加 deprecated
  **文件**: `src/backend/bisheng/tenant/domain/services/tenant_service.py`
  **逻辑**:
  - `aget_tenant_users` 内部调用从 `UserTenantDao.aget_tenant_users` 改为 `UserDepartmentDao.aget_users_by_tenant_subtree`，参数 / 返回值不变
  - `aadd_users` 顶部加 `import warnings; warnings.warn("F024: aadd_users is deprecated...", DeprecationWarning)` + `logger.warning('F024 deprecated: aadd_users called for tenant %d, %d uids', ...)`；保留实现给内部脚本用
  - `aremove_user` 同上
  **测试**: 现有 `test_tenant_users_query_source.py` 走完整 service 调用链路验证（不只 DAO 层）
  **覆盖 AC**: AC-01~04, AC-15
  **依赖**: T002

### 后端：API 层

- [x] **T004**: API 端点改 410 Gone + 端点测试
  **文件**:
  - 实现: `src/backend/bisheng/tenant/api/endpoints/tenant_users.py`
  - 测试: `src/backend/test/test_tenant_membership_endpoints_deprecated.py`
  **逻辑**:
  - `POST /tenants/{id}/users` 端点函数体替换为返回 `JSONResponse(status_code=410, content={...})`，参考 `bisheng/tenant/api/endpoints/user_tenant.py:30` `switch_tenant_deprecated` 的写法
  - `DELETE /tenants/{id}/users/{user_id}` 同上
  - `GET /tenants/{id}/users` 不动（路径不变，service 内部数据源已切）
  - 测试用 FastAPI TestClient + httpx，验证两个端点都返 410 + 响应 body 含 `migration` 字段
  - 测试不带 auth 也返 410（与 `switch_tenant_deprecated` 一致 —— deprecated 端点不需要 auth dependency）
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-14
  **依赖**: T003

### 前端：Platform UI

- [x] **T005**: TenantUserDialog 改造 + i18n + API deprecation 注释
  **文件**:
  - `src/frontend/platform/src/pages/TenantPage/components/TenantUserDialog.tsx`
  - `src/frontend/platform/src/controllers/API/tenant.ts`
  - `src/frontend/platform/public/locales/{en-US,zh-Hans,ja}/bs.json`
  **逻辑**:
  - `TenantUserDialog.tsx`：
    - 删除 `DepartmentUsersSelect` picker + `addTenantUsersApi` 调用（连带 `pickedToAdd` / `addingUsers` / `handleAddPicked` / `rootDeptId` 状态、effect、UI）
    - 删除每行的「移除用户」按钮（连带 `handleRemoveUser` / `removeTenantUserApi` 调用）
    - 在对话框顶部加 Banner（用 `bs-ui` 现有的 Alert / 提示组件）：
      - title: `t('tenant.membershipBanner.title')`
      - body: `t('tenant.membershipBanner.body')`
      - cta: `t('tenant.membershipBanner.cta')` → `<Link to='/admin/department'>` 跳转部门页
    - 保留：列表展示、`handlePromoteAdmin` / `handleRevokeAdmin`、Root tenant 短路（`isRootTenant`）、关闭按钮
  - `tenant.ts`：`addTenantUsersApi` / `removeTenantUserApi` 函数定义保留（避免破坏可能的旧引用），加 JSDoc `@deprecated F024 — endpoint returns 410 Gone since v2.5.1`
  - 三份 i18n 文件加 `tenant.membershipBanner.title` / `body` / `cta`：
    - zh-Hans：`成员管理已迁移` / `成员归属由用户主部门决定。添加/移除请到组织管理。本页只展示当前归属并提供管理员配置。` / `前往组织管理`
    - en-US：`Membership management has moved` / `Tenant membership is derived from the user's primary department. To add/remove members, edit them in Organization. This page only shows current members and admin assignment.` / `Go to Organization`
    - ja：（参照 zh-Hans 对照翻译）
  **覆盖 AC**: AC-05, AC-06, AC-07
  **手动验证**:
  - 打开「租户管理」→ 点任一非 Root 租户的「用户管理」按钮
    - ✅ 看到 Banner，「添加用户」picker 不存在，行内「移除用户」按钮不存在
    - ✅ 点 Banner 的「前往组织管理」跳转到 `/admin/department`
    - ✅ 「设为管理员/取消管理员」按钮仍可用，行为不变
  - 打开 Root 租户的「用户管理」对话框：Banner 显示，无管理员按钮（沿用 `isRootTenant` 短路）
  - 列表数据：通过 API 调用看到的成员 = 主部门挂在该租户子树下的用户（不再含 v2.5.0 时期 aadd_users 加进来但主部门在外的"幽灵"用户）
  **依赖**: T004

### 集成回归 + 文档

- [x] **T006**: 联调验证 + release-notes 起草
  **文件**:
  - 测试运行（无新文件）
  - `features/v2.5.1/release-contract.md`
  **逻辑**:
  - 跑全套相关后端单测：`pytest test/test_tenant_users_query_source.py test/test_tenant_membership_endpoints_deprecated.py test/test_apply_local_primary_dept_sync.py test/test_dept_member_add_sync.py test/test_user_department_service.py test/test_member_edit_form_scope_filtering.py test/test_tenant_resolver.py test/test_sync_user_scope_clear.py test/test_user_tenant_sync_subtree.py` 应全过
  - 在 release-contract.md 的「F010 修订记录」段（如不存在则新建）加一行：F024 修订 F010 AC-3.x（POST/DELETE /tenants/{id}/users 410）/ AC-7.x（列表数据源切到主部门 JOIN）
  - 起草 release-notes 片段（待 PM 收口）：
    - **BREAKING**: `POST /api/v1/tenants/{id}/users` / `DELETE /api/v1/tenants/{id}/users/{user_id}` 改为 HTTP 410 Gone
    - **行为变更**: `GET /api/v1/tenants/{id}/users` 数据源从 UserTenant 切到主部门派生；v2.5.0 时期的"幽灵成员"不再展示
    - **迁移指引**: 用 `POST /api/v1/department/{dept_id}/members/{user_id}/apply-edit` 改主部门即可改租户归属
  **覆盖 AC**: 全部
  **依赖**: T005

---

## 实际偏差记录

- **偏差 1（T001 测试策略）**：spec 起草时倾向 mock-based 测试（与 `test_tenant_resolver.py` / `test_user_department_service.py` 对齐），但 DAO 的 SQL JOIN + path LIKE 是核心逻辑，纯 mock 信号不足。最终选择 **aiosqlite 集成测试**：自带 5 表 DDL + `pytest_asyncio` 异步 fixture + `monkeypatch` 把 `get_async_db_session` 指到测试引擎。代价是要绕过 conftest premock 的 `bisheng.user.domain.models.user`：写一个真 SQLModel `_TestUser` 类 *augment*（不替换）conftest 已注入的 mock module，保留其他测试需要的 `UserDao` 等 attr 不变。
- **偏差 2（T005 跳转目标）**：spec 写 Banner CTA 跳转 `/admin/department`，实际项目里部门管理在 `/sys` 页的 `organization` tab 下（`SystemPage` 用 Radix Tabs，无 URL 参数），路由 `/admin/department` 不存在。改为跳转 `/sys`，超管/部门管理员/Child Admin 默认进入 organization tab，体验等价。
- **偏差 3（T004 GET 端点测试覆盖）**：spec 写"测试不带 auth 也返 410"，实际靠 `Dependant.dependencies` 树检查 `name == 'login_user'` 来判定（`__qualname__` 不可靠，因为 `LoginUser.get_admin_user` 是 bound method 没含 `UserPayload`）。结果：3 个 410 端点确实没有 `login_user` dependency；GET 端点保留了 dependency。覆盖等价 spec 意图。
- **偏差 4（T003 是否需要单独测试）**：tasks.md 里 T003 的「测试」字段写"现有 `test_tenant_users_query_source.py` 走完整 service 调用链路验证"。实际由于 T001/T002 直接打到 DAO 层，service 层只是薄封装（return shape 不变），没单独写 service 测试。Service 切源行为通过 T001 的 7 个用例间接覆盖（下层 DAO 通过 = service 上层透传通过）。AC-15（deprecation logger.warning）由人工 grep 确认，未写自动化用例。
