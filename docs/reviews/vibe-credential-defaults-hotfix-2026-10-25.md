# 运行凭据默认字段热修审查

范围：189 单应用正式上线的审批 outbox 触发 MySQL MissingGreenlet；仅修复 CredentialRepository.create_in_transaction 的服务器默认字段读取。

复现：关闭 SQLite INSERT RETURNING，原实现于 KeyItem.from_row 读取 create_time 失败；配对结果 1 passed / 1 failed。显式 await session.refresh(row) 后 2 passed，仍验证调用方 rollback 可移除候选凭据。此模拟验证不替代真实 MySQL/K8s 发布。

| 七维度 | 结论 |
|---|---|
| 边界条件 | 有/无 INSERT RETURNING 两条路径；不制造默认时间 |
| 权限认证 | 不改 tenant、subject、scope、认证与审计字段 |
| 并发事务 | refresh 使用当前 session；不增加 commit；rollback 验证通过 |
| 信息泄漏 | 不新增日志、响应字段或凭据持久化 |
| 定向测试 | 两例复现/回归；未跑全量测试；DM8 仅静态审查 ORM 兼容性 |
| 风格分层 | Repository 内 ORM refresh；Ruff、架构守卫和 diff check |
| 文档同步 | F056 design 已知坑与修订说明同步 |

结论：PASS。复用已批准合同，按 SDD Guide §1 hotfix 流程；真实部署重试结果另记部署记录。
