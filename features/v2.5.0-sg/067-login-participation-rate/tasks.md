# 任务

- [x] T001 登录参与度精确去重及累计查询，覆盖日/周/月/区间、日期和组织筛选。
  _Requirements: REQ-01, REQ-02_；_Acceptance: AC-01, AC-02, AC-03, AC-04_；_Verification: V2 服务层回归_
- [x] T002 指标配置和查询/导出接入，兼容已有用户数据集入口。
  _Requirements: REQ-03_；_Acceptance: AC-05_；_Verification: V2 模块回归_
- [x] T003 记录实际验证和部署边界。
  _Requirements: REQ-04_；_Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05_；_Verification: 定向检查与验证文档_
- [x] T004 按 2026-10-23 用户更正，将累积登录人数修正为同人同日去重后跨天累加，同步导出并保护参与度公式。
  _Requirements: REQ-01, REQ-02, REQ-03, REQ-04_；_Acceptance: AC-02, AC-03, AC-04, AC-05_；_Verification: V2 图表查询、导出及相关回归，记录修复前失败和修复后结果_；_Depends: T001, T002_；_Boundary: 仅查询和导出；不改登录事实、组织、权限，不执行部署或历史补数_

## 实际偏差记录

- 2026-10-23：用户直接更正已有指标并给出同日 5 次计 1、7 天登录 5 天计 5 的明确验收，复用已有规格执行局部修正，不另建分支和新功能规格，不重复索要同一口径确认。真实环境与部署对账仍单独标记。
