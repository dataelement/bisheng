---
name: approval-module
description: >-
  BiSheng 审批模块（审批中心 F025）的架构与代码参考。
  覆盖多场景引擎、多节点流转、legacy outbox、decision delivery、业务域执行、站内信与异常处理。
  迭代审批功能或修复审批相关 Bug 前先读本 skill，可直接定位架构与代码锚点，无需全仓搜索。
  TRIGGER when: 用户要改动/修复"审批""审批中心""approval"相关功能（菜单权限申请、频道订阅审批、
  知识空间加入审批、个人邀请确认、文件变更审核、审批流程/节点配置、决定交付、outbox/Celery 执行），
  或排查审批通过后业务未生效、审批人看不到任务、站内信未发等问题。
---

# 审批模块（审批中心 F025）

## ⚠️ 维护契约（修改代码后必读）

**本 skill 是审批模块的唯一权威参考，必须与代码永远一致。**
当你改动以下任意一项时，**同一个改动里必须同步更新本文件对应章节**，否则视为改动未完成：

- 主流程或 completion mode（legacy `ApprovalGate`、`ApprovalSubmissionService`、终态决定交付、节点流转）→ 更新 [§2 架构与主流程](#2-架构与主流程)
- 新增/删除/重命名服务文件或关键方法 → 更新 [§3 代码锚点](#3-代码锚点)
- 新增/删除预置场景或改动其触发入口、legacy handler、policy/subscriber → 更新 [§4 预置场景](#4-预置场景)
- 数据库表/状态枚举变化 → 更新 [§5 数据库表](#5-数据库表)
- API 路由增删改 → 更新 [§7 API 列表](#7-api-列表)
- 站内信触发时机/接收人变化 → 更新 [§8 站内信通知矩阵](#8-站内信通知矩阵)
- Celery 队列/路由变化 → 更新 [§6 异步交付与 Celery](#6-异步交付与-celery)

> 自检：改完代码后问自己"本 skill 里有没有哪句话现在变成假的了？"——有就改它。

---

## 1. 概述

审批中心是一套**通用多场景审批引擎**。五个场景共用场景、路由、流程、节点、实例、任务和审批时间线，业务完成方式分为两类：

| completion mode | 场景 | 审批终态后的动作 |
|---|---|---|
| legacy handler/outbox | 菜单申请、频道订阅、知识空间加入 | 写 `approval_outbox`，默认队列调用三个既有 handler；业务失败可形成 `execute_failed` |
| decision delivery | F045 个人邀请、F046 文件变更 | 写 `approval_decision_outbox`，业务 subscriber 接收决定后推进自有 request/saga；业务失败不形成 Approval 异常 |

**核心原则：审批事实与业务执行事实分属各自的业务域。**菜单、频道订阅、知识空间加入这三个已上线场景仍在通过后写
`approval_outbox(PENDING)`，由三个既有 handler 异步执行业务。

F045/F046 走 `decision_delivery`：F025 在审批终态同一 UoW 只写
`approval_decision_outbox`，业务域 subscriber 幂等接收决定后推进自己的 request/saga；业务成功或失败都不回写审批终态。

> ⚠️ **已废弃**：另有一套独立的旧系统——部门知识空间文件上传审批（`approval_request` 表），由 `approval_service.py` + `message_handler.py` 承载，路由在 `/approval/requests/*` 与 `/approval/department-knowledge-space/*`。该功能**已废弃**，仅为兼容存量保留，**不要在其上新增功能**；新需求一律走审批中心引擎。改审批中心时也不要误改它。

---

## 2. 架构与主流程

### 2.1 两类提交入口

```text
legacy 三场景
业务入口 → ApprovalGate.request_or_pass()
         → route_type=pass: instance approved + ApprovalOutbox
         → route_type=flow: instance pending + 首节点 tasks
         → route missing / approver empty: Approval exception

F045/F046
业务域 caller-owned transaction
  → 先写业务 request/stage/footprint
  → ApprovalSubmissionPort.submit_in_uow(session, command)
  → policy 校验 + instance/tasks/log
  → 回填 approval_instance_id
  → 外层一次 commit；post-commit effects 只在提交后运行
```

F045/F046 的 policy 禁止 `pass`，也不创建 `ApprovalOutbox`。场景缺失、关闭、审批人为空或固定流程不匹配时，业务申请与审批 bundle 同事务回滚或形成通用提交异常；不得降级为直接执行业务。

### 2.2 任务决定与多节点流转

`ApprovalCenterService.decide_task()` 与 `decide_instance_for_current_approver()` 共用决定 UoW：

- OR 节点：任一人通过，同节点其余 pending task 置 skipped。
- AND 节点：同节点全部通过才进入下一节点。
- 有下一节点：解析审批人、创建 task；为空则形成 `approver_empty`。
- 最后节点通过：instance 进入 `approved`；legacy 场景同事务写 `ApprovalOutbox`，F045/F046 同事务写唯一 `ApprovalDecisionOutbox`。
- 拒绝、撤回、取消：审批终态与 F045/F046 决定事件同事务落盘。

固定锁序以 instance 为首，再锁当前节点 tasks 及 open exception/outbox；提交后才派发 Celery、发通知或执行 legacy terminal hook。

### 2.3 decision delivery

```text
Approval terminal UoW
  → ApprovalDecisionOutbox(pending, unique terminal event)
  → 默认 celery 队列 deliver_approval_decision
  → registry subscriber
  → subscriber 先提交业务 queued/closed + decision_event_id
  → approved 再派业务 worker；非 approved 再做业务清理
  → delivery 独立事务 ack delivered / retryable / permanent
```

交付成功只代表业务域已接收审批事实；broker task ID、subscriber 返回或审批 `approved` 都不是业务成功证据。F045/F046 的业务 `failed`、重试、补偿与通知只写业务表，不把 Approval instance 改成 `executing/executed/execute_failed`，也不创建 `execute_failed` exception。

**资源个人用户邀请是强制本人确认特例**：Permission 域先写
`resource_user_invite_request(awaiting_approval)`，再在 caller-owned UoW 经 `ApprovalSubmissionPort` 创建审批 bundle。
`ResourceUserInviteApprovalPolicy` 强制唯一被邀请人 OR 审批且禁止管理员代办；
`ResourceUserInviteDecisionSubscriber` 锁定权威业务申请并校验 tenant/instance/fingerprint。approved 先提交
`queued + decision_event_id`再派发业务任务，派发临时失败保留 queued 供同事件重投；其他终态关闭请求并释放 active marker。

**知识空间文件变更也由 Knowledge 消费决定事实**：`KnowledgeSpaceFileChangeApprovalPolicy` 强制初始审批人
精确等于当前 owner/manager 集合，并在决定时持锁重读 request 绑定、实时资格与 tenant ContextVar；OpenFGA
不可用时 fail-closed。`KnowledgeSpaceFileChangeDecisionSubscriber` 只锁 Knowledge request，approved 先提交
`queued + decision_event_id` 再派发 Knowledge 任务；其他终态先提交 `closed + decision_event_id` 再清理暂存上传。
`result_snapshot` 记录派发/清理确认状态，同一事件可补派或补清，成功后不重复副作用。

**异常实例也留痕**：legacy Gate 与 submission service 的正常/异常提交都写审批 action log；通知失败不改变审批事实。

**动态审批人是“业务域解析资格 + Approval 物化待办”**：业务域在权限事件、页面惰性校验或补偿任务中计算
当前审批人 ID 集合，再调用 `ApprovalDynamicAssigneeService.reconcile_assignees()`。该 API 校验 tenant ContextVar，
固定按 `instance → tasks → open exception/outbox` 加锁；失效审批人的 pending task 置 cancelled，新增审批人新建
pending task，并维护 `approver_empty`，历史终态 task 永不复活。审批列表/详情只读 Approval 自有表和安全快照，
不得在 Approval 查询中发现 Knowledge 业务候选或查询业务状态投影，响应也不暴露
`business_status_projection`；决定时仍由已注册 policy 实时校验资格并在依赖故障时 fail-closed。
Permission 的 `FileChangeApproverReconcileDispatcher` 只编排 Knowledge 公共 resolver 与 F025 application port：
显式 tenant 必须与 ContextVar 一致，Knowledge 返回 `instance_id + approver_user_ids` DTO 后，F025 只接收
`tenant_id/instance_id/approver_user_ids/reason`。权限写成功事件、Knowledge 页面惰性校验和 Beat 均复用该入口；
resolver/OpenFGA 故障必须传播，绝不能伪造成空审批人集合，也不能回退到 `worker/approval` 或 Approval ORM 查询。

`decide_instance_for_current_approver()` 是文件页单条/批量审批的权威入口，endpoint 不得直接改 task。F046 policy 在管理员旁路或历史 task 判断之前实时校验 owner/manager；资格依赖故障 fail-closed。

---

## 3. 代码锚点

> 路径相对 `src/backend/bisheng/`。这些是定位问题的第一入口。

### 后端服务

| 文件 | 职责 | 关键方法 |
|------|------|---------|
| `approval/domain/services/approval_gate.py` | 三个 legacy 场景入口：路由匹配、pass/pending/exception 分流和 `ApprovalOutbox` post-commit 派发 | `request_or_pass()`、`_create_exception_result()` |
| `approval/domain/services/approval_center_service.py` | Approval-only 列表/详情、task/instance 决策、撤回、多节点流转；按 completion mode 写 legacy outbox 或 decision event | `list_my_tasks()`、`get_task_detail()`、`get_instance_detail()`、`decide_task()`、`decide_instance_for_current_approver()`、`withdraw_instance()` |
| `approval/domain/services/approval_dynamic_assignee_service.py` | 接受业务域预解析 ID，在实例锁内对账动态审批人、维护 approver_empty、生成新增任务通知 effect | `reconcile_assignees()`、`resolve_and_reconcile_in_uow()`、`reconcile_resolved_in_uow()` |
| `approval/domain/services/approval_exception_service.py` | 管理端处理 route_missing/approver_empty 及三个 legacy 场景的 execute_failed；F045/F046 业务失败不进入此处 | `retry_exception_api()`、`cancel_exception_api()`、`assign_approvers()`、`skip_node()` |
| `approval/domain/services/approval_outbox_service.py` | 仅执行/重试三个 legacy handler outbox，并原子记录 success/failed 与 legacy execute_failed | `execute_outbox()`、`retry_outbox()` |
| `approval/domain/services/approval_scenario_admin_service.py` | 管理端：场景/分支/流程/节点配置、异常列表 | — |
| `approval/domain/services/approver_resolver.py` | 解析审批人来源 `direct_user` / `department_admin` / `tenant_admin` | `resolve_approvers_from_sources()` |
| `approval/domain/services/approval_registry.py` | 五场景目录与两类 completion adapter 注册；启动期校验 protocol/event/completion mode 后 freeze | `with_default_presets()`、`register_handler()`、`register_policy()`、`register_subscriber()`、`freeze_decision_delivery()` |
| `bootstrap/approval_scenarios.py` | 唯一 composition root；完成五场景 adapter 与 Knowledge/Channel grant executor 装配，完整性校验后 freeze | `bootstrap_approval_scenarios()`、`get_approval_scenario_registry()`、`get_resource_grant_executor_registry()` |
| `approval/domain/services/approval_submission_service.py` | F047 decision-delivery 场景的 caller-owned 建单；并通过 public port 提供 tenant-bound 场景行锁 guard，保护 F045 资源创建/direct 副作用前的 18106 门禁 | `submit_in_uow()`、`scenario_guard()` |
| `approval/domain/services/approval_decision_delivery_service.py` | F047 终态决定的可靠交付；独立事务 claim 后调用 subscriber，再独立事务按 token ack；绑定/协议错误 permanent，临时故障 retryable，永不回退审批终态 | `deliver_next()` |
| `worker/approval/decision_delivery_tasks.py` | F047 默认队列单事件交付与有界 recoverable coordinator；tenant 仅取显式 header 并 finally 恢复 ContextVar，broker task ID 只作派发证据 | `deliver_approval_decision`、`coordinate_approval_decision_delivery` |
| `approval/domain/services/approval_runtime_handler_factory.py` | 只为菜单、频道订阅、知识空间加入三个 legacy outbox 构造 handler | `build_runtime_handler(scenario_code)` |
| `approval/domain/services/approval_notification_service.py` | 站内信统一封装 | `notify_user()` / `notify_users()` / `notify_admins()` |
| `approval/domain/ports/scenario_policy.py` | F047 决定交付场景的版本化 submission command/result、决定前 policy context 和 caller-owned submission port；submission 与 Center 终态决定都已接入 policy | `ApprovalScenarioPolicy`、`ApprovalSubmissionPort` |
| `approval/domain/ports/decision_subscriber.py` | F047 版本化终态决定事件、业务 subscriber 协议及 permanent/retryable 消费失败契约；已接 registry 与 delivery service | `ApprovalDecisionEvent`、`ApprovalDecisionSubscriber`、`ApprovalDecisionPermanentError`、`ApprovalDecisionRetryableError` |
| `approval/domain/ports/approval_status_reader.py` + `approval/domain/services/approval_status_read_service.py` | 只向业务域批量暴露不可变 `instance_id/status`，显式 tenant ContextVar 校验；不暴露 payload、任务或 Approval ORM | `ApprovalStatusReadPort`、`ApprovalStatusSnapshot`、`ApprovalStatusReadService.get_statuses()` |
| `approval/domain/models/approval_decision_outbox.py` | F047 决定交付模型；Center 已在 F045/F046 终态 UoW 写唯一事件，delivery service 按 lease/token 投递 | `ApprovalDecisionOutboxStatus`、`ApprovalDecisionFailureKind` |
| `approval/domain/repositories/approval_decision_outbox_repository.py` | caller-owned 决定事件 claim/ack/retry/fail 原语；强制 tenant ContextVar 一致，MySQL 用 skip-locked、DM8 用 portable row lock、全方言以 claim token + 条件更新兜底 | `claim_next()`、`mark_delivered()`、`mark_retryable_failure()`、`mark_permanent_failure()`、`list_recoverable()` |
| `permission/domain/ports/resource_grant_executor.py` | F047 F045 稳定授权命令、不可变快照、资源 owner executor 与权威读后校验结果；不 import Knowledge/Channel 实现 | `ResourceGrantCommand`、`ResourceGrantExecutor`、`ResourceGrantVerificationResult` |
| `permission/domain/services/resource_grant_executor_registry.py` | F047 F045 按 resource type 注册和分派授权 owner；composition root 完整注册后 freeze，重复、缺失和未知类型均 fail-closed | `register()`、`freeze()`、`execute()`、`verify()` |
| `permission/domain/models/resource_user_invite_request.py` | F047 F045 邀请业务事实模型；Application Service/Repository/policy/subscriber/授权 worker 均以此为事实源 | `ResourceUserInviteExecutionState` |
| `permission/domain/services/resource_user_invite_application_service.py` | F047 F045 的 Permission-owned 建单/跨邀请人去重/审批绑定；待生效查询只读业务表并经 Approval public read port 批量组合状态；仅 approved+failed 原请求可稳定重派；业务授权终态通知按 execution token 在业务 request 内持久去重，发送失败不预先标成功 | `scenario_guard()`、`request_invite()`、`list_pending_invites()`、`list_pending_invite_items()`、`retry_failed_invite()`、`ResourceUserInviteBusinessNotificationService.notify_execution_result()` |
| `permission/domain/services/resource_authorization_service.py` | F045 知识空间 owner 适配；新个人用户只建 Permission 业务申请，部门/组/已有用户 direct 语义不变；executor 严格重读并在 tuple 权威可见后提交 binding，失败补偿不留半状态 | `ResourceAuthorizationService.authorize()`、`KnowledgeSpaceResourceGrantExecutor` |
| `permission/domain/services/file_change_approver_reconcile_dispatcher.py` | F046 权限变化后的外部对账编排；只消费 Knowledge 预解析 DTO 并调用 F025 application reconcile port，严格 tenant ContextVar、传播 resolver 故障 | `FileChangeApproverReconcileDispatcher.reconcile_space()`、`dispatch_file_change_approver_reconcile_for_permission_change()` |
| `permission/domain/repositories/resource_user_invite_request_repository.py` | caller-owned F045 业务事实读写；唯一约束为最终去重，active marker=0 表示占槽；业务 retry 按 tenant+request ID 加行锁 | `get_active()`、`get_by_id()`、`add_and_flush()`、`bind_approval_instance()`、`list_pending_for_resource()` |
| `permission/domain/ports/resource_user_invite_dispatcher.py` | Permission-owned 稳定 business request 派发协议，Application Service 与 decision subscriber 均不反向依赖 worker/彼此实现 | `ResourceUserInviteDispatcher.dispatch()` |
| `permission/domain/services/resource_user_invite_lock.py` | F047 F045 的 Permission 域降争用锁；业务键跨邀请人稳定，复用核心 token-safe Redis lease，数据库唯一约束仍是最终事实源 | `build_resource_user_invite_business_key()`、`resource_user_invite_lock()` |
| `permission/domain/services/resource_user_invite_approval_policy.py` | F045 提交和决定前的权威校验；唯一被邀请人 OR，绑定不匹配或 tenant 上下文缺失时 fail-closed | `validate_submission()`、`authorize_decision()` |
| `permission/domain/services/resource_user_invite_decision_subscriber.py` | F045 幂等决定消费；approved 先持久化 queued/event 再派发，拒绝/撤回/取消只关闭 Permission 请求 | `accept()` |
| `worker/permission/resource_user_invite_tasks.py` | F045 默认队列授权 worker；显式 tenant header，稳定 execution token 与 CAS，execute 后以资源 owner 权威读后校验决定 applied/failed；业务状态提交后只调用 Permission notifier，日志只记录关联 ID、异常类型或受控错误码；retry 派发仅证明 broker 接受 | `execute_resource_user_invite`、`CeleryResourceUserInviteDispatcher.dispatch()` |
| `channel/domain/services/channel_authorization_service.py` | F045 频道 owner 适配；新增个人用户只经 Permission Application Service 建单，executor 实时重读频道/租户/授权边界并通过 `PermissionService.authorize` 唯一写入、随后权威 verify | `ChannelAuthorizationService.authorize_channel()`、`ChannelResourceGrantExecutor` |
| `approval/domain/services/user_menu_access_service.py` | 菜单授权增删查，含父级菜单依赖自动补全 | `grant_menu_access()`、`revoke_menu_access()`、`ensure_application_allowed()` |
| `approval/domain/services/approval_service.py` + `message_handler.py` | **旧系统（已废弃）**：部门知识空间文件上传审批（`approval_request` 表），与审批中心独立，仅兼容存量、勿新增功能 | `ApprovalService.decide_request()` |
| `worker/approval/tasks.py` | Celery 任务（走默认 `celery` 队列） | `execute_approval_outbox`、`retry_approval_outbox` |
| `worker/knowledge/file_change_tasks.py` | F046 Knowledge-owned coordinate/step/ack/watchdog/补偿/cleanup/动态审批人任务；显式 tenant header，统一 `knowledge_celery` | `CeleryKnowledgeSpaceFileChangeDispatcher`、`coordinate_file_change_execution`、`execute_file_change_step`、`watchdog_all_file_change_executions`、`compensate_all_file_change_execution_steps`、`cleanup_all_file_change_residue`、`reconcile_all_file_change_approvers` |
| `knowledge/domain/services/knowledge_space_file_change_approval_policy.py` | F046 Knowledge-owned 提交/决定 policy；严格 owner/manager 集合、实时资格与 tenant/instance/fingerprint 绑定 fail-closed | `validate_submission()`、`authorize_decision()` |
| `knowledge/domain/services/knowledge_space_file_change_approver_resolver.py` | F046 owner/manager 权威解析与 Permission 对账公共 DTO/port；OpenFGA/tenant/候选读取失败统一 fail-closed | `resolve_approver_user_ids()`、`resolve_reconciliation_targets()` |
| `knowledge/domain/services/knowledge_space_file_change_decision_subscriber.py` | F046 幂等决定消费；先持久化 queued/closed 与 event，再补派业务任务或补做终态清理 | `accept()` |
| `knowledge/domain/services/knowledge_space_file_change_terminal_cleanup_service.py` | F046 独立稳定终态清理 owner；校验 request/stage 绑定并持久化 pending/success，只依赖 Knowledge 事实 | `cleanup()` |
| `knowledge/domain/services/knowledge_space_file_change_service.py` | F046 Knowledge-owned 建单入口；权限/冲突校验后，在 caller-owned UoW 内写 request/stage/footprint，并以 canonical business key/fingerprint 调 Approval public submission port | `request_change()`、`_create_pending_bundle_in_uow()` |
| `knowledge/domain/services/knowledge_space_file_change_uow.py` | F046 业务事实与审批 bundle 的同事务边界；只承载 public post-commit callback，事务提交后才执行 | `execute()`、`run_post_commit_effects()` |
| `knowledge/domain/services/knowledge_space_file_change_policy_service.py` | F046 当前租户策略与单空间设置；Platform 多项保存使用一个事务，拒绝跨租户空间并整体回滚 | `save_configuration()`、`is_approval_required()`、`get_space_settings_page()` |
| `knowledge/domain/services/knowledge_space_file_change_execution_coordinator.py` | F046 Knowledge-owned generation/step 编排；按 action 处理 retry/补偿，完成判据只认当前 token、权威 phase/guard 与 durable step | `begin_execution()`、`queue_retry()`、`reconcile()`、`is_business_complete()` |
| `knowledge/domain/services/knowledge_space_upload_stage_service.py` | F046 opaque stage：登记临时桶对象、申请绑定后幂等复制到永久桶、预览与终态清理 | `create_stage()`、`retain_bound_stage()`、`cleanup()`、`reconcile_expired_orphan()` |
| `knowledge/domain/services/knowledge_space_mutation_executor.py` | F046 mutation owner 编排入口：先原子补齐正式文件图或 mutation/delete manifest，再从持久化 request/step/token 恢复并校验后执行或补偿 | `prepare_execution()`、`execute_and_verify_step()`、`continue_compensation()`、`continue_post_cutover_cleanup()` |
| `knowledge/domain/services/knowledge_space_mutation_step_owner.py` | rename/move 外部副作用的稳定 owner 协议；具体实现可演进，但 worker 只经 executor 调用该协议 | `MutationStepOwner` |
| `knowledge/domain/services/knowledge_space_mutation_read_projection_service.py` | transition 期间按 durable phase 向正式读路径投影唯一 old/new view | `list_invisible_ids()`、`authoritative_space_ids()`、`name_projection()` |
| `knowledge/domain/services/knowledge_space_file_change_compensation_service.py` | F046 纯 Knowledge 补偿扫描 Service：校验 tenant ContextVar，以 request/step ID 返回有界 keyset 页，不查询 Approval instance/outbox | `list_watchdog_page()`、`list_step_recovery_page()`、`list_cleanup_page()`、`list_expired_orphan_stage_page()` |
| `knowledge/domain/services/knowledge_space_file_change_application_service.py` | Knowledge list/detail/decision/retry/cleanup；业务状态来自 Knowledge，审批状态只经 public read/decision port | `list_uploads()`、`get_detail()`、`decide_upload()`、`retry_ingest()`、`cleanup_upload()`、`batch_approve()` |
| `worker/config.py` | Celery 路由：F046 精确匹配 `knowledge_celery`；Approval delivery、legacy outbox、F045 Permission worker落默认队列 | `task_routes` |
| `approval/api/endpoints/approval_user.py` | Client 端 API（`/api/v1/approval/...`） | — |
| `approval/api/endpoints/approval_admin.py` | Platform 管理 API（`/api/v1/approval/admin/...`） | — |
| `approval/api/endpoints/approval.py` | 旧系统 legacy API（`/api/v1/approval/requests/...`），**已废弃** | — |
| `permission/api/endpoints/resource_permission.py` | F045 active/pending 权限查询与原业务 request 重试 | `get_resource_permissions()`、`retry_resource_user_invite()` |
| `knowledge/api/endpoints/knowledge_space_file_change.py` | F046 policy/settings 与纯 Knowledge 文件变更 API；决定委托 Approval public port | `list_pending_uploads()`、`get_file_change_detail()`、`retry_file_change_ingest()` |

### 场景扩展实现

| completion mode | 文件 | 类 |
|---|---|---|
| legacy | `approval/domain/services/menu_access_handler.py` | `MenuAccessApprovalHandler` |
| legacy | `approval/domain/services/channel_subscribe_scenario_handler.py` | `ChannelSubscribeScenarioHandler` |
| legacy | `approval/domain/services/knowledge_space_subscribe_scenario_handler.py` | `KnowledgeSpaceSubscribeScenarioHandler` |
| decision delivery | `permission/domain/services/resource_user_invite_approval_policy.py` / `resource_user_invite_decision_subscriber.py` | `ResourceUserInviteApprovalPolicy` / `ResourceUserInviteDecisionSubscriber` |
| decision delivery | `knowledge/domain/services/knowledge_space_file_change_approval_policy.py` / `knowledge_space_file_change_decision_subscriber.py` | `KnowledgeSpaceFileChangeApprovalPolicy` / `KnowledgeSpaceFileChangeDecisionSubscriber` |

### 前端

| 文件 | 职责 |
|------|------|
| `src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx` | 审批中心弹窗（我的审批 + 我的申请 + 时间线） |
| `src/frontend/client/src/api/approval.ts` | 审批 API 封装，含 `ApprovalApiError`（非 200 自动抛出） |
| `src/frontend/client/src/pages/MenuUnavailablePage.tsx` | 无权限占位页 + 申请入口 |
| `src/frontend/client/src/layouts/MenuApprovalPluginGate.tsx` | 菜单审批路由守卫 |
| `src/frontend/platform/src/pages/ApprovalPage/index.tsx` | 管理后台审批页（场景/分支/流程/节点/异常） |
| `src/frontend/platform/src/controllers/API/approval.ts` | Platform 审批 API 封装 |
| `src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpace.tsx` | 工作台“知识空间”配置页；承载 F046 租户级全局开关、按空间配置入口和统一保存动作 |
| `src/frontend/platform/src/pages/KnowledgePage/FileChangeApprovalSettings.tsx` | F046 策略及按空间配置组件；嵌入工作台配置页，知识库列表页不再展示独立设置 Tab |
| `src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx` | F046 待审上传按 `source_parent_id` 投影到当前知识空间目录的普通文件列表；暂存记录不提前创建正式 `KnowledgeFile` |
| `src/frontend/client/src/pages/knowledge/hooks/useFileChangeApproval.ts` | F046 当前目录待审上传查询、虚拟文件行投影、详情及同意/拒绝 mutation |
| `src/frontend/client/src/pages/knowledge/SpaceDetail/FileChangeApprovalDetail.tsx` | 分区展示 Knowledge 六词业务状态与 `approvalStatus`；仅 failed 显示原 request 重试 |
| `src/frontend/client/src/api/knowledge.ts` | F046 Raw DTO 映射；内部 `not_started` 对外呈现 queued + pending，不接收 Approval outbox/token/projection |

---

## 4. 预置场景

五个场景由 `ApprovalRegistry.with_default_presets()` 注册；前四个是目录预置，F046 是隐藏的系统固定场景。preset **不等于已启用或已落库**。需要部门管理员解析的 legacy 入口在创建 `ApprovalGateRequest` 时传 `applicant_department_id`。

| 场景 | completion mode | 业务事实/执行 owner | 业务 worker queue |
|---|---|---|---|
| `menu_access_request` | legacy handler/outbox | Approval `UserMenuAccessService` | 默认 `celery` |
| `channel_subscribe_request` | legacy handler/outbox | Channel membership + OpenFGA | 默认 `celery` |
| `knowledge_space_subscribe_request` | legacy handler/outbox | Knowledge membership + OpenFGA | 默认 `celery` |
| `resource_user_invite_confirmation` | decision delivery | Permission request + ResourceGrantExecutor | 默认 `celery` |
| `knowledge_space_file_change_request` | decision delivery | Knowledge request/saga | `knowledge_celery` |

**首次部署自动落库**：4.2 频道订阅、4.3 知识空间加入和 4.4 资源个人用户邀请由 `common/init_data.py::_init_default_approval_scenarios()` 为默认租户幂等 seed。按 `tenant_id+scenario_code` 存在即整体跳过，绝不覆盖人工改动。邀请场景的默认流程是单个 `or` 节点，唯一来源 `invited_user`。4.5 文件变更由 `ensure_system_file_change_scenario()` 在默认初始化、新租户、策略保存和首次需审 mutation 四入口幂等确保；菜单权限申请(4.1)不自动 seed。

### 4.1 菜单权限申请 (`menu_access_request`)
- **入口**：Client `/workspace/menu-unavailable?plugin=xxx` → `POST /api/v1/approval/menu-access/apply`
- **Handler**：`MenuAccessApprovalHandler`
- `on_approved` 调 `UserMenuAccessService.grant_menu_access()`，自动补父级依赖（如 `knowledge_space` → 同时授权 `workstation`）；`on_revoke` 调 `revoke_menu_access()`
- 申请前校验 `ensure_application_allowed()`（`menu_approval_mode=false` 或已有权限时拒绝）

### 4.2 频道订阅审批 (`channel_subscribe_request`)
- **入口**：`channel/domain/services/channel_service.py::subscribe_channel()`（`REVIEW` 可见性频道）
- **Handler**：`ChannelSubscribeScenarioHandler`
- 通过 / pass 路径调 `ChannelService.sync_direct_channel_user_permissions()` 写 ReBAC(OpenFGA) 关系（否则成员不出现在 ReBAC 成员列表）
- `on_approved` 先把申请人的 **PENDING** membership 翻成 ACTIVE 再写 ReBAC（查 membership 注意频道默认只返回 ACTIVE，激活需带非 ACTIVE 状态）
- PENDING 时调 `_send_channel_approval_notification()` 通知审批人

### 4.3 知识空间加入审批 (`knowledge_space_subscribe_request`)
- **入口**：`knowledge/domain/services/knowledge_space_service.py::subscribe_space()`（`auth_type=APPROVAL`）
- **Handler**：`KnowledgeSpaceSubscribeScenarioHandler`
- 通过 / ACTIVE 路径调 `sync_direct_space_user_permissions()` 写 ReBAC 关系
- PENDING 时调 `_send_space_approval_notification()` 通知审批人
- **不变量：先过网关、再落 membership。** `subscribe_space` 对 APPROVAL 空间必须先 `await gate.request_or_pass()`，按 gate 结果（pass→ACTIVE / pending·exception→PENDING）才通过 `_persist_space_member()` 写 `space_channel_member`。**严禁在调网关前预写 PENDING membership**——否则场景未配置/未启用时网关 `raise ApprovalScenarioDisabledError`，但 PENDING 行已落库，下次点"关注"会被 `subscribe_space` 顶部"已 PENDING 直接返回 pending"的早退分支短路，掩盖错误（首次报错、二次假成功）。无场景时每次点击都应一致报错。

### 4.4 资源个人用户邀请确认 (`resource_user_invite_confirmation`)
- **入口**：知识空间/频道授权 Service 识别"新增个人用户" 后调 Permission 域 `ResourceUserInviteApplicationService.request_invite()`；不再以 Approval payload 作邀请事实源。
- **18106 失败关闭**：场景缺失/关闭时，业务请求与 submission bundle 同事务回滚，不得降级直接授权。
- **去重**：稳定 business key 只含 `tenant/resource_type/resource_id/target_user_id`，不含邀请人；Redis token-safe 锁只降争用，`(tenant_id,business_key,active_marker=0)` 唯一约束才是最终事实源。
- **审批**：只允许被邀请人在唯一 OR 节点处理，管理员不可代办；F025 终态固定为 `approved/rejected/withdrawn/cancelled`，不存在业务 `executed/execute_failed` 回写。
- **决定消费**：approved 事件幂等写 `queued + decision_event_id` 后派发 Permission 业务任务；派发或 ack 不确定时允许同事件重投，最终授权必须由资源 owner 权威读后校验保证幂等。reject/withdraw/cancel 只关闭业务请求并释放占槽。

### 4.5 知识空间文件变更审核 (`knowledge_space_file_change_request`)
- **入口**：知识空间上传、重命名、移动、删除 application service；不接入 legacy `approval_request`
- **completion mode**：`decision_delivery`；由 Knowledge policy/subscriber 接入，不注册 handler，不创建 `ApprovalOutbox`
- **固定配置**：始终 enabled、单 catch-all flow、单个 `or` 节点，审批人来源只能是
  `knowledge_space_owner + knowledge_space_manager`；管理端不得 disable/delete/改 route/flow/node
- **动态资格**：显式 owner/manager 由 OpenFGA 权威解析；知识空间数据库创建者按 F044 永久 owner 语义合并，
  其 best-effort owner tuple 尚未补偿时仍可直接执行或审批。OpenFGA 查询故障始终 fail-closed，不以数据库创建者
  降级绕过故障。新管理员通过候选发现和对账补 task，former approver 的 pending task 取消且失去详情可见性；
  最终 decision 前再次校验当前资格
- **决定消费**：Knowledge request 使用正式 `business_key/request_fingerprint/decision_event_id/result_snapshot`
  绑定审批事实。approved 先提交 queued/event 后派发；reject/withdraw/cancel 先提交 closed/event 后清理 upload stage；
  临时失败抛 retryable，同一 event 只补未确认副作用，绑定或乱序错误 permanent。
- **异常策略**：审批侧只处理 `approver_empty` 等审批异常；业务执行失败留在 Knowledge request，由文件页按原 request 重试，审批中心不展示业务异常或重试入口
- **列表投影**：待审上传仍是 `knowledge_space_upload_stage + knowledge_space_file_change_request`，不提前生成正式
  `KnowledgeFile`。Client 按 request 的 `source_parent_id` 查询并投影成不可选择、不可移动/重命名的虚拟文件行；
  根目录仅展示 `source_parent_id IS NULL`，子目录仅展示等于当前目录 ID 的记录。列表内预览继续读取暂存对象，
  当前审批人可直接同意/拒绝，状态标签可进入完整详情及 Knowledge 业务重试/清理。`applied` 上传已经成为正式
  文件，Client 不再将其投影为虚拟待审行，也不在文件列表展示“已生效”标签；后续仅展示普通文件生命周期状态。
- **执行**：审批决定交付只把 Knowledge request 置 `queued`；之后由 Knowledge generation token、request/step/footprint
  独立推进，业务失败不回写 F025。upload 的完成判据固定为正式文件图已提交、OpenFGA 权限写入成功且普通文件
  解析调度已接收；之后的解析、索引、向量化成功或失败只属于文件生命周期，不回写或回退审批状态。
  upload 业务交接、rename/move transition 和 delete purge 的补偿由 `knowledge_celery` 任务持续处理

---

## 5. 数据库表

| 表名 | 说明 | 关键状态字段 |
|------|------|------------|
| `approval_scenario` | 租户下启用的审批场景 | `enabled` |
| `approval_route_rule` | 场景下条件分支（按 `sort_order` 匹配） | `route_type: pass/flow`、`enabled` |
| `approval_flow_definition` | 审批流程定义头 | — |
| `approval_flow_version` | 流程版本快照 | `is_active` |
| `approval_node_definition` | 流程版本内顺序节点 | `node_order`、`node_mode: or/and`、`approver_config` |
| `approval_instance` | 一次审批申请；F045/F046 只使用审批终态 | 通用 `pending/approved/rejected/withdrawn/exception/cancelled`；`executing/executed/execute_failed` 仅三个 legacy completion 场景 |
| `approval_task` | 分配给审批人的节点待办 | `pending/approved/rejected/skipped/cancelled` |
| `approval_exception` | 审批配置/审批人异常；`execute_failed` 只属于三个 legacy handler 场景 | `open/resolved`，`route_missing/approver_empty/execute_failed` |
| `approval_outbox` | 三个已上线场景的 legacy 业务执行队列 | `pending/success/failed`；不承载 F045/F046 |
| `approval_decision_outbox` | F045/F046 审批终态可靠交付；一个终态一个版本化事件 | `pending/processing/delivered/failed`；claim token/lease；`retryable/permanent` 失败分类 |
| `approval_action_log` | 时间线日志 | — |
| `user_menu_access` | 用户级菜单授权（菜单审批专用） | `active/revoked` |
| `resource_user_invite_request` | F047 F045 邀请业务事实表；建单、决定消费和 token-bound 授权 worker 均已接入 | `awaiting_approval/queued/applying/applied/failed/closed` |
| `knowledge_space_file_change_policy/setting` | F046 租户策略与单空间配置；不继承 root tenant | `enabled`、`scope`、`approval_required` |
| `knowledge_space_upload_stage` | F046 未正式入库上传的 opaque 暂存对象 | `uploaded/attaching/attached/consumed/cleanup_pending/cleaned`；`uploaded` 引用临时桶对象，`attaching` 表示申请已绑定但临时对象尚待幂等复制到永久桶 |
| `knowledge_space_file_change_request` | F046 Knowledge 业务事实；保存 business key/fingerprint/decision event/result snapshot、执行代次与清理 checkpoint | 内部 `not_started/queued/applying/applied/failed/compensating/closed`；API 把 `not_started` 映射为 `queued + approval_status=pending` |
| `knowledge_space_file_change_footprint` | F046 文件/文件夹/子树/目标位置的冲突占用与 deletion/transition guard footprint | `exact/subtree/destination` |
| `knowledge_space_file_change_execution_step` | F046 durable step、稳定幂等键、attempt token 和补偿游标 | `pending/dispatched/succeeded/failed/compensating/compensated` |
| `approval_request` | **旧系统（已废弃）**：部门知识空间文件上传审批，仅兼容存量 | — |

> Approval 模型见 `approval/domain/models/approval_instance.py`、`approval_scenario.py`、`approval_decision_outbox.py`；业务状态必须回到 Permission/Knowledge 模型确认，不能从 Approval payload 或 exception 推导。

---

## 6. 异步交付与 Celery

### 6.1 队列矩阵

| 任务 | completion mode | 队列 | 成功事实 |
|---|---|---|---|
| `execute_approval_outbox` / `retry_approval_outbox` | 三个 legacy 场景 | 默认 `celery` | handler 完成且 outbox/instance 同事务进入 success/executed |
| `deliver_approval_decision` / recovery coordinator | F045/F046 | 默认 `celery` | `approval_decision_outbox=delivered`，仅代表业务 subscriber 已接收决定 |
| `execute_resource_user_invite` | F045 Permission | 默认 `celery` | ResourceGrantExecutor 权威读后校验通过，Permission request=`applied` |
| `bisheng.worker.knowledge.file_change_tasks.*` | F046 Knowledge | `knowledge_celery` | 当前 generation 的 required steps、phase/guard 与 owner 权威判据全部满足，Knowledge request=`applied` |

`worker/config.py` 只为 `bisheng.worker.knowledge.file_change_tasks.*` 叠加精确 `knowledge_celery` route，不覆盖其他 task routes。Approval decision delivery 与 Permission invite worker 不指定 queue，自然落默认队列；`workflow_celery` 只用于工作流 DAG。

### 6.2 legacy outbox

仅菜单、频道订阅、知识空间加入通过后创建 `ApprovalOutbox`。最后节点与 pass 分支都在审批事务提交后派发 `execute_approval_outbox`。handler 成功/失败必须原子写 outbox、instance；确定失败可创建 legacy `execute_failed` exception。

F045/F046 不查询、不创建、不重试这张表。

### 6.3 decision delivery 与 F045

F025 终态 UoW 写唯一决定事件；delivery service 用 tenant + claim token 投递、ack 或分类 retryable/permanent，永不反向改变审批终态。

F045 subscriber 把 approved 先提交为 `queued`，再派稳定 Permission request ID。`execute_resource_user_invite` 从显式正整数 tenant header 恢复 ContextVar，以 execution token claim，调用资源 owner executor 并权威验证 tuple/binding；`failed` 仍占唯一槽位，只能重试原业务 request。业务结果和通知都不写 Approval outbox/exception。

### 6.4 F046 Knowledge saga

F046 subscriber 把 approved 先提交为 `queued`，Knowledge dispatcher 只发送 tenant/request。首次 coordinate 与带 token
恢复均先调用 Knowledge mutation owner 的 `prepare_execution()`，在同一业务事务补齐正式文件图或 mutation/delete
manifest 和当前 generation steps；随后 coordinator 只加载已准备的当前 token，旧 token 回调忽略。准备过程幂等，
可修复已进入 applying 但准备上下文尚未完整提交的 generation，且不会提前执行 FGA、检索或解析派发副作用。

- upload：正式文件图、FGA 权限和普通解析任务调度均成功接受后才 applied；后续解析失败是普通文件状态。
- rename/move：durable transition footprint 保证 OLD_VIEW/NEW_VIEW 单一正式视图，owner read-after-verify 后推进。
- delete：DB cutover 与 deletion guard 同一 Knowledge 事务；FGA/MinIO/ES/Milvus purge 全部权威验证、required steps 属于当前 token且 guard 退役后才 applied。
- retry/compensation：只操作 Knowledge request/step/footprint；业务失败保持 Approval approved，不创建 Approval exception。

Beat 注册四个 Knowledge coordinator：动态审批人对账、执行 watchdog、step recovery/compensation、stage/residue/delete cleanup。coordinator 只在 `bypass_tenant_filter()` 内枚举租户，再带显式 tenant header 逐租户派发；逐租户 keyset 有界扫描、ContextVar finally reset、单租户失败隔离。所有 F046 task 与 Beat 字符串均位于 `bisheng.worker.knowledge.file_change_tasks` 并路由到 `knowledge_celery`。

> 部署至少需要同时消费默认 `celery` 与 `knowledge_celery`。task ID 和 broker ACK 只证明派发，不证明业务成功。

v2.6.0 发布采用停服直接升级：同时停止 API、默认/Knowledge worker 与 Beat，完成未发布 F045/F046 DDL/代码替换后整组启动；不保留两场景开发期消息/数据兼容，也不允许新旧 worker 混跑。三个已上线 legacy 场景的 outbox 数据与 worker 语义必须保留。

---

## 7. API 列表

> 全局前缀 `/api/v1`。以代码为准（`approval_user.py` / `approval_admin.py` / `approval.py`）。

### 用户端（`/approval`）
```
GET  /approval/my-tasks                        # 我的待办（审批人视角）
GET  /approval/my-tasks/{task_id}              # 任务详情
POST /approval/tasks/{task_id}/decision        # 同意/拒绝
GET  /approval/my-requests                     # 我的申请（申请人视角）
GET  /approval/instances/{instance_id}         # 实例详情（tasks + flow_nodes + action_logs）
POST /approval/instances/{instance_id}/withdraw # 撤回
GET  /approval/menu-access/pending-check       # 菜单申请前置校验
POST /approval/menu-access/apply               # 菜单权限申请
POST /approval/menu-access/{instance_id}/revoke-grant # 撤销菜单授权（审批人）
```

### F045 Permission 域入口（`/permissions`）

权限列表仍保留既有 active/pending 前端字段；pending 来源是 `resource_user_invite_request`，只经 Approval
public read port 批量补充审批状态。重试只接受 business request ID，且只重派 approved+failed 原请求，不新建审批。

```text
GET  /permissions/resources/{resource_type}/{resource_id}/permissions
POST /permissions/resource-user-invites/{request_id}/retry
```

### F046 知识域入口（`/knowledge/space`）

这些 API 的业务资源归 Knowledge 域，审批决策最终仍委托 F025 的 instance 决策入口；endpoint 不直接写
`ApprovalTask/ApprovalInstance`。

```text
GET    /knowledge/space/admin/file-change-policy
PUT    /knowledge/space/admin/file-change-policy
GET    /knowledge/space/admin/file-change-settings
PUT    /knowledge/space/admin/file-change-settings/{space_id}
PUT    /knowledge/space/admin/file-change-configuration       # 当前租户 policy + settings 单事务保存
GET    /knowledge/space/{space_id}/file-changes/uploads
GET    /knowledge/space/{space_id}/file-changes/{request_id}
GET    /knowledge/space/{space_id}/file-changes/{request_id}/preview
POST   /knowledge/space/{space_id}/file-changes/{request_id}/decision  # approve/reject，委托 F025 instance 决策
POST   /knowledge/space/{space_id}/file-changes/{request_id}/retry-ingest
DELETE /knowledge/space/{space_id}/file-changes/{request_id}
POST   /knowledge/space/{space_id}/file-changes/batch-approve
```

### 管理端（`/approval/admin`）
```
GET    /approval/admin/scenario-presets                       # 预置场景目录（下拉来源）
GET    /approval/admin/scenarios                              # 场景列表
POST   /approval/admin/scenarios                              # 新增场景
PUT    /approval/admin/scenarios/{scenario_id}                # 更新场景
DELETE /approval/admin/scenarios/{scenario_id}                # 删除场景
GET    /approval/admin/scenarios/{scenario_id}/routes         # 分支列表
POST   /approval/admin/scenarios/{scenario_id}/routes         # 新增分支
PUT    /approval/admin/routes/{route_rule_id}                 # 更新分支
DELETE /approval/admin/routes/{route_rule_id}                 # 删除分支
PATCH  /approval/admin/scenarios/{scenario_id}/routes/reorder # 分支排序
GET    /approval/admin/scenarios/{scenario_id}/flows          # 流程列表
POST   /approval/admin/scenarios/{scenario_id}/flows          # 新增流程
PUT    /approval/admin/flows/{flow_definition_id}             # 更新流程
DELETE /approval/admin/flows/{flow_definition_id}             # 删除流程
GET    /approval/admin/flows/{flow_definition_id}/nodes       # 节点配置
PUT    /approval/admin/flows/{flow_definition_id}/nodes       # 提交节点（全量提交触发新版本）
GET    /approval/admin/flows/{flow_definition_id}/versions/{flow_version_id} # 版本预览
GET    /approval/admin/exceptions                            # 异常列表
POST   /approval/admin/exceptions/{exception_id}/retry       # 重试/指定审批人/跳过节点/标记完成
POST   /approval/admin/exceptions/{exception_id}/cancel      # 取消审批（必须填原因）
```

### 旧系统 legacy（`/approval/requests`、`/approval/department-knowledge-space`）— ⚠️ 已废弃
部门知识空间文件上传审批，独立于审批中心，见 `approval.py`。**已废弃**，仅兼容存量数据，不要在此新增/扩展接口。

---

## 8. 站内信通知矩阵

| 触发时机 | 接收人 | 实现位置 |
|----------|--------|---------|
| 创建审批任务（菜单申请） | 审批人 | `ApprovalCenterService._send_menu_access_approval_messages()` |
| 频道审批创建（PENDING） | 审批人 | `ChannelService._send_channel_approval_notification()` |
| 知识空间审批创建（PENDING） | 审批人 | `KnowledgeSpaceService._send_space_approval_notification()` |
| 中间节点通过、生成下一节点任务 | 下一节点审批人 | `_advance_after_node_approved()` → `_send_approval_notify('approval_task_pending')` |
| 审批通过（最后节点 finalize） | 申请人 | `_advance_after_node_approved()` → `_send_approval_notify('approval_instance_approved')` |
| 审批拒绝 | 申请人 | `decide_task()` reject 分支 |
| 申请撤回 | 有 task 的审批人 | `ApprovalCenterService.withdraw_instance()` |
| 异常产生（route_missing/approver_empty） | 管理员（AdminRole） | `ApprovalGate._notify_admins_of_exception()` / `ApprovalNotificationService.notify_admins()` |
| 异常取消 | 申请人 | `ApprovalExceptionService.cancel_exception_api()` |
| F045 资源个人邀请建单 | 被邀请用户 | `ApprovalSubmissionService` post-commit effect → `approval_task_pending` |
| F045 审批通过/拒绝/撤回/取消 | 邀请人或已有 task 的相关用户 | `ApprovalCenterService` 审批决定通知；即使 action code 含 invite failed，也只表达拒绝/撤回等决定，不表达授权 worker 失败 |
| F045 授权完整生效/失败 | 邀请人 | Permission `ResourceUserInviteBusinessNotificationService` → `resource_user_invite_effective/failed`；按 execution token 去重 |
| F046 初次建单 | 当前有效 owner/manager | `ApprovalSubmissionService` post-commit effect → `approval_task_pending` |
| F046 审批通过/拒绝/撤回/取消 | 申请人或已有 task 的相关用户 | `ApprovalCenterService` 审批决定通知；只表达审批状态 |
| F046 动态对账补建 task | 新增的当前有效 owner/manager | `ApprovalDynamicAssigneeService._notify_created_task()` → `approval_task_pending`；只通知新 task |
| F046 首次进入 approver_empty | 租户管理员 | `ApprovalDynamicAssigneeService._notify_approver_empty()` → `approval_exception_approver_empty`；同一 open exception 不重复通知 |
| F046 Knowledge applied/failed/compensating | 无 Approval 业务通知 | 文件页从 Knowledge API 刷新业务状态；F025 不发送文件执行成败通知 |

> 注：审批通知在审批事实提交后发送。F045 授权生效/失败由 Permission worker 提交业务状态后发送；F046 的业务状态由 Knowledge API 展示。业务通知或刷新失败都不能回写 Approval 终态。

---

## 9. 审批进度时间轴

`get_instance_detail` 返回三组数据，前端合并展示：
```
action_logs[action=submitted]      ← 提交申请
flow_nodes (按 node_order 排序)     ← 完整流程骨架（来自 approval_node_definition，含未到达节点）
  ├── 已有 task → 实际状态
  └── 无 task  → 灰色"未到达"
action_logs[action!=submitted]     ← 撤回/取消等其他日志
```
`flow_nodes` 解决了"tasks 只有已创建节点"的问题，能展示完整流程定义。

---

## 10. 配置要点

条件分支 `match_config` 格式：
```json
{}                                                  // 无条件，始终命中（catch-all）
{"field": "applicant_role", "value": "dept_admin"}  // 申请人是部门管理员
{"field": "menu_key", "value": "knowledge_space"}   // 申请特定菜单
{"field": "space_type", "value": "department"}      // 知识空间类型
```
`applicant_role` 枚举：`admin`(系统管理员) / `tenant_admin`(租户管理员) / `dept_admin`(部门管理员) / `regular_user`(普通用户, catch-all) / `role_{id}`(特定角色)。

节点 `approver_config.sources` 格式：
```json
[
  {"type": "direct_user", "user_ids": [701], "user_names": ["00017"]},
  {"type": "department_admin"},
  {"type": "tenant_admin"}
]
```
`user_names` 由前端保存时写入，用于节点卡片直接显示用户名，避免二次查库。

F046 的 sources 固定为：
```json
[
  {"type": "knowledge_space_owner"},
  {"type": "knowledge_space_manager"}
]
```
它不是租户可编辑配置；若管理端写入其他 source、pass route、AND 或多节点，服务端必须拒绝。

---

## 11. 调试指南

### 第一步：识别 completion mode

```sql
SELECT id, tenant_id, scenario_code, status, business_key
FROM approval_instance WHERE id=<N>;
```

- `menu_access_request/channel_subscribe_request/knowledge_space_subscribe_request`：查 legacy outbox。
- `resource_user_invite_confirmation/knowledge_space_file_change_request`：查 decision outbox，再查业务 request；没有 `ApprovalOutbox` 是正确行为。

### legacy 场景“通过但业务没生效”

```sql
SELECT id, status, error_summary FROM approval_outbox WHERE instance_id=<N>;
SELECT id, exception_type, status, detail FROM approval_exception WHERE instance_id=<N>;
```

- `pending`：确认默认 `celery` 队列有消费者。
- `failed`：查受控错误摘要与 legacy `execute_failed`，通过管理端异常入口重试；不要手工调用 handler 绕过 claim/审计。
- `success` 但成员不可见：检查 membership 是否 active，以及 `sync_direct_*_permissions()` 的 OpenFGA 权威结果。

### F045/F046“审批 approved 但业务未生效”

```sql
SELECT id, status, failure_kind, retry_count, error_summary, next_retry_at
FROM approval_decision_outbox WHERE instance_id=<N>;

SELECT id, approval_instance_id, decision_event_id, execution_state,
       execution_token, error_summary, result_snapshot
FROM resource_user_invite_request WHERE approval_instance_id=<N>;

SELECT id, approval_instance_id, decision_event_id, execution_state,
       execution_token, cleanup_state, result_snapshot
FROM knowledge_space_file_change_request WHERE approval_instance_id=<N>;
```

- 决定事件 `pending/processing`：检查默认 `celery` 的 delivery worker 和显式 tenant header。
- 决定事件 `failed + retryable`：等待 recovery；`permanent` 通常是 tenant/instance/key/fingerprint/version 绑定错误，先修事实，不要强改 delivered。
- 事件 `delivered`、F045 `queued/applying`：检查默认队列 Permission worker；`failed` 从 Permission 原 request 重试。
- 事件 `delivered`、F046 `queued/applying/compensating`：检查 `knowledge_celery`、当前 generation steps、footprint/guard 与 watchdog；`failed` 从 Knowledge retry API 重试。
- F045/F046 业务 `failed` 时 Approval 保持 approved；审批中心无 `execute_failed` 是正确行为。

### "审批人看不到任务"
```sql
SELECT id, approver_user_id, status FROM approval_task WHERE instance_id=<N>;
SELECT id, exception_type, status, detail FROM approval_exception WHERE instance_id=<N>;
```
静态 source 检查 `applicant_department_id` 与节点配置；F046 检查 Knowledge resolver 的当前 owner/manager、tenant ContextVar 与 OpenFGA 可用性。former approver 的 pending task 被取消且不会复活是预期行为。

---

## 12. 测试

审批相关测试在 `src/backend/test/approval/`（`asyncio_mode=auto`）。新测试放到该目录，不放 `test/` 根。
```bash
cd src/backend && uv run pytest test/approval/
```

decision delivery 与两业务域的聚焦回归至少覆盖：
```bash
cd src/backend
uv run pytest \
  test/approval/test_approval_submission_service.py \
  test/approval/test_approval_decision_registry.py \
  test/approval/test_approval_decision_uow.py \
  test/approval/test_approval_decision_delivery_service.py \
  test/approval/test_existing_scenario_outbox_regression.py \
  test/permission/test_resource_user_invite_application_service.py \
  test/permission/test_resource_user_invite_worker.py \
  test/knowledge/test_file_change_approval_policy_subscriber.py \
  test/knowledge/test_file_change_submission_decoupling.py \
  test/knowledge/test_file_change_execution_coordinator.py \
  test/knowledge/test_file_change_business_status_api.py \
  test/approval/test_file_change_beat_schedule.py
```
