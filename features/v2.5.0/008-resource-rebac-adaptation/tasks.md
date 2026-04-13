# Tasks: 资源模块 ReBAC 适配

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户确认通过 |
| tasks.md | ✅ 已拆解 | 11 个任务，审查通过 |
| 实现 | ✅ 已完成 | 10 / 11 完成，T09 N/A |

---

## 任务依赖图

```
T01(LoginUser适配器)──┐
T02(delete_resource_tuples)──┤
                             ├→ T03(Knowledge) → T04(KnowledgeSpace双写)
                             ├→ T05(Workflow)
                             ├→ T06(Assistant)
                             ├→ T07(Tool)
                             ├→ T08(Channel双写)
                             ├→ T09(Dashboard)
                             └→ T10(审计日志+清理)
T11(前端group_ids移除) ← T05,T06 完成后
```

**可并行组**：A(T01, T02) → B(T03, T05, T06, T07, T08, T09) → C(T04, T10, T11)

---

## T01: LoginUser 适配器层 ✅

- **AC 覆盖**: AC-01, AC-10
- **依赖**: 无（F004 已提供 rebac_check/rebac_list_accessible）

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/user/domain/services/auth.py` |

### 实现要点

1. **添加映射字典** `_ACCESS_TYPE_TO_REBAC`（LoginUser 类内或模块级）：
   ```python
   _ACCESS_TYPE_TO_REBAC = {
       AccessType.KNOWLEDGE: ('can_read', 'knowledge_space'),
       AccessType.KNOWLEDGE_WRITE: ('can_edit', 'knowledge_space'),
       AccessType.WORKFLOW: ('can_read', 'workflow'),
       AccessType.WORKFLOW_WRITE: ('can_edit', 'workflow'),
       AccessType.ASSISTANT_READ: ('can_read', 'assistant'),
       AccessType.ASSISTANT_WRITE: ('can_edit', 'assistant'),
       AccessType.GPTS_TOOL_READ: ('can_read', 'tool'),
       AccessType.GPTS_TOOL_WRITE: ('can_edit', 'tool'),
       AccessType.DASHBOARD: ('can_read', 'dashboard'),
       AccessType.DASHBOARD_WRITE: ('can_edit', 'dashboard'),
   }
   ```

2. **改造 `access_check`**（line 158）— 保留 `@wrapper_access_check` 装饰器（admin 短路不变）：
   - 从 `_ACCESS_TYPE_TO_REBAC` 查找 access_type 对应的 (relation, object_type)
   - 找到时：`return asyncio.run(self.rebac_check(relation, object_type, str(target_id)))`
   - 未找到时：回退到旧的 `RoleAccessDao.judge_role_access` 逻辑（向后兼容）
   - 同步 → 异步桥接用 `asyncio.run()`（FastAPI sync 端点运行在 threadpool，无 event loop）

3. **改造 `async_access_check`**（line 171）— 保留 `@async_wrapper_access_check`：
   - 映射查找同上
   - 找到时：`return await self.rebac_check(relation, object_type, str(target_id))`
   - 未找到时：回退旧逻辑

4. **改造 `get_user_access_resource_ids`**（line 249）：
   - 从 access_types 列表中提取唯一的 object_type（取第一个有映射的）
   - `ids = asyncio.run(self.rebac_list_accessible(relation, object_type))`
   - ids 为 None（admin）→ 返回空列表（调用方已通过 is_admin 短路）
   - ids 为列表 → 直接返回
   - 未映射时回退旧逻辑

5. **改造 `aget_user_access_resource_ids`**（line 254）：
   - 同上但使用 `await`

### 测试验证

- Mock `PermissionService.check` 和 `PermissionService.list_accessible_ids`
- 验证 `access_check(uid, '123', AccessType.WORKFLOW)` → 调用 `rebac_check('can_read', 'workflow', '123')`
- 验证 admin 用户仍然短路返回 True
- 验证未映射的 AccessType 回退旧逻辑

### 风险

- `asyncio.run()` 在已有 event loop 的上下文中会报错。FastAPI sync 端点运行在 threadpool（无 loop）是安全的。但 Celery worker 中如有调用需验证 — grep `access_check` in `worker/` 目录确认。

---

## T02: OwnerService.delete_resource_tuples ✅

- **AC 覆盖**: AC-03
- **依赖**: 无（F004 已提供 OwnerService + FGAClient.read_tuples）

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/permission/domain/services/owner_service.py` |

### 实现要点

1. **新增 `delete_resource_tuples` classmethod**：
   ```python
   @classmethod
   async def delete_resource_tuples(cls, object_type: str, object_id: str) -> None:
       """Delete all FGA tuples for a resource (called on resource deletion).
       
       Reads all tuples via FGA read_tuples, then batch deletes.
       Does not raise on failure — logs warning and returns.
       """
       from bisheng.permission.domain.services.permission_service import PermissionService
       fga = PermissionService._get_fga()
       if fga is None:
           logger.warning('FGAClient not available for tuple cleanup: %s:%s', object_type, object_id)
           return
       try:
           tuples = await fga.read_tuples(object=f'{object_type}:{object_id}')
           if not tuples:
               return
           from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
           operations = [
               TupleOperation(action='delete', user=t['user'], relation=t['relation'], object=t['object'])
               for t in tuples
           ]
           await PermissionService.batch_write_tuples(operations)
           logger.info('Cleaned up %d tuples for %s:%s', len(operations), object_type, object_id)
       except Exception as e:
           logger.warning('Failed to cleanup tuples for %s:%s: %s', object_type, object_id, e)
   ```

2. FGA 不可用或 read_tuples 失败时仅记日志，不阻塞删除流程。

### 测试验证

- Mock FGAClient，验证 read_tuples → batch_write_tuples 调用链
- 验证空元组列表时不调用 batch_write_tuples
- 验证 FGA 不可用时不抛异常

---

## T03: Knowledge 模块适配 ✅

- **AC 覆盖**: AC-02(Knowledge), AC-03(Knowledge), AC-04(Knowledge), AC-05(Knowledge), AC-08
- **依赖**: T01, T02

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/knowledge/domain/services/knowledge_service.py` |
| 修改 | `src/backend/bisheng/knowledge/domain/services/knowledge_file_service.py` |
| 修改 | `src/backend/bisheng/knowledge/domain/services/knowledge_permission_service.py` |
| 修改 | `src/backend/bisheng/knowledge/api/endpoints/knowledge.py`（如有 GroupResource 导入） |

### 实现要点

1. **创建时写 owner 元组**：在 `create_knowledge` 方法中，DAO.create 成功后调用：
   ```python
   await OwnerService.write_owner_tuple(login_user.user_id, 'knowledge_space', str(knowledge.id))
   ```
   - 如果 `create_knowledge` 当前是同步方法，需转为 async 或用 asyncio.run() 桥接

2. **创建前 quota 检查**：在创建入口处添加：
   ```python
   await QuotaService.check_quota(login_user.user_id, 'knowledge_space', login_user.tenant_id, login_user)
   ```
   - 或在端点函数上添加 `@require_quota(QuotaResourceType.KNOWLEDGE_SPACE)` 装饰器

3. **删除时清理 FGA 元组**：替换现有 `GroupResourceDao.delete_group_resource_by_third_id(knowledge_id, ResourceTypeEnum.KNOWLEDGE)` 为：
   ```python
   await OwnerService.delete_resource_tuples('knowledge_space', str(knowledge_id))
   ```

4. **列表过滤**：找到构建 `knowledge_id_extra` 的位置（使用 `RoleAccessDao.aget_role_access` 或 `get_role_access`），替换为：
   ```python
   accessible_ids = await login_user.rebac_list_accessible('can_read', 'knowledge_space')
   # accessible_ids is None for admin (no filter), list of ID strings for normal users
   ```
   - 调整 DAO 查询条件：若 accessible_ids 不为 None，添加 `WHERE id IN (accessible_ids)`

5. **移除 GroupResource 写入/删除逻辑**：
   - 删除 `GroupResourceDao.insert_group_batch(batch_resource)` 相关代码块
   - 删除 `GroupResource` 导入和 `batch_resource` 构建逻辑
   - 保留 `RoleAccessDao` 中 WEB_MENU 相关查询（如有）

6. **access_check 调用**（14 处）：由 T01 适配器自动处理，本任务无需逐个改动。但需确认调用参数中的 `AccessType` 已在映射表中。

### 测试验证

- 创建 knowledge 后验证 OwnerService.write_owner_tuple 被调用
- 删除 knowledge 后验证 OwnerService.delete_resource_tuples 被调用
- 列表 API 验证使用 rebac_list_accessible 过滤
- 验证 GroupResource 相关代码已移除

---

## T04: KnowledgeSpace + SpaceChannelMember 双写适配 ✅

- **AC 覆盖**: AC-06
- **依赖**: T01, T02, T03

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` |
| 修改 | `src/backend/bisheng/knowledge/domain/services/subscribe_handler.py` |

### 实现要点

1. **拆分 `_require_write_permission`**（line 117）为操作级检查：
   - 新增 `_require_edit_permission(space_id)` → `PermissionService.check(user_id, 'can_edit', 'knowledge_space', space_id)`
   - 新增 `_require_manage_permission(space_id)` → `PermissionService.check(user_id, 'can_manage', 'knowledge_space', space_id)`
   - 新增 `_require_delete_permission(space_id)` → `PermissionService.check(user_id, 'can_delete', 'knowledge_space', space_id)`
   - 更新所有调用点，按 PRD 权限操作表映射：
     - 修改名称/描述、文件夹/文件 CRUD → `_require_edit_permission`
     - 管理权限、成员管理 → `_require_manage_permission`
     - 删除空间 → `_require_delete_permission`

2. **改造 `_require_read_permission`**（line 129）：
   - 从 `SpaceChannelMemberDao.async_get_active_member_role` 改为 `PermissionService.check(user_id, 'can_read', 'knowledge_space', space_id)`
   - 保留 knowledge 对象查询返回（很多调用方依赖返回的 Knowledge 对象）

3. **Space 创建**（line 170 附近）：
   - 保留 SpaceChannelMember(CREATOR) 写入（订阅流需要）
   - 新增 `await OwnerService.write_owner_tuple(login_user.user_id, 'knowledge_space', str(space.id))`

4. **成员审批通过**（subscribe_handler.py）：
   - 在 SpaceChannelMember 状态更新为 ACTIVE 后，额外写 FGA 元组：
   ```python
   await PermissionService.authorize(
       object_type='knowledge_space', object_id=str(space_id),
       grants=[AuthorizeGrantItem(subject_type='user', subject_id=user_id, relation='viewer')]
   )
   ```

5. **成员移除**（line 578 附近 `delete_space_member`）：
   - 在 SpaceChannelMember 删除后，额外删 FGA 元组：
   ```python
   await PermissionService.authorize(
       object_type='knowledge_space', object_id=str(space_id),
       revokes=[AuthorizeRevokeItem(subject_type='user', subject_id=user_id, relation='viewer')]
   )
   ```

6. **成员角色变更**（line 499-536 `update_member_role`）：
   - SpaceChannelMember 角色更新后，同步更新 FGA 元组：
   - 旧角色映射：ADMIN → manager, MEMBER → viewer
   - revoke 旧 relation + grant 新 relation

7. **列表查询**保留 SpaceChannelMember 用于「我的空间」/「关注空间」（涉及订阅状态），不改动。

### 测试验证

- 创建 Space 后验证 SpaceChannelMember(CREATOR) + FGA owner 元组都写入
- 审批通过后验证 FGA viewer 元组写入
- 移除成员后验证 FGA 元组删除
- 角色变更后验证 FGA 元组更新
- 验证 `_require_edit_permission` 调 `can_edit`，`_require_manage_permission` 调 `can_manage`

---

## T05: Workflow 模块适配 ✅

- **AC 覆盖**: AC-02(Workflow), AC-03(Workflow), AC-04(Workflow), AC-05(Workflow), AC-08
- **依赖**: T01, T02

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/api/services/flow.py` |
| 修改 | `src/backend/bisheng/api/services/workflow.py` |
| 修改 | `src/backend/bisheng/api/v1/workflow.py`（access_check 由 T01 自动适配） |

### 实现要点

1. **flow.py 创建 hook**（line 285 附近）：
   - 替换 `GroupResourceDao.insert_group_batch(batch_resource)` → `await OwnerService.write_owner_tuple(user_id, 'workflow', str(flow.id))`
   - 移除 `batch_resource` 构建和 `GroupResource` 导入

2. **flow.py 删除逻辑**：
   - 找到 `GroupResourceDao.delete_group_resource_by_third_id` 调用 → `await OwnerService.delete_resource_tuples('workflow', str(flow_id))`

3. **workflow.py 列表过滤**（line 122）：
   - 替换 `flow_id_extra = user.get_user_access_resource_ids(access_list)` → `flow_id_extra = await user.rebac_list_accessible('can_read', 'workflow')`（注意同步/异步转换）
   - line 383 同理

4. **workflow.py RoleAccessDao 直接调用**（line 434）：
   - 替换 `RoleAccessDao.get_role_access_batch(role_ids, ...)` → `await user.rebac_list_accessible('can_read', 'workflow')`

5. **workflow.py 移除 group_ids**（line 66）：
   - 移除 `GroupResourceDao.get_resources_group(None, resource_ids)` 调用
   - 移除响应中 `group_ids` 字段构建逻辑

6. **Quota 检查**：在 workflow 创建端点添加 quota 检查（`@require_quota(QuotaResourceType.WORKFLOW)` 或在 service 中调用）

### 测试验证

- 创建 workflow 后验证 FGA owner 元组写入
- 列表 API 验证 ReBAC 过滤
- 响应中无 group_ids 字段

---

## T06: Assistant 模块适配 ✅

- **AC 覆盖**: AC-02(Assistant), AC-03(Assistant), AC-04(Assistant), AC-05(Assistant), AC-08
- **依赖**: T01, T02

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/api/services/assistant.py` |

### 实现要点

1. **列表过滤**（line 69）：
   - 替换 `RoleAccessDao.get_role_access(role_ids, AccessType.ASSISTANT_READ)` → `await login_user.rebac_list_accessible('can_read', 'assistant')`

2. **移除 group_ids**（line 77）：
   - 移除 `GroupResourceDao.get_resources_group(ResourceTypeEnum.ASSISTANT, assistant_ids)` 及 group_ids 构建

3. **创建 hook**（line 195）：
   - 替换 `GroupResourceDao.insert_group_batch(batch_resource)` → `await OwnerService.write_owner_tuple(user_id, 'assistant', str(assistant.id))`

4. **删除 hook**（line 234）：
   - 替换 `GroupResourceDao.delete_group_resource_by_third_id(assistant.id, ResourceTypeEnum.ASSISTANT)` → `await OwnerService.delete_resource_tuples('assistant', str(assistant.id))`

5. **Quota 检查**：创建 assistant 前添加 quota 检查

6. **access_check**（line 115, 216, 345, 411）：由 T01 适配器自动处理

### 测试验证

- 创建 assistant 后验证 FGA owner 元组写入
- 列表 API 验证 ReBAC 过滤
- 响应中无 group_ids 字段

---

## T07: Tool 模块适配 ✅

- **AC 覆盖**: AC-02(Tool), AC-03(Tool), AC-04(Tool), AC-05(Tool), AC-08
- **依赖**: T01, T02

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/tool/domain/services/tool.py` |

### 实现要点

1. **列表过滤**（line 47, 80）：
   - 替换 `aget_user_access_resource_ids([AccessType.GPTS_TOOL_READ])` → `await self.login_user.rebac_list_accessible('can_read', 'tool')`
   - 替换 `aget_user_access_resource_ids([AccessType.GPTS_TOOL_WRITE])` → `await self.login_user.rebac_list_accessible('can_edit', 'tool')`

2. **创建 hook**（line 132）：
   - 替换 `GroupResourceDao.insert_group_batch(batch_resource)` → `await OwnerService.write_owner_tuple(user_id, 'tool', str(tool.id))`

3. **删除 hook**（line 381）：
   - 替换 `GroupResourceDao.delete_group_resource_by_third_id` + `GroupResourceDao.get_resource_group` → `await OwnerService.delete_resource_tuples('tool', str(tool.id))`

4. **update_tool_hook**（line 357）：
   - 移除 `GroupResourceDao.aget_resource_group(ResourceTypeEnum.GPTS_TOOL, ...)` 审计调用

5. **Quota 检查**：创建 tool 前添加 quota 检查

6. **async_access_check**（line 146, 347, 369）：由 T01 适配器自动处理

### 测试验证

- 创建 tool 后验证 FGA owner 元组写入
- 列表 API 验证 ReBAC 过滤（read 和 write 两种级别）

---

## T08: Channel 模块双写适配 ✅

- **AC 覆盖**: AC-02(Channel), AC-03(Channel), AC-07
- **依赖**: T01, T02

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/channel/domain/services/channel_service.py` |
| 修改 | `src/backend/bisheng/channel/domain/services/channel_subscribe_approval_handler.py` |

### 实现要点

1. **Channel 创建**：在 channel 创建逻辑中添加：
   - `await OwnerService.write_owner_tuple(user_id, 'channel', str(channel.id))`
   - `await QuotaService.check_quota(user_id, 'channel', tenant_id, login_user)`

2. **Channel 删除**：添加 `await OwnerService.delete_resource_tuples('channel', str(channel.id))`

3. **权限检查替换**（line 1450）：
   - `SpaceChannelMemberDao.async_get_active_member_role` 用于权限判断的场景 → `PermissionService.check`
   - 保留 SpaceChannelMember 用于订阅状态查询（pending/active/rejected）

4. **成员审批通过**（channel_subscribe_approval_handler.py）：
   - SpaceChannelMember 状态更新为 ACTIVE 后，写 FGA viewer 元组

5. **成员移除**：删 FGA 元组

### 测试验证

- Channel 创建后验证 FGA owner 元组写入
- 成员审批通过后验证 FGA viewer 元组
- 权限检查走 PermissionService 而非 SpaceChannelMemberDao

---

## T09: Dashboard 模块适配 ⏭️ N/A

- **AC 覆盖**: AC-02(Dashboard), AC-03(Dashboard), AC-05(Dashboard)
- **依赖**: T01, T02

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | 待定位（dashboard 可能在 `api/services/` 或 `workstation/` 中处理，FlowType.WORKSTATION=15） |

### 实现要点

1. **定位 Dashboard CRUD 入口**：Dashboard 在 DB 中是 `flow` 表的一种类型（`flow_type=15`）。需 grep `FlowType.WORKSTATION` 或 `DASHBOARD` 找到创建/删除入口。

2. **创建时**：`await OwnerService.write_owner_tuple(user_id, 'dashboard', str(flow_id))`

3. **删除时**：`await OwnerService.delete_resource_tuples('dashboard', str(flow_id))`

4. **Quota 检查**：`await QuotaService.check_quota(user_id, 'dashboard', tenant_id, login_user)`

5. 权限检查/列表过滤由 T01 适配器自动处理（AccessType.DASHBOARD/DASHBOARD_WRITE）

### 测试验证

- Dashboard 创建后验证 FGA owner 元组
- 列表过滤使用 ReBAC

---

## T10: 审计日志 GroupResource 改造 + 导入清理 ✅

- **AC 覆盖**: AC-09, AC-08
- **依赖**: T03, T05, T06, T07, T08, T09

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | `src/backend/bisheng/api/services/audit_log.py` |
| 修改 | `src/backend/bisheng/api/services/tag.py` |
| 修改 | 各模块文件（清理废弃导入） |

### 实现要点

1. **audit_log.py**（6 处 GroupResourceDao）：
   - 替换 `GroupResourceDao.get_resource_group(resource_type, object_id)` → `await PermissionService.get_resource_permissions(object_type, str(object_id))`
   - 替换 `GroupResourceDao.aget_resource_group(...)` → 同上
   - 审计日志记录当前权限主体（用户/部门/用户组名称 + relation）而非旧的 group_id
   - 注意 audit_log 中 ResourceTypeEnum → OpenFGA object_type 映射

2. **tag.py**：
   - 替换 `GroupResourceDao.get_resource_group(resource_type, resource_id)` → PermissionService 调用
   - access_check 由 T01 自动处理

3. **全局导入清理**：
   - 在 T03-T09 各模块文件中，移除不再使用的导入：
     - `from bisheng.database.models.group_resource import GroupResource, GroupResourceDao, ResourceTypeEnum`
     - `from bisheng.database.models.role_access import RoleAccessDao`（如不再有直接调用）
   - 保留 `AccessType` 导入（T01 适配器映射需要）
   - 保留 `role_group_service.py` 中的 GroupResourceDao 使用（不在 F008 范围内）

### 测试验证

- 审计日志记录使用 PermissionService 返回的权限主体信息
- 不因 GroupResource 停止写入而产生空结果或报错
- 无废弃导入导致的 lint 警告

---

## T11: 前端 group_ids 字段移除 ✅

- **AC 覆盖**: AC-08
- **依赖**: T05, T06（后端 group_ids 移除后）

### 产出文件

| 操作 | 文件 |
|------|------|
| 修改 | Platform 前端 workflow 列表组件 |
| 修改 | Platform 前端 assistant 列表组件 |
| 修改 | `src/frontend/platform/src/controllers/API/` 相关类型定义 |

### 实现要点

1. **定位 group_ids 使用**：在前端 grep `group_ids` 或 `groupIds`，找到列表页中展示用户组标签的位置

2. **移除展示逻辑**：删除 group_ids 相关的列、标签、过滤器

3. **类型定义更新**：将 API 响应类型中 `group_ids` 字段改为 optional（`group_ids?: string[]`）或移除，确保后端不返回该字段时前端不报错

4. 不引入新组件或新 UI 元素（F007 已提供权限 UI 组件）

### 手动验证

- 打开 http://192.168.106.114:3001 → 工作流列表、助手列表
- 确认无 group_ids 相关展示（无用户组标签/列）
- 确认列表正常渲染，无 JS 错误

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- **偏差 1**: _（实现时填写）_
