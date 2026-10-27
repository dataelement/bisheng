# 任务

- [x] T001 明确原件不可读分类与解析接入
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-01, AC-02_
  - _Verification: V-001 原件及解析测试_
  - _Depends: none_
  - _Boundary: 仅接口来源，无新增依赖、不影响普通上传_
- [x] T002 受保护的单文件事务删除与持久清理
  - _Requirements: REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-03, AC-04, AC-05_
  - _Verification: V-002 锁定快照、关系保护、回滚和重复处理_
  - _Depends: T001_
  - _Boundary: 不级联历史/分发/审批，不清理审计，不写线上_
- [x] T003 权限补偿、相关回归与交付
  - _Requirements: REQ-002, REQ-004, REQ-005_
  - _Acceptance: AC-02, AC-04, AC-05_
  - _Verification: V-003 后台失败恢复、既有解析及 Filelib 回归、静态检查_
  - _Depends: T002_
  - _Boundary: 不提交、推送或部署；真实基础设施未测则明确标记_

## 实际偏差记录

用户在已有检索与具体方案后确认实施，本目录固化该批准方案，不重复确认；直接在当前分支进行本地修改，保护已有 `docs/api/mcp-usage.md` 改动。

既有相关回归有 4 项失败，已通过只读 HEAD 源码对照复现，未扩大范围修复；最终相关集排除这 4 项，详见 verification.md。无前端改动，后端正式解析入口与真实 SQLite 事务作为最小集成验收，不制作模拟页面。
