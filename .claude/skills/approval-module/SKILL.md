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
```

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
| `approval/domain/services/approval_center_service.py` | 用户端：任务列表/详情、同意/拒绝、撤回、菜单申请、多节点流转 | `decide_task()`、`_advance_after_node_approved()`、`_dispatch_outbox()`、`_send_approval_notify()` |
| `approval/domain/services/approval_exception_service.py` | 管理端异常处理：重试/指定审批人/跳过节点/取消/标记完成 | `assign_approvers()`、`_resolve_exception_node()` |
| `approval/domain/services/approval_outbox_service.py` | outbox 执行与重试；成功后置 instance=EXECUTED | `execute_outbox()`、`retry_outbox()` |
| `approval/domain/services/approval_scenario_admin_service.py` | 管理端：场景/分支/流程/节点配置、异常列表 | — |
| `approval/domain/services/approver_resolver.py` | 解析审批人来源 `direct_user` / `department_admin` / `tenant_admin` | `resolve_approvers_from_sources()` |
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

### 三个场景 Handler

| 文件 | 类 |
|------|----|
| `approval/domain/services/menu_access_handler.py` | `MenuAccessApprovalHandler` |
| `approval/domain/services/channel_subscribe_scenario_handler.py` | `ChannelSubscribeScenarioHandler` |
| `approval/domain/services/knowledge_space_subscribe_scenario_handler.py` | `KnowledgeSpaceSubscribeScenarioHandler` |

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

三个场景由 `ApprovalRegistry.with_default_presets()` 注册。每个场景的业务入口在创建 `ApprovalGateRequest` 时**都需要传 `applicant_department_id`**（供 `department_admin` 审批人来源使用，查 `UserDepartmentDao.aget_user_primary_department()`）。

### 4.1 菜单权限申请 (`menu_access_request`)
- **入口**：Client `/workspace/menu-unavailable?plugin=xxx` → `POST /api/v1/approval/menu-access/apply`
- **Handler**：`MenuAccessApprovalHandler`
- `on_approved` 调 `UserMenuAccessService.grant_menu_access()`，自动补父级依赖（如 `knowledge_space` → 同时授权 `workstation`）；`on_revoke` 调 `revoke_menu_access()`
- 申请前校验 `ensure_application_allowed()`（`menu_approval_mode=false` 或已有权限时拒绝）

### 4.2 频道订阅审批 (`channel_subscribe_request`)
- **入口**：`channel/domain/services/channel_service.py::subscribe_channel()`（`REVIEW` 可见性频道）
- **Handler**：`ChannelSubscribeScenarioHandler`
- 通过 / pass 路径调 `ChannelService.sync_direct_channel_user_permissions()` 写 ReBAC(OpenFGA) 关系（否则成员不出现在 ReBAC 成员列表）
- `on_approved` 先把申请人的 **PENDING** membership 翻成 ACTIVE 再写 ReBAC；查 membership 必须用 `include_inactive=True`（CHANNEL 默认只查 ACTIVE），缺失时直接 raise。详见 [§11 调试指南](#11-调试指南) 的已知坑
- PENDING 时调 `_send_channel_approval_notification()` 通知审批人

### 4.3 知识空间加入审批 (`knowledge_space_subscribe_request`)
- **入口**：`knowledge/domain/services/knowledge_space_service.py::subscribe_space()`（`auth_type=APPROVAL`）
- **Handler**：`KnowledgeSpaceSubscribeScenarioHandler`
- 通过 / ACTIVE 路径调 `sync_direct_space_user_permissions()` 写 ReBAC 关系
- PENDING 时调 `_send_space_approval_notification()` 通知审批人

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

---

## 6. outbox 与 Celery

业务执行走 outbox：通过后写 `approval_outbox(PENDING)` → Celery `execute_approval_outbox` 执行 `handler.on_approved()` → 成功 outbox=SUCCESS、instance=EXECUTED；失败 outbox=FAILED、instance=EXECUTE_FAILED 并建 `execute_failed` 异常。

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
POST /approval/instances/{instance_id}/withdraw # 撤回
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
检查对应 `sync_direct_channel_user_permissions` / `sync_direct_space_user_permissions` 是否在该激活路径被调用（写 ReBAC/OpenFGA 关系）。

**已知坑（频道场景，2026-06 修复）**：`on_approved` 第一步 `_get_membership` 要找到那条 **PENDING** 的 membership 才能翻成 ACTIVE。但 `SpaceChannelMemberRepositoryImpl.find_membership` 对 `business_type=CHANNEL` 默认**只查 ACTIVE**，导致查不到 PENDING → 返回 None。激活路径（`approval_runtime_handler_factory._AsyncSpaceChannelMembershipAdapter.find_membership`、旧 `channel_subscribe_approval_handler._get_membership`）**必须传 `include_inactive=True`**。知识空间场景用的是 `SpaceChannelMemberDao.async_find_member`（不过滤状态），所以不受影响——这也是"知识空间正常、频道异常"的原因。

> 该 bug 还会被一个静默分支掩盖：旧版 `on_approved` 在 membership 缺失时 `return {'status':'missing_membership'}` 不抛异常 → outbox 仍标 success、instance 仍 executed，但 membership 永远停在 PENDING、ReBAC 从未写。现已改为 **raise**，让 outbox 进 FAILED + `execute_failed` 异常暴露问题。排查时若看到 instance=executed 但 `space_channel_member.status=PENDING`，就是这个老数据。

排查 SQL：
```sql
SELECT i.id, i.status, m.id, m.status
FROM approval_instance i JOIN space_channel_member m
  ON m.business_id=i.business_resource_id AND m.business_type='CHANNEL' AND m.user_id=i.applicant_user_id
WHERE i.scenario_code='channel_subscribe_request' AND i.status IN ('executed','approved') AND m.status='PENDING';
```

---

## 12. 测试

审批相关测试在 `src/backend/test/approval/`（`asyncio_mode=auto`）。新测试放到该目录，不放 `test/` 根。
```bash
cd src/backend && uv run pytest test/approval/
```
