# 任务拆分 Tasks: F070 看板配置化数据范围

## 元信息 Metadata

- Feature ID: `070-dashboard-configured-data-scope`
- Status: `complete`
- Related requirements: `features/v2.6.0/070-dashboard-configured-data-scope/requirements.md`
- Related design: `features/v2.6.0/070-dashboard-configured-data-scope/design.md`
- Created: `2026-08-06`
- Updated: `2026-08-06`

## 阶段 1：回归保护 Regression

- [x] T001 建立无隐式数据范围回归
  - Done when: 组件查询与枚举查询用例在旧实现下因服务端范围注入失败，并验证用户维度筛选仍保留。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03_
  - _Depends: none_
  - _Boundary: `src/backend/test/test_realtime_dashboard.py` and `src/backend/test/telemetry_search/test_dashboard_enum_labels.py`_

## 阶段 2：最小修复 Implementation

- [x] T002 删除服务端数据范围查询通道
  - Done when: `DashboardService` 不再计算范围，`DataQueryService` 不再接收或转换 `scope_filters`，枚举 DSL 不再注入隐式权限条件。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03_
  - _Depends: T001_
  - _Boundary: telemetry dashboard query services only_

- [x] T003 保留并回归看板资源权限
  - Done when: 既有读取、发布状态和实时看板写入守卫未被删除，允许与拒绝路径测试通过。
  - _Requirements: REQ-002_
  - _Acceptance: AC-REQ-002-01_
  - _Verification: V-AC-REQ-002-01_
  - _Depends: T002_
  - _Boundary: no resource-permission behavior changes_

## 阶段 3：契约与验证 Contract and Verification

- [x] T004 更新策略契约并记录 V3 证据
  - Done when: release contract 不再要求后端按用户裁剪统计数据，`verification.md` 记录定向和相关模块回归结果。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-002-01_
  - _Depends: T003_
  - _Boundary: contract and verification docs only_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T001, T002, T004 | V-AC-REQ-001-01..03 |
| REQ-002 | AC-REQ-002-01 | T003, T004 | V-AC-REQ-002-01 |

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

- 用户在 2026-08-06 明确确认移除包括 `tenant_id` 在内的全部服务端硬过滤。
- 修复前新增回归稳定失败，观察到组件查询仍传入 `scope_filters=[tenant_id=1]`。
- 修复后指标查询只接收显式的 `dimension_filters`，枚举查询仅在 `exact_values` 存在时生成查询过滤。
- 看板资源读取、已发布实时看板访问、跨看板组件拒绝和实时看板写入守卫保持原有实现。
