**REVISE — 权限动作与 v2 收敛方向成立，但系统自愈的授权来源尚未闭合，阶段鉴权也需覆盖阻断旧服务的首个效果。**

| # | 维度 | 评价 | 依据 |
|---|---|---|---|
| 1 | 需求与质量属性一致性 | 🟢 | 已明确授权一致性、租户隔离与运行安全，71 条 AC 有设计追溯，非目标清晰。 |
| 2 | 边界质量 | 🟢 | app 业务事实、F048 动作、审批资格与平台能力各有归属，对外采用 application 接口和上下文端口。 |
| 3 | 模式克制 | 🟢 | 复用既有授权、审批与运行状态机；删除双协议和通用重建分支，有明确需求依据。 |
| 4 | 数据与状态建模 | 🔴 | 用户操作的上下文生产、持久化和消费基本完整，但自动自愈创建的新 operation 缺少对应的系统授权模型。 |
| 5 | 变化容忍与 YAGNI | 🟢 | 未新增权限模型、通用重建框架或全局事务；未来动作细分等扩展只保留重审条件。 |
| 6 | 失败与规模现实性 | 🟡 | 撤权、凭据失效、阶段围栏已有安排；维护态的首次副作用顺序及预览凭据的部分失败处理仍需具体化。 |
| 7 | 决策记录与可读性 | 🟢 | D1–D9 均记录备选、选择、原因与重审条件，能够区分现状与拟改目标。 |

### blocker

**B1 — 系统自愈创建新部署，却没有可供阶段鉴权验证的独立授权来源。**

- **维度：** 数据与状态建模、失败现实性。
- **设计锚点：** [design.md:185](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/features/v3.0.0/114-vibe-permission-actions/design.md:185) 要求持久化真实主体、凭据引用及动作，续办重查当前凭据/F113/F048；§4.8 拒绝未知用途。与此同时，§2、§4.5、§6.5 承诺自愈不依赖历史操作者继续持权。
- **已核实源码：** [recover():481](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/src/backend/bisheng/app_runtime/domain/services/runtime_delivery_coordinator.py:481) 根据观测生成新的 `deploy` operation，设置 `auto_commit=True`，随后重新注入运行环境；[observation():701](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py:701) 是其生产入口，`fact()` 再自动提交路由。现有生产者没有系统授权上下文。且 [配置确认重建:130](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/src/backend/bisheng/app_runtime/domain/services/secret_rebuild_service.py:130) 同样使用 `deploy + auto_commit`。
- **影响：** 直接套用缺上下文拒绝会破坏 AC-60；按 `deploy`、`auto_commit` 或“后台调用”豁免，又可能放过本应检查 `edit AND publish` 的配置重建。正文的“沿原可信意图”尚未说明该意图如何生产、持久化和验证。
- **建议方向：** 在现有上下文中明确区分用户意图与系统自愈意图。列出 `observation → recover → authorize-step → route commit` 的生产消费链，系统意图绑定可信来源 operation、route/epoch、tenant 和批准版本；阶段鉴权验证此来源，不复用历史用户凭据，也不按通用标志豁免。

### should-fix

**S1 — 阶段鉴权需要明确先于维护态投影和旧 writer 停止。**

- **维度：** 失败现实性。
- **设计锚点：** [design.md:189](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/features/v3.0.0/114-vibe-permission-actions/design.md:189) 描述迁移、正式启动和路由提交前的一步准入，但没有列出进入维护态的授权边界。
- **已核实源码：** [OperationExecutor._deploy():304](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/src/runtime-manager/runtime_manager/operations.py:304) 先上报 `maintenance`、停止旧实例，然后才备份、迁移和启动；[fact():491](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py:491) 收到维护事实即阻断正式路由，[RuntimeProjectionService.block():20](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/src/backend/bisheng/app_runtime/domain/services/runtime_projection_service.py:20) 还会撤销出站策略。
- **影响：** 若将检查放到“迁移前”或“启动前”，已撤权的发布仍可能先切断旧版本服务，再被拒绝，无法兑现 AC-40 的旧服务保护。
- **建议方向：** 补一张最小阶段顺序表，明确首次准入先于维护投影和停 writer；另说明进入维护后撤权的安全收尾。增加“准备完成后、维护开始前撤权”的定向验证。

**S2 — 新预览凭据加入后，会话、凭据和 operation 的提交及失败回收顺序不明确。**

- **维度：** 数据与状态建模、失败现实性。
- **设计锚点：** [design.md:211](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/features/v3.0.0/114-vibe-permission-actions/design.md:211) 扩展会话复用键，§4.7 新增独立凭据与 operation 绑定；§4.9 只列凭据唯一索引和会话查询索引。
- **已核实源码：** [start():165](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/src/backend/bisheng/app_publish/domain/services/preview_instance_service.py:165) 采用先查后建；[_insert_session():429](/Users/zhangguoqing/.codex/worktrees/vibe-permission-actions/bisheng/src/backend/bisheng/app_publish/domain/services/preview_instance_service.py:429) 独立提交 `running` 会话后，才创建运行操作；启动异常直接关闭会话。当前索引未保证同一复用键只存在一个活跃会话。
- **影响：** 并发启动或进程在签发后崩溃时，可能产生重复会话、未绑定凭据或缺少对应清理记录的凭据。入口拒绝可以限制访问，但不能替代生命周期收敛。
- **建议方向：** 明确复用键的并发串行点，以及会话、凭据绑定、operation 的事务边界；签发采用可参与事务的既有方式，并覆盖启动失败、超时及未知结果的单凭据回收，避免仅靠查询索引承担幂等性。

评审结论：先补齐系统自愈的授权生产消费链及首次运行副作用边界，再进入任务拆解；无需新增授权引擎或重建框架。
