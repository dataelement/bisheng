# F086 Code Review Report

## R3评审问题修正后的源码自检

基线a58ab1c2cb；用户已授权修正此前NEEDS_FIX的R1/R2/R3。此记录不是独立第三方复审或生产放行。

| 原问题 | 修正与验证 | 当前边界 |
| --- | --- | --- |
| R1 / P1 全局排他Catalog锁误伤正常变更 | 统一共享发布读屏障；普通资源授撤权复用，模型发布仍被排斥。确定性MySQL/DM调度及真实MySQL多连接通过 | DM实机多连接和完整FGA/Redis E2E待执行 |
| R2 / P1 合法挂载子树被拒绝 | 同事务按实际父链/后代更新path，保持tenant/mount，允许合法单层挂载，仅非法拓扑拒绝；真实SQLite回滚及合法/非法对照通过 | 同步挂载并发的真实双库验收仍必需 |
| R3 / P2 旧缓存写回旧path | 写事务核实当前父链，缓存路径只作提示；混合批次/重复/跨请求旧快照和健康改名查询范围通过 | 大规模真实同步耗时待QA测量 |

最终383项核心回归与1项隔离MySQL多连接通过；扩展回归7个失败在前后基线完全一致，无新增失败。详见validation.md。源码自检：PASS_WITH_WARNINGS，完整部署仍PARTIAL；修复不会把部门级门禁细化为单用户隔离，QA Q28已明确。

## 原实现自检（历史记录）

范围：cofco-1111基线00720a9c上的本次工作树（含新增文件）。依sdd-code-review七维度进行源码自检；不是独立人工审查或上线批准。

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS（本地证据） |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | 外部验收待执行 |
| Code Style | 0 | 0 | 0 | 新文件通过，无新增lint |
| Docs Sync | 0 | 0 | 0 | PASS |

已修正的检查点：正常归档不能被自动恢复“清理必须先完成”反向阻塞；恢复后的ORM refresh不能被旧outcome覆盖；源消息在锁内重新核对ts；软删/非叶子及陈旧前缀不能隐藏孤儿后代；当前/旧维护source要求sealed证明；归档全拥有域包含admin；无tenant列的关联使用D拥有范围子查询；正常/自动/手动共享执行权、资源恢复资格不扩围。

MEDIUM：缺真实MySQL/DM/FGA/Redis及多节点隔离验收，详见validation.md与e2e-checklist.md。当前源码可进入分支评审/测试，不应直接当作客户生产验收通过。

推送前追加检查：正常新业务投影与恢复模型发现/限速隔离，仍保留Catalog锁/运行时pin、租约及同SQL UOW；真实SQL事务测试覆盖正常失败、恢复和正常归档。最终369项本地回归通过；QA交接见[QA-IMPACT.md](QA-IMPACT.md)，外部验收边界不变。

Overall：PASS_WITH_WARNINGS（源码自检）；完整部署E2E：PARTIAL。
