---
name: approval-module
description: >-
  BiSheng 审批模块（审批中心 F025）的架构与代码参考。
  覆盖统一审批网关、多场景引擎、多节点流转、outbox 业务执行、站内信通知、异常处理。
  迭代审批功能或修复审批相关 Bug 前先读本 skill，可直接定位架构与代码锚点，无需全仓搜索。
  TRIGGER when: 用户要改动/修复"审批""审批中心""approval"相关功能（菜单权限申请、频道订阅审批、
  知识空间加入审批、审批流程/节点配置、异常处理、outbox/Celery 执行），或排查审批通过后业务未生效、
  审批人看不到任务、站内信未发等问题。
---

# 审批模块（审批中心 F025）

## ⚠️ 维护契约（修改代码后必读）

**本 skill 是审批模块的唯一权威参考，必须与代码永远一致。**
当你改动以下任意一项时，**同一个改动里必须同步更新本文件对应章节**，否则视为改动未完成：

- 主流程分支逻辑（`ApprovalGate.request_or_pass` 的 pass/flow/exception 分流、`decide_task` / `_advance_after_node_approved` 的节点流转）→ 更新 [§2 架构与主流程](#2-架构与主流程)
- 新增/删除/重命名服务文件或关键方法 → 更新 [§3 代码锚点](#3-代码锚点)
- 新增/删除预置场景或改动其触发入口、Handler → 更新 [§4 预置场景](#4-预置场景)
- 数据库表/状态枚举变化 → 更新 [§5 数据库表](#5-数据库表)
- API 路由增删改 → 更新 [§7 API 列表](#7-api-列表)
- 站内信触发时机/接收人变化 → 更新 [§8 站内信通知矩阵](#8-站内信通知矩阵)
- Celery 队列/路由变化 → 更新 [§6 outbox 与 Celery](#6-outbox-与-celery)

> 自检：改完代码后问自己"本 skill 里有没有哪句话现在变成假的了？"——有就改它。

---

## 1. 概述

审批中心是一套**通用多场景审批引擎**，所有场景共用同一套网关 / 路由 / 流程 / 节点 / 实例 / 任务 / outbox 机制。

**核心原则：审批"通过"与"执行业务"解耦为两步**——通过后只写 `approval_outbox(PENDING)`，由 Celery
异步执行业务 `on_approved()`。同步完成返回 `Completed`（旧 handler 的正常返回会归一化为 Completed）后实例才置
`EXECUTED`；返回 `Deferred(token, deadline)` 时保持 `instance=EXECUTING/outbox=DEFERRED`，只由对应 coordinator
的 token-bound complete/fail/resume 推进终态。

> ⚠️ **已废弃**：另有一套独立的旧系统——部门知识空间文件上传审批（`approval_request` 表），由 `approval_service.py` + `message_handler.py` 承载，路由在 `/approval/requests/*` 与 `/approval/department-knowledge-space/*`。该功能**已废弃**，仅为兼容存量保留，**不要在其上新增功能**；新需求一律走审批中心引擎。改审批中心时也不要误改它。

---

## 2. 架构与主流程

```
申请人触发业务入口
        │
        ▼
ApprovalGate.request_or_pass()        ← 统一网关，所有场景从这里进入
        │
   路由匹配 (approval_route_rule 表，按 sort_order 自上而下)
        │
   ┌────┴───────────────────────────┐
   │ pass 分支 (route_type=pass)      │ → instance(APPROVED) + outbox → Celery → on_approved() → EXECUTED
   │ flow 分支 (route_type=flow)      │ → instance(PENDING) + 首节点 task(PENDING) → 等待审批人
   │ 无分支命中                       │ → instance(EXCEPTION, route_missing) + 通知管理员
   │ 审批人解析为空                   │ → instance(EXCEPTION, approver_empty) + 通知管理员
   └────────────────────────────────┘
        │ (flow 分支被审批人处理)
        ▼
ApprovalCenterService.decide_task()
        │
   通过 → _advance_after_node_approved()
        ├── 有后续节点(node_order 更大) → 解析下一节点审批人 + 建 tasks + 通知审批人；解析为空 → EXCEPTION(approver_empty)
        └── 无后续节点(最后节点)        → instance(APPROVED) + outbox → Celery → EXECUTED + 通知申请人
   拒绝 → instance(REJECTED) + 通知申请人
   撤回 → instance(WITHDRAWN) + 通知有 task 的审批人
```

**多节点 / 会签**：`_advance_after_node_approved()` 实现顺序流转。
- OR 节点（`node_mode=or`）：任一人通过即把同节点其余 PENDING task 置 SKIPPED 并 advance。
- AND 节点（`node_mode=and`）：同节点全部通过才 advance。
- finalize 时若 `handler_key` 未注册，记录 error 后仍照常 APPROVED + 建 outbox（避免卡死）。

**资源个人用户邀请是强制本人确认特例**：`resource_user_invite_confirmation` 由 Handler 声明
`requires_self_confirmation` 和 business-key 去重。Gate 禁止 pass，且只接受单个 `or` 节点、唯一
`invited_user` 处理人；instance/task/log 同事务创建。Center 即使操作人是管理员也不允许代办，
approve/reject/withdraw 通过 Repository 单事务只接受一个终态。

**异常实例也留痕**：`_create_exception_result()` 在创建异常后会补写 `action='approval.request.submit'` 审计日志（与正常 PENDING/PASS 分支一致）。

**动态审批人是“权威资格 + 物化待办”**：声明了 runtime hook 的场景在
`list_my_tasks/count_pending_tasks/count_unread_tasks` 查询历史 task 前先调用
`discover_candidate_instances()` 正向发现当前用户有资格处理、但尚无 task 的实例，再由
`ApprovalDynamicAssigneeService` 在实例锁内对账。失效审批人的 pending task 置 cancelled，新增审批人新建
pending task；历史终态 task 不改写。列表/详情还必须经过 `filter_visible_instances()` / `authorize_view()`，
历史 task 不能继续授予业务快照可见性。

**Decision UoW**：task-id 和 instance-id 决策入口共用 `ApprovalCenterService._decide_in_uow()`，固定按
`instance → current-node tasks → open exception/outbox` 加锁，并在一个事务内完成动态对账、资格校验、
task/sibling/instance/log/exception/outbox 状态迁移。提交后才执行 outbox dispatch、通知和终态 hook；
`decide_instance_for_current_approver()` 是文件页单条/批量审批的权威入口，endpoint 不得直接改 task。

---

## 3. 代码锚点

> 路径相对 `src/backend/bisheng/`。这些是定位问题的第一入口。

### 后端服务

| 文件 | 职责 | 关键方法 |
|------|------|---------|
| `approval/domain/services/approval_gate.py` | 统一入口：路由匹配、实例创建、pass/pending/exception 分流 | `request_or_pass()`、`_create_exception_result()`、`_notify_admins_of_exception()` |
| `approval/domain/services/approval_center_service.py` | 用户端：动态候选发现后的任务列表/详情、task/instance 决策 UoW、撤回、菜单申请、多节点流转 | `list_my_tasks()`、`decide_task()`、`decide_instance_for_current_approver()`、`_decide_in_uow()`、`_advance_after_node_approved_locked()` |
| `approval/domain/services/approval_dynamic_assignee_service.py` | 实例锁内对账动态审批人、维护 approver_empty、生成新增任务通知 effect | `resolve_and_reconcile_in_uow()`、`reconcile_resolved_in_uow()` |
| `approval/domain/services/approval_exception_service.py` | 管理端异常处理：重试/指定审批人/跳过节点/取消/标记完成；F046 execute_failed 只走 token-bound Deferred resume | `assign_approvers()`、`_resolve_exception_node()`、`retry_execute_failed_api()` |
| `approval/domain/services/approval_outbox_service.py` | outbox 执行与重试；支持 Deferred heartbeat/complete/fail/resume 和业务 cutover caller-owned UoW | `execute_outbox()`、`resume_deferred_execution()`、`require_deferred_execution_in_uow()`、`fail_deferred_execution_in_uow()`、`complete_deferred_execution_in_uow()` |
| `approval/domain/services/approval_uow.py` | caller-owned session 的 Gate bundle、post-commit effect 与 F046 cutover/purge 原子写适配 | `ApprovalGateUowResult.run_post_commit_effects()`、`SessionBoundApprovalInstanceRepository.require_deferred_execution()`、`fail_deferred_execution()`、`complete_deferred_execution()` |
| `approval/domain/services/approval_scenario_admin_service.py` | 管理端：场景/分支/流程/节点配置、异常列表 | — |
| `approval/domain/services/approver_resolver.py` | 解析审批人来源 `direct_user` / `department_admin` / `tenant_admin` | `resolve_approvers_from_sources()` |
| `approval/domain/services/approval_registry.py` | 场景预置目录 + handler 注册表 | `with_default_presets()`、`register_handler()`、`get_handler()` |
| `approval/domain/services/approval_runtime_handler_factory.py` | 为 outbox 执行 / 多节点 advance 重新构造运行时 handler | `build_runtime_handler(scenario_code)` |
| `approval/domain/services/approval_notification_service.py` | 站内信统一封装 | `notify_user()` / `notify_users()` / `notify_admins()` |
| `approval/domain/services/resource_user_invite_service.py` | 18106 场景门禁、操作期场景行锁、快照/指纹、跨邀请人去重和建单 | `ensure_scenario_available()`、`scenario_guard()`、`request_invite()`、`list_pending_invites()` |
| `approval/domain/services/approval_business_lock.py` | token-safe Redis 短锁，串行化同资源同用户的查重建单 | `approval_invite_business_lock()` |
| `approval/domain/services/user_menu_access_service.py` | 菜单授权增删查，含父级菜单依赖自动补全 | `grant_menu_access()`、`revoke_menu_access()`、`ensure_application_allowed()` |
| `approval/domain/services/approval_service.py` + `message_handler.py` | **旧系统（已废弃）**：部门知识空间文件上传审批（`approval_request` 表），与审批中心独立，仅兼容存量、勿新增功能 | `ApprovalService.decide_request()` |
| `worker/approval/tasks.py` | Celery 任务（走默认 `celery` 队列） | `execute_approval_outbox`、`retry_approval_outbox` |
| `worker/approval/file_change_tasks.py` | F046 动态审批人及 Deferred/step/stage/delete 补偿：单次 Beat 跨租户 coordinator、显式 tenant header 的 keyset 分页任务和 token-bound owner 任务（走默认 `celery` 队列） | `reconcile_all_file_change_approvers`、`watchdog_all_file_change_executions`、`compensate_all_file_change_execution_steps`、`cleanup_all_file_change_residue` |
| `knowledge/domain/services/knowledge_space_file_change_scenario_handler.py` | F046 runtime handler：严格 owner/manager、候选发现、详情可见性、固定异常策略、Deferred resume/dispatch 与终态清理 | `discover_candidate_instances()`、`reconcile_pending_approvers()`、`exception_action_policy()`、`prepare_resume()`、`dispatch_deferred_execution()` |
| `knowledge/domain/services/knowledge_space_file_change_policy_service.py` | F046 当前租户策略与单空间设置；Platform 多项保存使用一个事务，拒绝跨租户空间并整体回滚 | `save_configuration()`、`is_approval_required()`、`get_space_settings_page()` |
| `knowledge/domain/services/knowledge_space_file_change_execution_coordinator.py` | F046 durable step dispatch/ack、heartbeat、Deferred complete/fail/resume 与业务状态投影；upload 在正式记录、FGA 与普通解析调度交接完成后结束审批执行 | `reconcile()`、`prepare_resume_in_uow()`、`get_business_status_projection()` |
| `knowledge/domain/services/knowledge_space_upload_stage_service.py` | F046 opaque stage：登记临时桶对象、申请绑定后幂等复制到永久桶、预览与终态清理 | `create_stage()`、`retain_bound_stage()`、`cleanup()`、`reconcile_expired_orphan()` |
| `knowledge/domain/services/knowledge_space_mutation_executor.py` | F046 mutation owner 编排入口：从持久化 request/step/token 恢复并校验后执行或补偿 | `execute_and_verify_step()`、`continue_compensation()`、`continue_post_cutover_cleanup()` |
| `knowledge/domain/services/knowledge_space_mutation_step_owner.py` | rename/move 外部副作用的稳定 owner 协议；具体实现可演进，但 worker 只经 executor 调用该协议 | `MutationStepOwner` |
| `knowledge/domain/services/knowledge_space_mutation_read_projection_service.py` | transition 期间按 durable phase 向正式读路径投影唯一 old/new view | `list_invisible_ids()`、`authoritative_space_ids()`、`name_projection()` |
| `knowledge/domain/services/knowledge_space_file_change_compensation_service.py` | F046 补偿扫描 Service：校验 tenant ContextVar 并返回有界 keyset 页 | `list_deferred_watchdog_page()`、`list_step_recovery_page()`、`list_cleanup_page()`、`list_expired_orphan_stage_page()` |
| `worker/config.py` | Celery 路由配置（审批任务**不**配路由，fall through 到默认队列） | `task_routes` |
| `approval/api/endpoints/approval_user.py` | Client 端 API（`/api/v1/approval/...`） | — |
| `approval/api/endpoints/approval_admin.py` | Platform 管理 API（`/api/v1/approval/admin/...`） | — |
| `approval/api/endpoints/approval.py` | 旧系统 legacy API（`/api/v1/approval/requests/...`），**已废弃** | — |

### 五个场景 Handler

| 文件 | 类 |
|------|----|
| `approval/domain/services/menu_access_handler.py` | `MenuAccessApprovalHandler` |
| `approval/domain/services/channel_subscribe_scenario_handler.py` | `ChannelSubscribeScenarioHandler` |
| `approval/domain/services/knowledge_space_subscribe_scenario_handler.py` | `KnowledgeSpaceSubscribeScenarioHandler` |
| `approval/domain/services/resource_user_invite_scenario_handler.py` | `ResourceUserInviteScenarioHandler`（强制本人确认；执行时调资源 owner Service 的 `apply_confirmed_personal_user_grant()`） |
| `knowledge/domain/services/knowledge_space_file_change_scenario_handler.py` | `KnowledgeSpaceFileChangeScenarioHandler`（F046 系统固定场景；动态 owner/manager OR 审批） |

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

---

## 4. 预置场景

五个场景由 `ApprovalRegistry.with_default_presets()` 注册（仅是"目录/下拉来源"，**不等于已启用**）。需要部门管理员解析的业务入口在创建 `ApprovalGateRequest` 时传 `applicant_department_id`。

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
- **入口**：知识空间/频道授权 Service 识别"新增个人用户" 后调 `ResourceUserInviteService.request_invite()`
- **18106 失败关闭**：含新个人用户的请求必须在资源创建/direct 授权前调 `ensure_scenario_available()`；场景缺失/关闭不得降级直接授权
- **并发关闭保护**：授权 Service 通过 `scenario_guard()` 对场景行加 `FOR UPDATE`，保护区覆盖创建资源、direct 写入和全部邀请建单；管理端关闭/删除场景必须等待本次已通过门禁的操作结束，避免二次检查返回 18106 时遗留部分副作用
- **去重**：`tenant/resource_type/resource_id/target_user_id`，不含邀请人；`pending/approved/executing` 阻止新单并保留首次角色快照
- **生效**：本人 approve 只使 instance 进入 `approved`；outbox claim 后是 `executing/processing`，Handler 实时复核并调用资源 owner Service，完整成功后才 `executed/success`
- **日志/审计**：发起 `created/existing` 与 Handler `start/success` 只记结构化 ID、business key、validation stage，不记姓名/完整 payload；outbox 终态审计 action 为 `resource.user_invite.execute.success/failed`，其他场景仍用 `approval.handler.success/failed`

### 4.5 知识空间文件变更审核 (`knowledge_space_file_change_request`)
- **入口**：知识空间上传、重命名、移动、删除 application service；不接入 legacy `approval_request`
- **Handler**：`KnowledgeSpaceFileChangeScenarioHandler`
- **固定配置**：始终 enabled、单 catch-all flow、单个 `or` 节点，审批人来源只能是
  `knowledge_space_owner + knowledge_space_manager`；管理端不得 disable/delete/改 route/flow/node
- **动态资格**：显式 owner/manager 由 OpenFGA 权威解析；知识空间数据库创建者按 F044 永久 owner 语义合并，
  其 best-effort owner tuple 尚未补偿时仍可直接执行或审批。OpenFGA 查询故障始终 fail-closed，不以数据库创建者
  降级绕过故障。新管理员通过候选发现和对账补 task，former approver 的 pending task 取消且失去详情可见性；
  最终 decision 前再次校验当前资格
- **异常策略**：只允许 `retry` 与 `cancel`。`approver_empty` retry 重新解析完整当前集合，
  `execute_failed` retry 进入 token-bound Deferred resume；禁止 assign/assign-flow/skip/mark-complete
- **列表投影**：待审上传仍是 `knowledge_space_upload_stage + knowledge_space_file_change_request`，不提前生成正式
  `KnowledgeFile`。Client 按 request 的 `source_parent_id` 查询并投影成不可选择、不可移动/重命名的虚拟文件行；
  根目录仅展示 `source_parent_id IS NULL`，子目录仅展示等于当前目录 ID 的记录。列表内预览继续读取暂存对象，
  当前审批人可直接同意/拒绝，状态标签可进入完整详情及异常重试/清理。
- **执行**：审批通过后可返回 `Deferred`；只有 durable step 的权威读后校验满足完成判据，才能把
  outbox/instance 置 success/executed。upload 的完成判据固定为正式文件图已提交、OpenFGA 权限写入成功且普通文件
  解析调度已接收；之后的解析、索引、向量化成功或失败只属于文件生命周期，不回写或回退审批状态。
  upload 业务交接、rename/move transition 和 delete purge 的补偿由默认队列任务持续处理

---

## 5. 数据库表

| 表名 | 说明 | 关键状态字段 |
|------|------|------------|
| `approval_scenario` | 租户下启用的审批场景 | `enabled` |
| `approval_route_rule` | 场景下条件分支（按 `sort_order` 匹配） | `route_type: pass/flow`、`enabled` |
| `approval_flow_definition` | 审批流程定义头 | — |
| `approval_flow_version` | 流程版本快照 | `is_active` |
| `approval_node_definition` | 流程版本内顺序节点 | `node_order`、`node_mode: or/and`、`approver_config` |
| `approval_instance` | 一次审批申请 | `pending/approved/executing/rejected/withdrawn/executed/execute_failed/exception/cancelled` |
| `approval_task` | 分配给审批人的节点待办 | `pending/approved/rejected/skipped/cancelled` |
| `approval_exception` | 异常记录 | `open/resolved`，`exception_type: route_missing/approver_empty/execute_failed` |
| `approval_outbox` | 业务执行队列 | `pending/processing/deferred/success/failed`；deferred 带 `execution_token/deferred_deadline/heartbeat_at` 且普通 claim 永不重领 |
| `approval_action_log` | 时间线日志 | — |
| `user_menu_access` | 用户级菜单授权（菜单审批专用） | `active/revoked` |
| `knowledge_space_file_change_policy/setting` | F046 租户策略与单空间配置；不继承 root tenant | `enabled`、`scope`、`approval_required` |
| `knowledge_space_upload_stage` | F046 未正式入库上传的 opaque 暂存对象 | `uploaded/attaching/attached/consumed/cleanup_pending/cleaned`；`uploaded` 引用临时桶对象，`attaching` 表示申请已绑定但临时对象尚待幂等复制到永久桶 |
| `knowledge_space_file_change_request` | F046 动作快照、审批实例绑定、执行代次与清理 checkpoint；审批状态仍以 ApprovalInstance 为准 | `not_started/applying/applied/failed/compensating`、`cleanup_state` |
| `knowledge_space_file_change_footprint` | F046 文件/文件夹/子树/目标位置的冲突占用与 deletion/transition guard footprint | `exact/subtree/destination` |
| `knowledge_space_file_change_execution_step` | F046 durable step、稳定幂等键、attempt token 和补偿游标 | `pending/dispatched/succeeded/failed/compensating/compensated` |
| `approval_request` | **旧系统（已废弃）**：部门知识空间文件上传审批，仅兼容存量 | — |

> 模型定义见 `approval/domain/models/approval_instance.py`、`approval_scenario.py`、`user_menu_access.py`。
> `approval_instance.latest_approver_user_id` 在强制本人邀请的单任务事务终态中会赋值；通用多节点路径仍未统一赋值。

---

## 6. outbox 与 Celery

业务执行走 outbox：通过后写 `approval_outbox(PENDING)` → Celery `execute_approval_outbox` 执行
`handler.on_approved()`。`Completed` 使 outbox=SUCCESS、instance=EXECUTED；`Deferred` 原子保存 token/deadline，
使 outbox=DEFERRED、instance=EXECUTING；确定失败使 outbox=FAILED、instance=EXECUTE_FAILED 并建
`execute_failed` 异常。成功的 outbox/instance 终态必须由 repository 同一事务落库；确定失败的
outbox/instance/exception 也必须同一事务落库。重复投递遇到历史 `success/executing` 中间态时，只修复
instance 为 `executed`，不重跑 handler。

执行前 `ApprovalInstanceRepository.claim_outbox()` 在同事务中把 outbox 置 `processing`、instance 置 `executing`。未超过 `approval_invite.outbox_claim_ttl_seconds` 的 claim 不得并行重领；TTL 必须大于 worker 900s hard time limit。邀请授权补偿结果不确定时抛 `ApprovalInviteRetryableExecutionError`：repository 在原子事务中保持 `processing/executing`，但把当前 claim 时间标记为已过期，使 Celery 下一次重试可立即重领；不得先记 `failed/execute_failed`或发送失败通知。

> **原则：业务回调（`on_approved` 等）不得静默失败。** 抛异常 → outbox=FAILED + `execute_failed`；
> 返回 `Deferred` → 保持 executing/deferred；其他正常返回归一化为 `Completed` 并置 instance=EXECUTED。
> 因此前置条件缺失（如找不到要激活的 membership/资源）**必须 raise**，异步业务必须返回有 token/deadline 的
> `Deferred`，绝不能 `return {'status':'xxx'}` 把失败或“仅已入队”伪装成同步成功。

**dispatch 入口（两处，功能相同名字不同）：**
- `approval_center_service.py::_dispatch_outbox(outbox_id, tenant_id)` — `decide_task` 最后节点通过 / skip_node，显式发送 `tenant_id` header
- `approval_gate.py::_dispatch_outbox_task(outbox_id, tenant_id)` — PASS 分支 post-commit effect，显式发送 `tenant_id` header

**Celery 队列：走默认 `celery` 队列。** `worker/config.py` **不**为 `bisheng.worker.approval.*` 配路由，任务自然 fall through 到默认队列。`workflow_celery` 专供工作流 DAG 执行，审批任务不占用。

F046 动态审批人补偿也走默认 `celery` 队列。空间权限事件投递
`reconcile_space_file_change_approvers`，Beat coordinator
`reconcile_all_file_change_approvers` 仅在 `bypass_tenant_filter()` 内枚举活跃租户，再为每个租户投递
`reconcile_tenant_file_change_approvers`。空间级和租户级任务都必须从 Celery headers 读取显式正整数
`tenant_id`，在入口设置并在 `finally` 恢复 ContextVar；每次只处理一个有界 keyset 页，续页继续携带同一
tenant header。两个业务任务使用指数 backoff，单租户或单实例失败不阻断其他租户/实例；Worker 只调用
F046 runtime handler，不能直接写 `ApprovalTask` / `ApprovalException`。

F046 delete 的逻辑 cutover 使用 caller-owned session，固定锁序为
`instance → outbox → file-change request → space/resource → execution steps`；同一事务内完成正式 DB 删除、
deletion guard 激活，但 request 保持 applying、outbox/instance 保持 deferred/executing。cutover 后的
FGA/MinIO/ES/Milvus purge 不回滚已完成的逻辑删除；每类必须对 immutable manifest 做权威读后验证。
失败时在 caller-owned UoW 内置 request/F025/outbox 为 failed/execute_failed/failed 并保留 guard；新 token
只续跑未成功 step。四类全部 verified 后，才在同一 UoW complete outbox/instance、置 request applied 并退役
guard footprint。普通 dict、task id 或仅 DB cutover 均不得作为成功证据。

F046 rename/move/upload 的异步执行使用 token-bound Deferred generation。通用 step dispatcher 只处理
`applying` 的当前 token，并按动作依赖逐步开放外部步骤。rename/move 的 queue task id 只表示已派发，只有 owner
Service 的 read-after-verify 结果可以 ack succeeded；upload 则以正式文件图提交、OpenFGA 权限权威写入和
`enqueue_or_dispatch()` 成功接收为审批业务完成证据，调度时不得再携带 F046 parser terminal callback 上下文。
解析任务后续按普通用户上传流程独立更新文件状态，解析、索引或向量化失败不得将已经完成的审批改为
`execute_failed`。`execute_failed` 异常的 retry 不进入动态审批人
对账，而是由 `ApprovalOutboxService.resume_deferred_execution()` 在 instance/outbox 锁事务内调用
handler `prepare_resume()`，原子生成新 token 并复位未完成业务步骤；提交后通过 handler 的
`dispatch_resumed_execution()` 携带显式 `tenant_id` header 补投 coordinator。旧 token、FAILED、
COMPENSATING 或 APPLIED 代次的通用 dispatch/ack 一律忽略。

F046 rename/move 的稳定 owner 边界是
`KnowledgeSpaceMutationExecutor.execute_and_verify_step(broker_context)` + `MutationStepOwner` 协议：broker
context 只作为身份提示，executor 必须重新读取并比对 tenant ContextVar、request/instance/current token、
durable step/idempotency key 与 mutation manifest；具体 owner 实现可演进，worker 不得直接调用存储或解释 manifest。
跨 MySQL/DM8、OpenFGA 和检索存储的 transition 必须保持单一正式视图不变量：durable transition footprint
激活后，`MutationReadProjectionService` 按 phase 对 children/search/preview/download/RAG/citation 统一投影
OLD_VIEW 或 NEW_VIEW，任何入口都不得绕过投影而同时暴露源/目标或部分状态；外部 parent、DB、检索状态只在
owner 权威读后校验完成后推进。进程崩溃保留 active projection；明确失败必须经 owner
rollback/compensation 验证后才能退回旧视图，cleanup 验证后才退役 projection。
Citation 是同一边界的一部分：必须在 accessScope、权限分层和 URL enrichment 前，以 `documentId + tenant_id`
权威回查正式 KnowledgeFile，并叠加 projection 的 authoritative space/name；缓存 payload 的旧 knowledgeId/name
不能绕过当前投影。
补偿只调用 token-bound `continue_compensation(request_id, execution_token)`，不得以 task id 作为完成证据。

F046 在 Beat 中注册四个无业务参数的单次 coordinator：动态审批人对账、Deferred watchdog、execution
step 补偿、stage 生命周期/已绑定 residue/delete 清理。每个 coordinator 只在 `bypass_tenant_filter()` 内枚举一次活跃租户，
随后以显式 `tenant_id` header 投递逐租户任务；逐租户任务恢复并最终 reset ContextVar，通过
`(update_time,id)` 或 `id` keyset 每次读取有界页。watchdog 查询限定 F046 scenario、`executing + deferred`
且 deadline/heartbeat 已超时的当前 token；step 查询限定当前 deferred token、
`pending/dispatched/failed/compensating` 且 `next_retry_at` 已到期；业务 stage 清理只覆盖已绑定终态/执行失败且
`cleanup_state != success` 的 upload；delete 清理只取 cutover 后仍有 active purge step 的 request。知识空间上传沿用
统一上传入口的流式写临时桶和 legacy `file_path/repeat` 响应，并额外返回 opaque `upload_id`；申请绑定事务先把 stage
置 `attaching`，提交后以稳定目标键从临时桶幂等复制到永久桶并置 `attached`，失败由同一 cleanup coordinator 补偿。
从未绑定申请的对象只留在临时桶，由临时桶既有生命周期自动过期；Beat 不物理删除 orphan，只在确认临时对象已不存在后
把 stage 置 `cleaned` 并释放配额预占。`applying` 补投
coordinator，`compensating` 只调用 Knowledge owner Service 的 token-bound `continue_compensation()`，不得由
worker 解释 manifest 或直接写 ORM。所有 schedule 和 task 都不指定 queue，保持默认 `celery` 队列；
broker/单租户/单候选失败隔离，业务任务使用指数 backoff，task id 永远不能作为成功依据。
Cleanup scanner 只扫描尚未退役 footprint 的候选；Repository 即使把 raw page 全部过滤为空，也必须用 raw
keyset 最后一行推进 cursor，不能因“filtered page empty”停在同一页或提前宣称扫描完成。

> ⚠️ 部署时必须有 worker 消费默认 `celery` 队列（`run_celery.py` 的 `all` / `file` 模式都含），否则审批通过后业务不执行。站内信发送是同步写库，不依赖 Celery。

启动消费默认队列的 worker：
```bash
uv run celery -A bisheng.worker.main worker -l info -c 100 -P threads -n default@%h
```

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
| 资源个人邀请建单 | 被邀请用户 | `ResourceUserInviteService` → `resource_user_invite_pending` |
| 资源个人邀请完整生效 | 邀请人 | `ApprovalOutboxService` 成功终态 → `resource_user_invite_effective` |
| 资源个人邀请拒绝/撤回/执行失败 | 邀请人（撤回时亦提醒目标用户） | `resource_user_invite_failed` |
| F046 初次建单 | 当前有效 owner/manager | `KnowledgeSpaceFileChangeService` post-commit notifier → `approval_task_pending` |
| F046 动态对账补建 task | 新增的当前有效 owner/manager | `ApprovalDynamicAssigneeService._notify_created_task()` → `approval_task_pending`；只通知新 task |
| F046 首次进入 approver_empty | 租户管理员 | `ApprovalDynamicAssigneeService._notify_approver_empty()` → `approval_exception_approver_empty`；同一 open exception 不重复通知 |

> 注：申请人侧"通过"通知是在**最后节点 finalize** 时发的（即审批通过即通知），不等 outbox 业务真正执行完。若要"业务执行成功"的精确通知，需在 `execute_outbox` 成功回调里补。

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

### "审批通过但业务没下发"
```sql
SELECT id, status, applicant_user_id FROM approval_instance WHERE id=<N>;
SELECT id, status, error_summary FROM approval_outbox WHERE instance_id=<N>;
```
- outbox 不存在 → `_dispatch_outbox` 没调
- outbox 存在且 `pending` → 没有 worker 消费默认 `celery` 队列
- outbox 存在且 `failed` → 看 `error_summary`，并查 `approval_exception` 的 `execute_failed`

手动补偿：
```python
# set_current_tenant_id(tenant_id)
# handler = await build_runtime_handler(outbox.handler_key)
# await handler.on_approved(instance_id, outbox.payload_snapshot)
```

### "审批人看不到任务"
```sql
SELECT id, approver_user_id, status FROM approval_task WHERE instance_id=<N>;
SELECT id, exception_type, status, detail FROM approval_exception WHERE instance_id=<N>;
```
若异常类型是 `approver_empty`：检查 `approval_instance.applicant_department_id` 是否为 NULL，以及节点 `approver_config.sources` 里 `department_admin` 是否依赖部门。

### "频道/知识空间审批通过但成员列表看不到"
检查对应 `sync_direct_channel_user_permissions` / `sync_direct_space_user_permissions` 是否在该激活路径被调用（写 ReBAC/OpenFGA 关系）。若 `instance=executed` 但 `space_channel_member.status` 仍为 `PENDING`，说明 `on_approved` 没真正激活成员（见 §6 的"业务回调不得静默失败"原则）。

---

## 12. 测试

审批相关测试在 `src/backend/test/approval/`（`asyncio_mode=auto`）。新测试放到该目录，不放 `test/` 根。
```bash
cd src/backend && uv run pytest test/approval/
```

F046 同时跨 Approval 与 Knowledge owner，聚焦回归至少覆盖：
```bash
cd src/backend
uv run pytest \
  test/approval/test_dynamic_approver_service.py \
  test/approval/test_approval_decision_uow.py \
  test/approval/test_approval_deferred_outbox.py \
  test/approval/test_file_change_execution_worker.py \
  test/approval/test_file_change_compensation_scan.py \
  test/knowledge/test_file_change_policy_api.py \
  test/knowledge/test_file_change_policy_service.py \
  test/knowledge/test_file_change_request_service.py \
  test/knowledge/test_file_change_execution_coordinator.py \
  test/knowledge/test_file_change_production_mutation_step_owner.py \
  test/channel/test_file_change_approval_boundary.py
```
