# 需求说明 Requirements: F059 解除知识空间创建数量上限

## 阅读摘要
- 本文档说明：解除知识空间固定、角色及租户数量上限，同时保留其他限制和历史配置兼容。
- 当前状态：`confirmed`
- 已确认范围：全部创建入口、全部具备权限的用户、全部合法知识空间类型。

## 元信息 Metadata
- Feature ID: `059-unlimited-knowledge-space-creation`
- Status: `confirmed`
- Mode: `spec-then-implement`
- Created: `2026-07-16`
- Updated: `2026-07-16`
- Source request: 当前门户网站知识库下的知识空间创建上线时解除 200 个限制。
- Related combined spec: [spec.md](./spec.md)

## 需求入口摘要 Intake Summary
- 问题 Problem: 创建人已有 200 个知识空间时，后端返回 `SpaceLimitError(18001)` 并阻断创建。
- 当前状态 Current state: Service 存在硬编码 200 上限，角色和租户还可能保存有限 `knowledge_space` 配额。
- 目标结果 Target outcome: 知识空间创建数量完全不限量，运行时有效配额统一为 `-1`。
- 影响对象 Affected users/systems: 所有具备创建权限的用户、全部合法空间类型、直接创建及首钢审批完整链路。
- 请求停止点 Requested stopping point: `verification`

## 范围 Scope

### 包含 Includes
- 移除 `validate_knowledge_space_create` 与 `create_knowledge_space` 的固定数量判断。
- `QuotaService.check_quota` 对 `knowledge_space` 始终允许创建。
- 单项及批量有效配额查询对 `knowledge_space` 返回无限量语义。
- 保留并忽略角色、租户历史 `knowledge_space` 有限值。
- 覆盖直接创建、审批预校验、审批提交及审批通过落库。

### 不包含 Excludes
- 不修改 `knowledge_space_file`、`storage_gb`、知识空间订阅及其他资源配额。
- 不修改权限、审批策略、名称唯一性、层级、标签库或模型配置规则。
- 不修改门户、BiSheng Client、API 路径或成功响应结构。
- 不做数据库迁移、配置批量更新、历史数据清理或生产数据操作。
- 不删除 `SpaceLimitError(18001)`、历史 DAO 或 `skip_user_limit` 兼容参数。

## 需求列表 Requirements

### REQ-001：移除固定创建数量限制
系统不得根据创建人已有知识空间数量拒绝新的知识空间创建或创建预校验。

### REQ-002：统一所有创建入口行为
直接创建、首钢审批预校验、审批提交和审批通过落库必须共享不限量行为。

### REQ-003：角色与租户数量配额失效
任何角色或租户中保存的有限 `knowledge_space` 数值均不得阻断创建。

### REQ-004：配额读取语义一致
单项和批量有效配额查询中的 `knowledge_space` 必须表达为 `-1`（无限量）。

### REQ-005：保留其他限制和兼容性
文件容量、租户存储、订阅数量、其他资源配额及其他创建业务校验保持不变；历史键继续兼容。

### REQ-006：保护现有工作区与改动边界
不得重置、覆盖、stash、批量格式化或改写用户现有未提交变更及无关代码。

## 验收标准 Acceptance Criteria

| ID | Requirement | 可观察结果 | Verification |
|---|---|---|---|
| AC-01 | REQ-001 | 已有数量达到或超过 200 时，预校验不查询用户空间计数、不返回 `18001`。 | V-001 |
| AC-02 | REQ-001 | 已有数量达到或超过 200 时，实际创建不查询用户空间计数、不返回 `18001`。 | V-001 |
| AC-03 | REQ-002 | 审批预校验和提交均不因数量失败。 | V-002 |
| AC-04 | REQ-002 | 审批通过落库不因申请人已有空间数量失败。 | V-002 |
| AC-05 | REQ-003 | 角色或租户配置 `knowledge_space=0/200` 时，`check_quota` 仍允许创建且不读取资源使用量。 | V-003 |
| AC-06 | REQ-004 | 单项有效配额查询固定返回 `-1`。 | V-003 |
| AC-07 | REQ-004 | 批量查询的 `role_quota`、`tenant_quota`、`effective` 均表达无限量，其他资源保持原计算。 | V-003 |
| AC-08 | REQ-005 | 历史 `knowledge_space` 键继续通过配置校验和保存。 | V-003 |
| AC-09 | REQ-005 | 文件容量、租户存储及订阅上限继续阻断超限请求。 | V-004 |
| AC-10 | REQ-005 | 权限、审批、名称、标签库及模型配置校验保持不变。 | V-002, V-005 |
| AC-11 | REQ-006 | 最终差异保留用户既有修改，F059 仅修改规格、独立测试和目标代码。 | V-007 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 不新增数据库查询；移除数量计数后创建链路不得产生额外性能开销。
- `NFR-002`: 不新增依赖、迁移、配置或数据操作。
- `NFR-003`: 修改保持最小且可通过局部代码回滚。

## 澄清记录 Clarifications

### Session 2026-07-16
- Q: 数量策略是否完全不限量？ -> A: `1A`，固定、角色和租户上限全部解除。
- Q: 是否覆盖所有创建入口？ -> A: `2A`，审批与直接创建全部覆盖。
- Q: 是否覆盖所有用户和空间类型？ -> A: `3A`，全部具备权限的用户和全部合法类型。

## 风险 Risks
- `knowledge_space_service.py` 含用户未提交修改，必须使用精确局部补丁。
- 旧有限配额值保留在数据中，运行时忽略；代码回滚后会恢复原行为。
- 无限创建会增加资源数量，但性能扩展不属于本特性范围。

## 需求质量门 Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
