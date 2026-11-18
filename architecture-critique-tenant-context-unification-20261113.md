**REVISE：总体方向合理，能复用现有机制渐进落地；但创建者执行身份、写入保护及异步恢复仍有未闭合契约，目前不足以直接进入实现。**

评审基线为当前 HEAD `3ce7e7ef3de81a06f57520a7ab74d6b9e253d8fc`。完整读取方案，核对根级及后端约束与 constitution；全部只读，未连接环境、未运行现场测试。以下区分源码事实和待验证影响。

| 维度 | 评级 | 理由 |
|---|---|---|
| 1. 需求与质量属性 | 🟡 | 身份不变、目标统一及历史保护明确；隔离正确性、兼容性、可运维性三者的优先级和最低交付范围尚未明确。 |
| 2. 边界质量 | 🟡 | 路由准入、资源归属和权限授权分工合理；权威 Home 与“配置作者执行身份”仍没有明确公共契约。 |
| 3. 模式克制 | 🟢 | 复用 Redis、ContextVar、现有权限端口；拒绝新身份系统、数据库及通用操作中心，结构与问题规模相称。 |
| 4. 数据与状态建模 | 🔴 | 操作者与目标区分正确，但创建者字段的运行期消费者未闭合，异步任务也未逐类列出持久生产者和恢复者。 |
| 5. 变化容忍与 YAGNI | 🟢 | 每会话独立选择及新计费政策留待后续，统一入口属于已有漏接问题的合理接缝。 |
| 6. 故障与规模现实性 | 🟡 | 已考虑 A→B→A、旧响应、Redis 故障和滚动版本；切换后的审计失败、重试及批量写绕过仍需落实。 |
| 7. 决策记录与可读性 | 🟡 | 主要取舍有解释；管理调试、旧任务恢复及历史异常行的上线行为仍是待定项，不能只作为后续清单。 |

### blocker

**B1｜维度 2、4：创建者并非只用于展示，跨租户创建会进入错误的执行身份链。**

- **锚点：**方案 §2.3 保留真实创建者，§5 覆盖人员展示和发布摘要，却未明确创建者作为运行身份的处理。源码中，[tasks.py:63](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/worker/workflow/tasks.py:63) 将 `Flow.user_id` 作为 `flow_user_id`；[knowledge.py:463](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/workflow/common/knowledge.py:463) 在知识权限开关关闭时选择该创建者；[space_flow_retrieval.py:57](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/knowledge/domain/services/space_flow_retrieval.py:57) 又以流程租户初始化此用户。[auth.py:552](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/user/domain/services/auth.py:552) 将该租户当作预期 Home，[effective_roles.py:55](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/role/application/effective_roles.py:55) 在不匹配时拒绝。
- **影响：**Root 超管在 A 创建流程，A 普通用户执行知识空间检索且权限开关关闭时，静态调用链会把“Root 创建者 + A 资源租户”送入 Home 一致性校验，存在 `24006` 拒绝路径。Agent 节点也采用同样的创建者选择逻辑。**这是源码确认，未现场复现；实际触发还取决于流程配置和数据。**
- **建议方向：**将创建者的展示、审计和执行依据分开审查。保留真实创建者，明确这种已配置资源执行使用什么经验证的资格；沿既有知识检索及权限入口做最小修正，不伪造 Home，不因修展示而扩大检索授权。必须增加“A 普通用户运行超管在 A 创建的流程”验收。

### should-fix

**S1｜维度 2、4：权威 Home 不能再派生一套近似规则。**

- **锚点：**方案 §3.2 只称“权威主属”；现有 [tenant_scope_repository.py:19](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/admin/domain/repositories/tenant_scope_repository.py:19) 自行查询活跃 `UserTenant`，而现有身份策略通过 `read_policy_subject`、`load_effective_roles` 还检查 Home 与主部门业务归属一致性。
- **影响：**复用现有管理范围仓储并不自动等于复用权威身份判定；异常成员记录可能在准入和业务身份阶段得到不同结果。
- **建议方向：**点名唯一事实来源及校验责任。准入消费用户领域的最窄公开事实端口，避免复制全部角色策略，也避免另写 Home 推断。

**S2｜维度 4、6：把警告改为拒绝，仍覆盖不了现有批量更新和删除。**

- **锚点：**方案 §4.2、§6.1 承诺错租户写入拒绝。实际 [tenant_filter.py:230](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/core/database/tenant_filter.py:230) 仅过滤 SELECT，`before_flush` 仅遍历 `session.new`。例如 [mark_task.py:108](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/database/models/mark_task.py:108) 直接按任务 ID 执行 `update()`。
- **影响：**路由声明齐全、插入保护通过，不能证明更新、删除及存量对象修改被目标范围约束。
- **建议方向：**实施契约明确区分 INSERT、ORM 修改、批量 UPDATE/DELETE、原始 SQL。优先在已有仓储写入口验证资源目标并约束语句，不为解决此问题立即建设通用 SQL 安全框架。上述标注调用是否已有可靠上游验证，仍待逐链核实。

**S3｜维度 4、6：异步任务需要明确旧消息和新持久事实的优先关系。**

- **锚点：**方案 §3.4 要求从持久任务恢复，§7 允许按需补字段；现有 [tenant_context.py:81](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/worker/tenant_context.py:81) 从当前 ContextVar 写消息头，消费者在缺少头的普通任务上 [回退 Root](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/worker/tenant_context.py:107)。方案 §5 没有点名这一生产、消费机制。
- **影响：**仅修改任务内部恢复逻辑，可能在恢复前就被旧信号设置错误范围；旧队列、重试和 Beat 任务不能统一按浏览器任务处理。
- **建议方向：**逐类列出提交入口、持久字段、消息参数、恢复入口及缺失处理；明确持久目标与头不一致时拒绝还是告警。发布清单纳入旧消息，复用已有持久任务记录，缺字段才补。

**S4｜维度 6：切换原子性只覆盖 Redis 值，没有定义切换后的部分失败。**

- **锚点：**方案 §3.3.3 要求原子更新目标和视图；现有 [tenant_scope.py:99](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/admin/domain/services/tenant_scope.py:99) 先写 Redis，再写 SQL 审计，最后响应。
- **影响：**审计失败或响应丢失时，选择可能已经改变，客户端却认为失败；加入每次更新的视图标识后，盲目重试还会再次使旧视图失效。
- **建议方向：**明确切换的提交点、失败响应后的重新读取及重试行为，并决定审计失败策略。无需追求跨 Redis/SQL 分布式事务，但不能留下“接口失败即未切换”的假设。

**S5｜维度 1、7：历史数据保护原则正确，历史可用性影响尚不能判断。**

- **锚点：**方案 §7.6 禁止回退时搬迁业务行，§7 又提出无需整体迁移；与此同时 §4 将加强错租户拒绝和目标验证。
- **影响：**历史父子记录、授权行或引用若已有归属不一致，新约束可能使原有操作明确失败。**当前只读源码评审未证明现场存在多少此类数据，也未证明全部历史数据可透明继续使用。**
- **建议方向：**上线前提供只读预检分类和结果：合法跨范围引用、可证明异常、无法证明异常；定义各类的保留、拒绝及人工处理路径。无需自动修复，更不能根据创建者 Home 批量改资源租户。

### nit

**N1｜维度 1、7：将“最小改动”定义为最小可验收闭环。**

方案 §7 同时覆盖全路由、两套前端、网关、数据库外存储及异步任务，已经是跨模块治理。建议明确首批闭环与启用门禁：保留现有身份和存储，先统一准入及视图快照，再修真实创建/执行链，最后在覆盖完成后启用全入口强制检查；不要把“零新增业务表”当成改动量小的证明。

**一句话结论：可以保留方案方向，但进入实现前必须补齐创建者执行消费者及上述最小契约，历史数据继续只读盘点、独立确认处理。**
