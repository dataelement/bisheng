# Feature: F045/F046 审批流程与业务职责解耦

> **本文档定位 — 纯 What（需求口径，不随代码漂移）**
>
> 本文档只回答做什么、验收标准与范围边界。模块端口、事件协议、状态归属、服务拆分和文件清单在 `design.md` 中确定。

**关联需求**: 2026-08-12 用户确认“审批模块只负责审批流程，具体业务数据由业务模块管理；F045/F046 均未上线，不考虑旧实现兼容，按高内聚低耦合重新实现”
**Feature ID**: F047
**优先级**: P0
**所属版本**: v2.6.0
**依赖**: [F025](../025-approval-center-unification/spec.md)、[F045](../045-personal-user-invite-confirmation/spec.md)、[F046](../046-knowledge-space-file-change-approval/spec.md)

> **范围边界**
>
> - **本次纳入**：
>   - 同时重构 F045“个人用户邀请本人确认”和 F046“知识空间文件变更审核”。
>   - F025 统一负责场景、流程、节点、审批实例、审批任务、审批决定、审批日志、审批通知及审批决定的可靠交付。
>   - Permission/资源授权业务负责 F045 邀请申请、角色快照、邀请去重、待生效展示、授权执行、业务失败和重试。
>   - Knowledge 域负责 F046 待审业务数据、上传暂存、目录归属、资源占用、正式变更、解析调度、业务失败、重试、清理和补偿。
>   - 两个业务域均通过 F025 公共端口创建审批、处理审批决定，并以幂等方式消费审批终态。
> - **本次明确排除**：
>   - 不改变菜单权限申请、频道订阅、知识空间加入等已存在审批场景的状态机和业务执行机制。
>   - 不把 F045 邀请数据或 F046 文件数据继续寄存在 Approval payload、instance、task 或 outbox 中作为业务事实源。
>   - 不扩展已废弃的 `approval_request` 文件上传审批系统。
>   - 不改变 F045 的本人确认、逐人处理、角色与权限安全规则。
>   - 不改变 F046 的审核开关、空间策略、审核人范围、或签规则和最终文件业务效果。
>   - F045/F046 均未上线；不迁移、不兼容当前开发版本生成的审批实例、outbox、Celery 消息或业务数据。

---

## 1. 用户故事

### 1.1 审批中心维护者

作为审批中心维护者，我希望 F025 只理解通用审批概念和版本化审批决定，不导入权限、频道或知识文件执行服务，以便新增业务场景不会继续扩大审批引擎职责。

### 1.2 F045 业务维护者

作为权限与资源授权维护者，我希望个人邀请申请、角色快照、去重、待生效展示和授权结果都由业务模块管理，以便审批流程变化不会改变邀请业务事实。

### 1.3 F046 业务维护者

作为 Knowledge 维护者，我希望文件变更申请、暂存、执行步骤、失败和补偿都由 Knowledge 管理，以便文件生命周期不再反向驱动审批状态。

### 1.4 用户与运维人员

作为申请人、审批人或运维人员，我希望能区分“审批决定是否成立”“决定是否已交付”“业务是否执行成功”，并在各自归属模块中查询和恢复。

---

## 2. 验收标准

### 2.1 通用职责边界

- **AC-01** — THE SYSTEM SHALL 仅由 F025 创建和修改 Approval 场景、流程、节点、实例、任务、决定、日志、审批异常和审批通知数据。
- **AC-02** — THE SYSTEM SHALL 仅由对应业务域创建和修改 F045/F046 业务申请、业务执行、失败、重试、清理和补偿数据。
- **AC-03** — THE SYSTEM SHALL 禁止 F025 导入或调用 F045/F046 的授权、文件 mutation、解析、清理或补偿 Service。
- **AC-04** — THE SYSTEM SHALL 禁止 F045/F046 直接写 Approval ORM/Repository；业务域只能调用 F025 公共 application port。
- **AC-05** — THE SYSTEM SHALL 使审批列表和详情只依赖审批事实及提交时快照；业务服务不可用时仍可读取，需实时资格校验的决定必须失败关闭。
- **AC-06** — THE SYSTEM SHALL 保持 F045/F046 之外审批场景的流程、状态、outbox、异常处理、通知和用户行为不变。

### 2.2 审批提交与决定交付

- **AC-07** — WHEN 业务申请创建成功, THE SYSTEM SHALL 在同一数据库事务中建立唯一业务申请与审批实例绑定；任一方失败均不得留下孤儿记录。
- **AC-08** — WHEN 最后审批节点形成终态, THE SYSTEM SHALL 在同一 F025 事务中保存审批终态和唯一审批决定交付记录。
- **AC-09** — THE SYSTEM SHALL 使 `approved/rejected/withdrawn/cancelled` 成为 F045/F046 的审批终态；业务执行不得把实例改为 `executing/executed/execute_failed`。
- **AC-10** — IF 决定交付暂时失败, THEN THE SYSTEM SHALL 保留审批终态并独立重试交付，不重新打开任务、不回退决定、不要求重新审批。
- **AC-11** — WHEN 同一决定重复、延迟或乱序投递, THE SYSTEM SHALL 由业务域以稳定事件 ID、业务申请绑定和行锁保证单次有效处理。
- **AC-12** — IF 事件关联的业务申请不存在、租户不一致或快照指纹不一致, THEN THE SYSTEM SHALL 拒绝业务执行并记录交付失败，不得根据审批快照重建业务数据。

### 2.3 F045 个人邀请业务

- **AC-13** — THE SYSTEM SHALL 由 Permission/资源授权业务保存每个目标用户的邀请申请、资源、邀请人、角色快照、关系、指纹、审批实例绑定和业务执行状态。
- **AC-14** — WHEN 同一资源与目标用户存在阻塞中的邀请, THE SYSTEM SHALL 由 F045 业务唯一约束和业务锁返回原申请，不依赖 ApprovalInstance 扫描实现去重。
- **AC-15** — WHEN 创建邀请审批, THE SYSTEM SHALL 将被邀请人作为唯一审批人，并保持本人确认、管理员不可代办和逐人独立决定规则。
- **AC-16** — WHEN F045 审批通过, THE SYSTEM SHALL 由 F045 consumer 重新校验业务申请、角色指纹、资源和权限，再调用资源 owner Service 执行授权。
- **AC-17** — IF F045 授权失败, THEN THE SYSTEM SHALL 在 F045 业务申请记录失败并允许复用原审批结果重试；审批实例仍为 `approved`。
- **AC-18** — WHEN F045 被拒绝、撤回或取消, THE SYSTEM SHALL 关闭对应业务申请且不写有效授权。
- **AC-19** — THE SYSTEM SHALL 由 F045 业务查询提供待生效邀请和授权结果；不得从 Approval payload 推导邀请列表。

### 2.4 F046 文件变更业务

- **AC-20** — THE SYSTEM SHALL 由 Knowledge 保存文件变更申请、暂存对象、footprint、执行步骤、token、业务状态、失败和补偿数据。
- **AC-21** — WHEN F046 审批通过, THE SYSTEM SHALL 由 Knowledge consumer 将业务申请置为待执行并派发 Knowledge worker；F025 不等待或观察文件执行。
- **AC-22** — IF F046 执行失败, THEN THE SYSTEM SHALL 仅在 Knowledge 记录和恢复失败，复用原审批结果，不生成 `execute_failed` 审批异常。
- **AC-23** — WHEN F046 被拒绝、撤回或取消, THE SYSTEM SHALL 由 Knowledge 停止未开始的正式变更并幂等清理其拥有的暂存数据。
- **AC-24** — WHILE 文件业务执行中或失败, THE SYSTEM SHALL 在审批中心显示审批决定，在文件页显示真实业务状态，二者不得合并为一个状态。
- **AC-25** — THE SYSTEM SHALL 继续满足 F046 原 spec 的权限复核、冲突占用、正式发布门禁、幂等步骤、权威读后校验和补偿要求。

### 2.5 场景策略、通知与可观测性

- **AC-26** — THE SYSTEM SHALL 通过应用装配层注册版本化 `ApprovalScenarioPolicy`；approval 包不得直接导入 Permission、Channel 或 Knowledge 业务实现。
- **AC-27** — THE SYSTEM SHALL 由 F025 在实例锁内物化和推进审批任务；业务 policy 只提供快照、审批人解析、当前资格校验和可见性判断，不写业务数据。
- **AC-28** — WHEN F046 owner/manager 变化, THE SYSTEM SHALL 由 Knowledge/Permission 权限事件或 Knowledge 补偿任务计算当前集合，再调用 F025 对账端口；普通审批列表不得主动扫描 Knowledge 业务表。
- **AC-29** — THE SYSTEM SHALL 由 F025 发送待办、通过、拒绝、撤回和取消等审批通知；业务执行成功或失败通知由对应业务域发送。
- **AC-30** — THE SYSTEM SHALL 分别记录审批流程、决定交付、F045 授权执行和 F046 文件执行指标，并以 `tenant_id + approval_instance_id + business_request_id` 关联。

### 2.6 发布边界

- **AC-31** — THE SYSTEM SHALL 以线上 `v2.6.0` 无 F045/F046 数据为发布基线，直接替换当前开发实现，不提供旧 F045/F046 task、outbox、token 或数据迁移适配器。
- **AC-32** — WHEN 升级发布, THE SYSTEM SHALL 采用停服升级；停 API/Beat/worker 后执行迁移并整体启动新版本，不支持新旧实现混跑。
- **AC-33** — IF 升级前只读检查发现 F045/F046 场景、实例、业务表数据或相关 broker 消息, THEN THE SYSTEM SHALL 阻止标准发布并要求先清理非生产数据。
- **AC-34** — THE SYSTEM SHALL 以 F025 decision outbox 和业务申请状态为恢复事实；broker task ID 和消息本身不得作为业务完成证据。

---

## 3. 边界情况

- 业务申请事务成功而审批提交失败时，整个事务回滚；审批提交成功而业务绑定失败时同样回滚。
- 文件页与审批中心并发提交同一决定时，只允许一个终态生效，另一请求返回最新审批事实。
- 审批决定已成立但业务 worker 暂不可用时，决定交付和业务执行分别积压并可恢复。
- F045 授权副作用成功但 ack 丢失时，业务域必须通过授权权威读后校验确认结果，不能重复写入不可逆副作用。
- F046 部分执行失败时，只有 Knowledge 可以续跑或补偿，审批中心不提供业务重试入口。
- F046 当前审批人变化时，历史任务保留审计但不继续授予查看或决定资格。
- 两个业务场景都不得把完整业务对象、存储路径、角色明细或执行 checkpoint 放入审批决定事件。

---

## 相关文档

- F045 原需求: [个人用户邀请本人确认](../045-personal-user-invite-confirmation/spec.md)
- F046 原需求: [知识空间文件变更审核](../046-knowledge-space-file-change-approval/spec.md)
- 审批中心基线: [F025](../025-approval-center-unification/spec.md)
- 版本契约: [release-contract.md](../release-contract.md)
- 架构约束: [docs/constitution.md](../../../docs/constitution.md)
- 设计真相: [design.md](./design.md)
