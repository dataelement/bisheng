# 设计说明 Design: 一个部门绑定多个知识空间

## 阅读摘要
- 本文档说明：通过放宽绑定表约束、集合化读取、全量权限同步和共享目标解析器实现一部门多空间。
- 设计重点：保留 `space_id` 唯一；所有自动选库使用“当前部门优先、部门层级优先、歧义显式失败”。
- 不在本设计中处理：多部门绑定同一空间、主知识库配置、现有数据自动转换、生产库直接升级。

## 元信息 Metadata
- Feature ID: `060-department-multiple-spaces`
- Status: `implemented`
- Related requirements: `features/v2.6.0/060-department-multiple-spaces/requirements.md`
- Created: `2026-07-16`
- Updated: `2026-07-16`

## 上下文 Context
- 现有架构 Existing architecture: `department_knowledge_space` 通过 `uk_dks_department_id` 与 `uk_dks_space_id` 表达一对一；知识库服务、自由库迁移和 Open Endpoints 直接或间接读取该绑定。
- 已检查文件 Relevant files inspected: `department_knowledge_space.py`、`department_space_binding_repository_impl.py`、`department_knowledge_space_service.py`、`free_space_migration_service.py`、`filelib_sync_service.py`、`filelib_sync_repository_impl.py`、F021 migration、F058 spec/tests。
- 现有测试或验证命令 Existing tests or validation commands: `pytest test/knowledge/test_department_space_rebind.py`、`pytest test/test_department_knowledge_space_service.py`、`pytest test/test_free_space_migration_target.py`、`pytest test/open_endpoints/test_filelib_sync.py`、Client Jest 定向测试、ruff 与 compileall。
- 项目约束 Constraints from project guidance: Router → Endpoint → Service → Repository → DB；MySQL/DM8 双兼容；schema 必须新增 Alembic migration；不修改用户已有脏文件；非平凡功能遵循 SDD。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals
- 将部门到知识空间关系改为一对多，知识空间到部门仍为一对一。
- 确保所有部门绑定读取、管理员同步和列表展示覆盖完整集合。
- 为自由库迁移和外部文件同步提供共享且确定的目标解析规则。
- 以向前迁移安全删除唯一约束，并记录不可直接回退的条件。

### 非目标 Non-Goals
- 不引入主空间字段或管理 UI。
- 不修改知识空间权限模型、内容、层级和审批配置。
- 不自动修复两条旧团队绑定；它们作为合法并存数据保留。
- 不对真实配置数据库执行 schema 变更。

## 边界承诺 Boundary Commitments
| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| `department_knowledge_space` schema | 删除部门唯一约束，保留索引与空间唯一约束 | 删除/合并现有行，移除 `space_id` 唯一 | 用户要求一个空间多部门或迁移现有数据 |
| 部门知识库绑定 | 同一部门新增、创建、重新归属多个空间 | 修改层级、创建者、审批配置 | 绑定需新增排序或主空间语义 |
| 管理员同步 | 遍历全部绑定空间复用既有成员/权限规则 | 改变手工成员与 creator 保护规则 | 管理员同步需异步化或部分成功协议 |
| 自动选库 | 共享优先级、父级回退、歧义失败 | 随机取第一条、按时间隐式选择 | 用户确认新增主空间配置 |
| Client | 更新旧冲突预期并保持刷新行为 | 新增多选、主空间或数据清理 UI | API contract 变化 |
| 数据库执行 | 创建迁移和隔离验证 | 未确认执行真实 upgrade | 用户单独批准数据库升级 |

- Allowed dependencies: `none`

## 需求追踪 Requirements Traceability
| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | 约束迁移、模型约束、绑定入口与 rebind repository | 绑定、并发/唯一性及 migration 测试 |
| REQ-002 | AC-REQ-002-01..03 | 复用 `aget_by_department_ids` 集合方法，移除生产单值调用 | Service/DAO 测试与 `rg` 静态检查 |
| REQ-003 | AC-REQ-003-01..03 | `sync_department_admin_memberships` 一次加载全部绑定后逐空间同步 | 管理员新增、移除、失败路径测试 |
| REQ-004 | AC-REQ-004-01..05 | 新增共享 `DepartmentSpaceTargetResolver` | Resolver、自由库 guard、filelib sync 测试 |
| REQ-005 | AC-REQ-005-01..03 | 保持现有更新 API；新增歧义错误映射；更新 Client 测试 | Backend/Client 定向测试 |
| REQ-006 | AC-REQ-006-01..05 | Alembic constraint drop、guarded downgrade、工作区保护 | Migration 测试、静态检查、git evidence |

## 架构设计 Architecture
- Pattern: `现有 DDD 服务编排 + 集合化绑定读取 + 共享领域解析器 + forward schema migration`
- Rationale: 约束变化会影响所有单值消费者；共享解析器能保证自由库迁移与外部同步不出现不同选择规则。
- Preserved existing patterns: 绑定仍由 `DepartmentKnowledgeSpace` 保存；知识库更新继续使用现有 repository/session；权限写入继续走 `PermissionService`；Open Endpoints 保持自己的错误映射。
- Architecture change justification, if any: 新增领域解析器是必要的跨调用共享规则，避免复制“部门层级优先、歧义失败”的高风险逻辑。

### 数据关系

```text
Department 1 ── N DepartmentKnowledgeSpace N ── 1 KnowledgeSpace
                         │
                         └── space_id 继续唯一
```

### 共享目标解析算法

输入为从当前部门到根部门的 ID 链，例如 `[18, 3, 1]`：

1. 按链顺序逐个部门读取全部绑定及对应 `KnowledgeSpaceScope`。
2. 当前部门有 `level=department` 且 `owner_type=department` 的候选时：
   - 1 个：返回；
   - 多个：抛出 `DepartmentKnowledgeSpaceAmbiguousError(18004)`。
3. 当前部门没有部门层级候选但有旧绑定时：
   - 1 个：返回；
   - 多个：抛出同一歧义错误。
4. 当前部门完全无候选时才继续父部门。
5. 全链无候选时返回 `None`，由调用方沿用既有 not-found/block 行为。

该算法不读取数据库自然顺序；候选集合仅使用数量和显式 scope 类型作决策。

## 文件结构计划 File Structure Plan
| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `features/v2.6.0/060-department-multiple-spaces/{requirements,design,spec,tasks,verification}.md` | create | SDD 需求、设计、任务和证据 | REQ-001..REQ-006 |
| `src/backend/bisheng/core/database/alembic/versions/<new-revision>.py` | create | 删除部门唯一约束并提供受保护 downgrade | REQ-001, REQ-006 |
| `src/backend/bisheng/knowledge/domain/models/department_knowledge_space.py` | modify | ORM 约束改为仅 `space_id` 唯一；去除单值 DAO 使用面 | REQ-001, REQ-002, REQ-006 |
| `src/backend/bisheng/knowledge/domain/repositories/implementations/department_space_binding_repository_impl.py` | modify | rebind 不再拒绝已占用部门，保留空间唯一与事务语义 | REQ-001, REQ-005 |
| `src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py` | modify | 创建/旧绑定放宽；管理员同步全部空间 | REQ-001, REQ-002, REQ-003 |
| `src/backend/bisheng/knowledge/domain/services/department_space_target_resolver.py` | create | 共享候选优先级、父级回退和歧义检测 | REQ-004 |
| `src/backend/bisheng/knowledge/domain/services/free_space_migration_service.py` | modify | 使用共享 resolver 并将歧义转为 block | REQ-004 |
| `src/backend/bisheng/common/errcode/knowledge_space.py` | modify | 定义 `DepartmentKnowledgeSpaceAmbiguousError(18004)` | REQ-004, REQ-005 |
| `src/backend/bisheng/open_endpoints/domain/services/filelib_sync_service.py` | modify | 使用共享 resolver；歧义映射为 `FilelibSyncConflictError(19904)` | REQ-004, REQ-005 |
| `src/backend/bisheng/open_endpoints/domain/repositories/interfaces/filelib_sync_repository.py` | modify | 移除已无确定语义的单绑定接口（若无其他调用） | REQ-002, REQ-004 |
| `src/backend/bisheng/open_endpoints/domain/repositories/implementations/filelib_sync_repository_impl.py` | modify | 对齐接口并移除 `.first()` 单绑定查询 | REQ-002, REQ-004 |
| `src/backend/test/knowledge/test_department_multiple_spaces.py` | create | 一对多绑定、管理员同步、resolver 与迁移行为 | REQ-001..REQ-006 |
| `src/backend/test/knowledge/test_department_space_rebind.py` | modify | 目标部门已有绑定由拒绝改为允许 | REQ-001, REQ-005 |
| `src/backend/test/test_department_knowledge_space_service.py` | modify | 列表、批量创建和管理员全量同步 | REQ-001..REQ-003 |
| `src/backend/test/test_free_space_migration_target.py` | modify | 唯一候选、父级回退、歧义 block | REQ-004 |
| `src/backend/test/open_endpoints/test_filelib_sync.py` | modify | 多候选冲突与无上传副作用 | REQ-004, REQ-005 |
| `src/frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.test.tsx` | modify | 更新“部门已有知识库”旧失败预期 | REQ-005 |

实现时先复核工作区；若目标测试文件新增用户变更，则改用新的独立测试文件避免覆盖。

## 组件与接口 Components and Interfaces

### DepartmentSpaceBindingRepositoryImpl
- Responsibility: 在同一事务内更新当前空间的绑定、scope owner 和部门管理员来源成员。
- Inputs: `space_id`、新 `department_id`、管理员集合。
- Outputs: `DepartmentSpaceRebindPlan`。
- Dependencies: AsyncSession、`KnowledgeSpaceScope`、`DepartmentKnowledgeSpace`。
- Error behavior: 空间绑定并发唯一冲突继续转换为稳定业务错误；不再把部门已有其他绑定视为错误。
- Requirements: `REQ-001`, `REQ-005`

### DepartmentKnowledgeSpaceService
- Responsibility: 批量创建、旧团队库绑定、部门管理员成员同步和部门知识库列表。
- Inputs: 部门 ID、用户变更集合、创建请求。
- Outputs: 多绑定完整集合或逐空间同步结果。
- Dependencies: 现有 DAO、DepartmentService、PermissionService。
- Error behavior: 单空间同步失败传播；不静默跳过余下失败状态。
- Requirements: `REQ-001`, `REQ-002`, `REQ-003`

### DepartmentSpaceTargetResolver
- Responsibility: 解析部门链中唯一、最高优先级的目标空间。
- Inputs: 由近到远的部门 ID 链。
- Outputs: `space_id | None`。
- Dependencies: `DepartmentKnowledgeSpaceDao.aget_by_department_ids`、`KnowledgeSpaceScopeDao.aget_by_space_ids`。
- Error behavior: 同一优先级多候选抛出 `DepartmentKnowledgeSpaceAmbiguousError`，包含部门 ID 和候选空间 ID 供日志诊断，但用户提示不暴露跨租户数据。
- Requirements: `REQ-004`

### FreeSpaceMigrationService / FilelibSyncService
- Responsibility: 复用 resolver 并转换各自业务结果。
- Inputs: 当前/责任部门路径。
- Outputs: 迁移决策或上传目标空间。
- Dependencies: shared resolver。
- Error behavior: 自由库返回 `block(reason="ambiguous_target")`；filelib 映射 `FilelibSyncConflictError(19904)`，文件保存前失败。
- Requirements: `REQ-004`, `REQ-005`

## 数据 / 状态变化 Data / State Changes
- Entities: `DepartmentKnowledgeSpace`。
- Persistence changes: 删除 `uk_dks_department_id`；保留 `idx_dks_department_id`、`uk_dks_space_id` 及所有现有列。
- Migration or rollback: upgrade 只做 DDL drop constraint；无 DML。downgrade 先查询是否存在重复 `department_id`，有重复则明确失败，无重复才恢复唯一约束。
- Compatibility: 现有一对一数据是新模型的合法子集；无需 backfill。旧团队绑定继续可读。

## 测试策略 Testing Strategy
| Acceptance ID | Test Type | Target | Notes |
|---|---|---|---|
| AC-REQ-001-01..03 | unit/integration | rebind repository、创建/绑定 service、migration | 先红后绿，覆盖保留原行与空间唯一 |
| AC-REQ-002-01..03 | unit/static | department service/list、`rg` | 验证完整集合与无单值调用 |
| AC-REQ-003-01..03 | unit/failure | admin sync | 多 `space_id` 新增、移除和中途失败 |
| AC-REQ-004-01..05 | unit/integration | shared resolver、free migration、filelib sync | 覆盖所有优先级与无副作用 |
| AC-REQ-005-01..03 | backend + Client | PortalKnowledgeWorkbench、权限回归 | API 路径不变，只改变冲突语义 |
| AC-REQ-006-01..05 | migration/static/manual CI | migration helper、git diff | DM8 真实验证在 Linux CI |

## 设计决策 Decisions

### Decision: 保留空间唯一，仅删除部门唯一
- Context: 用户只要求一个部门可绑定多个空间。
- Options considered: 删除两个唯一约束；建立多对多表；仅删除部门唯一约束。
- Decision: 仅删除 `uk_dks_department_id`。
- Rationale: 最小化数据模型变化并保持现有 update/unbind API 语义。
- Consequences: 一个空间仍不能同时服务多个部门。

### Decision: 共享确定性 resolver
- Context: 自由库迁移与外部文件同步都曾按部门取第一条。
- Options considered: 各自实现；按时间排序选一个；共享解析器并在歧义时报错。
- Decision: 共享解析器。
- Rationale: 避免两条高风险写入链路产生不一致或随机选择。
- Consequences: 部分历史调用会从隐式成功变为明确冲突，需要管理员消除歧义或未来引入主空间配置。

### Decision: downgrade 不自动清理重复数据
- Context: 放宽约束后可能产生合法重复部门绑定。
- Options considered: downgrade 删除多余行；迁移标记不可逆；无重复时恢复、有重复时终止。
- Decision: 受保护 downgrade。
- Rationale: 数据删除超出迁移权限，明确失败比自动丢数据安全。
- Consequences: 回退前需人工处理多绑定数据。

## 风险 / 取舍 Risks / Trade-Offs
| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| DDL 锁表 | 部署期间短暂阻塞绑定写入 | 保留独立小迁移；上线前评估表规模和窗口；本会话不执行真实 upgrade | migration/deploy |
| 多空间权限同步部分失败 | 部分空间已同步、调用整体失败 | 复用现有幂等授权和失败记录；顺序执行并传播错误；增加失败路径测试 | implementation |
| resolver 查询量增加 | 部门链较深时额外查询 | 一次批量读取整条链绑定与 scope，在内存按链分组，不逐层 N+1 | implementation |
| 旧调用仍使用单值 DAO | 随机选库风险残留 | 删除生产调用并通过 `rg` 质量门验证 | verification |
| 迁移多头基线 | Alembic revision 冲突 | 实施前重新计算 active heads，按仓库惯例创建 merge-compatible revision | implementation |

## 设计质量门 Design Quality Gate
- [x] Every requirement ID is represented in Requirements Traceability.
- [x] Every acceptance criterion has a verification strategy.
- [x] Boundary Commitments include allowed and disallowed changes.
- [x] Every changed file has one clear responsibility and linked requirement.
- [x] Existing architecture is preserved or changes are justified.
- [x] Runtime prerequisites, migrations, and risky operations are explicit.
- [x] No speculative abstractions are included.
