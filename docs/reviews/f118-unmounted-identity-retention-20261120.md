# Code Review Report

**Feature**：F118 取消租户身份后的历史记录保留，AC-135～137 / D13。用户已确认保留兼容方案并要求继续升级。

**Review scope**：原生只读事实、原完整性探针适配、封闭冻结元数据、首次 M3/权限中间状态/最终 CURRENT 原事务复验、保留 FGA 端点、原 Run 恢复及文档。基线 `25a3391541f6231816b9627e35c0eaab6b0bde43`；按项目 `sdd-code-review` 技能逐项审查，没有子代理。

## 行为与恢复

实际 Tenant 不存在、精确取消审计、零绑定/挂载、预置类别及子项/已迁出助手结构、稳定原 ACL 和 FINALIZED 操作共同闭合，才可保留。原行只读分页摘要，不删数据、不改 tenant_id、不创建 Tenant 或 Grant。原 assignee 父关系校验不排除，实际 Tenant/Coverage 不扩大。

仅有保留集合的新 Run 添加 `preserve_unmounted_v1`、身份数和摘要，baseline/plan 同值。首次业务写入、每次权限状态验证与最终 CURRENT 事务重读；新增/修改/移除事实、恢复身份或重新绑定/挂载拒绝。旧 Run 无字段时继续原严格合同。原 Store 完整快照保持，保留 resource/稳定 Grant 端点相关键在 before/staged/after 必须精确相等；原失效助手不被收编成 Root 授权。

## 验证与性能

- 新增 31 项原生 SQLite + 真实转换/投影/账本逻辑测试：原行保持、206 身份分页、拒绝未知或活动身份、SQL/审计/身份漂移、原冻结合同、SQL/FGA/最终事务取消后沿原 Run 完成 Coverage。FGA 仅替换传输，核心迁移不 mock。
- 最新定向组合 **67 通过**：新增保留测试、原 CLI 和权限原始快照仓库；包含带真实原 Grant/model/主体键的原 M2→M3→权限→引用→Coverage 及重复执行不再写入。
- 实际 MySQL 只读 acquisition：206 身份、3,708 预置类别、8,034 子项、3,709 组原 ACL 及其最终操作事实，185 SELECT，约 1.7 秒；SQL 事件钩子拒绝 DML/DDL。只记录数量/耗时，不导出原行或凭据。本轮没有执行 DM8。
- 正常无孤儿路径保留原五条探针；空保留集合不扫描 before/staged/after。非空集合按 <=200 行主键/有限 Owner ID 批次读取、流式摘要，相关 scope 以集合查找，不逐项重扫原表或重复加载大载荷，不设置部署租户总数上限。
- 扩展迁移回归执行中，包含 10,001 资源、10,001 tuple/source 和 1,001 模型规模。当前单个查询计数失败已在未改 `b6c58466b2` 基线复现：`test_full_m2_keeps_original_default_sources_and_freezes_safe_after_commands` 预期 9、实际 6。最终结果补记，不宣称扩展全绿。
- 整个 knowledge 测试目录还包含 API/中间件依赖；本地不可连接相应中间件，已停止该无效扩展。首个 API MySQL 连接失败也在未改基线复现，不把它算作本次新缺陷。
- Ruff/F821、格式、架构守卫、diff 空白、六条 QA 用例八列校验通过。真实 MySQL 完整正式预检/转换及开服验证按现场阶段日志记录；原生传输测试不代替真实 OpenFGA 或真实非管理员验收。

## Summary

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

## Overall: PASS

针对本次变更未发现须阻止合入的问题；上述基线失败、规模测试进度与真实双库/现场验收边界单独保留，不扩大为全功能验收结论。
