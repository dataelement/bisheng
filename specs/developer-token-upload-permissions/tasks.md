# 修复任务

- [x] T1 建立列表和保存校验失败复现及必要拒绝回归。
  - _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_
  - _Acceptance: AC-1, AC-2, AC-3, AC-4_
  - _Verification: 回归在修复前因上传关系不存在/目录校验目标错误而失败_
  - _Boundary: 本地测试与 spec，无生产修改_
- [x] T2 实施统一细粒度上传判断、目录候选查询和最终目标校验。
  - _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_
  - _Acceptance: AC-1, AC-2, AC-3, AC-4_
  - _Verification: T1 回归转绿，保留权限和候选类型边界_
  - _Depends: T1_
  - _Boundary: design 指定文件，不修改权限授予或用户已有目录权限改动_
- [x] T3 执行相关模块回归、静态检查并记录验证限制。
  - 修正相关同步目标测试中已过时的目录显示/审计依赖模拟和既有 `tags` 字段断言。
  - _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_
  - _Acceptance: AC-1, AC-2, AC-3, AC-4_
  - _Verification: verification.md 记录实际命令、结果和未验证项_
  - _Depends: T2_
  - _Boundary: 本地验证，不提交、推送或部署_
