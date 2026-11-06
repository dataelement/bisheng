REVISE — 单表配置与手动生效的简化方向成立，但异步 ready 提交和实际锁序尚未闭合；另有一处跨事务凭据写入需要明确处理。本报告仅供评审，不构成实施授权。

| 维度 | 评分 | 锚定理由 |
|---|---|---|
| 需求与质量属性忠实度 | 🟢 | 设计 L5、L17、L97–105、L248 明确无意外停机、秘密隔离、保存与运行差异，并覆盖手动确认、A→B→A 和在途保存。 |
| 边界与公共接口 | 🟢 | 设计 L171–176、L207、L219 将配置主数据、生命周期执行和运行快照分属原 Owner，采用显式 session 与内部 DTO。 |
| 模式克制 | 🟢 | 设计 L89–105 以有界单表配置和既有 RuntimeOperation 取代三表、独立 applied 状态机与配置执行引擎，结构与当前需求相称。 |
| 数据、状态及生产消费完整性 | 🔴 | 设计 L197、L211–214 描述异步受理和 ready 后提交，但没有接通当前唯一后台 ready→commit 条件；环境装配也包含独立提交的凭据生产者。 |
| YAGNI 与变化容忍度 | 🟢 | 设计 L93、L105、L309 明确不预建值历史、外部 Vault、轮换工具或热加载；现有执行上下文缺失可退化为 unknown。 |
| 故障与规模现实性 | 🔴 | 设计 L208 的 node→operation 锁序与当前 claim/fact 的 operation→node 相反，会使重建受理与在途事实消费形成死锁。 |
| 决策记录与可读性 | 🟡 | D17–D20 的选型、否决方案及重议条件清楚；L208 对“既有锁序”的事实描述错误，L209 未说明凭据独立事务的处理。 |

### blocker

**B1 — 异步受理后缺少明确的 ready 提交触发器**  
维度：数据与状态、生产消费完整性。

- **锚点：**[设计 L197](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/features/v3.0.0/055-app-publish-pipeline/design.md:197) 返回 `{operation_id,status}`，序列图 L129–135 表示受理后由后台完成；L211–214 只规定执行与提交行为。当前 [RuntimeOperationService.fact L543](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py:543) 仅在 `payload.auto_commit` 为真时自动调用提交。普通部署依赖 [Coordinator L379](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py:379) 的 `wait → commit_runtime_delivery`。
- **失败序列及影响：**新接口创建并返回操作，manager 停止旧实例、启动候选并上报 ready；没有等待中的普通 deploy 调用者，也没有明确冻结 `auto_commit`。manager 随后在 [operations.py L323](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/src/runtime-manager/runtime_manager/operations.py:323) 等待 serving，直至超时，造成已确认重建无法上线。
- **最小方向：**明确在受理事务中冻结 `auto_commit=true`，由既有 fact 消费者调用 purpose 专属提交分支；同时规定 ready 重放在首次提交回滚后仍会再次提交原操作。无需增加执行器或新表。

**B2 — 新受理锁序与当前事实消费锁序相反**  
维度：故障与并发。

- **锚点：**[设计 L208](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/features/v3.0.0/055-app-publish-pipeline/design.md:208) 要求 node→assignment/operation→App/route→配置。实际 [Repository.claim L392–402](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py:392) 先锁 operation 再锁 node；[fact guard L374–377](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py:374) 同样如此。
- **失败序列及影响：**重建受理先持有 node，随后检查并锁定已有 operation；同时 manager 的事实处理已持有该 operation，正在等待 node。双方互等。即使重建本应因已有在途操作而拒绝，也可能先触发死锁；若数据库选择事实事务为牺牲者，还会干扰正在执行的部署。
- **最小方向：**列清这次受理与 create/admit/claim/fact/commit 共用的锁集合，选用兼容的顺序；不得把 node→operation 写成现有一致约定。可以避免持 node 后回锁已有 operation，或调整本次会接触的生命周期入口，不需要扩成通用锁框架。

### should-fix

**S1 — 外层运行 UoW 不能回滚现有凭据签发的独立事务**  
维度：数据一致性、生产消费完整性。

- **锚点：**[设计 L208–209](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/features/v3.0.0/055-app-publish-pipeline/design.md:208) 宣称通过现有 `inject_environment` 同事务冻结，失败整次回滚。该方法 [L314–316](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py:314) 调用 `AppRuntimeCredentialService.stage`；后者 [L197–213](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/src/backend/bisheng/app_publish/domain/services/app_credential_service.py:197) 先签发 ApiCredential，再经运行 Repository 写 binding。凭据 [Repository L31–44](/Users/zhangguoqing/works/bisheng/.worktrees/vibe-app-integration/src/backend/bisheng/open_api/domain/repositories/credential_repository.py:31) 使用自己的 session 和事务。
- **失败序列及影响：**候选凭据及签发审计先独立提交，随后 seal、运行记录 flush 或外层事务提交失败；RuntimeOperation、binding 和预占回滚，凭据行却保留。重新受理又生成一条凭据，留下无法由原操作账本完整追踪的候选凭据与签发记录。当前 route/binding 校验会拒绝其正式调用，但这仍不符合整次回滚的设计承诺。
- **最小方向：**明确由凭据 Owner 提供本次受理所需的 session-aware staging，或定义以原 operation 为键的幂等补偿。不能原样调用现有独立事务方法并宣称外层 UoW 已覆盖。此项仅涉及受理路径，不要求重做历史凭据审计治理。

### nit

无。

最新的自身 maintenance 精确转换与幂等消费修订已解决 origin epoch 自冲突，不再列为问题。审查仅阅读文档与源码，未编辑文件、运行测试或执行远程操作。
