# 任务

- [x] T001 抽取共用 PDF 生成、校验、保存函数，接回知识库处理器。
  _Requirements: REQ-1_
  _Acceptance: AC-4_
  _Verification: 知识库 PDF 回归_
  _Depends: none_
  _Boundary: 保留现有 Repository/任务/原文件引用行为_
- [x] T002 问答按源快照持久化并复用基础 PDF，预览/下载统一使用；补充重复、并发、失效与失败回归。
  _Requirements: REQ-2, REQ-3, REQ-4_
  _Acceptance: AC-1, AC-2, AC-3_
  _Verification: 问答服务回归与真实 PDF 校验_
  _Depends: T001_
  _Boundary: 不修改权限、Schema、前端接口，不部署_
- [x] T003 执行相关回归与静态检查，记录证据和未验证边界。
  _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_
  _Acceptance: AC-1, AC-2, AC-3, AC-4_
  _Verification: verification.md_
  _Depends: T001, T002_
  _Boundary: 不触碰用户其他未提交改动_
