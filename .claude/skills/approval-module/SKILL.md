---
name: approval-module
description: >-
  BiSheng 审批模块（审批中心 F025）的架构与代码参考。
  覆盖统一审批网关、多场景引擎、多节点流转、outbox 业务执行、站内信通知、异常处理。
  迭代审批功能或修复审批相关 Bug 前先读本 skill，可直接定位架构与代码锚点，无需全仓搜索。
  TRIGGER when: 用户要改动/修复"审批""审批中心""approval"相关功能（菜单权限申请、频道订阅审批、
  知识空间加入审批、应用发布审批、审批流程/节点配置、异常处理、outbox/Celery 执行），或排查审批通过后业务未生效、
  审批人看不到任务、站内信未发、撤回被 18118 拒等问题。
---

# 审批模块（审批中心 F025）

## ⚠️ 维护契约（修改代码后必读）

**本 skill 是审批模块的唯一权威参考，必须与代码永远一致。**
当你改动以下任意一项时，**同一个改动里必须同步更新本文件对应章节**，否则视为改动未完成：

- 主流程分支逻辑（`ApprovalGate.request_or_pass` 的 pass/flow/exception 分流、`decide_task` / `_advance_after_node_approved` 的节点流转）→ 更新 [§2 架构与主流程](#2-架构与主流程)
- 新增/删除/重命名服务文件或关键方法 → 更新 [§3 代码锚点](#3-代码锚点)
- 新增/删除预置场景或改动其触发入口、Handler、**seed 内容**（`approval_seed_service.DEFAULT_APPROVAL_SCENARIO_SEEDS`）→ 更新 [§4 预置场景](#4-预置场景)
- **改动 `approver_resolver` 的任一来源解析语义** → 更新 [§10 配置要点](#10-配置要点)，并当作**跨场景行为变更**处理：所有配了该来源的既有节点当场受影响，须跑全场景回归 + release note 声明
- 数据库表/状态枚举变化 → 更新 [§5 数据库表](#5-数据库表)
- API 路由增删改 → 更新 [§7 API 列表](#7-api-列表)
- 站内信触发时机/接收人变化 → 更新 [§8 站内信通知矩阵](#8-站内信通知矩阵)
- Celery 队列/路由变化 → 更新 [§6 outbox 与 Celery](#6-outbox-与-celery)

> 自检：改完代码后问自己"本 skill 里有没有哪句话现在变成假的了？"——有就改它。

---

## 1. 概述

审批中心是一套**通用多场景审批引擎**，所有场景共用同一套网关 / 路由 / 流程 / 节点 / 实例 / 任务 / outbox 机制。

**核心原则：审批"通过"与"执行业务"解耦为两步**——通过后只写 `approval_outbox(PENDING)`，由 Celery 异步执行业务 `on_approved()`，成功后实例才置 `EXECUTED`。

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
        └── ⚠️ 前置守卫：instance 非 PENDING 一律拒 18118（见下）
   业务对象被删 → cancel_instance_by_business() → instance(CANCELLED) + 通知有 task 的审批人（排除操作人）
```

**`withdraw_instance` 的终态守卫（2026-08-19 加，F055 T051 / AC-22）**：`withdraw_instance` 过去**只校验 `applicant_user_id`、不校验实例状态**，于是已 APPROVED / REJECTED / CANCELLED 的单子被直接打 API 也能「撤回」，`on_withdrawn` 照样触发——落到应用发布场景就是**已上线版本的 `app_version.terminal_state` 被反复改写成 `withdrawn`**。现在守卫是 `if instance.status != PENDING: raise ApprovalInstanceNotPendingError()`（**18118**，approval 段），位置在 `applicant_user_id` 校验**之后**、任何写入**之前**：
- 排在 applicant 之后是刻意的——反过来的话，陌生人打一个终态单子会拿到「已结束」而不是「无权限」，等于把「哪些单子还开着」探测出去。
- ⚠️ **这是审批模块公共 API 的行为收紧，对菜单权限申请 / 频道订阅 / 知识空间加入三个既有场景同样生效**。`executing` / `executed` / `execute_failed` / `exception` 四个审批后状态同样被拒（「已结束不能撤回」）。回归护栏在 `test/app_publish/test_withdraw_guard.py`（15 例，含频道订阅与知识空间加入两个既有场景）。

**多节点 / 会签**：`_advance_after_node_approved()` 实现顺序流转。
- OR 节点（`node_mode=or`）：任一人通过即把同节点其余 PENDING task 置 SKIPPED 并 advance。
- AND 节点（`node_mode=and`）：同节点全部通过才 advance。
- finalize 时若 `handler_key` 未注册，记录 error 后仍照常 APPROVED + 建 outbox（避免卡死）。

**异常实例也留痕**：`_create_exception_result()` 在创建异常后会补写 `action='approval.request.submit'` 审计日志（与正常 PENDING/PASS 分支一致）。

---

## 3. 代码锚点

> 路径相对 `src/backend/bisheng/`。这些是定位问题的第一入口。

### 后端服务

| 文件 | 职责 | 关键方法 |
|------|------|---------|
| `approval/domain/services/approval_gate.py` | 统一入口：路由匹配、实例创建、pass/pending/exception 分流 | `request_or_pass()`、`_create_exception_result()`、`_notify_admins_of_exception()` |
| `approval/domain/services/approval_center_service.py` | 用户端：任务列表/详情、同意/拒绝、撤回、**业务侧取消**、菜单申请、多节点流转 | `decide_task()`、`_advance_after_node_approved()`、`_dispatch_outbox()`、`_send_approval_notify()`、`withdraw_instance()`（**带 18118 终态守卫**）、**`cancel_instance_by_business()`**（公共 API，见 §4.5） |
| `approval/domain/services/approval_exception_service.py` | 管理端异常处理：重试/指定审批人/跳过节点/取消/标记完成 | `assign_approvers()`、`_resolve_exception_node()` |
| `approval/domain/services/approval_outbox_service.py` | outbox 执行与重试；成功后置 instance=EXECUTED | `execute_outbox()`、`retry_outbox()` |
| `approval/domain/services/approval_scenario_admin_service.py` | 管理端：场景/分支/流程/节点配置、异常列表 | — |
| `approval/domain/services/approver_resolver.py` | 解析审批人来源 `direct_user` / `department_admin` / `tenant_admin` | `resolve_approvers_from_sources()`、**`resolve_tenant_admin_user_ids()`** |
| `approval/domain/services/approval_seed_service.py` | **预置场景 seed（每租户）**：`DEFAULT_APPROVAL_SCENARIO_SEEDS` 三条 × 五行（scenario / route / flow / flow_version / node） | `seed_approval_scenarios_for_tenant()`、`seed_approval_scenarios_in_session()` |
| `approval/domain/services/approval_registry.py` | 场景预置目录 + handler 注册表 | `with_default_presets()`、`register_handler()`、`get_handler()` |
| `approval/domain/services/approval_runtime_handler_factory.py` | 为 outbox 执行 / 多节点 advance 重新构造运行时 handler | `build_runtime_handler(scenario_code)` |
| `approval/domain/services/approval_notification_service.py` | 站内信统一封装 | `notify_user()` / `notify_users()` / `notify_admins()` |
| `approval/domain/services/user_menu_access_service.py` | 菜单授权增删查，含父级菜单依赖自动补全 | `grant_menu_access()`、`revoke_menu_access()`、`ensure_application_allowed()` |
| `approval/domain/services/approval_service.py` + `message_handler.py` | **旧系统（已废弃）**：部门知识空间文件上传审批（`approval_request` 表），与审批中心独立，仅兼容存量、勿新增功能 | `ApprovalService.decide_request()` |
| `worker/approval/tasks.py` | Celery 任务（走默认 `celery` 队列） | `execute_approval_outbox`、`retry_approval_outbox` |
| `worker/config.py` | Celery 路由配置（审批任务**不**配路由，fall through 到默认队列） | `task_routes` |
| `approval/api/endpoints/approval_user.py` | Client 端 API（`/api/v1/approval/...`） | — |
| `approval/api/endpoints/approval_admin.py` | Platform 管理 API（`/api/v1/approval/admin/...`） | — |
| `approval/api/endpoints/approval.py` | 旧系统 legacy API（`/api/v1/approval/requests/...`），**已废弃** | — |

### 四个场景 Handler

| 文件 | 类 |
|------|----|
| `approval/domain/services/menu_access_handler.py` | `MenuAccessApprovalHandler` |
| `approval/domain/services/channel_subscribe_scenario_handler.py` | `ChannelSubscribeScenarioHandler` |
| `approval/domain/services/knowledge_space_subscribe_scenario_handler.py` | `KnowledgeSpaceSubscribeScenarioHandler` |
| **`app_publish/domain/services/app_publish_scenario_handler.py`**（⚠️ 不在 `approval/` 下，归 F055 应用发布域） | `AppPublishScenarioHandler` |

> ⚠️ Handler 是**鸭子类型**、没有基类可继承。完整协议九个方法：`validate` / `build_title` / `build_detail` / `build_business_link` / `resolve_approvers` / `on_approved` / `on_rejected` / `on_withdrawn` / `on_cancelled`。少一个的表现是审批时引擎深处抛 `AttributeError`——新场景务必照抄这九个。
> ⚠️ **`resolve_approvers` 必须显式转调 `resolve_approvers_from_sources`**：网关调它之后不再做别的，`department_admin` / `tenant_admin` / `direct_user` 这些通用来源**只因为 handler 主动调了那个函数才被解析到**。返回 `[]` 的症状与「管理员没配审批人」完全一样。

### 前端

| 文件 | 职责 |
|------|------|
| `src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx` | 审批中心弹窗（我的审批 + 我的申请 + 时间线） |
| `src/frontend/client/src/api/approval.ts` | 审批 API 封装，含 `ApprovalApiError`（非 200 自动抛出） |
| `src/frontend/client/src/pages/MenuUnavailablePage.tsx` | 无权限占位页 + 申请入口 |
| `src/frontend/client/src/layouts/MenuApprovalPluginGate.tsx` | 菜单审批路由守卫 |
| `src/frontend/platform/src/pages/ApprovalPage/index.tsx` | 管理后台审批页（场景/分支/流程/节点/异常） |
| `src/frontend/platform/src/controllers/API/approval.ts` | Platform 审批 API 封装 |

---

## 4. 预置场景

四个场景由 `ApprovalRegistry.with_default_presets()` 注册（仅是"目录/下拉来源"，**不等于已启用**）。每个场景的业务入口在创建 `ApprovalGateRequest` 时**都需要传 `applicant_department_id`**（供 `department_admin` 审批人来源使用，查 `UserDepartmentDao.aget_user_primary_department()`）。

**首次部署自动落库**（2026-08-19 重写，随 F055）：真身已从 `common/init_data.py::_init_default_approval_scenarios()` 迁到 **`approval/domain/services/approval_seed_service.py`**，`init_data` 那个函数现在只是转调的薄壳。三条 seed（`DEFAULT_APPROVAL_SCENARIO_SEEDS`）= 4.2 频道订阅审批 · 4.3 知识空间加入审批 · **4.4 应用发布**，各建五行「场景 → 默认分支(catch-all `match_config={}`, route_type=flow) → 默认流程 → 流程版本 → 单节点(node_mode=or 或签)」，场景 `enabled=True`。审批人来源：频道 `channel_owner`/`channel_manager`，知识空间 `knowledge_space_owner`/`knowledge_space_manager`，**应用发布 `department_admin` + `tenant_admin`**。菜单权限申请(4.1)**仍不**自动 seed（它是「管理员主动打开」的能力，在 seed 里偷偷启用等于把产品决策夹带进一次 seed 改动）。

⚠️ **两条已变的事实，别再照旧文办事**：
1. **租户是参数不是常量**。旧实现在六处硬编码默认租户，结果**开机之后新建的租户一个场景都没有**；现在两条建租户路径（`tenant_service.py:163`、`tenant_mount_service.py:245`）都调 `seed_approval_scenarios_for_tenant(tenant_id)`。"新租户需管理后台手工配置"这句话已经不成立。
2. **幂等键仍是 `(tenant_id, scenario_code)`，且这就是 AC-19 的全部**：场景行存在 → **整条 seed 跳过**（含流程、节点、分支），管理员改过的审批人 / 加过的节点不会被下次平台升级重置。

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

### 4.4 应用发布审批 (`app_publish_request`) — F055，2026-08-19 新增
- **入口**：`app_publish/domain/services/publish_approval_service.py`（`bisheng deploy` 管线的审批节点；**每次发布必审，无免审分支**，故 preset 的 `condition_fields=[]`）
- **Handler**：`AppPublishScenarioHandler`（`app_publish/domain/services/app_publish_scenario_handler.py`，**不在 `approval/` 下**）
- **审批人来源**：`department_admin`（owner 的**主部门**管理员）**∪** `tenant_admin`，同一 OR 节点或签；preset 另放行 `direct_user`，否则管理员改配后再也放不回一个具名审批人（管理页的来源下拉就是从 `approver_source_types` 建的）
- **`business_key` = `deployment_id`**：一次发布尝试 = 一个审批单
- **申请人是 owner 自然人，不是提交用的服务账号**——审批单的 `applicant_user_id` 取 `resource_owner_user_id`
- **不得自审**：「提交人不能批自己的发布」这条过滤在 **handler 出口**做，不在共享 resolver 里做——频道订阅与知识空间加入要的恰恰相反，一个 resolver 两套策略，策略跟着场景走
- **首节点站内信由 F055 自己发**（网关只建 task + 写审计、不发消息，见 §8 注）
- ⚠️ **终态回调的成功语义**：outbox 只按「有没有抛异常」判成败。「待上线（资源不足 / 拉起失败）」是**产品终态**（有应用态、有通知、有发布面呈现）→ **必须正常返回**；只有系统坏了才抛。判据是「这个申请会不会自己变好——会，就 return；不会，就 raise」

### 4.5 业务侧取消：`cancel_instance_by_business()` — 公共 API，2026-08-19 新增
`ApprovalCenterService.cancel_instance_by_business(*, instance_id=None, scenario_code=None, business_resource_type=None, business_resource_id=None, tenant_id=None, reason=None, operator_user_id=0, operator_user_name=None)`

**用途**：审批单指向的业务对象**已经不存在了**（首例：owner 删除了托管应用，F055 AC-35）→ 把在途单置 `CANCELLED`、PENDING task 置 `CANCELLED`、写 `action_log('cancelled')` + 审计 `approval.request.cancel`、通知**有 task 的审批人**（排除操作人本人）、最后调 `handler.on_cancelled()`。

四点容易踩：
- **两种寻址**：按 `instance_id`，或按业务对象（`scenario_code` + `business_resource_type` + `business_resource_id` + `tenant_id`）——删除钩子只知道自己的 id、不知道审批的存在，所以第二种是给它用的。
- **找不到在途单返回 `None`，不是报错**：「删一个从来没提交过发布的应用」是常态。
- **它不是 `cancel_exception_api`**：那个从**异常记录**起手（碰不到健康的 pending 单）、且通知**申请人**。这里申请人就是刚按下删除的人，他知道；需要被告知的是审批人——否则待办里留着一个指向已消失应用的任务。
- **`on_cancelled` 抛异常被吞**（记 log）：审批侧此时已经一致，钩子失败不该让实例停在半取消状态。

---

## 5. 数据库表

| 表名 | 说明 | 关键状态字段 |
|------|------|------------|
| `approval_scenario` | 租户下启用的审批场景 | `enabled` |
| `approval_route_rule` | 场景下条件分支（按 `sort_order` 匹配） | `route_type: pass/flow`、`enabled` |
| `approval_flow_definition` | 审批流程定义头 | — |
| `approval_flow_version` | 流程版本快照 | `is_active` |
| `approval_node_definition` | 流程版本内顺序节点 | `node_order`、`node_mode: or/and`、`approver_config` |
| `approval_instance` | 一次审批申请 | `pending/approved/rejected/withdrawn/executed/execute_failed/exception/cancelled` |
| `approval_task` | 分配给审批人的节点待办 | `pending/approved/rejected/skipped/cancelled` |
| `approval_exception` | 异常记录 | `open/resolved`，`exception_type: route_missing/approver_empty/execute_failed` |
| `approval_outbox` | 业务执行队列 | `pending/success/failed` |
| `approval_action_log` | 时间线日志 | — |
| `user_menu_access` | 用户级菜单授权（菜单审批专用） | `active/revoked` |
| `approval_request` | **旧系统（已废弃）**：部门知识空间文件上传审批，仅兼容存量 | — |

> 模型定义见 `approval/domain/models/approval_instance.py`、`approval_scenario.py`、`user_menu_access.py`。
> `approval_instance.latest_approver_user_id` 字段已定义但**当前从未赋值**（已知限制，需要时在 `decide_task` 里补）。
> **2026-08-19 补**：`approval_instance.status` 的取值集合没变，但 `cancelled` 现在**多了一条到达路径**——除既有的「异常被管理员取消」外，业务对象消失时由 `cancel_instance_by_business()` 直接置（§4.5）。同时 `pending → withdrawn` 现在**只能从 `pending` 出发**（18118 守卫，§2），此前任何状态都能被改写成 `withdrawn`。
> **无新表、无新枚举值**：应用发布场景完全复用既有九张表，`app_publish_request` 只是 `approval_scenario.scenario_code` 的一个新取值。

---

## 6. outbox 与 Celery

业务执行走 outbox：通过后写 `approval_outbox(PENDING)` → Celery `execute_approval_outbox` 执行 `handler.on_approved()` → 成功 outbox=SUCCESS、instance=EXECUTED；失败 outbox=FAILED、instance=EXECUTE_FAILED 并建 `execute_failed` 异常。

> **原则：业务回调（`on_approved` 等）不得静默失败。** 该执行成功/失败由「是否抛异常」判定：抛异常 → outbox=FAILED + `execute_failed` 异常暴露问题；正常返回 → 一律视为成功并置 instance=EXECUTED。因此前置条件缺失（如找不到要激活的 membership/资源）**必须 raise**，绝不能 `return {'status':'xxx'}` 之类把失败伪装成成功——否则会出现 instance=executed 但业务实际没生效的「假成功」，且无任何告警。

**dispatch 入口（两处，功能相同名字不同）：**
- `approval_center_service.py::_dispatch_outbox(outbox_id)` — `decide_task` 最后节点通过 / skip_node
- `approval_gate.py` PASS 分支 — 调 `execute_approval_outbox.delay(outbox_id)`

**Celery 队列：走默认 `celery` 队列。** `worker/config.py` **不**为 `bisheng.worker.approval.*` 配路由，任务自然 fall through 到默认队列。`workflow_celery` 专供工作流 DAG 执行，审批任务不占用。

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
POST /approval/instances/{instance_id}/withdraw # 撤回（⚠️ 仅 PENDING；非 PENDING 答 18118，见 §2）
GET  /approval/menu-access/pending-check       # 菜单申请前置校验
POST /approval/menu-access/apply               # 菜单权限申请
POST /approval/menu-access/{instance_id}/revoke-grant # 撤销菜单授权（审批人）
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

> **2026-08-19：路由本身零增删**（应用发布场景没有自己的审批端点，它复用上面这一套）。唯一的对外行为变化是 `withdraw` 多了 **18118**「该审批申请已结束，无法撤回」——错误码归 **approval 段 181xx**（`common/errcode/approval.py`），三语文案在 `src/frontend/packages/locales/src/api_errors/`。⚠️ **181 是审批引擎的段位，不是某个场景 owner 的段位**：在这里加码会同时收紧菜单权限 / 频道订阅 / 知识空间加入 / 应用发布四个场景，必须有全场景回归（`docs/constitution.md` C5 已登记该口径）。

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
| **应用发布审批创建（PENDING）** | 审批人 | `app_publish/domain/services/publish_notification_service.py::notify_approvers_of_new_task()`（`approval_task_pending`） |
| **业务对象消失致取消**（首例：应用被 owner 删除） | 有 task 的审批人，**排除操作人本人** | `ApprovalCenterService.cancel_instance_by_business()`（`approval_instance_cancelled`，2026-08-19 新增 action_code） |
| **应用上线终检遇容量不足 → 待上线** | owner + 超管 + 租户管理员（**无条件 union**） | `publish_notification_service.notify_pending_online()`（`app_publish_pending_capacity`，**非审批类**） |
| **应用拉起 / 探活失败 → 待上线** | 同上 | `publish_notification_service.notify_pending_online()`（`app_publish_deploy_failed`，**非审批类**） |

> 注：申请人侧"通过"通知是在**最后节点 finalize** 时发的（即审批通过即通知），不等 outbox 业务真正执行完。若要"业务执行成功"的精确通知，需在 `execute_outbox` 成功回调里补。

> ⚠️ **网关不发首节点站内信**（`approval_gate.py` 只建 task + 写审计）——**每个场景都在自己那侧补发**，四个场景无一例外。新加场景漏了这一步的症状是「审批人永远不知道有活」，而一切正常、无任何报错。

> ⚠️ **非审批类通知的 `message_type` 必须中性**（`MessageTypeEnum.NOTIFY`，走 `ApprovalNotificationService` → `send_generic_notify` 天然满足）。client 的 `isApprovalMessageType`（`NotificationsDialog.tsx:152-156`）只看 `message_type` 是不是 `request` / `approve`，**不看 action_code 白名单**——类型用错会长出一个点了就报错的跳转按钮。两条待上线通知走 `getNotificationText` 的兜底 key `com_notifications_action_{action_code}`，因此前端零改动。

> ⚠️ **待上线两类的收件人是无条件 union（`ApprovalNotificationService._get_admin_recipient_ids`），这与审批人解析的条件回退是两码事，别混用**：多通知一个超管无害；多解析出一个审批人 = 多一个能拍板的人。

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

### ⚠️ `tenant_admin` 来源的语义已变（2026-08-19，F055 T025 / AC-21）——**对三个既有场景与所有人工配置立即生效**

| | 旧（"务实近似"） | 新 |
|---|---|---|
| 解析什么 | `UserRoleDao.aget_roles_user([AdminRole])` = **全站平台超管**，**完全忽略 `tenant_id`** | `TenantAdminService.list_tenant_admins(tenant_id)` = **该租户真正的租户管理员** |
| 多租户下的后果 | 每个租户的审批全压到超管一人；真正被配成租户管理员的人**一条待办都收不到** | 各租户各自的管理员各管各的 |
| Root / 单租户 | 同上（恰好"能用"，掩盖了缺陷） | `list_tenant_admins` 对 Root **按构造返回 `[]`**（INV-T3：Root 的权威是全局超管权限，不是租户管理员授予），故**仅 Root 回退平台超管** |

三条不能改的性质：
1. **回退是条件式的，不是 union**。非 Root 租户没有管理员就是解析为空 → `approver_empty` 异常（管理员看得见、能处理），**往那里补超管正是这次要消灭的缺陷**。
2. **它不是 `ApprovalNotificationService._get_admin_recipient_ids`**。那个是超管 ∪ 租户管理员的**无条件 union**，且必须保持无条件——它挑的是**通知收件人**（多一个读者无害）；审批人解析是反面（多一个解析出的人 = 多一个能拍板的人）。两边任一方向的合并都会破坏另一边的契约。
3. **`list_tenant_admins` fail-closed**（权限后端不可达时返回 `[]`）：结果是一个管理员看得见的 `approver_empty` 异常，严格优于静默放宽「谁可以审批」。

> 🔁 **回归口径**：这条改的是**共享 resolver**，所以频道订阅 / 知识空间加入 / 菜单权限申请三个既有场景里凡是配了 `tenant_admin` 来源的节点，**审批人集合当场就变了**。改动这里必须跑全场景回归，并在 release note 里显著声明。

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

### "撤回接口返回 18118"
不是 bug：该实例已不是 `PENDING`（已通过 / 已驳回 / 已取消 / 已进入执行态）。查 `SELECT status FROM approval_instance WHERE id=<N>;`。前端应引导用户刷新列表——单子已经有终态了。**这是 2026-08-19 起的新行为，对所有场景生效**（§2）。

### "审批人从超管变成了别人 / 超管突然收不到某租户的待办了"
是 `tenant_admin` 来源语义变更的预期结果（§10）。查 `SELECT approver_user_id FROM approval_task WHERE instance_id=<N>;` 与该租户的租户管理员名单。**单租户（Root）部署下仍应解析到平台超管**——若解析为空，先看 `TenantAdminService.list_tenant_admins` 是不是因权限后端不可达而 fail-closed 返回了 `[]`（那会先落 Root 回退，不该为空）。

### "频道/知识空间审批通过但成员列表看不到"
检查对应 `sync_direct_channel_user_permissions` / `sync_direct_space_user_permissions` 是否在该激活路径被调用（写 ReBAC/OpenFGA 关系）。若 `instance=executed` 但 `space_channel_member.status` 仍为 `PENDING`，说明 `on_approved` 没真正激活成员（见 §6 的"业务回调不得静默失败"原则）。

---

## 12. 测试

审批相关测试在 `src/backend/test/approval/`（`asyncio_mode=auto`）。新测试放到该目录，不放 `test/` 根。
```bash
cd src/backend && uv run pytest test/approval/
```

**跨模块的审批测试有两处**（改审批公共 API 时两处都得跑）：
```bash
cd src/backend && uv run pytest test/approval test/app_publish
```
- `test/app_publish/test_withdraw_guard.py` —— 18118 终态守卫（含频道订阅 / 知识空间加入两个既有场景的回归）
- `test/app_publish/test_publish_notification.py` —— 六类事件触达与「消息不承载操作」的发送契约

> ⚠️ 2026-08-19 实测：`test/approval` 有 13 例失败，**全部是本批之前就红的既有漂移**（本地 MySQL 未起 4–5 例、fake 与被测 API 漂移 6 例、断言漂移 2 例），不是新引入的。改审批模块前先跑一次拿基线，别把既有红当成自己弄坏的。
