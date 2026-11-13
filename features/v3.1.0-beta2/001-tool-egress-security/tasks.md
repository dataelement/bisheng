# 实施任务

用户已确认最终简化：两个入口固定公网、无配置或私网例外，无需迁移。以下按最终范围验收，不沿用此前阶段的完成标记；主实施者核实当前实现和回归后更新。共享工作树不自动提交、切换或全仓恢复。

- [x] T01 核实两个入口临时超管限制、拒绝前无副作用和纯内容解析兼容。
  _Requirements: 两入口准入及解析兼容_
  _Acceptance: AC-01, AC-02, AC-03, AC-04_
  _Verification: V-ENTRY_
  _Depends: none_
  _Boundary: 不改正常工具资源权限，不自动恢复普通用户测试权限_
- [x] T02 核实两入口专用异步传输：URL/IP、DNS 固定、TLS、代理及重定向拒绝。
  _Requirements: 两入口实际连接安全_
  _Acceptance: AC-06, AC-07, AC-08, AC-09, AC-10_
  _Verification: V-TRANSPORT_
  _Depends: T01_
  _Boundary: 不保留同步安全传输，不接管正常 OpenApiTools/executor/Bounded_
- [x] T03 核实 identity、正文上限、超时、脱敏及固定公网且无配置/例外。
  _Requirements: 两入口资源边界与不可放行的公网策略_
  _Acceptance: AC-08, AC-11, AC-12_
  _Verification: V-LIMITS_
  _Depends: T02_
  _Boundary: 工具测试 1 MiB、Schema 2 MiB；总超时最多 30 秒、连接最多 5 秒_
- [x] T04 核实正常 OpenApiTools、ToolExecutor、BoundedOpenApiTools 恢复 HEAD，正常内部工具无需迁移；完成当前范围定向回归及质量检查。
  _Requirements: 正常执行保持兼容、交付证据真实_
  _Acceptance: AC-05, AC-06_
  _Verification: V-COMPAT, V-FINAL_
  _Depends: T01, T02, T03_
  _Boundary: 只记录实际结果；已知正常执行同族风险非本补丁覆盖_

## 范围修订

原 T03 的同步传输、T05 的全部执行接线和内部工具迁移要求撤销，收敛到上述入口专用任务。历史 195 passed 不计作当前 T04 完成依据；最终Python3.11合并243 passed，Ruff/arch-guard/diff通过，见verification.md。
