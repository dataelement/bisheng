# 任务拆分 Tasks: 交叉表双列维度

## 阅读摘要
- 按配置契约、查询路径、前端透视与渲染三个批次实施。
- 用户已经确认本设计，任务状态从实现开始更新。

## 元信息 Metadata
- Feature ID: `061-dashboard-pivot-two-column-dimensions`
- Status: `complete`
- Related requirements: `features/v2.5.0-sg/061-dashboard-pivot-two-column-dimensions/requirements.md`
- Related design: `features/v2.5.0-sg/061-dashboard-pivot-two-column-dimensions/design.md`
- Created: `2026-08-21`
- Updated: `2026-08-21`

## 阶段 1：配置与查询契约 Core Behavior

- [x] T001 实现交叉表双列维度配置的保存、恢复和上限控制
  - Done when: 新配置保存两个维度，旧配置恢复一个维度，非交叉表仍限制一个。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03_
  - _Verification: V-AC-REQ-001_
  - _Depends: none_
  - _Boundary: frontend dashboard config_

- [x] T002 实现后端完整行列维度路径查询
  - Done when: 双列维度按行维度之后的固定顺序查询和返回，旧单维配置保持原路径。
  - _Requirements: REQ-002_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02_
  - _Verification: V-AC-REQ-002_
  - _Depends: none_
  - _Boundary: backend telemetry query_

## 阶段 2：透视与展示 Integration

- [x] T003 实现多级列路径透视和两级表头渲染
  - Done when: 叶子列按完整路径唯一标识、重复结果累计、两级表头正确合并、单维表头兼容。
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03_
  - _Verification: V-AC-REQ-003_
  - _Depends: T001, T002_
  - _Boundary: frontend dashboard pivot transform and render_

## 阶段 3：点击添加入口回归修复 Bug Fix

- [x] T004 修复交叉表通过字段点击只能添加一个堆叠维度
  - Done when: 已有一个堆叠维度且两个行维度已占用时，点击新的维度字段可将堆叠维度增加到两个；非交叉表仍拒绝第二个。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01_
  - _Verification: V-AC-REQ-001_
  - _Depends: T001_
  - _Boundary: frontend dashboard field-click configuration path_

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T001, T004 | V-AC-REQ-001 |
| REQ-002 | AC-REQ-002-01..02 | T002 | V-AC-REQ-002 |
| REQ-003 | AC-REQ-003-01..03 | T003 | V-AC-REQ-003 |

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
- 新数组配置仅用于交叉表；非交叉表继续使用单个 `stackDimension`。
- 后端对新 `stackDimensions` 使用普通多维聚合，对旧 `stackDimension` 保留原查询路径。
- 真实页面地址在验证阶段加载超时，人工视觉检查记录在 `verification.md`。
- 2026-08-21 回归调查确认：`handleFieldClick` 仍以堆叠维度数量等于 0 作为添加条件，遗漏第二个点击添加入口；T004 仅修复该直接原因。
- `getMaxStackDimensionCount` 统一配置恢复、图表切换、拖拽、点击和保存路径的上限规则，避免入口再次漂移。
