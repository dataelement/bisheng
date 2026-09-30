# 实施任务

- [x] T001 快照契约、批量 Repository 和重建登记。
  _Requirements: REQ-001, REQ-002, REQ-005_；_Acceptance: AC-001, AC-004, AC-006_；_Verification: Repository 回归_；_Depends: none_；_Boundary: 无新表_
- [x] T002 两端完整查询、批量属性修复和幂等失败恢复。
  _Requirements: REQ-002, REQ-003_；_Acceptance: AC-002, AC-003, AC-006_；_Verification: adapter 故障测试_；_Depends: T001_；_Boundary: 现有 schema_
- [x] T003 对账编排、异常隔离、有限重试、熔断、汇总。
  _Requirements: REQ-001, REQ-003, REQ-005_；_Acceptance: AC-001, AC-003, AC-006_；_Verification: service 回归_；_Depends: T001, T002_；_Boundary: 每批比较后修改_
- [x] T004 每日调度、Redis 租约、原摘要保留。
  _Requirements: REQ-002, REQ-004_；_Acceptance: AC-004, AC-005_；_Verification: worker/loader/调度测试_；_Depends: T003_；_Boundary: 不执行生产任务_
- [x] T005 相关回归、静态检查和验证记录。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_；_Acceptance: AC-001–AC-006_；_Verification: verification.md_；_Depends: T004_；_Boundary: 不部署_

## 实际偏差记录

- 已在对话中完成多轮需求/设计确认，用户明确“规划一下开始实施吧”，按已确认简化方案连续实施，不重复要求确认。
- 沿用当前工作分支，不擅自切换/提交/合并；规格以 requirements/design/tasks 保存。
- 本地最终相关回归 172 passed；真实 ES/Milvus/Redis 和 DM8 验证为 MANUAL_REQUIRED，详见 verification.md。
- 检索按 membership_generation 严格过滤，因此属性修复同时校正已有关系代次，不新增字段。
- 检查发现旧 writer 只删除同一版本的旧代次，补充规范文档范围的更旧代次清理，并建立失败复现及回归，确保重建能够收敛。
