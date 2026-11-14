# F118 原权限图保留与特殊类别抽检

用户最新明确调整现场验证为“抽检特殊情况”，保留历史原值，不扩大清理。此变更保留未变化命名空间的现场关系，避免自动填补缺失marker重新启用历史资源。

| 维度 | 结论 | 证据 |
| --- | --- | --- |
| Boundary Conditions | PASS | 仅原冻结键、端点均不移动/不属于destination、双schema和typed关系合法；缺技术marker保持缺失。 |
| Permission & Auth | PASS_WITH_WARNINGS | 保留键不新增写入，不创建SQL授权；新namespace未授权边继续拒绝。历史SQL/FGA偏差保留，按用户要求抽检，不声称完整业务ACL证明。 |
| Concurrency Safety | PASS | 不改冻结字节、SQL命令、intent/ACK、原始/阶段/最终Store核验或同Run续跑。 |
| Information Leakage | PASS | 无新端点/凭据；原数据证据私有保存，不将关系原文暴露为新来源绑定。 |
| Test Coverage | PASS_WITH_WARNINGS | 68项发布与恢复回归通过；缺标记、旧父原样保留、零新增写入、新destination拒绝，保留完整性漂移及未知ACK拒绝。现场样本待执行。 |
| Code Style | PASS | Ruff/diff-check/变更文件arch-guard通过，限定原tuple builder与测试夹具。 |
| Docs Sync | PASS | 用户指示、AC-113、design/tasks/八列QA173及现场报告同步；明确未清理的两条旧父关系。 |

此处不执行业务数据或FGA残留删除。完整F118验收、DM8和全业务权限等价性不由该抽检证明。
