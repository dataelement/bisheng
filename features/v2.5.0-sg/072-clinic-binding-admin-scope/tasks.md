# 实施任务

- Status: `implemented-local-verified`
- 用户已确认本规格对应的行为及权限影响，不重复请求同范围确认。

- [x] T001 建立最近科室、混合授权、无效父链及创建/改绑拒绝回归。
  _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_
  _Acceptance: AC-1, AC-2, AC-3, AC-4_
  _Verification: 相关基线及新增用例失败原因_
  _Depends: none_
  _Boundary: 仅现有科室范围与权限测试_
- [x] T002 实现共用候选范围，接入下拉、创建和改绑，更新接口注释。
  _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_
  _Acceptance: AC-1, AC-2, AC-3, AC-4_
  _Verification: 相关回归集、Ruff、diff 检查_
  _Depends: T001_
  _Boundary: 不变更授权源、数据、接口契约和默认权限写入流程_

## 实际偏差记录

- 在当前 `feat/2.5.0-sg` 分支实施，不切换用户工作分支；不提交、不部署。
- 用户已在聊天中确认具体规则与执行计划，规格文件持久化该确认，不新增重复确认步骤。
- 验证见 [verification.md](verification.md)：原基线 29 项通过；新增预期行为在修改前 8 项失败；最终 46 项相关回归通过。
- 已有权限集成测试补齐真实组织标签和父链，以验证班组及更下级的最近科室查找；不连接外部数据库或线上 OpenFGA。
- 真实门户浏览器及生产数据验证为 `MANUAL_REQUIRED`，没有部署或修改线上数据。
