# 实施任务

- Status: `implemented-local-verified`

- [x] T001 建立权限接口失败回归，修复子资源最近一级授权规则。
  - _Requirements: REQ-1_
  - _Acceptance: AC-1, AC-2_
  - _Verification: E-001, E-003_
  - _Depends: none_
  - _Boundary: 子资源细粒度操作查询，不修改授权或业务写接口_
- [x] T002 统一目录写权限状态、隐藏无权限入口，验证异步隔离及浏览器行为。
  - _Requirements: REQ-2, REQ-3_
  - _Acceptance: AC-3, AC-4_
  - _Verification: E-002, E-004, E-005_
  - _Depends: T001_
  - _Boundary: 两处知识列表和实际门户操作栏，不扩大到其他未使用组件_

## 实际偏差记录

- 用户已对上轮具体方案“确认修复”，规格记录该授权，不重复确认。
- 在当前 feat/2.5.0-sg 分支实施，保持其他任务不变；不提交、推送或部署。
- 大型既有列表文件只做局部替换与移除重复 effect，不全文件重构或格式化。
- 测试发现原 checkPermission 短缓存及在途去重仅按资源，账号切换仍可能复用允许结果。为 REQ-2 的两处目录查询增加可选客户端 cacheScope 隔离，其他查询保持兼容，不改变后端接口。
