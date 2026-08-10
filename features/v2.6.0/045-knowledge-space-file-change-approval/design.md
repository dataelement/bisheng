# Design: 知识空间文件与文件夹变更审核

> **本文档定位 — 现状快照（Why this How）**
>
> - [spec.md](./spec.md) 回答做什么、验收标准和范围边界。
> - 本文回答为什么采用当前实现、运行时数据流、契约和已知风险。
> - [tasks.md](./tasks.md) 在设计确认后生成，记录实施顺序和实际偏差。

**关联**: [spec.md](./spec.md) · `tasks.md`（待创建）
**版本**: v2.6.0
**最后更新**: 2026-08-10

---

## 1. 目标与非目标

### 1.1 目标

- 在不把未审批上传写入正式知识空间文件表的前提下，为上传建立独立暂存和审批链路。
- 对正式文件和文件夹的重命名、移动、删除增加审批网关；审批通过前保持当前正式状态不变，通过后复用现有权威业务链路执行。
- 文件夹申请覆盖整个子树；通过统一互斥检查阻止同资源、祖先文件夹和子树中的并行变更审批。
- 文件列表和审批中心展示同一审批实例；详情明确动作及待生效变更。
- 每个租户独立保存审核策略；私密知识空间免审，部门知识空间禁止变为私密。

### 1.2 非目标

- 不扩展已废弃的 `approval_request` 部门空间文件上传审批系统。
- 不给频道内容增加上传、重命名、移动或删除审核。
- 不重写解析、版本、F034 移动、删除、OpenFGA 或检索链路。
- 不把业务暂存表作为审批状态事实源；审批状态仍只认 F025 的 `approval_instance` / `approval_task`。
- 不为私密知识空间保留“可强制开启审核”的例外开关。

---

## 2. 关键约束

- 遵循 [docs/constitution.md](../../../docs/constitution.md) C1–C7 与 [release-contract.md](../release-contract.md)。新增表使用 `JsonType`、`UPDATE_TIME_SERVER_DEFAULT` 等双数据库兼容类型；所有表带 `tenant_id`。
- 审批统一走 F025 `ApprovalGate → ApprovalInstance/Task → ApprovalOutbox → Celery → handler.on_approved()`；审批通过不代表业务执行成功。
- 审批回调必须重新校验当前权限、资源状态、目标位置和结构约束；失败必须抛异常，使实例进入 `execute_failed`，不能返回假成功。
- `KnowledgeFile` 同时表示正式文件和文件夹。未审批上传不得提前创建 `KnowledgeFile`、`KnowledgeDocument`、版本、FGA child tuple 或解析任务。
- F034 跨空间移动会迁移版本链、检索数据、标签和 parent tuple；本功能只能在审批通过后调用该权威执行路径，不复制移动实现。
- 文件夹变更覆盖子树。冲突判断必须同时检查“当前资源的祖先存在审批”和“待操作文件夹子树存在审批”，并发下不能只靠应用层先查后写。
- 租户策略不得继承根租户配置。现有 `WORKSTATION_KNOWLEDGE_SPACE` 配置具有 root-share fallback，不适合本功能。
- 上传原文件已经由 `/api/v1/knowledge/upload/{space_id}` 暂存；审批等待期间必须有可回收的临时对象生命周期，不能让拒绝/撤回长期泄漏 MinIO。
- 文件列表沿用 F027 cursor 契约；审批状态补充必须批量查询，禁止逐行查询审批实例或形成 N+1。

---

## 3. 方案对比与选定

### 决策 1：独立变更申请表，不给正式文件表增加审批状态

- **备选**：
  - A. 给 `KnowledgeFile` 增加审批状态、动作和审批实例字段。
  - B. 只使用 `approval_instance.payload_snapshot`，列表实时扫描审批表。
  - C. 新增知识空间变更申请业务表，正式文件表保持原语义；审批状态通过关联实例读取。
- **选定**：C。
- **原因**：A 会让未审批上传必须提前创建正式文件，并迫使检索、列表、版本和 FGA 链路识别新状态，违背“尽量不改主流程”。B 无法可靠保存上传临时对象和批量查询资源锁，也难以表达文件夹子树占用。C 让业务表只承载暂存、动作快照、资源关联和查询索引，审批状态仍来自 F025。
- **何时重新考虑**：未来正式文件模型原生支持 draft/published 双态，且所有检索入口统一基于发布态过滤时，可合并暂存模型。

### 决策 2：租户总控和单空间配置使用专属关系表

- **备选**：
  - A. 扩展 `WORKSTATION_KNOWLEDGE_SPACE` JSON 配置。
  - B. 在 `Knowledge` 增加单空间布尔字段，并另建租户总控表。
  - C. 新建租户策略表和单空间设置表。
- **选定**：C。
- **原因**：A 具有根租户继承语义，违反“不同租户保存不同配置”，且 JSON 内的空间列表无法建立约束。B 会改动正式知识空间主表，并让总控关闭后恢复单空间配置的语义分散。C 可用 `(tenant_id)` 和 `(tenant_id, space_id)` 唯一约束清楚表达归属，不触碰 `Knowledge` 主表。
- **何时重新考虑**：若平台形成统一、无继承且带强类型 schema 的租户策略中心，可迁入该中心。

### 决策 3：上传先暂存，审批通过后才调用现有正式上传链路

- **备选**：
  - A. 先调用 `add_file()` 创建 WAITING 文件，审批通过后再派发解析。
  - B. 保留上传返回的临时对象路径，审批通过后调用现有正式注册和解析流程。
- **选定**：B。
- **原因**：A 会提前创建正式文件、版本和权限 tuple，要求所有列表与检索路径识别草稿。B 完全隔离待审批上传，审批通过后复用现有配额、去重、版本、权限初始化和 scheduler 行为。
- **代价**：审批等待期间的用户/租户容量预占不能靠正式文件统计完成，需要在变更申请表记录文件大小并纳入配额校验；执行时仍要再次校验实际配额。
- **何时重新考虑**：上传基础设施改为统一 multipart upload/session 模型时，可让暂存申请引用 upload session。

### 决策 4：现有 mutation 入口薄包装，直接执行体保持单一

- **备选**：
  - A. 在 endpoint 复制权限与策略判断，再决定调审批或原 Service。
  - B. 在 `KnowledgeSpaceService` 的公开 mutation 方法前接入 `KnowledgeSpaceFileChangeService`，把当前直接执行体提取为内部权威 executor。
- **选定**：B。
- **原因**：endpoint 只应做 DTO/response；复制逻辑会让单条、批量、文件夹上传和审批回调产生多套规则。公开入口统一执行“权限校验 → 策略判断 → 直接执行或创建审批”，审批 handler 只调用受控 executor；原重命名、移动、删除主体不重写。
- **防绕过**：executor 不暴露为 HTTP/公共 application API，只由编排服务和审批 handler 注入调用；所有 executor 在真正执行前仍重新校验申请人身份下的业务权限。
- **何时重新考虑**：知识空间 mutation 已整体迁入新的 command bus 时，再把 wrapper 变为 command middleware。

### 决策 5：单一审批场景，动作随不可变快照保存

- **备选**：
  - A. 上传、重命名、移动、删除各建一个场景。
  - B. 共用 `knowledge_space_file_change_request`，用 `action` 区分操作。
- **选定**：B。
- **原因**：四类动作共享相同策略、审批人和 OR 节点，拆场景会让每租户重复配置并产生漂移。`action`、资源、原值、目标值和上传暂存信息进入申请快照；handler 按动作分派。
- **何时重新考虑**：某一动作需要不同审批人、节点或 SLA，且路由条件无法清晰表达时拆场景。

### 决策 6：空间行锁串行化冲突检查，业务表负责资源占用索引

- **备选**：
  - A. 依赖 ApprovalGate 当前“申请人 + business_key”去重。
  - B. 仅在业务表加目标资源唯一索引。
  - C. 创建申请前对涉及空间按 ID 升序 `SELECT ... FOR UPDATE`，随后查询活跃审批的资源/祖先/子树重叠，再创建申请。
- **选定**：C。
- **原因**：A 允许不同申请人或不同动作并行；B 无法表达父文件夹与子资源重叠。C 在 MySQL/DM8 都可用，按空间串行的临界区只覆盖低频变更申请创建，可可靠阻止父子竞态。跨空间移动同时锁源、目标空间，固定升序避免死锁。
- **活跃定义**：关联审批实例状态属于 `pending / exception / approved / executing / execute_failed` 均视为占用；只有 `executed / rejected / withdrawn / cancelled` 释放。`approved` 在 outbox 执行完成前仍必须锁定。
- **何时重新考虑**：单空间变更申请达到高并发并出现明显锁等待时，升级为规范化祖先锁表；不能退回无事务的先查后写。

### 决策 7：文件夹审批锁覆盖整棵子树，但只展示根申请

- **选定**：业务表只创建文件夹根申请。冲突检查通过 `file_level_path` 判断祖先和子树；子项不生成审批实例。列表在根文件夹显示“审批中”，进入子目录时返回 `inherited_approval_lock` 使子项操作置灰，但不把每个子项伪装成独立审批。
- **原因**：符合“一次文件夹动作覆盖内部元素”，避免千文件夹生成千任务；同时用户在子目录操作时仍能获得明确阻止原因。
- **何时重新考虑**：产品要求子项可从父审批中排除时，必须升级为可编辑的批次清单，当前根快照不支持部分批准。

### 决策 8：审批人创建时解析，处理时再次校验当前身份

- **选定**：场景节点来源固定为 `knowledge_space_owner + knowledge_space_manager`，单节点 OR。任务创建时解析当前直接用户；`ApprovalCenterService.decide_task()` 在状态变更前调用可选 handler hook `validate_decision()`，文件变更 handler 重新确认处理人仍是当前空间 owner/manager。
- **原因**：仅依赖 task owner 会让已移除的管理者继续审批。只在文件页做校验会被审批中心入口绕过。
- **影响**：这是 F025 主流程的可选扩展，其他 handler 未实现 hook 时行为不变；实现后必须同步更新 `approval-module/SKILL.md`。
- **何时重新考虑**：审批中心原生支持动态候选人或任务自动撤换时，迁移到引擎级能力。

### 决策 9：终态 hook 只做业务清理，锁状态不复制

- **选定**：业务申请表保存 `approval_instance_id`，活跃/终态实时读取审批实例。`on_rejected/on_withdrawn/on_cancelled` 负责清理上传临时对象等副作用，但不维护一份决定锁定的独立状态。
- **原因**：F025 当前终态 hook 失败会记录日志但不回滚审批终态；若锁依赖业务表状态，hook 失败会永久锁死资源。以审批实例为事实源符合 INV-1，清理失败可由补偿任务重试。
- **何时重新考虑**：审批引擎提供事务性 domain event/outbox 后，可把清理也改为可靠事件消费。

### 决策 10：跨空间移动按源空间策略发起，执行时校验两端

- **选定**：是否需要审核由资源当前所在的源空间决定；私密源空间直接执行。申请创建时校验源资源 move 权限和目标 upload 权限，审批通过执行前再次校验两端、目标是否存在、层级、循环、重名和租户一致性。
- **原因**：动作发生在源资源上，审批人也是源空间 owner/manager。若按目标策略，会出现审批人归属不清和同一动作双审批。目标变化通过执行失败暴露，不静默改目标。
- **何时重新考虑**：产品要求跨空间接收方也必须确认时，应设计双阶段审批，不能在当前单节点 OR 流程上叠加隐式确认。

---

## 4. 系统现状（接手必读）

### 4.1 当前代码基线

- `knowledge/api/endpoints/knowledge_space.py` 暴露文件/文件夹创建、重命名、移动、删除入口。
- `KnowledgeSpaceService.add_file()` 当前会立即创建 `KnowledgeFile`、`KnowledgeDocument`、V1、FGA child tuple，并派发解析 scheduler。
- `rename_file()` / `rename_folder()` 当前直接改名称；成功文件重命名后会触发 chunk rebuild。
- `move_items()` 是 F034 权威实现，含权限、层级、循环、跨租户、版本链、FGA parent tuple、跨空间向量迁移和标签处理。
- `delete_file()` / `delete_folder()` 是权威删除实现，含版本级联、MinIO/索引清理任务和 FGA tuple 清理。
- F025 `ApprovalGate` 当前只按 `(tenant_id, scenario_code, business_key, applicant_user_id)` 查重，不能实现跨申请人的资源/子树互斥。
- client `useFileUpload.ts` 当前对删除做乐观移除；接入审批后必须改为根据 `direct/pending` 响应决定是否移除。

### 4.2 目标数据流

#### 4.2.1 策略判断

`mutation 入口 → 校验现有操作权限 → 读取空间及部门绑定 → 私密空间直接执行 → owner/manager 直接执行 → 读取当前租户策略和单空间设置 → 无需审核直接执行 / 需要审核创建申请`

判断顺序固定：权限校验优先，防止无权限用户借审批探测资源；之后是私密免审和 owner/manager 直通；最后计算租户/空间策略。

#### 4.2.2 待审批上传

`multipart 上传取得临时 file_path → POST files/folders-upload → 逐文件校验权限/配额 → 空间锁内创建 KnowledgeSpaceFileChangeRequest → ApprovalGate → 返回 pending → 独立待审批上传列表`

审批通过：

`approval outbox → KnowledgeSpaceFileChangeScenarioHandler.on_approved → 重新校验申请人权限/空间状态/配额 → 调正式 add_file executor → 创建正式文件/版本/FGA tuple → 派发解析 → 申请详情关联正式 file_id → outbox success`

拒绝、撤回、取消：删除临时对象并保留最小审计元数据；清理失败进入补偿扫描。待审批上传从不进入正式列表。

文件夹上传按文件分别创建申请，`relative_path` 保存在每条快照。审批通过时按路径幂等创建缺失目录；同一批中的审批顺序不影响最终目录结构。目录创建本身不单独审批。

#### 4.2.3 正式资源重命名/移动/删除

`请求 → 权限/策略 → 锁空间行 → 检查目标、祖先和子树活跃申请 → 创建业务申请及 ApprovalGate → 返回 pending`

审批期间不修改 `KnowledgeFile`。列表批量关联活跃申请并展示根资源“审批中”；详情来自申请的不可变动作快照。

审批通过：

`outbox → handler → 重新校验当前资源与申请快照 → 调 rename/move/delete executor → 成功后 ApprovalOutbox=success、ApprovalInstance=executed`

执行失败：原业务动作必须保持未执行或按既有原子边界回滚；异常抛出后由 F025 标记 `execute_failed`。该状态继续占用资源，管理员重试成功或取消后才释放。

### 4.3 数据模型

#### `knowledge_space_file_change_policy`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | 主键 |
| `tenant_id` | bigint | 非空、唯一；无跨租户继承 |
| `enabled` | bool | 总开关；默认 `true` |
| `scope` | varchar(32) | `all_spaces` / `per_space`，默认 `per_space` |
| `create_time/update_time` | datetime | 双 DB 通用时间默认值 |

#### `knowledge_space_file_change_setting`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | 主键 |
| `tenant_id` | bigint | 当前租户 |
| `space_id` | bigint | 知识空间 ID；与 tenant 组成唯一约束 |
| `approval_required` | bool | 单空间是否审核，默认 `true` |
| `create_time/update_time` | datetime | 更新时间用于后台展示 |

总开关关闭不删除 setting；重新开启恢复原值。`all_spaces` 忽略 setting 但不删除。无 policy 行时读取默认 `enabled=true, scope=per_space`；无 setting 行时默认 `approval_required=true`。私密空间最终结果始终为 false。

#### `knowledge_space_file_change_request`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | 业务申请 ID |
| `tenant_id` / `space_id` | bigint | 源租户和源空间 |
| `action` | varchar(32) | `upload / rename / move / delete` |
| `resource_type` | varchar(32) | `staged_upload / knowledge_file / folder` |
| `resource_id` | bigint nullable | 正式资源 ID；上传审批前为空 |
| `applicant_user_id` | bigint | 业务执行时重新校验的身份 |
| `approval_instance_id` | bigint nullable unique | F025 实例；创建 gate 后回填 |
| `staged_object_name` | varchar(1024) nullable | 上传临时对象引用，不返回给普通列表 |
| `file_name` / `file_size` | varchar/bigint nullable | 待审批上传展示和容量预占 |
| `source_parent_id` | bigint nullable | 发起时父目录 |
| `target_space_id` / `target_parent_id` | bigint nullable | move 目标 |
| `action_snapshot` | `JsonType` | 原名称/新名称、原路径、relative_path、版本指纹等不可变详情；不通过 JSON 字段做过滤 |
| `executed_resource_id` | bigint nullable | 上传成功后的正式文件 ID |
| `cleanup_state` | varchar(32) | `none / pending / success / failed`，只表示临时对象清理，不表示审批状态 |
| `create_time/update_time` | datetime | 审计和清理扫描 |

审批实例的 `business_key` 使用 `knowledge-space-change:{request_id}`，避免依赖可变文件名；`business_resource_type` 为 `knowledge_space_file_change`，`business_resource_id` 为业务申请 ID。正式资源互斥由空间锁内的业务查询保证，不依赖 ApprovalGate 的申请人级去重。

所有三个模型放在 `knowledge/domain/models/`，Repository 放在 `knowledge/domain/repositories/`。表由 SQLModel 创建；如果同版本其他迁移或部署顺序依赖索引，则补 Alembic DDL。不得在 migration 中 seed 或回填租户数据。

### 4.4 审批场景和 handler

新增 preset：

```text
scenario_code = knowledge_space_file_change_request
handler_key   = knowledge_space_file_change_request
condition_fields = applicant_role, action, resource_type
approver_source_types = knowledge_space_owner, knowledge_space_manager
```

默认场景为单 catch-all flow、单节点、`node_mode=or`，来源同时包含 owner 和 manager。策略首次保存时幂等确保当前租户存在该场景；新租户创建流程同步 seed。已有租户无需继承根租户场景。管理员可在审批中心查看场景，但不能把处理人改成与 spec 冲突的来源；实现阶段在 preset/管理校验中限制允许来源。

`KnowledgeSpaceFileChangeScenarioHandler`：

- `build_title/build_detail`：输出空间、资源名称、动作、原值和目标值；不暴露 MinIO object name。
- `resolve_approvers`：复用知识空间 owner/manager 解析，去重并排除申请人（申请人若已变为 owner/manager，策略入口本应直通；竞态时不得自审）。
- `validate_decision`：处理前实时确认任务用户仍是目标空间 owner/manager。
- `on_approved`：按 action 调业务 executor，成功才返回；任何前置条件或副作用失败都抛出。
- `on_rejected/on_withdrawn/on_cancelled`：上传动作触发临时对象清理；正式资源动作无需回滚，因为尚未执行。

`approval_runtime_handler_factory.py` 注册运行时 handler；`approval_registry.py` 注册 preset；审批 skill 的场景、代码锚点、通知矩阵同步更新。

### 4.5 API 契约

#### 4.5.1 管理后台策略

- `GET /api/v1/knowledge/space/admin/file-change-policy`
- `PUT /api/v1/knowledge/space/admin/file-change-policy`
- `GET /api/v1/knowledge/space/admin/file-change-settings?keyword=&page=&page_size=`
- `PUT /api/v1/knowledge/space/admin/file-change-settings/{space_id}`

仅当前租户管理员可访问，不接受客户端 `tenant_id`。策略响应：

```json
{
  "enabled": true,
  "scope": "per_space"
}
```

单空间列表返回 `space_id/name/auth_type/space_kind/approval_required/effective_required`；私密空间 `effective_required=false` 且设置控件禁用，部门空间不允许 private。

#### 4.5.2 mutation 统一结果

单条上传、重命名、移动、删除统一使用：

```json
{
  "decision": "direct | pending",
  "approval_instance_id": 123,
  "change_request_id": 456,
  "resource": null
}
```

直接执行时 `resource` 使用原接口的资源结果，审批字段为空；pending 时正式资源不变。现有路径保持，但响应扩展：

- `POST /knowledge/space/{space_id}/files`
- `PUT /knowledge/space/{space_id}/files/{file_id}`
- `PUT /knowledge/space/{space_id}/folders/{folder_id}`
- `DELETE /knowledge/space/{space_id}/files/{file_id}`
- `DELETE /knowledge/space/{space_id}/folders/{folder_id}`

F034 批量 move 保留 `moved/invalid`，新增 `pending`：

```json
{
  "moved": [],
  "pending": [{"id": 1, "type": "file", "approval_instance_id": 123, "change_request_id": 456}],
  "invalid": []
}
```

批量删除同样改为逐项 `deleted/pending/invalid`，不能继续返回全空成功并让 client 乐观删除所有行。

#### 4.5.3 待审批上传和资源审批详情

- `GET /knowledge/space/{space_id}/file-changes/uploads?status=&cursor=&limit=`：申请人看自己的记录；当前 owner/manager 看可审批记录。响应不返回临时对象路径。
- `GET /knowledge/space/{space_id}/file-changes/{request_id}`：返回动作详情和可见的审批摘要。
- `GET /knowledge/space/{space_id}/file-changes/{request_id}/preview`：申请人/当前有效审核人获取短时预览 URL。
- `DELETE /knowledge/space/{space_id}/file-changes/{request_id}`：仅上传暂存清理；若审批仍 pending，先走撤回再清理，不创建删除审批。
- `POST /knowledge/space/{space_id}/file-changes/tasks/batch-approve`：只接受 task IDs，逐任务调用审批中心权威 decision service，不直接批量改实例状态。

正式文件/文件夹列表项扩展：

```ts
interface FileChangeApprovalView {
  status: 'pending' | 'exception' | 'approved' | 'executing' | 'execute_failed';
  action: 'rename' | 'move' | 'delete';
  instanceId: number;
  requestId: number;
  inherited: boolean;
  rootResourceId: number;
}
```

只有申请人和当前有效审核人收到完整字段。其他用户继续看到普通资源且字段为空。子树内项目可返回 `inherited=true` 以禁用操作，但 UI 只在根资源展示审批标签。

### 4.6 前端设计

#### Client

- `api/knowledge.ts` 扩展 mutation 结果、待审批上传列表、详情、预览和批量通过 API；不在 store 中发 HTTP。
- `useFileUpload.ts` 删除“调用前乐观移除”。只有 `decision=direct` 或批量结果进入 `deleted` 才移除；`pending` 原地标记审批中。
- `useKnowledgeMove.ts` 对 `pending` 保持源位置，关闭移动弹窗并刷新；不得提供 F034 同空间撤回 toast，因为动作尚未执行。
- `FileTable.tsx` / `FileCard.tsx` 在根资源显示“审批中”，详情展示动作及待生效值；资源或祖先带 lock 时重命名/移动/删除菜单禁用。
- 新增待审批上传面板，与正式文件列表分离；支持预览、撤回/清理和审核人批量通过。
- `ApprovalCenterDialog.tsx` 继续消费通用 `detail_snapshot`；补动作字段展示和通过后选中下一条的现有交互，不复制审批状态。
- 三语言 locale 同步新增；不引入新 UI/state 库。

#### Platform

- 在知识空间配置页增加“知识空间文件变更审核”总控、范围和单空间表格。
- `controllers/API/knowledgeSpaceFileChange.ts` 封装管理 API；页面只保存本地表单，点击保存成功后才更新基线。
- 私密空间行显示“无需审核”且禁用；部门空间不提供私密选项。

### 4.7 部门知识空间禁止私密

- `DepartmentKnowledgeSpaceService.batch_create_spaces()` 对显式 `auth_type=private` 返回领域错误，不静默改写。
- `KnowledgeSpaceService.update_knowledge_space()` 在目标空间存在 `DepartmentKnowledgeSpace` 绑定且请求切换为 private 时拒绝；不能只依赖前端隐藏选项。
- 创建默认继续使用非私密类型。若历史数据存在私密部门空间，部署前由独立运维脚本审计和修复；Alembic 不做数据迁移。

### 4.8 关键模块职责

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `knowledge_space_file_change_policy` models/repository/service | 租户策略与单空间设置 | 不读取根租户 fallback，不判断用户业务权限 |
| `knowledge_space_file_change_request` model/repository | 暂存引用、动作快照、实例关联、批量状态查询 | 不复制审批状态，不执行业务动作 |
| `KnowledgeSpaceFileChangeService` | 策略判断、空间锁、冲突检查、gate 编排、列表 enrichment | 不直接写审批表，不复制 rename/move/delete 主体 |
| `KnowledgeSpaceFileChangeScenarioHandler` | 审批详情、动态审核人、终态 hook、批准后执行 | 不吞执行异常，不返回 HTTP response |
| `KnowledgeSpaceMutationExecutor`（或现有 Service 内部 executor） | 复用现有上传/重命名/移动/删除权威实现 | 不自行决定是否审批，不允许 endpoint 直接绕过 |
| `ApprovalCenterService` | 在 decision 前调用可选 `validate_decision` | 不硬编码知识空间角色规则 |
| client knowledge 页面 | 状态展示、禁用操作、待上传面板、逐项结果 | 不把本地状态当审批事实，不直接处理 403 |
| platform 知识空间配置 | 当前租户策略表单和单空间配置 | 不传 tenant_id，不缓存其他租户设置 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | ApprovalGate 去重包含 applicant_user_id，不能满足资源级互斥 | 两个编辑者可同时删除/移动同一文件 | 空间行锁 + change request/instance 活跃查询 |
| 2 | `approved` 不是完成，outbox 执行前资源仍未变更 | 提前解锁后第二个动作与执行任务竞态 | 活跃状态包含 approved/executing/execute_failed |
| 3 | 终态 handler hook 失败不会回滚审批终态 | 若锁状态存在业务表会永久锁死 | 锁状态实时读取 approval_instance；清理另做补偿 |
| 4 | 当前 add_file 在解析前已经创建正式文件、版本和 FGA tuple | 只阻止 scheduler 仍会让待审批文件进入正式列表 | 审批前完全不调用 add_file，只保存 staged object |
| 5 | 当前 client 删除是乐观移除 | pending 响应会让仍存在的文件从页面消失 | useFileUpload 按逐项 decision 决定移除 |
| 6 | 文件夹锁不是单资源唯一约束，祖先/子树都可能冲突 | 父文件夹删除与子文件移动可同时获批 | 锁空间行后做双向路径重叠查询 |
| 7 | 文件夹上传当前会先重建目录树再逐文件 add_file | 会提前创建正式目录，且审批顺序影响结果 | 暂存 relative_path；批准时幂等创建目录 |
| 8 | 跨空间移动有两端权限、版本链和异步检索迁移 | handler 若只改 knowledge_id 会破坏 F034 不变量 | 只调用 F034 executor，执行前重校验两端 |
| 9 | 现有 workstation knowledge config 会继承 root | 子租户可能读到根租户开关 | 专属 policy 表，tenant_id 唯一，无 fallback |
| 10 | 私密是 `Knowledge.auth_type=private`，部门空间身份来自绑定表 | 仅看 auth_type 无法禁止部门空间切私密 | update 时查 DepartmentKnowledgeSpace 绑定 |
| 11 | 审核人可能在任务创建后被移除 | 旧 task 仍属于该用户 | decide_task 前 handler.validate_decision |
| 12 | 上传等待期仍占 MinIO 和租户配额 | 大量待审文件可绕过正式容量统计 | staged file_size 纳入配额；终态清理 + 补偿任务 |
| 13 | 文件重命名成功会触发 chunk rebuild | 审批通过不等于名称相关检索数据已更新 | executor 原样调用现有 rename；失败进入 execute_failed |
| 14 | 审批详情 payload 会返回给申请人和审批人 | 放入 object path 会泄露内部存储结构 | object path 只存业务表，detail_snapshot 只放业务字段 |

---

## 6. 对外契约与依赖

### 6.1 Outgoing

| 契约 | 消费者 | 兼容风险 |
|---|---|---|
| 现有文件/文件夹 mutation 响应增加 `decision` | client knowledge 页面 | 所有调用方需迁移，尤其删除不能再假定 200=已删除 |
| move/batch-delete 增加逐项 `pending` | client 批量操作 | 旧客户端会忽略 pending，必须同版本发布 |
| 文件列表增加可选 `file_change_approval` | client table/card/tree | 字段按可见性裁剪，不能用于服务端授权 |
| 管理策略 API | platform 知识空间配置 | 只作用当前 tenant，不接受 tenant_id |
| 待审批上传/详情/批量通过 API | client | task IDs 必须回到 ApprovalCenterService 处理 |
| `KnowledgeSpaceFileChangeScenarioHandler` | ApprovalGate/outbox/runtime factory | handler key 和 snapshot 字段变化会破坏存量实例重试 |

### 6.2 Incoming

| 依赖 | 风险点 |
|---|---|
| F025 ApprovalGate/Outbox/终态 hooks | 状态集合或 hook 时机变化会影响锁释放与临时清理 |
| F034 `move_items` | 移动请求/结果和跨空间执行语义必须保持一致 |
| KnowledgeSpaceService add/rename/delete | executor 提取不能改变直通路径的既有副作用 |
| PermissionService/OpenFGA | owner/manager 解析和执行权限重校验依赖可用性；失败应显式异常 |
| MinIO upload temp path | 临时对象命名或 TTL 变化会影响预览和清理 |
| F027 cursor list | enrichment 必须批量，不得恢复 total 或 fetch-all |
| DepartmentKnowledgeSpace binding | 部门空间私密校验依赖绑定完整性 |

版本级 `release-contract.md` 在实现前需登记 F045 拥有三个新领域对象及知识空间 mutation 审批编排；F034 仍拥有移动写行为，F025 仍拥有所有 Approval* 对象。

---

## 7. 测试与可观测

### 7.1 自动化策略

- **策略单元测试**：租户隔离、默认值、总控/scope/单空间优先级、私密免审、owner/manager 直通。
- **冲突并发测试**：同资源不同申请人、不同动作；父文件夹与子资源双向竞争；跨空间锁顺序；只有一个申请成功。
- **handler 测试**：四类 action、权限变化、目标变化、执行失败抛出、终态临时清理幂等。
- **Repository 双 DB 约束**：唯一键、JsonType、NULL 字段、分页和批量 enrichment；DM8 由中央回归验证。
- **API E2E**：上传不入正式列表；重命名/移动/删除 pending 保持原状；批准后执行；拒绝/撤回/取消；批量逐项结果；跨租户不可见。
- **前端组件/E2E**：审批标签、动作详情、禁用菜单、删除不乐观移除、待审批上传预览/清理、批量通过部分失败、三语言。
- **回归**：私密空间及 owner/manager 直通必须与改造前结果一致；F034 同/跨空间移动、版本链、文件夹上传和撤回行为不退化。

### 7.2 手工验证主路径

1. 租户 A 开启、租户 B 关闭，分别以 editor 上传同类型文件；A 仅出现在待审批上传，B 直接进入解析。
2. A 的 owner 批准上传，确认正式文件只在 outbox 执行后出现；解析失败可重试且不重新审批。
3. editor 对文件重命名，确认列表保持旧名称并显示审批中；详情显示新名称；批准后才变更。
4. editor 移动文件夹，确认根文件夹及子树不可再次变更；批准后整树移动且只有一个实例。
5. editor 删除正式文件，确认普通用户仍可检索；批准且执行成功后才消失。
6. 移除待办审核人的 manager 关系，确认审批中心和文件页均拒绝其处理。
7. 将普通空间改为 private 后新操作直通；确认部门空间切 private 被服务端拒绝。

### 7.3 日志与指标

- 统一结构化日志字段：`tenant_id, space_id, change_request_id, approval_instance_id, action, resource_type, resource_id, decision`。
- 指标：创建申请数/直通数、按 action 的审批结果、outbox 执行失败数、资源锁冲突数、staged bytes/count、临时清理失败数和最长等待时长。
- 清理补偿任务只扫描终态上传申请且 `cleanup_state != success`；失败抛出供 Celery 重试，不静默吞掉。

---

## 8. 后续改进 / 本期不做

- 本期不做目标空间接收方二次审批；若需要必须新增双阶段流程设计。
- 本期不做审批中的申请编辑；目标名称或目标位置变化需撤回后重提。
- 本期不把 file change lock 下沉为审批中心通用资源锁；其他场景出现同类需求后再抽象。
- 本期不处理历史私密部门空间的自动数据修复，只提供审计/修复脚本和部署前置说明。
- 若 staged upload 数量显著增加，可增加对象存储生命周期规则作为 DB 补偿任务之外的最后防线。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-10 | 初版：上传暂存、正式资源变更审批、子树互斥、租户策略和私密边界 | spec 确认后进入设计阶段 |
