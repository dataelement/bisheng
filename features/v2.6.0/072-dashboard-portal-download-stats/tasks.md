# 任务拆分 Tasks：知识空间内容统计增加门户下载次数

## 阅读摘要

- 本文档指导 Agent 实现门户下载历史聚合、下载日投影和看板指标。
- 实现顺序为回归基线、核心投影、数据集接入、文档与验证。
- 不得扩展到实时统计、下载人数或下载链路修改。

## 元信息 Metadata

- Feature ID: `072-dashboard-portal-download-stats`
- Status: `complete`
- Related requirements: `features/v2.6.0/072-dashboard-portal-download-stats/requirements.md`
- Related design: `features/v2.6.0/072-dashboard-portal-download-stats/design.md`
- Created: `2026-08-06`
- Updated: `2026-08-06`

## 阶段 1：回归基线 Regression Baseline

- [x] T001 建立门户下载统计回归用例
  - Done when: 测试可观察事件过滤、北京时间日桶、同日累加、确定性 ID、无效文件跳过、失败不清理和指标契约；旧实现至少因缺少下载投影或指标而失败。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-01..04, AC-REQ-002-01..05, AC-REQ-003-01_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-001-04, V-AC-REQ-002-01..05, V-AC-REQ-003-01_
  - _Depends: none_
  - _Boundary: tests only_

## 阶段 2：核心行为 Core Behavior

- [x] T002 扩展知识空间内容中间表下载日记录
  - Done when: mapping、记录模型、确定性 ID 构建和 stale download cleanup 支持 `download_daily`，且不改变 file/preview 行为。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-01..03, AC-REQ-002-02..03, AC-REQ-003-02_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-003-02_
  - _Depends: T001_
  - _Boundary: knowledge_space_content.py_

- [x] T003 实现门户下载历史分页聚合与当前文件维度补全
  - Done when: worker 仅查询门户成功下载事件，使用 composite `after_key` 遍历全部文件/日期桶，并批量生成当前有效文件的下载日记录。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01..03, AC-REQ-002-01, AC-REQ-002-03..05_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-002-01, V-AC-REQ-002-03, V-AC-REQ-002-05_
  - _Depends: T002_
  - _Boundary: worker/telemetry/mid_table.py_

- [x] T004 将下载投影接入全量同步生命周期
  - Done when: 文件投影完成后重建下载日投影；全部成功后才清理旧下载记录；任务结果和日志包含下载同步数量；重复执行结果稳定。
  - _Requirements: REQ-002, REQ-003_
  - _Acceptance: AC-REQ-002-01..05, AC-REQ-003-02_
  - _Verification: V-AC-REQ-002-01..05, V-AC-REQ-003-02_
  - _Depends: T003_
  - _Boundary: worker full projection lifecycle_

## 阶段 3：数据集集成 Dataset Integration

- [x] T005 注册“下载次数”数据集指标
  - Done when: `download_count` 使用 `record_type=download_daily`、允许空间层级过滤和 SUM 聚合，原有四指标配置不变。
  - _Requirements: REQ-001, REQ-003_
  - _Acceptance: AC-REQ-001-03..04, AC-REQ-003-01_
  - _Verification: V-AC-REQ-001-03, V-AC-REQ-001-04, V-AC-REQ-003-01_
  - _Depends: T002_
  - _Boundary: telemetry_search dataset schema_

- [x] T006 更新看板指标计算文档
  - Done when: 文档说明下载事实源、过滤口径、北京时间日汇总、当前文件维度、同步时效和删除文件排除规则。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-01..04, AC-REQ-002-01..04, AC-REQ-003-01_
  - _Verification: V0 diff and reference check_
  - _Depends: T004, T005_
  - _Boundary: docs only_

## 阶段 4：验证收尾 Verification Checkpoint

- [x] T007 执行相关回归并记录验证证据
  - Done when: 定向 pytest、相关模块回归、Ruff、架构守卫和 diff 检查通过，`verification.md` 记录实际命令、结果、未执行项和风险。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-01..04, AC-REQ-002-01..05, AC-REQ-003-01..02_
  - _Verification: EG-001, EG-002, EG-003_
  - _Depends: T004, T005, T006_
  - _Boundary: verification and SDD evidence only_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..04 | T001, T002, T003, T005, T006, T007 | V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-001-04 |
| REQ-002 | AC-REQ-002-01..05 | T001, T002, T003, T004, T006, T007 | V-AC-REQ-002-01..05 |
| REQ-003 | AC-REQ-003-01..02 | T001, T002, T004, T005, T006, T007 | V-AC-REQ-003-01..02 |

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

- 实施前必须确认 `base_telemetry_events` 动态字段的实际精确查询路径。
- 如果实测 composite aggregation 无法兼容当前 Elasticsearch 版本，必须先更新 design，不得静默改成一次性加载全部事件。
- 2026-08-06 已确认事件字段路径使用 `event_data.portal_document_download_*`，字符串精确查询使用 `.keyword` 子字段。
- 下载投影使用 composite `after_key` 分页、北京时间日期桶和确定性 `download_{file_id}_{local_date}` 文档 ID。
- 真实环境同步会改变 Elasticsearch 数据，未在自动化实施阶段执行，部署后按 `verification.md` 完成人工验证。
