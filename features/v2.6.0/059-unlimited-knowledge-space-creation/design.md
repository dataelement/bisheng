# 设计说明 Design: F059 解除知识空间创建数量上限

## 阅读摘要
- 本文档说明：在现有 Service 与 QuotaService 架构内统一实现知识空间数量不限量。
- 设计重点：移除两处固定计数校验，并在配额服务中集中定义无限量资源语义。
- 不在本设计中处理：前端提示、数据库数据、其他资源配额或无关重构。

## 元信息 Metadata
- Feature ID: `059-unlimited-knowledge-space-creation`
- Status: `confirmed`
- Related requirements: [requirements.md](./requirements.md)
- Related combined spec: [spec.md](./spec.md)
- Created: `2026-07-16`
- Updated: `2026-07-16`

## 上下文 Context
- 现有架构 Existing architecture: 首钢门户通过 BiSheng Client 调用审批 API；审批 service/handler 最终复用 `KnowledgeSpaceService`。直接创建端点通过 `QuotaService` decorator 校验配额。
- 已检查文件 Relevant files inspected: `knowledge_space_service.py`、`shougang_approval_service.py`、审批 handler、`quota_service.py` 及相关测试。
- 现有测试或验证命令 Existing tests or validation commands: `uv run pytest` 定向测试、`uv run ruff check`、`uv run ruff format --check`、`python -m compileall`。
- 项目约束 Constraints from project guidance: Test First；新测试放在 `test/<module>/`；保护当前 F057 未提交修改；不做无关格式化。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals
- 所有知识空间创建入口不再受到固定、角色或租户数量上限阻断。
- 单项及批量配额查询对 `knowledge_space` 返回一致的无限量语义。
- 保留其他业务限制与历史配置兼容。

### 非目标 Non-Goals
- 不调整知识空间文件容量、存储、订阅及其他资源配额。
- 不调整 API、前端、审批策略、权限或数据结构。
- 不删除兼容参数、错误码或历史 DAO。

## 边界承诺 Boundary Commitments

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| `KnowledgeSpaceService` | 删除两处数量计数与固定上限相关 import/常量 | 修改其他创建校验或 F057 代码 | 目标方法签名或调用链与已分析结果不一致 |
| `QuotaService` | 对 `knowledge_space` 定义无限量并保持旧键有效 | 放宽其他资源或移除配置键 | 发现调用方依赖有限配额返回值 |
| tests | 新增独立 service 测试并更新干净 quota 测试 | 修改用户脏测试文件 | 只能通过改写既有用户测试才能验证 |
| data/config/UI | none | migration、数据更新、配置更新、前端改动 | 后端无法独立解除限制 |

- Allowed dependencies: none

## 需求追踪 Requirements Traceability

| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-01, AC-02 | 删除 Service 两处用户空间计数判断 | V-001 |
| REQ-002 | AC-03, AC-04 | 审批 service/handler 继续复用同一 Service | V-002 |
| REQ-003 | AC-05 | `check_quota` 对无限量资源提前返回 | V-003 |
| REQ-004 | AC-06, AC-07 | 单项、角色合并及批量配额固定为 `-1` | V-003 |
| REQ-005 | AC-08, AC-09, AC-10 | 保留 `VALID_QUOTA_KEYS` 及其他资源原逻辑 | V-003, V-004, V-005 |
| REQ-006 | AC-11 | 局部补丁、独立测试与最终 diff 审计 | V-007 |

## 架构设计 Architecture
- Pattern: 在共享 domain service 中集中业务语义，入口继续复用现有服务。
- Rationale: 只修改 UI 或单个入口无法覆盖审批通过和直接创建；共享服务能保证一致性。
- Preserved existing patterns: 现有 API、decorator、错误码、参数签名、DAO、配额配置校验机制。
- Architecture change justification, if any: none；仅调整现有服务规则。

## 文件结构计划 File Structure Plan

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | modify | 移除固定数量阻断，保留其他创建校验 | REQ-001, REQ-002, REQ-006 |
| `src/backend/bisheng/role/domain/services/quota_service.py` | modify | 将知识空间创建及读取语义统一为无限量 | REQ-003, REQ-004, REQ-005 |
| `src/backend/test/knowledge/test_unlimited_knowledge_space_creation.py` | create | 独立覆盖 Service 与审批复用链路 | REQ-001, REQ-002, REQ-006 |
| `src/backend/test/test_quota_service.py` | modify | 覆盖角色/租户有限历史值与配额查询 | REQ-003, REQ-004, REQ-005 |
| `src/backend/test/test_quota_service_check_chain.py` | modify | 保留非无限资源的租户链阻断回归，移除与新规则冲突的知识空间预期 | REQ-003, REQ-005 |
| `features/v2.6.0/059-unlimited-knowledge-space-creation/verification.md` | create | 保存实际验证证据 | REQ-001..REQ-006 |

## 组件与接口 Components and Interfaces

### KnowledgeSpaceService
- Responsibility: 验证并创建知识空间。
- Inputs: 现有创建参数及兼容参数 `skip_user_limit`。
- Outputs: 保持现有返回对象和错误契约。
- Dependencies: `KnowledgeDao` 及现有权限、标签、模型等服务。
- Error behavior: 不再触发数量错误；其他既有错误保持不变。
- Requirements: `REQ-001`, `REQ-002`, `REQ-005`

### QuotaService
- Responsibility: 计算与校验角色、租户、资源配额。
- Inputs: `resource_type`、用户、租户及历史 `quota_config`。
- Outputs: `knowledge_space` 的有效配额固定为 `-1`；创建校验返回 `True`。
- Dependencies: 现有角色、租户和资源用量服务。
- Error behavior: 仅跳过 `knowledge_space` 数量错误，其他配额错误保持不变。
- Requirements: `REQ-003`, `REQ-004`, `REQ-005`

## 数据 / 状态变化 Data / State Changes
- Entities: none
- Persistence changes: none
- Migration or rollback: 无迁移；回滚两个生产代码文件的 F059 局部差异即可。
- Compatibility: 历史 `knowledge_space` 键继续允许读取和保存，但运行时有限值被忽略。

## 测试策略 Testing Strategy

| Acceptance ID | Test Type | Target | Notes |
|---|---|---|---|
| AC-01, AC-02 | unit | `test_unlimited_knowledge_space_creation.py` | 断言用户空间计数 DAO 未调用 |
| AC-03, AC-04, AC-10 | unit/regression | approval service/handler 定向测试 | 证明审批节点复用无限量行为并保留其他规则 |
| AC-05..AC-08 | unit | `test_quota_service.py` | 参数化历史有限值并检查单项/批量结果 |
| AC-09 | regression | storage、upload、subscription 定向测试 | 证明其他限制未放宽 |
| AC-11 | static/diff | `git status`、分段 diff、`git diff --check` | 保护用户改动边界 |

## 设计决策 Decisions

### Decision: 在 QuotaService 集中短路而非删除端点 decorator
- Context: 直接创建端点使用 `require_quota(KNOWLEDGE_SPACE)`，多个调用方复用配额服务。
- Options considered: 删除 decorator；仅修改默认值；在 QuotaService 集中定义无限量资源。
- Decision: 在 QuotaService 集中定义并短路 `knowledge_space`。
- Rationale: 入口结构保持不变，角色、租户与查询结果语义一致。
- Consequences: 历史有限配置仍可保存但不参与运行时决策。

### Decision: 保留兼容定义
- Context: `skip_user_limit`、`SpaceLimitError` 与计数 DAO 可能被其他扩展引用。
- Options considered: 删除；保留但目标链路不使用。
- Decision: 保留兼容定义，仅删除目标链路调用。
- Rationale: 降低范围和兼容风险。
- Consequences: 存在暂时未使用的兼容代码，但不在本特性清理。

## 风险 / 取舍 Risks / Trade-Offs

| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 脏生产文件被覆盖 | 丢失用户 F057 修改 | 精确 apply_patch、修改前后分段 diff | implementation |
| 短路条件误伤其他资源 | 文件或存储限制被放宽 | 严格匹配 `knowledge_space` 并运行其他资源回归 | verification |
| 配额 API 仍暴露有限值 | 调用方误判 | 单项、批量和角色合并均固定为 `-1` | implementation |
| 测试环境依赖外部服务 | 无法获得自动化证据 | 复用现有 mock，记录任何环境阻塞 | verification |

## 设计质量门 Design Quality Gate
- [x] Every requirement ID is represented in Requirements Traceability.
- [x] Every acceptance criterion has a verification strategy.
- [x] Boundary Commitments include allowed and disallowed changes.
- [x] Every changed file has one clear responsibility and linked requirement.
- [x] Existing architecture is preserved or changes are justified.
- [x] Runtime prerequisites, migrations, and risky operations are explicit.
- [x] No speculative abstractions are included.
