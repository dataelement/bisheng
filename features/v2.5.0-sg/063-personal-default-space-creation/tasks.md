# 默认个人库创建修复任务

- [x] T001: 建立并发创建回归并记录原实现失败证据。
  - _Requirements: REQ-001_
  - _Acceptance: AC-01_
  - _Verification: 并发屏障 + 真实入口 + 内存创建状态_
  - _Boundary: 新定向测试_
- [x] T002: 实现租户/用户锁、续期和失败保护; 获锁后二次查找; 稳定读取已有库。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04_
  - _Depends: T001_
  - _Verification: 并发及失败测试、相关回归、Ruff 和 diff_
  - _Boundary: design.md 指定代码和测试, 底层迁移锁只读复用_
- [x] T003: 完成审阅和验证记录, 明确部署/数据库约束边界。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04_
  - _Depends: T002_
  - _Verification: 汇总可复用证据与未验证项_

## 实际偏差记录

保留当前分支和已有脏工作区。用户授权先修复创建入口, 不重复规格确认; 无数据库写入与部署操作。

相关回归包含 7 项旧失败, 通过独立子进程从 HEAD 加载未修改模块后全部复现, 未扩展修复范围。详见 verification.md。
