# 需求说明 Requirements: F068 版本合并唯一键冲突修复

## 阅读摘要

- 本文档说明：修复知识库“关联新版本”时重复插入物理文件版本关系导致的 500。
- 当前状态：`approved`
- 修复只调整既有版本关系的迁移方式，不改变接口、数据库约束或产品规则。

## 元信息 Metadata

- Feature ID: `068-version-merge-unique-fix`
- Status: `approved`
- Mode: `bug-fix`
- Created: `2026-07-30`
- Updated: `2026-07-30`
- Source request: `门户网站知识库文件版本管理关联新版本报错，用户要求修复`

## 需求入口摘要 Intake Summary

- 问题 Problem: `POST /api/v1/knowledge/space/version/merge` 为已存在版本关系的来源文件再次执行 `INSERT`，触发 `uk_kdv_knowledge_file` 唯一键冲突并返回 500。
- 当前状态 Current state: 来源单版本文档无法合并到当前文件的版本链。
- 目标结果 Target outcome: 合并成功后复用原版本行，将其迁移到目标文档并设为新主版本。
- 影响对象 Affected users/systems: 知识库版本管理用户、`KnowledgeVersionService`、`knowledge_document_version`。
- 请求停止点 Requested stopping point: `verification`

## 范围 Scope

### 包含 Includes

- 修复 `merge_source_document_into_current` 的来源版本迁移逻辑。
- 使用真实测试数据库约束回归验证版本合并结果。

### 不包含 Excludes

- 不删除或放宽 `uk_kdv_knowledge_file` 唯一约束。
- 不修改前端、API 请求/响应、相似度规则或版本号规则。
- 不重构 Repository 的事务提交模型。

## 需求列表 Requirements

### REQ-001: 单版本来源文档可安全合并

作为知识库版本管理用户，我需要把单版本来源文档关联为当前文件的新版本，以便形成合法且可继续使用的版本链。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN 合法的单版本来源文档被合并 THEN 系统 SHALL 返回目标文档 ID 和递增后的版本号，且不触发 `knowledge_file_id` 唯一键冲突。
- `AC-REQ-001-02`: WHEN 合并完成 THEN 系统 SHALL 保留来源版本行 ID，将其归属更新为目标文档并设为主版本。
- `AC-REQ-001-03`: WHEN 合并完成 THEN 系统 SHALL 删除被搬空的来源文档，并保留目标文档的旧版本和新版本。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated integration test | `test_merge_force_allows_document_without_simhash` |
| AC-REQ-001-02 | V-AC-REQ-001-01 | automated integration test | 同一测试断言来源版本行 ID 不变且文件关系唯一 |
| AC-REQ-001-03 | V-AC-REQ-001-01 | automated integration test | 同一测试断言来源文档删除及目标链状态 |

## 非功能需求 Non-Functional Requirements

- `NFR-001`: 修复必须兼容 MySQL、DM8 及测试使用的 SQLite ORM 语义，不新增数据库方言相关 SQL。

## 假设 Assumptions

- 现有“来源链必须恰好一个版本”的守卫继续有效。
- `knowledge_file_id` 全局唯一是正确的数据不变量。

## 风险 Risks

- Repository 当前按操作提交，完整合并流程仍不是单事务；本次不扩大到事务架构重构。

## 需求质量门 Requirements Quality Gate

- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] Acceptance criteria sharing one behavior reuse an evidence target instead of duplicating commands.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
