# 独立设计评审

评审者：独立agent tenant_system_model_design_review；只读代码，未参与原方案生成。

## 首轮

**REVISE：业务原则成立；实施前需补齐槽位准入和持久共享生命周期两项设计。** 基线8d343af331。

| 维度 | 评分 | 理由 |
|---|---|---|
| 需求与质量属性 | 绿 | 配置来源、跨租户授权、成员范围、计费分别建模。 |
| 边界与职责 | 绿 | 保留owner/application、PermissionService及引用管理。 |
| 模式克制 | 绿 | 保持栏目级继承与提供商级共享。 |
| 数据与状态 | 红 | slot安全合同及共享意图/接收初始化生产者未定义。 |
| 变化容忍度 | 绿 | 槽位登记和消费者可追踪。 |
| 失败现实 | 黄 | 部分失败及原冻结计划协调待细化。 |
| 决策记录 | 黄 | 图片双来源迁移优先级未定。 |

Blocker：model_default_read.py原slot入口先整份准入，source_read.py同时检查完整性/effective/所有目标；新增slot入口不能丢完整摘要验证或返回未准入字段。source_read_target_owner将inherited_server_ids并入共享事实，违反继承不授权。

Blocker：LLMServer无持久共享开关，UI从tuple非空反推，model_sharing.py只冻结当次after；tenant_mount_service仍由Root.share_default_to_children选择全部Root提供商。需持久意图及完整挂载/新模型/接收默认生产者。

Should-fix：DSH vision租户键与非DSH visual双源要明确优先级；新增默认与历史无记录分开，重试不覆盖管理员限制；恢复手册保留原actor和command约束。

## 补充设计后复审原文

**PROCEED：复审通过，当前无剩余 blocker。** 已只读核对新基线 `c36ba672be` 的 spec/design/tasks。

首轮关键问题已在设计中闭合：

- §1 保留完整来源摘要、版本、effective、身份和事务验证；只投影已准入槽位，明确按请求执行租户核对共享，移除继承授权捷径。
- §2 明确持久提供商意图、当前拓扑与实际共享差异；旧未知意图不自动分发，原冻结计划不被新命令覆盖。
- §2 冻结新增接收模型集合，只初始化缺省可见规则，重试保留管理员限制。
- §3 统一图片能力解析，保留旧显式关闭，覆盖 DSH 与非 DSH 消费者。

两项 **should-fix 实施细节**建议补入设计或验收：

1. §2 的“完成后记录意图”应明确与原计划置 `COMPLETED` 在**同一 SQL 事务**提交，避免投影已完成但持久意图遗失。
2. §3 补能力优先级真值表，区分“owner 能力未知”和“子租户没有 override”；明确旧 `visual=false` 与已有 `dsh=true` 冲突时如何保留原限制，防止把无 override 错当关闭或开启。

以上无需改变已批准的业务政策，可在实现时同步补齐并验证。
