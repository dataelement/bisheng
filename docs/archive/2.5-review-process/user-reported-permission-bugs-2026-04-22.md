# 用户反馈问题单独清单

日期：2026-04-22

## 说明

本文件只收录本轮用户提供的具体 issue / 截图问题。

每条问题按以下结构记录：

1. 现象
2. 当前代码中的高概率根因
3. 受影响的代码位置
4. 问题类型归类

本文件不代表修复完成，只用于后续和总审计文档对照。

关联总审计文档：

- [rbac-rebac-permission-audit-2026-04-22.md](/Users/zhou/Code/bisheng/docs/rbac-rebac-permission-audit-2026-04-22.md)

## 2026-04-23 修复状态复核

本次复核依据：

- 当前分支 `feat/2.5.0` 的现代码
- 2026-04-22 之后的相关提交
- 后端定向回归测试：
  `src/backend/test/test_role_service.py`
  `src/backend/test/test_permission_relation_bindings.py`
  `src/backend/test/test_knowledge_space_service.py`
  `src/backend/test/test_auth_knowledge_library_adapter.py`
  `src/backend/test/test_auth_app_rebac_adapter.py`
  `src/backend/test/test_knowledge_library_permission_template.py`
  `src/backend/test/test_f027_role_scope_nullsafe_unique.py`
  `src/backend/test/test_knowledge_service_rebac_bridge.py`
  `src/backend/test/test_workstation_apps_permissions.py`
  共 `96 passed`
- 前端全量 vitest：
  `src/frontend/platform/src/test/*.test*`
  共 `17 passed`
- 前端新增回归测试：
  `src/frontend/platform/src/test/mainLayoutWorkspaceMenu.test.tsx`
  `src/frontend/platform/src/test/permissionRegressions.test.tsx`
- 前端构建验证：
  `npm run build` 通过

### 总表

| 编号 | 当前状态 | 说明 |
|------|----------|------|
| U-001 | 非问题 / 按产品策略保留 | 当前策略就是删除后不直接复用原 `person_id`，而是恢复原账号 |
| U-002 | 已修复 | 菜单单独编辑也会刷新 `role.update_time` |
| U-003 | 已修复 | 已改为 NULL-safe 唯一约束，`department_id IS NULL` 的全局作用域也由 DB 兜底 |
| U-004 | 已修复 | 已区分“显式空权限”和“默认空权限” |
| U-005 | 已修复 | 知识空间关系模型模板已切到后端 canonical 权限 ID |
| U-006 | 已修复 | 旧知识库列表现在会按 `knowledge_library` 的有效 `use_kb` 权限过滤，不再只看 relation 级 `can_read` |
| U-007 | 已修复 | 工作台入口已改为检查 `workstation`，并兼容旧 `frontend` |
| U-008 | 已修复 | 权限弹窗已移除无效“链接分享”Tab |
| U-009 | 已修复 | 广场可见的 `PUBLIC/APPROVAL + is_released` 空间现可打开详情预览，未加入用户仍不能读取空间内容 |
| U-010 | 已修复 | 助手详情、助手列表、应用聚合三条链路现在都统一走 `assistant/can_read` 或合并后的应用 ReBAC 可见集 |
| U-011 | 已修复 | direct grant 的知识空间已进入详情/我的管理/我的关注等入口 |
| U-012 | 部分修复 | 知识空间已接通 `permissions[]`；旧知识库列表已接通 `use_kb`，但其它动作链路与应用模块仍未完整接通 |

### 已修项 Review 结论

本轮已修项在现代码里未再看到同级别明显回归；其中 `U-004 / U-005 / U-007 / U-008` 已补上前端自动化回归测试，`U-002 / U-003 / U-006 / U-009 / U-010 / U-011` 已有后端回归测试覆盖。

`U-003` 本轮额外补了数据库层修复：

1. `role` 表新增 `department_scope_key = COALESCE(department_id, -1)` 的 generated column
2. 唯一约束切到 `(tenant_id, role_type, role_name, department_scope_key)`
3. migration 内置了对历史冲突数据的预去重逻辑，避免升级直接失败

当前剩余验证缺口只有一项：

1. 本轮未在真实 MySQL 库上实际执行 `alembic upgrade`，但 migration 单元测试、Python 编译检查、以及 MySQL DDL 编译检查都已通过

---

## U-001 人员被删除后，重新添加同一人员 ID 失败

**Issue**

- `#IJCCUJ`
- 标题：人员被删除，重新添加，已删除的人员 id，无法添加成功

**现象**

- 本地人员删除后，再次用同一个 `person_id` 创建本地人员
- 页面提示：`Person ID already exists`

**当前代码中的高概率根因**

删除本地人员时，用户并没有物理删除，而是软删：

- `db_user.delete = 1`

但重建本地人员时，查重逻辑用的是：

- `UserDao.aget_by_external_id(person_id)`

这个查询不会过滤 `delete == 1` 的软删用户，因此历史软删记录仍会命中“人员 ID 已存在”。

也就是说，当前是：

- 删除：软删
- 重建查重：按全量 `external_id` 查重
- 结果：被软删账号占住了 `person_id`

**证据**

- 本地人员创建：
  - [department_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/department/domain/services/department_service.py:1061)
  - [department_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/department/domain/services/department_service.py:1094)
- 本地人员删除：
  - [department_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/department/domain/services/department_service.py:1313)
  - [department_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/department/domain/services/department_service.py:1343)
- `external_id` 查询：
  - [user.py](/Users/zhou/Code/bisheng/src/backend/bisheng/user/domain/models/user.py:449)
  - [user.py](/Users/zhou/Code/bisheng/src/backend/bisheng/user/domain/models/user.py:452)

**问题类型**

- 软删数据与唯一性校验冲突
- 人员生命周期状态未收口

**2026-04-23 状态更新**

- 状态：非问题 / 按产品策略保留
- 用户已明确确认这条不作为 bug 处理。
- 当前产品策略就是：删除后不直接复用原 `person_id` 新建第二条账号，而是保留原账号并提示恢复。

---

## U-002 角色编辑后，更新时间没有更新

**Issue**

- `#IJCDKD`
- 标题：角色编辑，更新时间没有更新

**现象**

- 编辑角色后，角色列表中的“修改时间”不变
- 接口返回中的 `update_time` 仍是旧值

**当前代码中的高概率根因**

角色的 `update_time` 挂在 `role` 主表上，依赖数据库：

- `CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`

但“角色编辑”并不总是会更新 `role` 主表本身：

### 场景 1：只改资源权限 / 菜单权限

`update_menu()` 只改 `role_access`：

- 不会更新 `role`
- 所以 `role.update_time` 不会自动变化

### 场景 2：走 `update_role_with_menu()`，但实际只改菜单

虽然函数里会 `session.add(db_role)`，但如果本次没有修改：

- `role_name`
- `quota_config`
- `remark`
- `department_id`

ORM 可能不会真正发 `UPDATE role ...`

于是 `role` 表上的 `update_time` 仍不会触发。

**证据**

- `role.update_time` 字段：
  - [role.py](/Users/zhou/Code/bisheng/src/backend/bisheng/database/models/role.py:38)
- 只更新 role_access 的菜单更新链路：
  - [role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py:465)
  - [role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py:483)
- 角色主表更新链路：
  - [role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py:330)
  - [role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py:380)
  - [role.py](/Users/zhou/Code/bisheng/src/backend/bisheng/database/models/role.py:117)

**问题类型**

- 主表与附表更新时间脱节
- 元数据更新时间不可信

**2026-04-23 状态更新**

- 状态：已修复
- `update_menu()` 和 `update_role_with_menu()` 现在都会显式 touch `role.update_time`，菜单单独变更也会刷新角色列表里的修改时间。
- review：当前实现直接在提交前更新角色主表时间戳，未见明显问题；`src/backend/test/test_role_service.py` 已覆盖对应回归。

---

## U-003 角色名称现在是全局唯一，但预期应跨部门可重复

**Issue**

- `#IJD13D`
- 标题：角色名称全局不能重复，应该跨部门可以重复

**现象**

- 在不同部门/作用域下创建同名角色时
- 页面提示：`Role name already exists in this scope`

**当前代码中的高概率根因**

当前角色重名判断根本没有把 `department_id` 作为唯一性维度：

### 代码层查重

`RoleDao.aget_role_by_name()` 只按：

- `role_type`
- `role_name`

查询，不看 `department_id`

### 数据库唯一索引

当前唯一约束也是：

- `(tenant_id, role_type, role_name)`

同样不包含 `department_id`

所以系统当前实际规则是：

- 同一 tenant 内
- 同一 `role_type`
- 角色名唯一

而不是“同部门内唯一、跨部门可重复”。

**证据**

- 角色创建查重：
  - [role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py:66)
  - [role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py:107)
- 角色更新查重：
  - [role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py:354)
  - [role_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/role/domain/services/role_service.py:400)
- DAO 查重实现：
  - [role.py](/Users/zhou/Code/bisheng/src/backend/bisheng/database/models/role.py:279)
- DB 唯一约束：
  - [role.py](/Users/zhou/Code/bisheng/src/backend/bisheng/database/models/role.py:55)

**问题类型**

- 角色作用域语义与产品预期不一致
- 唯一性约束建模错误

**2026-04-23 状态更新**

- 状态：已修复
- 当前 service 层查重仍按部门作用域工作；同时数据库层已经补成 NULL-safe 约束：通过 `department_scope_key = COALESCE(department_id, -1)` 把全局作用域也纳入唯一性约束。
- 严格验证：
  `src/backend/test/test_role_service.py`
  `src/backend/test/test_f027_role_scope_nullsafe_unique.py`
  以及 MySQL DDL 编译检查均已通过。

---

## U-004 【关系模型】把权限都去掉后点击更新，模型会被重置，没有保存为空

**Issue**

- `#IJD6S0`
- 标题：【关系模型】把权限都去掉，点击更新，会重置模型，没有保存

**现象**

- 在关系模型里把 `permissions[]` 全部取消勾选
- 点击“更新”
- 页面刷新后模型被自动重置成默认权限，而不是保存为空数组

**当前代码中的高概率根因**

后端其实支持保存空数组：

- `update_relation_model()` 中如果 `request.permissions is not None`
- 就直接写入 `m['permissions'] = request.permissions`

问题出在前端读取后又把空数组当成“未配置”，自动回填默认值：

```ts
if (currentModel.permissions && currentModel.permissions.length > 0) {
  setSelectedPermissionIds(currentModel.permissions)
  return
}
// 否则回填 relation 对应默认权限
setSelectedPermissionIds(defaultIds)
```

也就是说：

- `permissions=[]` 被保存了
- 前端 reload 后看到 `length === 0`
- 误认为“没有配置”
- 自动按 relation 重置回默认模板

所以用户看到的是“清空没保存”，本质是前端把“显式空数组”和“未配置”混淆了。

**证据**

- 后端更新 API：
  - [resource_permission.py](/Users/zhou/Code/bisheng/src/backend/bisheng/permission/api/endpoints/resource_permission.py:467)
  - [resource_permission.py](/Users/zhou/Code/bisheng/src/backend/bisheng/permission/api/endpoints/resource_permission.py:482)
- 前端回填逻辑：
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:242)
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:244)
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:255)
- 前端更新动作：
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:296)

**问题类型**

- 前端状态回填逻辑错误
- “空数组”与“未配置”语义混淆

**2026-04-23 状态更新**

- 状态：已修复
- 后端 relation model 已新增 `permissions_explicit` 标记，前端也据此区分“显式保存为空数组”和“系统默认空数组”。
- review：当前 round-trip 语义已闭环，未见明显问题。
- 严格验证：后端 `src/backend/test/test_permission_relation_bindings.py` 已覆盖持久化语义；前端新增 `src/frontend/platform/src/test/permissionRegressions.test.tsx`，验证“显式空权限”不会在 reload 后被默认值回填。

---

## U-005 【关系模型】给用户知识库设置“可查看”权限后，列表可见但详情不可见

**Issue**

- `#IJD6WM`
- 标题：【关系模型】给用户知识库设置可查看权限，用户可以看到列表，无法查看详情数据

**现象**

- 给用户设置了知识库“可查看”权限
- 用户能看到列表
- 但无法打开详情

**当前代码中的高概率根因**

这是一个“关系级别”和“具体 permission id”不一致的问题。

### 列表为什么能看到

列表很多地方只看 ReBAC 档位：

- `viewer`
- `can_read`

只要资源 relation 是可读，列表就能出现。

### 详情为什么打不开

知识空间详情并不只检查 `can_read`，还会继续检查具体 permission id：

- `view_space`

而当前系统页里“知识库模块”给出的权限项是：

- `view_kb`
- `use_kb`
- `edit_kb`
- `delete_kb`

这套 `view_kb` 不是知识空间详情运行时真正检查的 `view_space`。

于是会出现：

- relation 级别够，所以列表可见
- 具体 permission id 不匹配，所以详情被拒绝

**证据**

- 前端关系模型模板里的“知识库模块”：
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:142)
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:148)
- 后端真正的知识空间权限模板：
  - [knowledge_space_permission_template.py](/Users/zhou/Code/bisheng/src/backend/bisheng/permission/domain/knowledge_space_permission_template.py:26)
  - [knowledge_space_permission_template.py](/Users/zhou/Code/bisheng/src/backend/bisheng/permission/domain/knowledge_space_permission_template.py:32)
- 知识空间详情运行时要求：
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:782)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:786)
- 相关详情/读操作继续要求 `view_space`：
  - [knowledge_space_chat_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py:56)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:1349)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:1740)

**问题类型**

- 权限模板与运行时权限 ID 不一致
- 列表与详情不是同一层权限判断
- 前端模板和后端模板分叉

**2026-04-23 状态更新**

- 状态：已修复
- 关系模型页当前第一组模板已经切到“知识空间模块”，权限 ID 使用 `view_space / edit_space / ...`，与知识空间运行时 `_require_permission_id()` 消费的 ID 对齐。
- review：知识空间运行时仍按 `permissions[]` 做 action check，这条链路目前是闭合的。
- 严格验证：前端新增 `src/frontend/platform/src/test/permissionRegressions.test.tsx`，验证关系模型页会消费后端返回的知识空间权限模板，不再依赖前端旧模板常量。

---

## 本文件当前结论

> 注：本节是 2026-04-22 当天的根因归类。当前修复状态以文首“2026-04-23 修复状态复核”和各条“状态更新”为准。

当前用户提供的这几条问题，已经可以归成三类：

### 1. 数据建模 / 唯一性规则问题

- U-001 人员软删后 ID 仍被占用
- U-003 角色名称唯一性粒度错误

### 2. 元数据与附表更新脱节

- U-002 角色编辑后更新时间不变

### 3. 权限模型与运行时行为不一致

- U-004 关系模型清空权限后被前端默认值回填
- U-005 列表按 relation 可见，但详情按具体 permission id 被拒绝

后续如果继续收到新的 issue，可以直接按 `U-006 / U-007 ...` 追加到本文件。

---

## U-006 【关系模型】知识库授权“可使用”后，即使模型里没配置“使用知识库”，用户仍能看到列表内容

**Issue**

- `#IJD700`
- 标题：【关系模型】知识库给用户授权可使用权限，但是模型里没有配置使用知识库权限，用户还能看见列表内容

**现象**

- 给用户配置了某个知识库关系模型
- 该模型里没有勾选“使用知识库（`use_kb`）”
- 用户仍然能看到知识库列表内容

**当前代码中的高概率根因**

当前知识库列表的可见性不是按具体 permission id 判断，而是直接按 ReBAC 的关系档位判断：

- 列表查询使用 `rebac_list_accessible('can_read', 'knowledge_space')`

也就是说，只要 relation 层上具有：

- `viewer`
- `editor`
- `manager`
- `owner`

并最终映射为 `can_read`

用户就会进入列表结果。

而前端系统页里展示的“知识库模块”权限项：

- `view_kb`
- `use_kb`
- `edit_kb`
- `delete_kb`

目前只存在于前端关系模型配置层，本轮审计未发现后端运行时有任何地方直接消费 `use_kb` / `view_kb` 这些知识库权限 ID。

所以当前真实行为是：

1. 关系模型在 relation 层授出了 `can_read`
2. 列表接口按 `can_read` 放行
3. `use_kb` 没有真正参与列表权限判断

最终表现就是：

- 虽然模型里没勾选“使用知识库”
- 但只要 relation 级别是可读
- 用户依然能看到列表

**证据**

- 前端关系模型里的“知识库模块”权限项：
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:142)
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:148)
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:149)
- 后端知识库列表直接按 `can_read` 查可见资源：
  - [knowledge_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_service.py:173)
  - [knowledge_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_service.py:185)
- 后端代码中没有发现 `use_kb / view_kb / edit_kb / delete_kb` 的运行时消费点：
  - 本轮代码检索结果仅出现在前端关系模型配置文件中

**问题类型**

- 具体 permission id 未进入后端运行时
- 知识库列表可见性仍按 relation 档位粗粒度放行
- 关系模型配置与列表权限行为不一致

**2026-04-23 状态更新**

- 状态：已修复
- 当前知识库列表已不再只按 relation 级 `can_read` 放行，而是先取 `knowledge_library` 的 ReBAC 可见候选集，再按当前用户在该知识库上的有效 `permission ids` 过滤，只有具备 `use_kb` 的知识库才会进入列表结果。
- 这次修复同时覆盖了两类来源：
  - system relation model 的默认 permission 映射
  - custom relation model 显式配置的 `permissions[]`
- 对应后端回归测试已覆盖：
  - `KnowledgeService.get_knowledge()` 会显式调用 `use_kb` 过滤
  - custom model 仅授 `view_kb` 时，不会再把知识库放进“可使用”列表

---

## U-007 普通用户已有工作台菜单权限，但平台没有“工作台”切换入口

**Issue**

- `#IJD6AF`
- 标题：普通用户，角色有工作台菜单权限，没有切换入口

**现象**

- 普通用户角色里已经勾选工作台菜单权限
- 进入平台后，右上角用户菜单里仍没有“工作台”切换入口

**当前代码中的高概率根因**

后端返回的工作台菜单 key 已经是：

- `workstation`

但前端 `MainLayout` 判断是否显示“工作台”入口时，仍在检查旧 key：

- `frontend`

也就是说，当前存在一组历史遗留 key 不一致：

- 后端权限语义：`workstation`
- 前端入口判断：`frontend`

结果就是：

- 用户确实有工作台菜单权限
- 但切换入口仍被前端隐藏

**证据**

- 后端 `WebMenuResource` / `get_roles_web_menu` 语义已经切到工作台：
  - [auth.py](/Users/zhou/Code/bisheng/src/backend/bisheng/user/domain/services/auth.py:29)
  - [auth.py](/Users/zhou/Code/bisheng/src/backend/bisheng/user/domain/services/auth.py:502)
  - [user.py](/Users/zhou/Code/bisheng/src/backend/bisheng/user/api/user.py:146)
- 前端工作台切换入口仍判断 `frontend`：
  - [MainLayout.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/layout/MainLayout.tsx:136)

**问题类型**

- 新旧菜单 key 不一致
- 工作台切换入口仍依赖历史字段

**2026-04-23 状态更新**

- 状态：已修复
- `MainLayout` 现在已把 `workstation` 作为 canonical key，同时兼容旧 `frontend` 值，普通用户有工作台菜单权限时可重新看到入口。
- review：实现简单直接，兼容策略明确，未见明显问题。
- 严格验证：前端新增 `src/frontend/platform/src/test/mainLayoutWorkspaceMenu.test.tsx`，覆盖 `workstation`、旧 `frontend` 兼容值，以及无权限隐藏三种情况。

---

## U-008 知识库/应用权限弹窗中仍显示“链接分享”入口，但该入口不可点击，产品预期应移除

**Issue**

- `#IJD7NS`
- 标题：知识库，应用链接分享入口，无法点击
- 用户补充：这里应该不可点击，直接把分享入口删除

**现象**

- 资源权限弹窗中仍显示“链接分享”Tab
- 但该 Tab 无法点击
- 用户预期：不支持时应直接移除，而不是展示一个禁用入口

**当前代码中的高概率根因**

前端 `PermissionDialog` 会无条件渲染 3 个 tab：

- 当前权限
- 添加权限
- 链接分享

其中“链接分享”被写死为 `disabled`，但没有按资源类型或产品开关隐藏。

所以当前行为不是“能力受控展示”，而是：

- 统一渲染
- 统一禁用

这导致用户看到一个永远不可用的入口。

**证据**

- [PermissionDialog.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/components/bs-comp/permission/PermissionDialog.tsx:37)
- [PermissionDialog.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/components/bs-comp/permission/PermissionDialog.tsx:41)

**问题类型**

- 无效 UI 入口残留
- 权限弹窗能力模型未按资源类型裁剪

**2026-04-23 状态更新**

- 状态：已修复
- `PermissionDialog` 已移除写死且禁用的“链接分享”Tab，只保留当前实际支持的“当前权限 / 添加权限”两个入口。
- review：这条修改范围小、回归面清晰，未见明显问题。
- 严格验证：前端新增 `src/frontend/platform/src/test/permissionRegressions.test.tsx`，验证弹窗仅渲染 `list / grant` 两个 tab，`share` 已不再出现。

---

## U-009 系统创建的部门知识空间在广场中可见，但点击详情报“该知识空间已失效或被删除”

**Issue**

- `#IJD9HG`
- 标题：系统创建的部门知识空间，广场点击部门空间详情，提示错误，参考原有未加入时的逻辑

**现象**

- 系统批量创建的部门知识空间会出现在知识空间广场
- 普通用户在广场点击详情时，弹出“该知识空间已失效或被删除”
- 但这些空间实际上并未删除，只是用户尚未加入/不具备直接读权限

**当前代码中的高概率根因**

这是“广场可见逻辑”和“详情可读逻辑”不一致：

### 广场侧

部门知识空间创建时默认：

- `auth_type = APPROVAL`
- `is_released = true`

因此它们会进入知识空间广场列表。

### 详情侧

`get_space_info()` 会先走：

- `_require_read_permission(space_id)`
- `_require_permission_id('knowledge_space', space_id, 'view_space')`

对于未加入、未获 direct read 的用户，这里会被拒绝。

最终前端/上层把这种拒绝表现成“已失效或被删除”，于是用户看到的是错误语义。

**证据**

- 部门知识空间创建默认值：
  - [department_knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py:182)
  - [department_knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py:213)
  - [department_knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py:214)
- 广场列表逻辑：
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:977)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:991)
- 详情读取逻辑：
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:688)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:782)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:786)

**问题类型**

- 广场曝光规则与详情访问规则不一致
- 未加入空间的错误语义被误报为“已删除/已失效”

**2026-04-23 状态更新**

- 状态：已修复
- `get_space_info()` 现已对“广场本就可见”的知识空间单独放行详情预览：`type=SPACE && is_released=true && auth_type in {PUBLIC, APPROVAL}` 时不再要求用户先具备 `can_read + view_space`。
- 这次修复只放开空间级预览元数据，不放开真实内容读取；`list_space_children()`、文件预览、标签等仍继续要求原有的 `can_read/view_*` 权限。
- 同时修正了详情接口默认把当前用户标记成“已订阅”的旧行为。现在默认是 `not_subscribed`，只有创建者、真实 membership、或生效的 ReBAC 直授角色才会被标成已订阅/有角色。
- 回归测试已覆盖：
  - released + approval 空间在未加入时可打开详情预览
  - unreleased + approval 空间仍然要求真实读权限
  - 详情接口不会把未加入用户误标成已订阅

---

## U-010 助手给用户授权 owner 后，用户仍看不见助手信息

**Issue**

- `#IJD7DM`
- 标题：【关系模型】助手，给用户授权所有者，用户看不见助手信息

**现象**

- 在权限弹窗中，用户已经被授予助手 `owner`
- 但用户仍看不到助手信息

**当前代码中的高概率根因**

这条目前更像“助手模块与应用聚合页仍存在接入不一致”，不宜先写死成单点根因。

当前已确认：

- 助手详情 API 本身是走 `ASSISTANT_READ -> can_read`
- 理论上 `owner` 应该覆盖 `can_read`

但与助手可见性相关的路径不只一条：

1. 助手详情接口：`AssistantService.get_assistant_info()`
2. 助手列表接口：`AssistantService.get_assistant()`
3. 应用聚合列表：`WorkFlowService.get_all_flows()`

其中应用聚合路径又和 workflow/assistant 混在一起，且历史上存在：

- ReBAC 列表异步化修复
- 同步/异步权限包装混用
- 聚合页与详情页不走同一套入口

因此，这条更高概率是：

- “direct owner grant 已写入，但助手列表/助手信息展示链路并未全量统一走同一套 ReBAC 可见性结果”

**已确认代码位置**

- 助手详情鉴权：
  - [assistant.py](/Users/zhou/Code/bisheng/src/backend/bisheng/api/services/assistant.py:94)
  - [assistant.py](/Users/zhou/Code/bisheng/src/backend/bisheng/api/services/assistant.py:100)
- `ASSISTANT_READ -> can_read` 映射：
  - [auth.py](/Users/zhou/Code/bisheng/src/backend/bisheng/user/domain/services/auth.py:43)
- 应用聚合列表：
  - [workflow.py](/Users/zhou/Code/bisheng/src/backend/bisheng/api/services/workflow.py:82)
  - [workflow.py](/Users/zhou/Code/bisheng/src/backend/bisheng/api/services/workflow.py:108)

**问题类型**

- 助手模块 direct grant 与聚合展示链路不一致
- 高概率属于“资源详情路径”和“应用聚合路径”双轨问题

**2026-04-23 状态更新**

- 状态：已修复
- 助手详情 `AssistantService.get_assistant_info()` 直接走 `ASSISTANT_READ -> can_read/assistant`。
- 助手列表 `AssistantService.get_assistant()` 通过 `get_user_access_resource_ids([ASSISTANT_READ])` 取 ReBAC 可见助手集合，不再依赖旧的 group/membership 侧路径。
- 应用聚合列表 `WorkFlowService.get_all_flows()` 通过 `aget_merged_rebac_app_resource_ids()` 合并 `workflow + assistant` 的 ReBAC 可见资源，助手 direct grant 会进入聚合页结果。
- 工作台 `recommended apps` 入口已去掉错误的 `AccessType.FLOW`，改为只按 `WORKFLOW + ASSISTANT_READ` 过滤可见资源。
- 工作台 `used apps` 入口已改为 await `aget_merged_rebac_app_resource_ids()`，不再在 async 端点里回退到同步 helper。
- 回归测试已补：
  - `src/backend/test/test_auth_app_rebac_adapter.py`
  - `src/backend/test/test_workstation_apps_permissions.py`
  - 覆盖 `ASSISTANT_READ -> assistant/can_read`
  - 覆盖助手列表的可见 ID 查询
  - 覆盖应用聚合列表对 `workflow + assistant` 可见集的合并
  - 覆盖工作台推荐 / 已使用应用入口的可见性过滤链路

---

## U-011 知识空间给用户授权 owner 后，用户仍看不见被授权内容

**Issue**

- `#IJD7GB`
- 标题：【关系模型】知识空间给用户授权所有者权限，用户看不见被授权的知识空间内容

**现象**

- 在权限弹窗中，用户被授予知识空间 `owner`
- 但用户仍看不见被授权的知识空间内容 / 列表

**当前代码中的高概率根因**

这条和前面知识空间问题是一类：知识空间“内容可见”依旧强依赖 membership overlay。

虽然详情读取本身会走：

- `PermissionService.check(can_read, knowledge_space, ...)`

但“我的创建 / 我的管理 / 我的关注”等知识空间内容入口，仍然主要基于：

- `SpaceChannelMemberDao`

直接 owner grant 不会自动写入 `space_channel_member`，因此会出现：

- FGA 已有 owner
- membership 中没有对应关系
- 某些列表/内容入口仍然不可见

**证据**

- 知识空间详情可读逻辑：
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:688)
- 知识空间“我的”列表仍基于 membership：
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:950)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:956)

**问题类型**

- knowledge_space direct owner grant 与 membership overlay 双轨
- “权限已授予”与“内容入口可见”不一致

**2026-04-23 状态更新**

- 状态：已修复
- `get_space_info()`、`get_my_managed_spaces()`、`get_my_followed_spaces()` 现在都会把 direct grant 的知识空间合并进来；没有 membership 行时，会根据权限档位补一个前端可理解的 `user_role`。
- review：当前实现满足用户“被授权后能看见”的核心诉求。
- 严格验证：`src/backend/test/test_knowledge_space_service.py` 已覆盖详情、管理列表、关注列表三条主链路。

---

## U-012 关系模型绑定到知识库/应用后，具体 `permissions[]` 仍整体不生效

**Issue**

- `#IJD731`
- 标题：【关系模型】知识库，应用绑定关系模型，给用户，用户没有权限使用，目前整体关系模型权限没有生效

**现象**

- 关系模型里配置了大量应用/知识库的具体权限项
- 绑定到用户后，用户实际仍然无法按模型中的具体能力使用资源
- 用户反馈为“整体关系模型权限没有生效”

**当前代码中的高概率根因**

当前仓库里，真正把 `permissions[]` 接到运行时动作判断的，主要是知识空间模块。

而应用/助手/工作流/工具/旧知识库模块，仍主要按以下方式判断：

- `AccessType.* -> can_read / can_edit`
- 或旧的 `role_access`
- 或资源聚合页自己的权限规则

也就是说：

### 已接入 `permissions[]`

- `knowledge_space`
- `folder`
- `knowledge_file`

### 未完整接入 `permissions[]`

- `assistant`
- `workflow`
- `tool`
- 旧知识库模块（`KnowledgeService`）

所以当前用户感知到的“关系模型不生效”并不是全错，而是：

- relation 层可能生效
- 具体 `permissions[]` 没有进入这些模块的运行时动作判断

**证据**

- 知识空间运行时已消费 `permissions[]`：
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:445)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:561)
  - [knowledge_space_service.py](/Users/zhou/Code/bisheng/src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:632)
- 应用/助手/工具仍按 relation 或 AccessType 判断：
  - [assistant.py](/Users/zhou/Code/bisheng/src/backend/bisheng/api/services/assistant.py:100)
  - [flow.py](/Users/zhou/Code/bisheng/src/backend/bisheng/api/services/flow.py:185)
  - [workflow.py](/Users/zhou/Code/bisheng/src/backend/bisheng/api/services/workflow.py:82)
  - [tool.py](/Users/zhou/Code/bisheng/src/backend/bisheng/tool/domain/services/tool.py:159)
- 前端关系模型里仍配置了 `view_app / use_app / use_kb ...`：
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:113)
  - [RolesAndPermissions.tsx](/Users/zhou/Code/bisheng/src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx:142)

**问题类型**

- `permissions[]` 只有部分模块接入
- 关系模型“细粒度权限”与大部分资源运行时脱节

**2026-04-23 状态更新**

- 状态：部分修复
- `knowledge_space` 这条链路当前已经完整消费 `permissions[]`；`knowledge_library` 列表链路现在也已开始消费 `use_kb`。
- 但 `assistant / workflow / tool` 以及旧知识库的其它动作链路仍主要是 relation / AccessType 级别判断，因此“关系模型细粒度权限整体生效”这件事目前还没有完成。
