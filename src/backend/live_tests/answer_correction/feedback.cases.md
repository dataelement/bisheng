# F119 功能验收

使用当前分支服务、真实会话及权限。以 JSON 环境变量 `BISHENG_CORRECTION_SCENARIO` 提供服务根地址 `url`、无引用的 `answer_id` 及其 `quote`、同一用户可见的无关联库回答 `unsupported_answer_id`、同一用户可见的跨租户共享应用回答 `shared_answer_id`、`knowledge_id`、`unrelated_knowledge_id`、`assignee_id`。 `actors` 为 user、owner、maintainer、other_maintainer、outsider、other_tenant 各自的请求认证头。other_maintainer 有目标库维护权限但未受派。

| 编号 | AC | 前置条件与步骤 | 预期 |
|---|---|---|---|
| FLOW-119-01 | AC-01 | 用户提交无引用原句，分别尝试省略依据或原句 | 完整反馈提交成功，缺项被拒绝 |
| FLOW-119-02 | AC-02 | 负责人查看待办，非负责人读取反馈 | 负责人看到完整反馈，非负责人被拒绝 |
| FLOW-119-03 | AC-03 | 负责人先选择无关库，再分派到关联库维护人 | 无关库分派失败且状态未变，受派人看到完整反馈 |
| FLOW-119-04 | AC-04 | 其他维护人尝试写结果，随后受派人写结果 | 前者被拒绝，后者提交后负责人看到结果和待回复状态 |
| FLOW-119-05 | AC-05 | 负责人分别在结果前后发送回复 | 前者被拒绝，后者发送成功 |
| FLOW-119-06 | AC-06 | 提交人、其他用户、其他租户用户分别查看反馈 | 提交人看到原句、已回复状态及回复，其余用户被拒绝 |
| FLOW-119-07 | AC-07 | 查询无关联库和跨租户共享应用的回答资格，并模拟旧页面提交 | 资格为否，提交被拒绝 |
