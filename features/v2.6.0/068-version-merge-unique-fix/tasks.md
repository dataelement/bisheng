# 任务拆分 Tasks: F068 版本合并唯一键冲突修复

## 元信息 Metadata

- Feature ID: `068-version-merge-unique-fix`
- Status: `complete`
- Related requirements: `features/v2.6.0/068-version-merge-unique-fix/requirements.md`
- Related design: `features/v2.6.0/068-version-merge-unique-fix/design.md`
- Created: `2026-07-30`
- Updated: `2026-07-30`

## 阶段 1：回归保护 Regression

- [x] T001 强化真实数据库版本合并回归用例
  - Done when: 用例能观察版本行 ID 保持、文件关系唯一、目标链和来源文档最终状态；修复前因唯一约束冲突失败。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03_
  - _Verification: V-AC-REQ-001-01_
  - _Depends: none_
  - _Boundary: `src/backend/test/knowledge/test_knowledge_version_service_similar_scan.py` only_

## 阶段 2：最小修复 Implementation

- [x] T002 将来源版本行迁移到目标文档
  - Done when: 合并路径更新既有 `source_version`，不再为相同 `knowledge_file_id` 创建新行，并仅删除被搬空的来源文档。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03_
  - _Verification: V-AC-REQ-001-01_
  - _Depends: T001_
  - _Boundary: `merge_source_document_into_current` persistence block only_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T001, T002 | V-AC-REQ-001-01 |

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

- 修复前回归用例稳定失败于 `knowledge_document_version.knowledge_file_id` 唯一约束。
- 修复后来源版本行主键保持不变，目标链包含旧版本和新主版本，来源文档被删除。
- 测试隔离了收藏通知副作用；收藏通知行为由 `test_favorite_version_notify.py` 独立覆盖。
