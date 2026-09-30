# 任务拆分 Tasks: 数据看板全屏浮层可用性修复

## 阅读摘要
- 先建立失败回归，再实现共享 Portal 容器解析并接入四类浮层，最后执行相关回归与构建。

## 元信息 Metadata
- Feature ID: `065-dashboard-fullscreen-overlays`
- Status: `complete`
- Related requirements: `features/v2.5.0-sg/065-dashboard-fullscreen-overlays/requirements.md`
- Related design: `features/v2.5.0-sg/065-dashboard-fullscreen-overlays/design.md`
- Created: `2026-09-10`
- Updated: `2026-09-10`

## 阶段 1：复现与核心行为 Core Behavior

- [x] T001 建立全屏 Portal 回归测试
  - Done when: 测试能复现全屏元素内触发浮层、内容却挂到全屏元素外的错误。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03_
  - _Verification: V-AC-REQ-001_
  - _Depends: none_
  - _Boundary: tests only_

- [x] T002 实现并接入动态 Portal 容器解析
  - Done when: 四类浮层在全屏内挂载，退出全屏恢复默认行为，显式容器优先。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03_
  - _Verification: V-AC-REQ-001_
  - _Depends: T001_
  - _Boundary: bs-ui portal components_

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T001, T002 | V-AC-REQ-001 |

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
- 修复前定向测试稳定出现 3 个全屏容器断言失败，显式容器场景通过，确认根因是默认 body Portal。
- `useOverlayPortalContainer` 使用单例事件订阅跟踪标准与 WebKit 全屏元素；显式容器优先于全屏元素。
- `Popover`、`Select`、`DropdownMenu`、`MultiSelect` 统一接入；未修改看板业务组件与数据请求。
