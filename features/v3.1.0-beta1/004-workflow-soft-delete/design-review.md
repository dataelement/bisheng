# 工作流逻辑删除设计审查

日期：2026-11-04。依据：`.claude/skills/sdd-review/references/design-checklist.md` 24 项与 `docs/constitution.md`；方式：自查。

结论：LGTM。用户已确认设计；后续代码实现与验证记录见 verification-report.md。

- 规格一致：AC-01、AC-05、AC-09 对应保留原删除链路；AC-02、AC-03、AC-06 对应显式过滤与新入口保护；AC-04 对应历史读取；AC-07 对应条件更新和父锁；AC-08、AC-10、AC-11 对应现有租户、双库迁移及不存在反馈。
- 接手信息：设计包含当前代码事实、关键方案取舍与重审条件、字段/接口、逐入口职责、已知坑及验证方法。
- Constitution Check：不新增权限运行时特权或直接 OpenFGA 调用；迁移只做 DDL；新查询走工作流 Repository，现有 DAO 仅修改既有入口；不新增手写租户过滤、秘密、配置或外部依赖。
- 特别检查：UNION 内部过滤、raw SQL 归属条件、历史按名搜索、版本分段事务和预览空 chat_id 入口均已纳入实施覆盖范围。
- 验证边界：这里仅为设计评审，代码测试、MySQL/DM8 集成与 API E2E 尚未执行。
