# 实施任务

- Feature ID: `066-dashboard-document-statistics`
- Status: `local-complete-deployment-pending`

- [x] T001 共享文档身份与库存规则，补回归 fixture。
  _Requirements: REQ-001, REQ-006_
  _Acceptance: AC-001, AC-006_
  _Verification: ORM 与脚本对账测试_
- [x] T002 全量/增量文件投影、保留日记录并关联历史入口。
  _Requirements: REQ-001, REQ-008_
  _Acceptance: AC-001, AC-008_
  _Depends: T001_
  _Verification: 投影和日统计 ID 稳定性测试_
- [x] T003 精确统计服务、时间累计和调用覆盖率。
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-005_
  _Acceptance: AC-002, AC-003, AC-004, AC-005_
  _Depends: T002_
  _Verification: 跨空间/组织/日期固定数据，分页失败与快照协议测试，真实 ES 见 T007_
- [x] T004 数据集更新、导出、交叉表合计与组织小计。
  _Requirements: REQ-002, REQ-005_
  _Acceptance: AC-002, AC-005_
  _Depends: T003_
  _Verification: 后端导出及前端转换/渲染测试_
- [x] T005 保留旧数据的新索引重建、校验、切换与回退工具。
  _Requirements: REQ-007, REQ-008_
  _Acceptance: AC-007, AC-008_
  _Depends: T002_
  _Verification: dry-run 零写入、导入失败不切换、计数守恒、模拟切换与回退；真实 ES 见 T007_
- [x] T006 受影响模块回归、对账报告和上线操作说明。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_
  _Acceptance: AC-001, AC-002, AC-003, AC-004, AC-005, AC-006, AC-007, AC-008_
  _Depends: T001, T002, T003, T004, T005_
  _Verification: 记录实际执行结果与未验证环境边界_

- [ ] T007 部署环境验收：真实 ES 快照分页、克隆和别名切换/回退，实际数据量性能，暂停写入并迁移后与脚本逐分类对账。
  _Status: 未执行；本机 Docker 未运行，尚无本次获确认的目标部署环境。_
  _Requirements: REQ-002, REQ-006, REQ-007, REQ-008_
  _Depends: T006_
