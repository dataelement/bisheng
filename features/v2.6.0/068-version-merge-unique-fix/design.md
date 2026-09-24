# 设计说明 Design: F068 版本合并唯一键冲突修复

## 阅读摘要

- 本文档说明：把反向合并路径由“复制版本关系”改为“迁移既有版本关系”。
- 设计重点：与 `link_file_to_document` 已采用的唯一关系迁移语义保持一致。
- 不在本设计中处理：数据库约束、接口契约和 Repository 事务架构。

## 元信息 Metadata

- Feature ID: `068-version-merge-unique-fix`
- Status: `approved`
- Related requirements: `features/v2.6.0/068-version-merge-unique-fix/requirements.md`
- Created: `2026-07-30`
- Updated: `2026-07-30`

## 上下文 Context

- 现有架构 Existing architecture: `Endpoint -> KnowledgeVersionService -> Repository -> knowledge_document_version`。
- 已检查文件 Relevant files inspected: 错误日志、版本 API、版本服务、版本模型、Repository、F071 migration、现有版本测试和前端调用。
- 现有测试或验证命令 Existing tests or validation commands: `test_knowledge_version_service_similar_scan.py::test_merge_force_allows_document_without_simhash` 已在修复前稳定复现唯一键冲突。
- 项目约束 Constraints from project guidance: 保留 DDD 分层、最小 diff、兼容多数据库、行为修改需要可执行回归证据。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals

- 合并时复用来源 `KnowledgeDocumentVersion` 主键和 `knowledge_file_id` 关系。
- 保留目标旧版本、更新目标主版本并删除空来源文档。

### 非目标 Non-Goals

- 不新增 Repository API 或数据库迁移。
- 不改变错误码、相似度校验、通知或审计行为。
- 不处理整个版本管理模块的事务原子性。

## 边界承诺 Boundary Commitments

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| `knowledge_version_service.py` | 修改反向合并的版本持久化方式 | 修改其他版本管理行为 | 需要改变产品规则或接口 |
| `test_knowledge_version_service_similar_scan.py` | 强化真实数据库合并结果断言 | 新建测试框架或 mock 数据库约束 | 现有 fixture 无法表达目标行为 |
| Database schema | none | 删除/修改唯一约束 | 产品明确改变文件归属模型 |

- Allowed dependencies: `none`

## 需求追踪 Requirements Traceability

| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | 更新 `source_version` 后删除空来源文档 | SQLite ORM integration regression |

## 架构设计 Architecture

- Pattern: 迁移既有聚合关系，不复制具有全局唯一身份的关系行。
- Rationale: `knowledge_file_id` 是物理文件身份；原版本行已经表达该文件与逻辑文档的关系。
- Preserved existing patterns: 复用 `version_repo.update`、`doc_repo.update_primary_version_id`、主版本降级、通知和审计流程。
- Architecture change justification, if any: `none`

## 文件结构计划 File Structure Plan

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/knowledge/domain/services/knowledge_version_service.py` | modify | 迁移来源版本关系 | REQ-001 |
| `src/backend/test/knowledge/test_knowledge_version_service_similar_scan.py` | modify | 真实数据库回归保护 | REQ-001 |
| `features/v2.6.0/068-version-merge-unique-fix/*.md` | create | SDD 追踪与验证证据 | REQ-001 |

## 数据 / 状态变化 Data / State Changes

- Entities: `KnowledgeDocumentVersion`、`KnowledgeDocument`。
- Persistence changes: 对来源版本执行 `UPDATE`，不再对相同 `knowledge_file_id` 执行第二次 `INSERT`。
- Migration or rollback: 无 Schema migration；代码回滚即恢复原实现。
- Compatibility: API 请求和响应不变。

## 测试策略 Testing Strategy

| Acceptance IDs | Risk / Level | Distinct Outcomes | Primary Layer | Evidence Group | Stop Condition |
|---|---|---|---|---|---|
| AC-REQ-001-01..03 | medium/V2 | 合并成功、关系唯一、来源文档删除 | integration | EG-001 | 原失败用例通过，相关测试文件与 Ruff 通过 |

## 设计决策 Decisions

### Decision: 更新版本行而不是先删后插

- Context: 先插入会违反唯一约束；先删除再插入会改变版本行 ID，并增加中途失败造成关系丢失的风险。
- Options considered: 删除唯一约束；先删后插；更新原版本行。
- Decision: 更新原版本行的 `document_id/version_no/is_primary`。
- Rationale: 与正向关联实现一致，满足数据不变量且最小化改动。
- Consequences: 来源版本行 ID 保持稳定；来源文档在迁移完成后删除。

## 风险 / 取舍 Risks / Trade-Offs

| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 多步 Repository 操作非单事务 | 后续步骤异常可能留下部分状态 | 本次保持现有顺序与既有正向路径一致；事务改造另行立项 | follow-up |

## 设计质量门 Design Quality Gate

- [x] Every requirement ID is represented in Requirements Traceability.
- [x] Every acceptance criterion has a verification strategy.
- [x] Verification uses the lowest sufficient layer and avoids duplicate commands across acceptance criteria.
- [x] Test cases map to distinct outcomes/risks instead of tasks, branches, roles, or raw input count.
- [x] One primary test layer is selected per behavior unless a boundary has independent risk.
- [x] Boundary Commitments include allowed and disallowed changes.
- [x] Every changed file has one clear responsibility and linked requirement.
- [x] Existing architecture is preserved or changes are justified.
- [x] Runtime prerequisites, migrations, and risky operations are explicit.
- [x] No speculative abstractions are included.
