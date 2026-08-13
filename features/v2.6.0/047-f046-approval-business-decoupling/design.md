# Design: F045/F046 审批流程与业务职责解耦

> **本文档定位 — 现状快照（Why this How）**
>
> - [spec.md](./spec.md) 回答做什么、验收标准和范围边界。
> - 本文回答统一审批端口、两个业务域的状态与数据流、代码归属和发布方式。
> - [tasks.md](./tasks.md) 只记录实施顺序和实际偏差。

**Feature ID**: F047
**覆盖场景**: F045 `resource_user_invite_confirmation`、F046 `knowledge_space_file_change_request`
**版本**: v2.6.0
**最后更新**: 2026-08-13

---

## 1. 目标与非目标

### 1.1 目标

- F025 只拥有审批配置、流程、任务、决定、审批日志、审批通知和决定交付，不拥有任何邀请或文件业务生命周期。
- Permission/资源授权域拥有 F045 邀请申请及授权执行；Knowledge 域拥有 F046 文件申请及文件执行。
- 两个新场景共享同一套“业务申请 + Approval submission port + decision outbox + 幂等 consumer”协议，不共享业务表或业务 executor。
- F045/F046 审批终态和业务终态永久分离；业务失败不再形成审批 `execute_failed`。

### 1.2 非目标

- 不重构菜单申请、频道订阅、知识空间加入等已上线场景；它们继续使用原 `approval_outbox → handler.on_approved()` 机制。
- 不迁移当前开发版本产生的 F045/F046 数据、Deferred outbox、token 或 Celery 消息；两个场景未上线，发布前清理开发数据后直接切换。
- 不创建通用企业消息总线；本次只建立审批域内部的决定交付端口和场景订阅注册表。
- 不通过本次解耦改变 F045/F046 原有权限、安全、业务效果或前端交互范围。

---

## 2. 关键约束

- 遵循 [docs/constitution.md](../../../docs/constitution.md) C1–C7 和 [release-contract.md](../release-contract.md)。
- 调用方向固定为：业务 application service → F025 application port；F025 不导入 Permission、Channel、Knowledge 的 domain service。
- 创建业务申请和审批 bundle 使用同一数据库事务；双方各自通过 Repository 写自己拥有的表，不能跨域直接写 ORM。
- 审批决定和 decision outbox 在同一 F025 事务中提交；business consumer 的接收和业务状态推进在自己的事务中提交。
- 业务 consumer 必须仅用 `business_request_id` 加载权威业务申请；审批快照只用于审批展示，不是业务执行参数。
- 双数据库只使用普通列、唯一约束、行锁和 `JsonType`；不依赖 JSON 条件、partial index 或数据库专属 upsert。
- 所有跨域命令显式携带并核对 `tenant_id`；不存在默认租户降级。
- F045/F046 不使用 `ApprovalInstance.executing/executed/execute_failed` 或原 `approval_outbox`。这些状态和表继续服务既有场景。
- 线上基线 `v2.6.0` 没有 F045/F046；发布为完全停服升级，不设计新旧实现混跑。

---

## 3. 方案对比与选定

### 决策 1：新增审批决定 outbox，不复用业务执行 outbox

- **备选**：
  - A. 继续让 `approval_outbox` 调业务 handler，业务完成后再结束审批。
  - B. 同步调用业务 service，调用成功才提交审批决定。
  - C. 新增 `approval_decision_outbox`，审批终态与决定事件原子提交，业务域幂等接收后独立执行。
- **选定**：C。
- **原因**：A 正是当前耦合根因；B 会让业务可用性阻塞审批事实且无法原子覆盖外部副作用；C 清楚区分审批、交付、业务执行三类状态，并满足可靠恢复。
- **边界**：原 `approval_outbox` 不改语义，既有场景零变化；只有 F045/F046 声明 `completion_mode=decision_delivery`。
- **何时重新考虑**：只有当所有审批场景都完成业务事实迁出、原 `approval_outbox` 已无消费者时，才评估合并两类 outbox；在此之前不得复用状态或 worker。

### 决策 2：业务申请必须先于审批存在，并与审批原子绑定

- **备选**：
  - A. 只保存 Approval payload，审批通过后凭快照创建业务申请。
  - B. 业务先提交，审批提交失败后异步补偿孤儿。
  - C. 业务 application service 在 caller-owned UoW 中写业务申请，再调用 F025 `submit_in_uow()` 写审批 bundle 并回填绑定，一次提交。
- **选定**：C。
- **原因**：A 让审批表成为业务事实源；B 会产生难以区分的孤儿和重复申请；C 利用同库事务保持强绑定，同时仍由各自 Repository 管理数据。
- **何时重新考虑**：业务申请与 F025 被拆到不同数据库、无法共享事务时，才改为业务侧 transactional outbox + F025 幂等 submission；当前同库部署不引入分布式补偿。

### 决策 3：通过应用装配层做依赖反转

- **备选**：
  - A. `approval_runtime_handler_factory.py` 按场景直接 import 业务 handler。
  - B. 把两个业务 handler 搬进 approval 包。
  - C. F025 定义 `ApprovalScenarioPolicy` 和 `ApprovalDecisionSubscriber` 协议，由应用/worker composition root 注册业务实现。
- **选定**：C。
- **原因**：A、B 都让 F025 了解业务模块；C 使 approval 只依赖协议，Permission/Knowledge 各自实现策略和消费逻辑，顶层装配是唯一同时认识双方的位置。
- **装配要求**：唯一装配文件为 `bisheng/bootstrap/approval_scenarios.py`；API `main.create_app()` 与 Celery `worker/main.py::create_celery_app()` 在接收请求/任务前同步调用同一 `bootstrap_approval_scenarios()`。注册过程不得做数据库或网络 I/O；重复注册、缺少 subscriber 或协议版本不匹配直接抛错并使进程启动失败，而不是在异步初始化线程里静默降级。
- **何时重新考虑**：只有项目建立统一 dependency-injection/container 启动框架后，才把该 composition root 迁入框架；协议归属仍留在 F025，业务实现仍留在业务域。

### 决策 4：动态审批人由业务域计算，F025 只物化任务

- **备选**：
  - A. F025 查询待办时主动扫描 Knowledge 并解析 owner/manager。
  - B. Knowledge/Permission 在权限变化、业务页惰性校验和补偿任务中计算当前集合，调用 F025 `reconcile_assignees()`。
  - C. 不维护任务，只在决定时临时找审批人。
- **选定**：B。
- **原因**：A 让普通审批查询依赖业务模块；C 无法提供稳定待办和通知。B 保持“资格规则归业务、任务事实归审批”，且审批列表只读 Approval 数据。
- **最终决定**：F025 在实例锁内调用已注册 policy 的 `authorize_decision()` 做实时资格校验；业务资格源故障时失败关闭。F045 policy 只验证操作者等于快照中的目标用户，F046 policy 调用 Knowledge 严格 owner/manager 只读端口。
- **何时重新考虑**：只有 OpenFGA 提供可订阅、可证明无丢失的权限变更日志，并且待办可由读模型重建时，才评估移除补偿对账；决定前实时资格校验不得移除。

### 决策 5：F045 新增业务申请表，不再投影 ApprovalInstance 为邀请

- **备选**：
  - A. 继续扫描 ApprovalInstance payload 生成待生效邀请。
  - B. Permission 域新增 `ResourceUserInviteRequest`，保存邀请业务快照、审批绑定和授权执行状态。
- **选定**：B。
- **原因**：邀请去重、角色指纹、待生效展示、授权失败和重试都是权限业务；把它们寄存在审批 payload 会让审批 schema 变成权限模型。
- **并发去重**：稳定 `business_key=tenant/resource_type/resource_id/target_user_id`，业务表使用 `(tenant_id,business_key,active_marker)` 唯一约束。阻塞记录 `active_marker=0`；进入 `applied/closed` 后原子改为自身 request ID，允许未来权限被移除后重新邀请。Redis token-safe lock 仅降低争用，数据库唯一约束才是最终保证。
- **何时重新考虑**：若邀请扩展为跨系统、跨数据库长事务，才将该聚合拆为独立服务；只增加新资源类型不构成拆分理由。

### 决策 6：F046 的 durable saga 完全留在 Knowledge

- **备选**：
  - A. F025 Deferred token 继续与 Knowledge step 同步推进。
  - B. 审批通过事件只把 request 置 `queued`；之后 token、step、watchdog、补偿和完成判据全部由 Knowledge 推进。
- **选定**：B。
- **原因**：F025 不需要知道上传解析、rename/move transition、delete purge 或外部存储状态。Knowledge 已有 request/footprint/step 模型，天然是 saga owner。
- **结果**：F046 不再创建 approval execution outbox、不再调用 `complete/fail/resume_deferred_execution()`，业务重试 API 只操作 Knowledge request 和 steps。
- **何时重新考虑**：只有多个业务域共享完全相同的外部副作用步骤和完成判据时，才抽取独立 saga 基础设施；不得把它重新放回审批域。

### 决策 7：两个业务场景未上线，直接替换开发实现

- **备选**：
  - A. 保留旧 task 名、Deferred token 和双读适配窗口。
  - B. 发布前清理所有开发环境 F045/F046 数据，重写未发布 DDL和代码，一次停服上线。
- **选定**：B。
- **原因**：线上 `v2.6.0` 不存在这两个场景；为未发布实现增加迁移层只会扩大代码面和长期维护成本。
- **门禁**：标准发布前只读检查 `scenario_code in (F045,F046)` 的 Approval 数据、新业务表数据和相关 broker 消息，任何非零结果都阻止发布并要求清理非生产数据。
- **何时重新考虑**：一旦任一环境被正式认定为需保留的数据源，就必须重新确认迁移设计；在用户确认的停服、零生产数据前提下不预置兼容代码。

---

## 4. 目标架构与数据流

### 4.1 通用提交与决定

```text
业务入口
  → BusinessApplicationService 校验并写 BusinessRequest
  → ApprovalSubmissionPort.submit_in_uow(session, command)
  → F025 写 instance/tasks/log，BusinessRequest 回填 instance_id
  → 单次提交，post-commit 发送审批待办通知

最后节点、拒绝、撤回或异常取消形成终态
  → F025 锁 instance/tasks
  → 写 approved|rejected|withdrawn|cancelled + action log
  → 写 approval_decision_outbox(PENDING)
  → 单次提交，审批决定立即成立
  → DecisionDeliveryWorker 以 claim token + lease claim 事件
  → 已注册 subscriber.accept(event)
  → 业务域锁 BusinessRequest、校验绑定/指纹、幂等接收
  → subscriber 提交后，F025 标记 delivery DELIVERED
```

consumer 提交成功而 delivery ack 丢失时，重复投递由 `decision_event_id` 幂等返回；交付完成不表示业务完成。

对 `approved` 事件，subscriber 固定按“锁业务申请并提交 `queued` → 以稳定 `business_request_id` 派发业务 task → 返回 delivery worker”执行；只有 broker 接受派发后 F025 才 ack delivered。若业务提交后进程崩溃或 broker 返回不确定，F025 lease 重投事件，subscriber 看到同一 `decision_event_id` 且 request 仍为 `queued` 时幂等补投；业务 worker 再用 request 行锁和 execution token 去重。拒绝、撤回、取消事件不派发业务 task，只提交 `closed` 后返回。

所有能把 F045/F046 instance 置为 `approved/rejected/withdrawn/cancelled` 的入口必须复用同一个终态 UoW；禁止某个管理端、批量或异常入口只改 instance 而漏写 decision outbox。F045/F046 的系统场景固定使用 flow，禁止 pass route；若未来通用 `decision_delivery` 场景显式允许 pass，pass 提交也必须在同一 Gate UoW 生成决定事件。

### 4.2 `ApprovalSubmissionCommand`

| 字段 | 说明 |
|---|---|
| `tenant_id/scenario_code` | 租户与场景 |
| `business_request_type/id` | 业务申请稳定身份 |
| `business_key` | 展示、审计和审批侧幂等键，不承担业务去重 |
| `request_fingerprint` | 业务不可变申请摘要 |
| `title/detail_snapshot/link_snapshot` | 经过业务域脱敏后的审批展示快照 |
| `applicant` | 申请人 ID、名称、部门 |
| `initial_approver_user_ids` | 业务域已解析的初始审批人集合 |
| `completion_mode` | F045/F046 固定 `decision_delivery` |

快照禁止包含 MinIO object name、存储路径、完整授权内部结构、execution token、step、补偿 checkpoint 或可作为业务执行依据的秘密字段。

### 4.3 `ApprovalDecisionEvent`

| 字段 | 说明 |
|---|---|
| `event_id/event_version` | outbox ID；协议版本初始为 `1` |
| `tenant_id/scenario_code` | 路由与租户隔离 |
| `approval_instance_id` | 审批事实 ID |
| `business_request_type/id` | 业务申请身份 |
| `business_key/request_fingerprint` | 绑定校验，不作为执行参数 |
| `decision/decided_at/operator_user_id` | `approved/rejected/withdrawn/cancelled` 及决定元数据 |

同一 instance 只能有一个 `decision_version=1` 终态事件；数据库唯一约束阻止并发重复创建。

---

## 5. F045 目标设计

### 5.1 归属

- `permission/domain/models/resource_user_invite_request.py`：邀请业务聚合。
- `permission/domain/services/resource_user_invite_application_service.py`：门禁、去重、建单、查询和业务重试。
- `permission/domain/services/resource_user_invite_approval_policy.py`：本人确认策略和安全快照。
- `permission/domain/services/resource_user_invite_decision_subscriber.py`：幂等接收决定并派发授权。
- Knowledge/Channel 的授权 owner Service 继续拥有实际授权写行为，通过 `ResourceGrantExecutor` 端口在 composition root 注册。

approval 包内不再存在 `resource_user_invite_service.py`、`resource_user_invite_scenario_handler.py` 或邀请专用 business lock。

### 5.2 业务模型

`resource_user_invite_request` 关键字段：

| 字段 | 说明 |
|---|---|
| `tenant_id/business_key/active_marker` | 活跃邀请唯一约束 |
| `resource_type/resource_id/resource_name` | 被授权资源 |
| `inviter_user_id/target_user_id` | 邀请关系 |
| `relation/model_id/include_children` | 授权命令 |
| `role_snapshot/role_fingerprint` | 权威角色快照及防篡改摘要 |
| `approval_instance_id` | 唯一审批绑定 |
| `decision_event_id` | 已接收的审批事件，唯一且可空 |
| `execution_state` | `awaiting_approval/queued/applying/applied/failed/closed` |
| `error_summary/result_snapshot` | 业务结果，不写 ApprovalException |

### 5.3 状态流

```text
awaiting_approval
  ├─ approved event → queued → applying → applied
  │                              └──────→ failed → retry → applying
  └─ rejected|withdrawn|cancelled event → closed
```

- `applied/closed` 将 `active_marker` 从 `0` 改为 request ID并释放邀请槽位。
- `failed` 仍占用槽位，只能重试原请求，不能重新审批。
- 授权执行前重读资源、申请人/目标用户、角色指纹和已有授权；已按同一 request 生效时通过权威读后校验幂等确认 `applied`。
- 待生效列表读取业务表并批量组合 F025 只读审批状态，不扫描 Approval payload。

---

## 6. F046 目标设计

### 6.1 归属

- policy/setting/upload stage/change request/footprint/execution step 全部留在 Knowledge。
- F046 `ApprovalScenarioPolicy` 留在 Knowledge，只提供初始审批人解析、最终资格校验和场景动作策略。
- 文件执行、parser ack、watchdog、补偿、stage/delete 清理由 `worker/knowledge/file_change_tasks.py` 承载并路由到 `knowledge_celery`。
- F025 只持有审批快照和 decision outbox，不构造 Knowledge handler、不查询 Knowledge request、不渲染业务执行状态。

### 6.2 状态流

`KnowledgeSpaceFileChangeExecutionState` 调整为：

```text
not_started
  ├─ approved event → queued → applying → applied
  │                              ├──────→ failed → retry → queued
  │                              └──────→ compensating → failed|applied
  └─ rejected|withdrawn|cancelled event → closed
```

`approval_instance.status` 在 approved event 后始终是 `approved`；Knowledge 的任何 transition、解析失败或 purge 失败都不回写 F025。

### 6.3 动态审批人

1. 创建业务申请时，Knowledge 严格解析当前 owner/manager，将初始集合传给 submission port。
2. owner/manager 权限变更成功后，Permission 事件调用 Knowledge resolver，再调用 F025 `reconcile_assignees(instance_id,user_ids)`。
3. Knowledge 文件待审页按当前页批量发现差异并触发有界对账。
4. Knowledge Beat 按 tenant/space keyset 补偿漏事件。
5. F025 在实例锁内取消失效 pending task、为新增用户创建 task并维护 `approver_empty`；不调用 Knowledge 查询候选。
6. 决定前通过 Knowledge policy 做实时资格校验，故障失败关闭。

### 6.4 文件执行不变量

原 F046 的以下业务设计保留，但执行终态全部落在 Knowledge：

- 上传审批前只保存 opaque stage，不创建正式 `KnowledgeFile`。
- footprint 继续防止同资源、祖先和子树并发变更。
- rename/move 使用 durable OLD_VIEW/NEW_VIEW transition 和权威读后校验。
- delete 使用 prepare、逻辑 cutover、deletion guard、外部 purge 和权威验证。
- 上传正式注册、FGA 写入和解析调度由 Knowledge step推进；解析与发布状态不回写审批。
- 失败重试复用原 `approval_instance_id` 和业务申请，只生成新的 Knowledge execution token。

---

## 7. F025 目标职责与代码调整

### 7.1 保留

- ApprovalGate 路由、流程、节点、实例、任务、日志、审批异常和审批通知。
- task/instance 决定 UoW、OR/AND、多节点、撤回、取消和动态任务对账能力。
- 既有场景的 `approval_outbox → handler.on_approved()` 执行路径及全部状态语义。

### 7.2 新增

- `approval/domain/ports/scenario_policy.py`
- `approval/domain/ports/decision_subscriber.py`
- `approval/domain/services/approval_submission_service.py`
- `approval/domain/services/approval_decision_delivery_service.py`
- `approval/domain/models/approval_decision_outbox.py`
- `worker/approval/decision_delivery_tasks.py`
- 顶层 composition root 的 policy/subscriber/executor 注册。

### 7.3 删除耦合

- `approval_runtime_handler_factory.py` 删除 F045/F046 业务 handler 分支。
- `approval_center_service.py` 删除 F046 `_prepare_dynamic_tasks()` 和业务状态 projection。
- `approval_exception_service.py` 删除 F046 Deferred resume 专用分支。
- `approval_outbox_service.py` 删除仅为 F046 增加的 deferred heartbeat/complete/fail/resume；若无其他消费者，`processing/deferred` 状态及三个 token 字段一并从未发布 DDL 中移除。
- `approval_uow.py` 删除 F046 cutover/purge 的 caller-owned完成适配，只保留通用 submission/decision UoW。
- `worker/approval/file_change_tasks.py` 删除，业务任务迁到 Knowledge。
- 审批中心前端不再从 runtime handler拉取 F046 业务 projection；只显示审批快照和审批终态。

### 7.4 关键模块职责

| 模块 / 文件 | 做什么 | 明确不做什么 |
|---|---|---|
| `approval/domain/services/approval_submission_service.py` | 校验场景策略并在 caller-owned session 中创建 instance/task/log | 不创建业务申请，不提交 caller 的事务，不调用业务 executor |
| `approval/domain/services/approval_decision_delivery_service.py` | claim/lease/retry/ack 决定事件并调用注册 subscriber | 不解释业务 payload，不等待业务执行完成，不修改审批终态 |
| `approval/domain/ports/*` | 定义 submission policy、决定消费和动态任务对账的版本化协议 | 不 import 任何业务实现，不保存进程外业务状态 |
| `bisheng/bootstrap/approval_scenarios.py` | 构造并注册 F045/F046 policy、subscriber 和资源 executor | 不包含业务规则，不读写数据库，不吞掉注册失败 |
| Permission F045 services/repositories | 拥有邀请、去重、决定接收、授权派发、失败和重试 | 不写 Approval ORM/Repository，不从审批快照重建邀请 |
| Knowledge F046 services/repositories/workers | 拥有文件申请、动态资格、saga、补偿和业务通知 | 不推进 Approval execution 状态，不调用 Deferred completion |

---

## 8. 数据结构与数据库

### 8.1 `approval_decision_outbox`

| 字段 | 说明 |
|---|---|
| `id/tenant_id/instance_id` | 事件与审批绑定 |
| `scenario_code/subscriber_key` | 订阅路由 |
| `business_request_type/id` | 业务申请身份 |
| `business_key/request_fingerprint` | 绑定校验 |
| `decision/decision_version/decided_at/operator_user_id` | 决定事实 |
| `status` | `pending/processing/delivered/failed` |
| `claim_token/claimed_at/claim_deadline` | worker 所有权和崩溃后的 lease 重领 |
| `retry_count/error_summary/next_retry_at` | 交付恢复；临时失败回到 `pending` 并设置下次重试时间 |
| `failure_kind` | `retryable/permanent`；永久绑定错误进入 `failed`，只允许运维明确重放 |

唯一约束：`(tenant_id,instance_id,decision_version)`。

claim 必须同时匹配 `id + claim_token` 才能 ack；未过 `claim_deadline` 的 `processing` 不得并行重领，过期后可以新 token 重领。subscriber 不存在、协议版本不匹配、租户/绑定/指纹不一致属于 permanent failure；进程、broker、数据库暂时不可用属于 retryable failure。两类失败都保留原审批终态，且不能创建第二个决定事件。

### 8.2 未发布 DDL 处理

- 新建 F025 decision outbox 和 F045 resource invite request 表。
- F046 migration 直接调整为 Knowledge 自有状态；移除对 `approval_outbox` deferred 字段的变更。
- F045/F046 当前开发表没有生产数据，不写 backfill、双写或兼容列。
- release contract 把 `ResourceUserInviteRequest` 登记为 F045 所有，不再声明“ApprovalInstance/Task 是邀请事实”。

---

## 9. API、页面与通知

- 审批中心 API 路由不变；F045/F046 决定仍走 F025 task/instance 决定端口。
- F045 待生效邀请查询和业务重试归 Permission/资源授权 API。
- F046 状态、retry、cleanup、compensation 归 Knowledge API。
- 审批中心只显示 `pending/approved/rejected/withdrawn/cancelled/exception` 及安全业务快照。
- F045/F046 业务页面分别显示 `queued/applying/applied/failed/closed`，并批量组合审批状态。
- F025 发送审批待办和决定通知；Permission 发送授权生效/失败通知；Knowledge 发送文件执行成功/失败通知。

---

## 10. 对外契约与依赖

### 10.1 Outgoing

| 契约 | 形式 / 关键字段 | 消费者 | 变更风险 |
|---|---|---|---|
| `ApprovalSubmissionPort.submit_in_uow(session, command)` | Python async port；返回 `instance_id/task_ids/post_commit_effects`，不提交 session | Permission F045、Knowledge F046 | 擅自提交会破坏业务 request 与审批绑定原子性；删字段必须提升协议版本 |
| `ApprovalTaskReconciliationPort.reconcile_assignees(...)` | Python async port；`tenant_id/instance_id/approver_user_ids/reason` | Knowledge 权限事件、页面惰性对账、Beat | 不在 instance 锁内写 task 会产生双待办或漏通知 |
| `ApprovalDecisionSubscriber.accept(event)` | 版本化 Python async subscriber；事件格式见 §4.3 | F045/F046 business consumer | event ID、tenant、绑定或指纹语义变化会破坏幂等和防串单 |
| `approval_decision_outbox` | 持久化交付协议；状态与 lease 见 §8.1 | decision delivery worker、运维恢复 | 不能用 broker task ID 代替；不能把 delivered 当作业务完成 |
| 既有 `/api/v1/approval/*` 决定接口 | HTTP；路径不变，终态响应只表达审批结果 | Client 审批中心、Knowledge 文件页 | 不得重新拼入 F045/F046 业务执行状态，否则恢复耦合 |

### 10.2 Incoming

| 依赖 | 提供方 | 风险点 / 失效策略 |
|---|---|---|
| caller-owned async DB session、行锁和唯一约束 | database/core | MySQL/DM8 行锁与约束必须等价；禁止数据库专属 upsert/partial index |
| `PermissionService.check/authorize` 与 strict OpenFGA owner/manager 解析 | Permission/OpenFGA | 决定资格解析失败必须 fail-closed；授权副作用后 ack 丢失要权威读后校验 |
| Knowledge request/footprint/step 与 OLD_VIEW/NEW_VIEW projection | F046 Knowledge | 字段、token 或完成判据变化只在 Knowledge 内演进，不能要求 F025 同步状态 |
| Celery tenant headers 与 ContextVar 恢复 | worker runtime | 所有交付/业务任务必须显式正整数 `tenant_id`，任务结束在 `finally` 恢复上下文 |
| notification service | F025、Permission、Knowledge | 审批通知和业务通知不可互相代发；通知失败不得伪造事实状态 |

---

## 11. 测试与架构门禁

### 11.1 自动化测试

- submission UoW：业务 request、instance、task、log、绑定同提交或同回滚。
- decision UoW：终态和 decision outbox 原子；并发双决定只有一个事件。
- delivery：失败重试、consumer commit 后 ack 丢失、重复/乱序事件、租户和指纹不匹配。
- F045：业务表去重、本人确认、管理员不可代办、角色防篡改、授权幂等、失败复用原审批重试、待生效列表不扫 Approval payload。
- F046：动态审批人对账、文件四类动作、业务失败不改审批、Knowledge token重试、发布门禁和补偿。
- 回归：菜单、频道订阅、知识空间加入的原 outbox 状态机和 handler行为不变。

### 11.2 静态架构检查

- `bisheng/approval/**` 禁止 import：
  - `bisheng.permission.domain.services.resource_authorization_service`
  - `bisheng.channel.domain.services.channel_authorization_service`
  - `bisheng.knowledge.domain.services.*file_change*`
- `worker/approval/**` 禁止注册 F046 文件执行/补偿任务。
- Permission/Knowledge 禁止调用 Approval Repository 或修改 Approval ORM。
- 只有 composition root 可以同时 import approval port 和业务 policy/subscriber。

### 11.3 E2E

- F045 创建邀请、本人通过、授权生效；授权失败后业务重试且审批保持 approved。
- F046 四类动作通过后分别执行；执行失败只在文件页出现并可恢复。
- 审批中心与业务页并发决定只生效一次。
- 业务 consumer停机时审批仍可完成，恢复后决定继续交付。
- 其他三个审批场景完整回归。

### 11.4 手动验证与可观测

- 后端聚焦测试：`cd src/backend && uv run pytest test/approval/ test/permission/ test/knowledge/ -k 'decision_delivery or resource_user_invite or file_change'`。
- 静态边界：仓库根目录执行 `bash scripts/arch-guard.sh`，并执行 F047 专用 import boundary 测试。
- Client：登录普通用户访问 `/workspace`，分别从知识空间/频道授权入口创建个人邀请，在审批中心由被邀请人处理；管理员账号代办必须失败。
- F046：在 `/workspace` 的知识空间文件页创建 upload/rename/move/delete 申请；审批中心只显示审批终态，文件页显示 `queued/applying/applied/failed/closed`。
- 关键结构化日志统一带 `tenant_id/approval_instance_id/business_request_id/event_id`；交付指标至少包含 pending 数、lease reclaim 数、retry 数、permanent failure 数和最老未交付时长，业务执行指标由各业务域独立记录。
- 故障演练：暂停 decision delivery worker，完成一条审批后确认 instance 已终态且 outbox 积压；恢复 worker 后确认幂等交付。再在 subscriber commit 后、F025 ack 前注入失败，确认只接受一次业务事件。

---

## 12. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | subscriber 提交成功不等于 F025 已 ack；该窗口必然会重复投递 | 重复授权、重复文件 mutation，或错误地把 outbox 标成永久失败 | `approval_decision_delivery_service.py` claim/ack + 两个业务 subscriber 的 `decision_event_id` 行锁幂等 |
| 2 | `processing` 不是永久所有权，必须有 claim token 和 lease | worker 崩溃后事件永远卡住，或过早重领导致并发 consumer | `approval_decision_outbox.py`、decision delivery repository/service |
| 3 | F045 本人确认 policy 必须先于通用管理员代办能力执行 | tenant admin 会绕过本人确认，直接让邀请进入授权执行 | `approval_center_service.py::_decide_in_uow()` 调 policy 的顺序 + F045 policy |
| 4 | F046 权限变化只负责计算当前集合，任何业务 worker 都不能直接改 ApprovalTask | Approval 与 Knowledge 出现双写，锁序分裂后生成重复/幽灵待办 | `ApprovalTaskReconciliationPort`、Knowledge resolver、Permission dispatcher |
| 5 | decision outbox delivered 只表示业务域已接收决定，不表示授权或文件变更成功 | 审批中心重新展示 `executed/execute_failed`，把本次解耦恢复成旧模型 | F025 查询投影、F045/F046 业务状态 API |
| 6 | 本次可以改写 F045/F046 未发布 DDL，但不能改写已上线 v2.6.0 migration 历史 | 生产 Alembic 图与代码模型不一致，或回滚到不认识新表的版本 | `v2_6_0_f046_knowledge_space_file_change_approval.py`、§13 发布门禁 |

---

## 13. 发布与回滚

### 13.1 停服发布

1. 停 API、Beat 和全部 worker。
2. 确认线上版本为 `v2.6.0`，并执行只读门禁：F045/F046 场景、实例、开发业务表和相关 broker 消息均为零。
3. 执行修订后的未发布 DDL，部署同一版本 API/worker/Beat。
4. 先启动 worker并验证 policy/subscriber 注册完整，再启动 API 和 Beat。
5. 分别创建一条 F045/F046 smoke request，确认审批状态与业务状态分离。

不需要旧 F045/F046 task adapter、Deferred token迁移、双读、双写或版本化队列。

### 13.2 回滚

- 回滚同样停服；关闭两个新场景入口后再回退应用。
- 不对已经产生 F045/F046 数据的环境直接回滚到不认识这些场景的 `v2.6.0`；先修复或完成当前业务，再采用数据库快照恢复或重新前滚。
- broker 消息不是事实源；恢复以 decision outbox 和业务 request 状态为准。

---

## 14. 后续改进 / 暂不实施

- 暂不把既有菜单、频道订阅、知识空间加入迁移到 decision delivery；这些场景已经上线，迁移需要独立兼容与数据方案，超出本次零存量前提。
- 暂不引入 Kafka 或通用事件平台；两类决定量级和同库恢复需求由数据库 outbox 足够满足。只有数据库轮询成为经指标证明的瓶颈时才重新评估。
- 暂不把 Knowledge saga 抽成通用框架；四类文件动作共享的是 Knowledge 不变量，不是跨域公共完成判据，过早抽象会把业务语义重新泄漏到基础设施。
- 暂不支持滚动混部；用户已确认停服升级。未来若部署要求变为滚动升级，必须重新设计协议版本、worker 路由隔离和双版本观察窗口。

---

## 15. 设计覆盖关系

本设计确认后，以下旧设计口径被覆盖：

- F045 design 中“ApprovalInstance/Task 是唯一邀请事实源”“approval handler直接执行授权”。
- F046 design 中“F025 Deferred 表示文件业务执行”“Knowledge coordinator 完成/失败 approval outbox/instance”。
- approval-module skill 中 F045/F046 handler、Deferred、业务 worker 和通知矩阵描述。

实施时必须同步更新 F045/F046 `design.md` 的相关章节、`release-contract.md` 和 `approval-module/SKILL.md`，不能让多个设计真相继续冲突。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-12 | 初版，仅覆盖 F046且包含存量兼容 | 初始范围 |
| 2026-08-12 | 重写为 F045/F046 统一解耦，删除未上线场景兼容层 | 用户确认两个新场景均未上线，要求高内聚低耦合重新实现 |
| 2026-08-13 | 设计评审补齐 decision lease、终态 UoW、装配入口、依赖风险、已知坑和验证门禁 | `/sdd-review design` 接手测试与 Constitution Check |
