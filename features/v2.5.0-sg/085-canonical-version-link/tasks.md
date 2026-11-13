# 修复任务

- [x] T001 线上状态最小复现、拒绝与事务回归
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-01, AC-02, AC-03_
  - _Verification: V-001：先观察18094失败，再验证关系与回滚_
- [x] T002 独立manager关联及生命周期持久化
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04_
  - _Verification: V-001, V-002：事务、权限、投影失败与恢复_
  - _Depends: T001_
- [x] T003 定向回归、静态检查及交付记录
  - _Requirements: REQ-004, REQ-005_
  - _Acceptance: AC-04, AC-05_
  - _Verification: V-002, V-003；记录实际命令、结果与未验证范围_
  - _Depends: T002_

## 实际偏差记录

- 用户已在只读根因和修复方向说明后要求“帮我修复一下”，作为本次修复范围的实施授权，不重复索要同范围确认。仅本地实现和测试，线上部署、数据操作不在本次授权内。
- 测试建表定义遗漏模型已有的belonging_organization_id列，补齐测试DDL后正确复现18094；没有修改业务Schema。真实清理器集成又复现“剩余0条时遗留文档、剩余1条时误删文档”，作为本修复直接闭环依赖一并修正。
- 最终21项新用例及相关回归共132项通过；清理时同时确认无剩余入口和物理版本。真实ES/Milvus/OpenFGA、MySQL/DM8锁竞争和部署后线上操作未验收，详见verification.md。
- 已纠正开发落点为正式仓库feat/2.5.0-sg，重新执行132项相关回归通过；镜像仓库main误放的本次改动经校验备份后还原。该分支测试DDL已有组织列，不重复迁移此前镜像仓库的fixture补丁。
