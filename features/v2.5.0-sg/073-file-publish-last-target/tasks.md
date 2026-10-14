# 发布路径记忆实施任务

- Status: `implemented-local-verified`
- 用户选择 user_link、不考虑租户视为对最终方案的执行授权，不重复确认。

- [x] T001 实现 UserLink 偏好仓储、服务、读取接口和提交成功保存。
  - Done when: 三组与账号独立、跨客户端读取、精确类型更新、失败不影响受理结果。
  - _Requirements: REQ-1, REQ-2, REQ-4_
  - _Acceptance: AC-1, AC-2, AC-4_
  - _Verification: 仓储/API/提交回归、Python 静态检查_
  - _Depends: none_
  - _Boundary: 当前用户专用 UserLink 类型及手动发布，不改 Schema/租户/业务权限_
- [x] T002 接入前端恢复、目录展开、失败降级及异步隔离。
  - Done when: 自动恢复完整目标，拒绝旧异步结果，分享正常。
  - _Requirements: REQ-1, REQ-3, REQ-4, REQ-5_
  - _Acceptance: AC-1, AC-3, AC-4, AC-5_
  - _Verification: API/弹窗/目录树/分享 Jest、构建、浏览器观察_
  - _Depends: T001_
  - _Boundary: 手动发布选择与共享目录树兼容，不修改发布执行或自动发布_

## 覆盖矩阵

| Requirement | Acceptance | Tasks |
|---|---|---|
| REQ-1 | AC-1 | T001, T002 |
| REQ-2 | AC-2 | T001 |
| REQ-3 | AC-3 | T002 |
| REQ-4 | AC-4 | T001, T002 |
| REQ-5 | AC-5 | T002 |

## 实际偏差记录

- 用户最终指定 user_link 并取消租户分组，撤销新增表和 config 备选方案，无需迁移。
- 保留工作区仪表盘、统计等其他改动；当前分支实施，不提交/推送/部署。
- 用户本次明确选择最终存储方案，复用已讨论的发布行为，不再重复规格确认。

- 本地实现与定向验证已完成；证据见 verification.md。真实数据库并发及线上部署不在已执行范围。
