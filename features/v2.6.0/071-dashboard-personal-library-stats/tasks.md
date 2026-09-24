# 任务拆分 Tasks: F071 看板个人知识库统计

## 元信息 Metadata

- Feature ID: `071-dashboard-personal-library-stats`
- Status: `complete`
- Related requirements: `features/v2.6.0/071-dashboard-personal-library-stats/requirements.md`
- Related design: `features/v2.6.0/071-dashboard-personal-library-stats/design.md`
- Created: `2026-08-06`
- Updated: `2026-08-06`

## 任务

- [x] T001 建立个人库纳入和收藏库排除回归
  - Done when: 旧实现不能满足个人库四指标口径和收藏库三条排除路径。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01..03, AC-REQ-002-01..03_
  - _Verification: V-AC-REQ-001-01..03, V-AC-REQ-002-01..03_
  - _Depends: none_
  - _Boundary: tests only_

- [x] T002 实现个人库指标口径和收藏库排除
  - Done when: 四指标纳入正常 personal，所有投影与预览入口排除 favorite，并清理旧记录。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01..03, AC-REQ-002-01..03_
  - _Verification: V-AC-REQ-001-01..03, V-AC-REQ-002-01..03_
  - _Depends: T001_
  - _Boundary: knowledge space dashboard telemetry only_

- [x] T003 运行相关回归并记录证据
  - Done when: 知识空间投影、看板数据集和架构检查通过。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01..03, AC-REQ-002-01..03_
  - _Verification: V-AC-REQ-001-01..03, V-AC-REQ-002-01..03_
  - _Depends: T002_
  - _Boundary: verification only_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks |
|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T001, T002, T003 |
| REQ-002 | AC-REQ-002-01..03 | T001, T002, T003 |

## 实现记录 Implementation Notes

- 修复前定向用例观察到个人库未进入指标集合、收藏预览仍访问索引、收藏文件仍可见且缺少空间级全记录清理。
- 修复后 `personal` 进入四个指标统一允许集合；`is_favorite` 在全量源查询、增量可见性和预览入口均被排除。
- 全量同步会清理全部收藏空间既有记录；空间增量无可见文件时也会删除文件与预览记录。
