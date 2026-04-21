# Feature: 资源模块 ReBAC 适配

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §2](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)、[2.5 多租户需求文档 §8](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md)
**优先级**: P1
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 逐模块改造（顺序 knowledge → workflow → assistant → tool → channel → dashboard）：
  - 替换 `LoginUser.access_check()` 为 PermissionService.check() 委托链路
  - 资源创建时调用 `OwnerService.write_owner_tuple()` 写 owner 元组
  - 资源删除时调用 `OwnerService.delete_resource_tuples()` 删除所有相关元组
  - 列表 API 使用 `LoginUser.rebac_list_accessible()` 过滤可访问资源
  - 资源创建前调用 `@require_quota` / `QuotaService.check_quota` 配额检查（F005）
- 改造 LoginUser 核心方法（适配器模式）：
  - `access_check` / `async_access_check` 内部委托 rebac_check，调用点零改动
  - `get_user_access_resource_ids` / `aget_user_access_resource_ids` 委托 rebac_list_accessible
- 替换所有 `RoleAccessDao.judge_role_access` 调用（WEB_MENU 类型除外）
- 替换所有 `GroupResource` 权限写入/删除逻辑
- KnowledgeSpace/Channel 双写适配：保留 SpaceChannelMember 订阅审批流，权限判断走 ReBAC
- 审计日志 GroupResourceDao 引用替换
- 前端移除列表 API 中的 group_ids 展示

**OUT**:
- linsight / workstation / mcp（无权限控制，PRD 明确豁免）
- evaluation / mark_task / dataset（仅 RBAC 菜单控制，F005 处理）
- GroupResource 彻底删表（保留 role_group_service 只读使用，后续清理）
- SpaceChannelMember 模型重构（保留用于订阅审批流）

**关键文件（预判）**:
- 修改: `src/backend/bisheng/user/domain/services/auth.py`（LoginUser 适配器层）
- 修改: `src/backend/bisheng/permission/domain/services/owner_service.py`（新增 delete_resource_tuples）
- 修改: `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`（最大改动）
- 修改: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（双写适配）
- 修改: `src/backend/bisheng/api/services/flow.py`、`workflow.py`、`assistant.py`
- 修改: `src/backend/bisheng/tool/domain/services/tool.py`
- 修改: `src/backend/bisheng/channel/domain/services/channel_service.py`
- 修改: `src/backend/bisheng/api/services/audit_log.py`

**关联不变量**: INV-2, INV-3, INV-11, INV-15

---

## 1. 概述与用户故事

F008 是 v2.5 权限体系改造的最终落地步骤。F004 构建了 ReBAC 引擎（PermissionService），F006 完成了旧数据迁移，F007 提供了前端授权 UI。F008 将这些基础设施接入 6 个业务模块的实际代码路径，使得资源创建、读取、更新、删除全链路都通过 OpenFGA 进行权限校验。

### 用户故事

**US-01 资源创建者**：作为资源创建者，我期望创建知识库/工作流/助手/工具时系统自动将我设为 owner，并且 OpenFGA 中写入对应的 owner 元组，以便后续权限检查和授权管理正常工作。

**US-02 被授权用户**：作为被授权用户（通过 F007 UI 获得 viewer/editor/manager 权限），我期望在列表页面只看到我有权访问的资源，且能执行与我权限等级匹配的操作（查看/编辑/管理）。

**US-03 管理员**：作为系统管理员或租户管理员，我期望仍然能访问所有资源（admin 短路），不受 ReBAC 切换的影响。

**US-04 知识空间成员**：作为知识空间的订阅成员，我期望订阅审批通过后自动获得 ReBAC 的 viewer 权限，被移除成员身份后权限同步撤销，且订阅审批流（申请/批准/拒绝）不受影响。

**US-05 配额受限用户**：作为配额受限的用户，我期望创建资源前系统检查配额限制，超额时返回明确的错误提示。

---

## 2. 验收标准

### AC-01: LoginUser 适配器层正确委托

- [ ] `access_check(owner_user_id, target_id, AccessType.WORKFLOW)` 内部映射为 `rebac_check('can_read', 'workflow', target_id)` 并返回正确结果
- [ ] `async_access_check` 同理，内部直接 `await rebac_check()`
- [ ] `get_user_access_resource_ids([AccessType.WORKFLOW])` 内部映射为 `rebac_list_accessible('can_read', 'workflow')` 并返回 ID 列表
- [ ] admin 用户通过适配器仍然短路返回 True / None（全量）
- [ ] 未映射的 AccessType 回退到旧逻辑（向后兼容）

### AC-02: 资源创建写入 owner 元组（INV-2）

- [ ] Knowledge 创建后调用 `OwnerService.write_owner_tuple(user_id, 'knowledge_space', str(id))`
- [ ] Workflow 创建后调用 `OwnerService.write_owner_tuple(user_id, 'workflow', str(id))`
- [ ] Assistant 创建后调用 `OwnerService.write_owner_tuple(user_id, 'assistant', str(id))`
- [ ] Tool 创建后调用 `OwnerService.write_owner_tuple(user_id, 'tool', str(id))`
- [ ] Channel 创建后调用 `OwnerService.write_owner_tuple(user_id, 'channel', str(id))`
- [ ] Dashboard 创建后调用 `OwnerService.write_owner_tuple(user_id, 'dashboard', str(id))`
- [ ] OpenFGA 写入失败时不阻塞创建流程（FailedTuple 补偿）

### AC-03: 资源删除清理 FGA 元组

- [ ] 各模块资源删除时调用 `OwnerService.delete_resource_tuples(object_type, str(id))`
- [ ] 删除时先 read_tuples 获取所有相关元组，再 batch delete
- [ ] FGA 不可用时不阻塞删除流程（仅记日志）

### AC-04: 列表 API 使用 ReBAC 过滤

- [ ] Knowledge 列表使用 `rebac_list_accessible('can_read', 'knowledge_space')` 过滤
- [ ] Workflow 列表使用 `rebac_list_accessible('can_read', 'workflow')` 过滤
- [ ] Assistant 列表使用 `rebac_list_accessible('can_read', 'assistant')` 过滤
- [ ] Tool 列表使用 `rebac_list_accessible('can_read', 'tool')` 过滤
- [ ] admin 用户列表不过滤（rebac_list_accessible 返回 None）
- [ ] 普通用户只看到被授权的资源

### AC-05: 配额检查集成（INV-11）

- [ ] Knowledge 创建前检查 `QuotaService.check_quota(user_id, 'knowledge_space', tenant_id)`
- [ ] Workflow 创建前检查 quota
- [ ] Assistant 创建前检查 quota
- [ ] Tool 创建前检查 quota
- [ ] Channel 创建前检查 quota
- [ ] Dashboard 创建前检查 quota
- [ ] 配额超限时抛出 `QuotaExceededError`，不创建资源

### AC-06: KnowledgeSpace 双写适配

- [ ] 拆分 `_require_write_permission` 为按操作精确检查（PRD 权限操作表）：
  - 「修改名称/描述、文件夹/文件 CRUD」→ `PermissionService.check(user_id, 'can_edit', 'knowledge_space', space_id)`
  - 「管理空间权限、成员管理」→ `PermissionService.check(user_id, 'can_manage', 'knowledge_space', space_id)`
  - 「删除知识空间」→ `PermissionService.check(user_id, 'can_delete', 'knowledge_space', space_id)`
- [ ] `_require_read_permission` 改为调用 `PermissionService.check(user_id, 'can_read', 'knowledge_space', space_id)`
- [ ] Space 创建时同时写 SpaceChannelMember(CREATOR) + OwnerService.write_owner_tuple
- [ ] 成员订阅审批通过时额外写 FGA viewer 元组
- [ ] 成员移除时额外删除 FGA 元组
- [ ] 成员角色变更时同步更新 FGA 元组（revoke旧 + grant新）

### AC-07: Channel 双写适配

- [ ] Channel 权限检查从 `SpaceChannelMemberDao.async_get_active_member_role` 改为 `PermissionService.check`
- [ ] Channel 创建时写 owner 元组
- [ ] 成员审批通过时写 FGA viewer 元组
- [ ] 成员移除时删 FGA 元组

### AC-08: GroupResource 写入停止 + group_ids 移除

- [ ] 所有模块停止调用 `GroupResourceDao.insert_group_batch`
- [ ] 所有模块停止调用 `GroupResourceDao.delete_group_resource_by_third_id`
- [ ] Workflow/Assistant 列表响应移除 `group_ids` 字段
- [ ] 前端移除 group_ids 相关展示逻辑

### AC-09: 审计日志适配

- [ ] `audit_log.py` 中 `GroupResourceDao.get_resource_group` 替换为 `PermissionService.get_resource_permissions`
- [ ] 审计日志记录当前权限主体（用户/部门/用户组）而非旧的用户组

### AC-10: AccessType 映射完整性

- [ ] 以下 AccessType 正确映射到 ReBAC relation + object_type：

| AccessType | relation | object_type |
|---|---|---|
| KNOWLEDGE | can_read | knowledge_space |
| KNOWLEDGE_WRITE | can_edit | knowledge_space |
| WORKFLOW | can_read | workflow |
| WORKFLOW_WRITE | can_edit | workflow |
| ASSISTANT_READ | can_read | assistant |
| ASSISTANT_WRITE | can_edit | assistant |
| GPTS_TOOL_READ | can_read | tool |
| GPTS_TOOL_WRITE | can_edit | tool |
| DASHBOARD | can_read | dashboard |
| DASHBOARD_WRITE | can_edit | dashboard |

---

## 3. 边界情况

- 当 OpenFGA 不可用时，资源创建仍然成功（OwnerService 内部记录 FailedTuple），权限检查 fail-closed（拒绝访问），但 owner 兜底生效（DB user_id 匹配则放行）
- 当 AccessType 未在 `_ACCESS_TYPE_TO_REBAC` 映射中时，回退到旧的 RoleAccessDao 逻辑（向后兼容）
- 当 SpaceChannelMember 和 FGA 元组不一致时（竞态场景），以 FGA 结果为准（权限判断唯一来源）
- 当 rebac_list_accessible 返回空列表时，列表 API 返回空结果集（非报错）
- 当 rebac_list_accessible 返回 None（admin）时，列表 API 不添加 ID 过滤
- **不支持**：GroupResource 表删除（保留 role_group_service 只读查询，后续版本清理）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 模块改造顺序 | A: 并行全改 / B: 按复杂度逐一 | 选 B | knowledge 最复杂有文件夹层级，先改验证模式，再推广到简单模块 |
| AD-02 | sync→async 桥接 | A: 适配器（access_check 内部委托）/ B: 逐个替换调用点 | 选 A | 54 个调用点零改动，风险最低，后续可渐进 async 化 |
| AD-03 | SpaceChannelMember 策略 | A: 完全替换 / B: 双写并行 / C: 延后 | 选 B | 订阅审批流（pending/rejected）依赖 SpaceChannelMember，ReBAC 不建模这些中间态 |
| AD-04 | group_ids 字段 | A: 移除 / B: 保留只读 | 选 A | v2.5 用户组语义已变（授权主体 vs 资源容器），展示失去意义 |
| AD-05 | 审计日志 | A: 同步改造 / B: 延后 | 选 A | GroupResource 停止写入后审计日志查询会返回空，必须同步适配 |

---

## 5. 数据库 & Domain 模型

### 数据库表变更

本 Feature **不新建表**。涉及的表操作：

| 表 | 变更 |
|---|---|
| `group_resource` | **停止写入和删除**（insert/delete），保留只读查询用于 role_group_service |
| `role_access` | 权限检查部分停止读取（WEB_MENU 类型除外），保留 WEB_MENU 查询 |
| `space_channel_member` | 保留全部读写（订阅审批流），权限判断链路改走 ReBAC |

### Domain 模型

无新增 Domain 模型。利用已有：
- `PermissionService`（F004）
- `OwnerService`（F004）
- `QuotaService` + `@require_quota`（F005）

---

## 6. API 契约

### 端点变更

本 Feature **不新增 API 端点**。所有变更在现有端点内部实现：

| 模块 | 端点 | 变更内容 |
|------|------|---------|
| Knowledge | `POST /api/v1/knowledge/create` | +owner 元组写入, +quota 检查 |
| Knowledge | `GET /api/v1/knowledge/list` | 列表过滤改为 ReBAC |
| Knowledge | `DELETE /api/v1/knowledge/{id}` | +FGA 元组清理 |
| Workflow | `POST /api/v1/flows/` | +owner 元组, +quota |
| Workflow | `GET /api/v1/workflow/list` | 列表过滤改为 ReBAC, 移除 group_ids |
| Assistant | `POST /api/v1/assistant/` | +owner 元组, +quota |
| Assistant | `GET /api/v1/assistant/` | 列表过滤改为 ReBAC, 移除 group_ids |
| Tool | `POST /api/v1/tool/` | +owner 元组, +quota |
| Tool | `GET /api/v1/tool/` | 列表过滤改为 ReBAC |
| Channel | 创建/删除 | +owner 元组, +FGA 清理, +quota |
| Dashboard | 创建/删除 | +owner 元组, +FGA 清理, +quota |

### 响应变更

Workflow/Assistant 列表响应移除 `group_ids` 字段（v2.4 遗留）。

---

## 7. Service 层逻辑

### 核心改造模式（每个模块统一）

```
创建链路: Endpoint → QuotaService.check_quota → DAO.create → OwnerService.write_owner_tuple
删除链路: Endpoint → PermissionService.check(can_edit) → DAO.delete → OwnerService.delete_resource_tuples
读取链路: Endpoint → PermissionService.check(can_read) → DAO.get
列表链路: Endpoint → rebac_list_accessible(can_read) → DAO.list(filter by accessible_ids)
```

### LoginUser 适配器

`access_check`/`async_access_check` 内部通过 `_ACCESS_TYPE_TO_REBAC` 映射表将 AccessType 转为 (relation, object_type)，然后调用 `rebac_check`。同步版通过 `asyncio.run()` 桥接。未映射的 AccessType 回退旧逻辑。

### KnowledgeSpace 双写策略

`_require_write_permission`/`_require_read_permission` 从查 SpaceChannelMember 角色改为调 PermissionService.check。保留 SpaceChannelMember 用于：
- 订阅状态管理（pending/active/rejected）
- "我的空间"/"关注空间" 列表查询
- 成员列表展示

角色变更时双写：SpaceChannelMember 更新 + FGA 元组 revoke/grant。

### 权限检查

所有资源操作通过 `PermissionService.check()` 检查权限。
资源创建通过 `OwnerService.write_owner_tuple()` 写入 OpenFGA owner 元组。
禁止直接查询 `role_access` 或 `group_resource`（WEB_MENU 类型除外）。

---

## 8. 前端设计

### 8.1 Platform 前端

**变更范围**：移除列表页中的 group_ids 展示。

**涉及文件**：
- Workflow 列表组件中 group_ids 相关列或标签
- Assistant 列表组件中 group_ids 相关列或标签
- API 类型定义中 group_ids 字段（改为 optional 或移除）

**无新页面/新组件**：F007 已提供权限 UI 组件（PermissionDialog, PermissionBadge 等）。

### 8.2 Client 前端

无变更。Client 端不涉及资源管理列表和权限控制。

---

## 9. 文件清单

### 修改

| 文件 | 变更内容 | 涉及任务 |
|------|---------|---------|
| `bisheng/user/domain/services/auth.py` | LoginUser 适配器层 | T01 |
| `bisheng/permission/domain/services/owner_service.py` | 新增 delete_resource_tuples | T02 |
| `bisheng/knowledge/domain/services/knowledge_service.py` | owner 元组/quota/列表过滤/移除 GroupResource | T03 |
| `bisheng/knowledge/domain/services/knowledge_file_service.py` | access_check 自动适配 | T03 |
| `bisheng/knowledge/domain/services/knowledge_permission_service.py` | access_check 自动适配 | T03 |
| `bisheng/knowledge/domain/services/knowledge_space_service.py` | 双写适配 | T04 |
| `bisheng/knowledge/domain/services/subscribe_handler.py` | 审批通过写 FGA 元组 | T04 |
| `bisheng/api/services/flow.py` | owner 元组/移除 GroupResource | T05 |
| `bisheng/api/services/workflow.py` | 列表过滤/移除 GroupResource/group_ids | T05 |
| `bisheng/api/v1/workflow.py` | access_check 自动适配 | T05 |
| `bisheng/api/services/assistant.py` | owner 元组/列表过滤/移除 GroupResource/group_ids | T06 |
| `bisheng/tool/domain/services/tool.py` | owner 元组/列表过滤/移除 GroupResource | T07 |
| `bisheng/channel/domain/services/channel_service.py` | 双写适配 | T08 |
| `bisheng/channel/domain/services/channel_subscribe_approval_handler.py` | 审批写 FGA 元组 | T08 |
| `bisheng/api/services/audit_log.py` | GroupResourceDao → PermissionService | T10 |
| `bisheng/api/services/tag.py` | GroupResourceDao 替换 | T10 |
| Platform 前端列表组件 | 移除 group_ids 展示 | T11 |

### 不新建文件

本 Feature 不新建 Python 文件或前端组件文件。

---

## 10. 非功能要求

- **性能**: 权限检查新增 OpenFGA 网络调用（L2 缓存 10s TTL 缓解），列表 API 的 list_objects 调用量 O(1)（非 O(N) 逐个 check），预期 P95 延迟增加 < 20ms
- **安全**: 五级检查链路（admin短路 → 缓存 → OpenFGA → owner兜底 → fail-closed），tenant_id 隔离由 SQLAlchemy event 自动注入
- **兼容性**: 适配器模式确保 54 个 access_check 调用点无需改动，未映射的 AccessType 回退旧逻辑，GroupResource 只读查询保留
- **可观测性**: OwnerService 操作通过 loguru 记录 INFO/WARNING 日志，FailedTuple 补偿队列提供异常可追溯性

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- ReBAC 核心: [features/v2.5.0/004-rebac-core/spec.md](../004-rebac-core/spec.md)
- 前端权限 UI: [features/v2.5.0/007-resource-permission-ui/spec.md](../007-resource-permission-ui/spec.md)
- 配额管理: [features/v2.5.0/005-role-menu-quota/spec.md](../005-role-menu-quota/spec.md)
- 数据迁移: [features/v2.5.0/006-permission-migration/spec.md](../006-permission-migration/spec.md)
