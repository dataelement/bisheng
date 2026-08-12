# 任务拆分 Tasks: 门户专家回答图片地址溢出修复

## 阅读摘要
- 本文档指导 Agent 先复现 schema contract 缺陷，再完成模型与 migration 的最小修复。
- 实现边界仅限 `images_url` 字段，不处理其他问答字段或图片生命周期。

## 元信息 Metadata
- Feature ID: `053-portal-qa-answer-image-url-overflow`
- Status: `completed`
- Related requirements: `specs/053-portal-qa-answer-image-url-overflow/requirements.md`
- Related design: `specs/053-portal-qa-answer-image-url-overflow/design.md`
- Created: `2026-08-11`
- Updated: `2026-08-11`

## 阶段 1：回归保护 Regression Guard

- [x] T001 建立 `images_url` 模型与迁移 contract 回归测试
  - Done when: 测试能因当前 `VARCHAR(255)` 模型或缺失 migration 按预期失败，并覆盖 MySQL/达梦目标类型、upgrade 幂等与 downgrade 截断保护。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03_
  - _Depends: none_
  - _Boundary: tests only_

## 阶段 2：最小修复 Minimal Fix

- [x] T002 将 `Answer.images_url` 声明为 `LargeText`
  - Done when: ORM MySQL DDL 包含 `images_url LONGTEXT`，达梦兼容 DDL 包含 `images_url CLOB`，字段仍为 nullable string。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02_
  - _Depends: T001_
  - _Boundary: `database/models/qa_expert.py`_

- [x] T003 新增 `f083` 字段扩容 migration
  - Done when: upgrade 可将 MySQL/达梦旧字段扩容、重复执行安全跳过；downgrade 在安全时恢复，在超长数据存在时拒绝执行。
  - _Requirements: REQ-002_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03_
  - _Depends: T001_
  - _Boundary: Alembic migration only_

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01, AC-REQ-001-02 | T001, T002 | V-AC-REQ-001-01, V-AC-REQ-001-02 |
| REQ-002 | AC-REQ-002-01..03 | T001, T003 | V-AC-REQ-002-01..03 |

## 任务质量门 Task Quality Gate
- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] Tasks sharing one behavior or command use a verification batch instead of duplicate verification tasks.
- [x] Test work covers distinct outcomes/risks and does not duplicate the same behavior across test layers.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes
- 调查证据：当前数据库 `images_url` 为 `VARCHAR(255)`；失败 URL 长 331；当前库 17 条回答且尚无图片回答。
- 迁移链：字段扩容使用 `f083`，并直接衔接当前分支已跟踪 head `f082_department_short_name`；不引入其他分支的 `f085` 占位 revision。
- 后续演进：spec 054 实施时确认两个 `attachments` 多值字段存在同类 255 字符风险，尚未部署的同一 `f083` 已扩展为三个 QA 多值资源字段的一次性安全扩容；本 spec 的 `images_url` 验收保持成立。
