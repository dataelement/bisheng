# Feature: F058 系统管理员调整部门知识库所属部门

**Feature ID**: `058-admin-reassign-department-space`  
**Status**: Implemented — 自动化验证完成，外部环境验证待执行  
**Mode**: Spec First  
**Created**: 2026-07-16  
**Updated**: 2026-07-16  
**Priority**: P1  
**Version**: v2.6.0  
**关联需求**: 首钢门户知识库编辑需求（2026-07-16）

---

## 1. 概述

当前部门知识库编辑抽屉中的“知识库层级”只读展示为“部门知识库 - 所属部门”，系统管理员无法修正错误的部门归属。

本特性允许 `admin` 系统管理员将一个现有部门知识库从部门 A 调整到尚未绑定知识库的部门 B。调整前后知识库层级始终为 `department`；知识库内容、创建者、手工成员、标签配置、上传审批及敏感内容检测配置保持不变。

### 用户故事

作为 **系统管理员**，我希望 **在编辑部门知识库时修改其所属部门**，以便 **修正部门归属错误，并同步更新部门成员和部门管理员的默认权限**。

---

## 2. 已确认业务规则

| ID | 规则 |
|----|------|
| BR-001 | 本需求只修改部门知识库的所属部门，不修改知识库层级；`space_level` 始终为 `department`。 |
| BR-002 | 只有 `admin` 系统管理员可以执行所属部门调整；租户管理员、部门管理员、知识库 creator/admin 和仅持有 `edit_space` 的用户均不可执行。 |
| BR-003 | 部门与部门知识库继续保持一对一关系；目标部门已绑定知识库时禁止调整。 |
| BR-004 | 调整后撤销旧部门自动获得的范围权限，并为新部门应用部门知识库默认权限。 |
| BR-005 | 手工添加的知识库成员及其角色保持不变。 |
| BR-006 | 原知识库的 `approval_enabled` 和 `sensitive_check_enabled` 保持不变。 |
| BR-007 | 目标部门已绑定知识库时提示“目标部门已绑定知识库”。 |

---

## 3. 范围

### 3.1 包含

- 系统管理员在知识库编辑抽屉查看并选择目标部门。
- 校验目标部门存在、有效、属于当前租户且未绑定其他知识库。
- 更新 `department_knowledge_space.department_id`。
- 同步更新 `knowledge_space_scope.owner_id`，保持 `level=department`、`owner_type=department`。
- 撤销旧部门及其子部门对知识库的默认 `viewer` 授权，授予新部门及其子部门默认 `viewer` 授权。
- 撤销旧部门管理员自动获得的 `manager` 身份，并为新部门管理员同步默认 `manager` 身份。
- 保留 `membership_source=manual` 的成员和角色；曾因部门管理员身份被临时提升的成员恢复其原手工角色。
- 保存成功后刷新知识库详情、侧边栏和相关知识库列表缓存。

### 3.2 不包含

- 将部门知识库改为公共、团队或个人知识库。
- 修改 `space_level`、知识库创建者或 owner 用户。
- 允许一个部门绑定多个知识库。
- 文件、目录、标签或知识库内容迁移。
- 合并两个部门知识库。
- 改变知识库名称唯一性规则。
- 修改上传审批或敏感内容检测配置。
- 扩大租户管理员、部门管理员或普通知识库管理员的操作权限。
- 修改独立仓库 `shougang-group-knowledge-portal`；截图对应实现位于 BiSheng Client 前端。

---

## 4. 需求 Requirements

### REQ-001：系统管理员编辑所属部门

系统必须允许 `admin` 系统管理员在编辑部门知识库时选择新的所属部门；非系统管理员继续看到只读层级信息。

### REQ-002：目标部门合法性与一对一约束

系统必须只接受当前租户内处于有效状态且尚未绑定其他知识库的目标部门，并保留现有一对一唯一约束作为并发兜底。

### REQ-003：部门归属数据一致性

系统必须在同一数据库事务中更新部门绑定、知识库范围归属及部门来源成员状态；冲突或数据库失败时不得留下部分数据库变更。

### REQ-004：默认权限迁移与手工成员保留

系统必须撤销旧部门自动权限、应用新部门默认权限，并保留所有手工成员及其角色。OpenFGA 写入失败必须留下可重试的 `FailedTuple` 记录，不得静默丢失。

### REQ-005：知识库业务数据保持不变

系统不得修改知识库内容、文件、目录、标签、创建者、自动标签绑定、上传审批和敏感内容检测配置。

### REQ-006：前端反馈与刷新

系统必须对目标部门冲突展示明确提示；成功后展示新部门并刷新所有相关知识库缓存。

---

## 5. 验收标准 Acceptance Criteria

| ID | 关联需求 | 场景 | 预期结果 | 验证方式 |
|----|----------|------|----------|----------|
| AC-01 | REQ-001, REQ-006 | `admin` 打开部门知识库编辑抽屉 | 显示当前所属部门，并可从当前租户有效部门中选择目标部门。 | Client 组件测试 + 人工冒烟 |
| AC-02 | REQ-001 | 非 `admin` 打开编辑抽屉或直接调用调整接口 | 页面保持只读；后端拒绝请求，绑定和权限均不变化。 | Client 组件测试 + Backend API 测试 |
| AC-03 | REQ-002, REQ-003 | `admin` 选择未绑定知识库的有效目标部门并保存 | `department_knowledge_space.department_id` 与 `knowledge_space_scope.owner_id` 同步更新；`space_level` 仍为 `department`。 | Backend service/API 测试 |
| AC-04 | REQ-002, REQ-006 | 目标部门已绑定其他知识库 | 请求失败并提示“目标部门已绑定知识库”；数据库和权限无变化。 | Backend 并发/冲突测试 + Client 错误提示测试 |
| AC-05 | REQ-002, REQ-003 | 目标部门不存在、已归档、跨租户，或源知识库不是部门知识库 | 请求失败；不得产生任何绑定、范围或成员变更。 | Backend 参数化测试 |
| AC-06 | REQ-003 | 目标部门与当前部门相同 | 接口幂等成功，不重复写权限、不改变成员和配置。 | Backend service/API 测试 |
| AC-07 | REQ-004 | 调整成功 | 旧部门范围 `viewer` 被撤销，新部门范围 `viewer` 被授予；旧部门自动管理员被撤销，新部门管理员获得默认管理权限。 | Backend service 测试 + OpenFGA operation 断言 |
| AC-08 | REQ-004 | 原知识库存在手工成员，或手工成员曾被部门管理员身份临时提升 | 手工成员保留；临时提升者在失去旧部门管理员身份后恢复原手工角色。 | Backend service 测试 |
| AC-09 | REQ-004 | 数据库提交后的 OpenFGA 写入失败 | 权限操作写入 `FailedTuple` 并可重试；接口和日志不得伪报权限同步成功。 | Backend failure-path 测试 |
| AC-10 | REQ-005 | 调整成功 | `approval_enabled`、`sensitive_check_enabled`、知识库内容、文件、标签、创建者和自动标签绑定保持不变。 | Backend snapshot 测试 |
| AC-11 | REQ-006 | 调整成功后重新加载门户 | 编辑抽屉、侧边栏和知识库详情展示新的所属部门。 | Client query invalidation 测试 + 人工冒烟 |

---

## 6. API 契约

### 6.1 调整所属部门

```http
PUT /api/v1/knowledge/space/department-binding/{space_id}
Content-Type: application/json
```

请求：

```json
{
  "department_id": 42
}
```

成功响应：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "space_id": 1001,
    "space_level": "department",
    "department_id": 42,
    "department_name": "制造部"
  }
}
```

### 6.2 错误契约

| 场景 | 错误类型/状态 | 用户提示 |
|------|---------------|----------|
| 非系统管理员 | 复用现有 `UnAuthorizedError` | 无权执行该操作 |
| 知识库不存在或不是部门知识库 | `SpaceNotFoundError` 或明确的部门知识库校验错误 | 当前知识库不是可调整的部门知识库 |
| 目标部门不存在、已归档或跨租户 | `DepartmentNotFoundError` | 目标部门不存在或不可用 |
| 目标部门已绑定其他知识库 | `DepartmentKnowledgeSpaceExistsError`（`18002`） | 目标部门已绑定知识库 |
| 数据库并发唯一冲突 | 统一转换为 `DepartmentKnowledgeSpaceExistsError`（`18002`） | 目标部门已绑定知识库 |

路由仍使用现有 `resp_200(...)` 成功包装和 `BaseErrorCode.return_resp_instance()` 业务错误返回方式，不新增响应协议。

---

## 7. 数据与事务设计

### 7.1 数据模型

不新增表、不删除字段、不放宽约束，也不需要 Alembic migration。

现有约束继续生效：

- `department_knowledge_space.department_id` 唯一：一个部门最多绑定一个知识库。
- `department_knowledge_space.space_id` 唯一：一个知识库最多绑定一个部门。
- `knowledge_space_scope.space_id` 唯一：一个知识库只有一个范围归属。

### 7.2 数据库事务

单次调整必须在一个 AsyncSession 事务内完成：

1. 锁定并读取源 `department_knowledge_space`、源 `knowledge_space_scope` 和目标部门绑定状态。
2. 再次校验源空间层级、目标部门状态、租户边界及唯一性。
3. 更新 `department_knowledge_space.department_id`。
4. 更新 `knowledge_space_scope.owner_id`，保持 `level=department`、`owner_type=department`。
5. 调整 `membership_source=department_admin` 的自动成员；保留或恢复手工成员。
6. 事务成功后提交；任何异常均回滚全部数据库写入。

并发请求即使同时通过预检，也必须由唯一约束阻止双重绑定，并将唯一冲突转换为稳定业务错误 `18002`。

### 7.3 OpenFGA 一致性

数据库与 OpenFGA 无法组成真正的分布式事务。本特性遵循现有项目一致性约定：

- 数据库事务成功后，按一个批次提交旧部门撤销和新部门授予操作。
- 使用 `PermissionService.batch_write_tuples(..., crash_safe=True)` 预记录 `FailedTuple`。
- OpenFGA 成功后清理补偿记录；失败时保留记录供重试，日志和响应不得把权限同步状态伪报为成功。
- 永久性权限丢失不允许；OpenFGA 故障期间允许存在可观察、可补偿的短暂最终一致窗口。

---

## 8. 权限与成员迁移规则

| 对象 | 旧部门处理 | 新部门处理 | 保留规则 |
|------|------------|------------|----------|
| 部门范围成员 | 撤销部门及子部门 `viewer` | 授予部门及子部门 `viewer` | 不影响其他显式授权 |
| 部门管理员自动成员 | 删除纯自动成员；临时提升成员恢复原角色 | 新增或提升为 `manager`，记录部门来源 | creator 永不降级或删除 |
| 手工成员 | 不删除、不降级 | 不重复新增 | `membership_source=manual` 和角色保持不变 |
| 知识库 owner/creator | 不变 | 不变 | 不做资源 owner 转移 |

权限修改必须通过 `PermissionService`，不得直接写 OpenFGA 或读取 `role_access`。

---

## 9. 前端行为

### 9.1 编辑抽屉

- 创建模式保持现有行为。
- 编辑部门知识库时：
  - `user.is_global_super === true`：显示单选部门选择器，默认选中当前部门；子租户管理员不显示。
  - 其他用户：继续显示只读“部门知识库 - 部门名称”。
- 仅在目标部门与当前部门不同时调用所属部门调整接口。
- 部门列表加载失败时禁止提交部门调整，并显示明确错误。
- 目标部门冲突时保留抽屉和用户输入，显示“目标部门已绑定知识库”。

### 9.2 成功刷新

成功后至少失效以下查询或等价缓存：

- `knowledgeSpaces` 列表与分组。
- 当前知识库详情。
- 部门知识库列表。

界面必须使用后端响应中的部门信息更新当前激活知识库，不能只依赖页面重载。

---

## 10. 架构决策

| ID | 决策 | 备选方案 | 结论与理由 |
|----|------|----------|------------|
| AD-01 | 操作语义 | 修改 `space_level` / 只修改所属部门 | 只修改所属部门。用户已确认层级仍为部门，避免扩大权限模型。 |
| AD-02 | API 边界 | 扩展通用知识库更新 / 增加专用 binding 更新端点 | 增加 `PUT /department-binding/{space_id}`。便于强制系统管理员权限和独立验证高风险归属变更。 |
| AD-03 | 一对一关系 | 放宽为一对多 / 保留唯一约束 | 保留唯一约束。用户确认目标部门已有知识库时禁止变更。 |
| AD-04 | 审批配置 | 重置默认值 / 复制目标值 / 保留原值 | 保留原值。审批和敏感检测是知识库级配置，不因部门调整改变。 |
| AD-05 | 手工成员 | 清空 / 全部保留 / 仅保留 creator | 保留手工成员；只处理部门来源成员。 |
| AD-06 | OpenFGA 一致性 | 忽略失败 / 强同步且无补偿 / crash-safe 最终一致 | 使用 crash-safe `FailedTuple`；符合现有架构并避免静默权限丢失。 |

---

## 11. 文件结构计划

> 以下为规格阶段的职责边界；最终任务拆分在本规格确认后写入 `tasks.md`。

### 新建候选文件

| 文件 | 职责 |
|------|------|
| `src/backend/bisheng/knowledge/domain/repositories/interfaces/department_space_assignment_repository.py` | 定义部门归属事务操作接口。 |
| `src/backend/bisheng/knowledge/domain/repositories/implementations/department_space_assignment_repository_impl.py` | 在单个 AsyncSession 事务中更新 binding、scope 和部门来源成员。 |
| `src/backend/test/knowledge/test_department_space_reassignment.py` | 覆盖服务、事务、权限及 API 契约。 |

### 修改候选文件

| 文件 | 变更内容 |
|------|----------|
| `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py` | 新增 `PUT /department-binding/{space_id}`。 |
| `src/backend/bisheng/knowledge/api/dependencies.py` | 注入事务 repository（若采用依赖注入落点）。 |
| `src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py` | 新增归属调整编排、预检和权限变更逻辑。 |
| `src/frontend/client/src/api/knowledge.ts` | 新增所属部门调整 API。 |
| `src/frontend/client/src/pages/knowledge/CreateKnowledgeSpaceDrawer.tsx` | 系统管理员编辑态部门选择器与提交数据。 |
| `src/frontend/client/src/pages/knowledge/index.tsx` | 调用调整接口并刷新当前空间及查询缓存。 |
| `src/frontend/client/src/pages/knowledge/CreateKnowledgeSpaceDrawer.test.tsx` | 管理员可编辑、非管理员只读、预选及错误状态。 |
| `src/frontend/client/src/api/knowledge.test.ts` | API 路径和请求体测试。 |
| `src/frontend/client/src/locales/zh-Hans/translation.json` | 补充冲突和加载失败文案（若现有键不足）。 |

明确不修改当前已有未提交变更涉及的 `knowledge_space_service.py` 和 `knowledge_space_schema.py`，优先通过专用 Service、Repository 和路由局部实现避免覆盖用户工作。

---

## 12. 验证矩阵

| Verification ID | 方法 | 覆盖 AC |
|-----------------|------|---------|
| V-001 | `uv run pytest test/knowledge/test_department_space_reassignment.py -q` | AC-02..AC-10 |
| V-002 | `uv run ruff check` 与 `uv run ruff format --check`（仅本特性后端文件） | 后端静态质量 |
| V-003 | Client 定向 Jest：`CreateKnowledgeSpaceDrawer.test.tsx`、`knowledge.test.ts` | AC-01, AC-02, AC-04, AC-11 |
| V-004 | Client TypeScript/ESLint 定向检查 | 前端类型与静态质量 |
| V-005 | 人工冒烟：admin 转移成功、非 admin 只读、目标冲突、刷新后分组变化 | AC-01, AC-02, AC-04, AC-11 |
| V-006 | MySQL 自动化测试 + DM8 CI/人工验证 | AC-03..AC-06、双数据库兼容 |

---

## 13. 非功能要求

- **安全**：后端必须以请求上下文预解析的 `login_user.is_global_super` 为权威判断，不能依赖前端隐藏控件或会包含子租户管理员的 `is_admin()`。
- **租户隔离**：源知识库、源部门、目标部门必须属于当前租户；不得手写绕过租户过滤条件。
- **兼容性**：不改变现有创建、绑定、解绑和普通知识库编辑接口行为。
- **性能**：单次调整只处理一个知识库和两个部门的管理员集合，不执行全租户知识库扫描。
- **可恢复性**：OpenFGA 失败必须有 `FailedTuple` 证据和重试路径。
- **可审计性**：关键日志包含 `space_id`、旧/新 `department_id`、操作者 `user_id` 和权限同步结果，不记录敏感数据。
- **双数据库**：所有事务与约束处理必须兼容 MySQL 和 DM8，不使用数据库专属 SQL。

---

## 14. 风险与回滚

| 风险 | 影响 | 控制措施 |
|------|------|----------|
| 并发调整到同一目标部门 | 唯一冲突 | 行级/事务校验 + 现有唯一约束兜底 + 稳定 `18002` 错误。 |
| 数据库成功但 OpenFGA 暂时失败 | 短暂权限不一致 | crash-safe `FailedTuple`、明确日志和可重试补偿。 |
| 将手工管理员误判为部门来源成员 | 手工权限丢失 | 仅按 `membership_source` 和 `department_admin_promoted_from_role` 处理，并做回归测试。 |
| 前端缓存未刷新 | 页面仍显示旧部门 | 使用后端返回数据更新 active space，并失效所有知识库查询。 |
| 工作区存在未提交修改 | 覆盖用户代码 | 避开已修改文件；编辑前复核 diff，禁止重置或覆盖现有变更。 |

回滚方式：系统管理员使用同一功能将知识库重新调整回原部门；数据库和权限同步遵循同一事务及补偿规则。若原部门已被其他知识库占用，则必须先解决一对一冲突，不允许强制覆盖。

---

## 15. Clarifications

| 日期 | 问题 | 用户确认 |
|------|------|----------|
| 2026-07-16 | 允许修改哪些层级？ | 仅修改部门知识库所属部门，层级保持 `department`。 |
| 2026-07-16 | 哪些角色可操作？ | 仅 `admin` 系统管理员。 |
| 2026-07-16 | 权限如何处理？ | 撤销旧部门自动权限、应用新部门默认权限、保留手工成员。 |
| 2026-07-16 | 目标部门已有知识库如何处理？ | 禁止变更并提示“目标部门已绑定知识库”。 |
| 2026-07-16 | 审批和敏感检测配置如何处理？ | 保留原知识库配置。 |

---

## 16. 相关文档

- [v2.6.0 Release Contract](../release-contract.md)
- `src/backend/AGENTS.md`
- `features/_templates/spec.md`
