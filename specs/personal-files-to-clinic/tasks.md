# 执行任务

- [x] T1 实现路径选择、上传人组织路由、版本链过滤和逐文件跳过报告。
  _Requirements: REQ-1, REQ-2_ _Acceptance: AC-1, AC-2_ _Verification: 规划和查询集成测试_ _Depends: none_ _Boundary: 新脚本和测试_
- [x] T2 实现目录准备、原地迁移、权限/共享索引验证及报告恢复。
  _Requirements: REQ-3, REQ-4_ _Acceptance: AC-3, AC-4_ _Verification: 事务、失败和恢复测试_ _Depends: T1_ _Boundary: 不运行真实迁移_
- [x] T3 添加使用说明，完成相关回归、静态检查并记录限制。
  _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_ _Acceptance: AC-1, AC-2, AC-3, AC-4_ _Verification: verification.md_ _Depends: T2_ _Boundary: 保留已有未提交改动_

## 实际偏差记录

- [x] T5 增加显式权限所有者回退选项，保持上传人/库所有者不变，验证默认拒绝、有效所有者不替换、失效账号回退和中断恢复。
  _Requirements: REQ-5_ _Acceptance: AC-5_ _Verification: 所有者失效集成回归_ _Depends: T4_ _Boundary: 不运行真实迁移或修改库所有者_

- [x] T4 精简主报告为匹配但未迁移文件及原因，隔离最小恢复状态并验证预览、失败、中断和恢复。
  _Requirements: REQ-4_ _Acceptance: AC-4_ _Verification: 精简报告及恢复回归_ _Depends: T3_ _Boundary: 不修改迁移规则、不执行真实迁移_

用户已在会话确认迁移口径，按授权持续完成脚本和本地验证，不重复索要阶段确认；不执行 apply。
