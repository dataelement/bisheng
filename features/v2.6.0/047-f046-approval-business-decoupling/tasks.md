# Tasks: F045/F046 审批流程与业务职责解耦

**关联规格**: [spec.md](./spec.md)
**关联设计**: [design.md](./design.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | F045/F046 均未上线，不做旧实现兼容 |
| design.md | ✅ 已评审 | 2026-08-13 完成 Constitution Check 与接手测试评审 |
| tasks.md | ✅ 已拆解 | `/sdd-review tasks` 两轮自检 LGTM；81 个原子任务、34 条 AC 全覆盖 |
| 实现 | ✅ 已完成 | 81 / 81 完成；F045/F046 开发期旧 outbox 扩展已按用户确认原子删除 |

---

## 开发模式

- 按 Wave 执行；同 Wave 中无共同写文件的任务可并行，跨 Wave 必须满足显式依赖。
- 后端采用 Test-First：测试任务先落红，再执行配对实现任务；新测试分别放在 `test/approval/`、`test/permission/`、`test/knowledge/`、`test/channel/`。
- 基础设施任务只定义模型、协议和未发布 DDL，不混入业务行为。
- 所有 Celery 任务从 headers 读取显式正整数 `tenant_id`，设置 ContextVar，并在 `finally` 恢复；业务 task ID 只表示派发，不表示完成。
- F045/F046 当前实现未上线，可以删除或改写其耦合代码；不得改变菜单申请、频道订阅、知识空间加入三个已上线场景。
- 每完成一个实现任务，执行对应测试和 `scripts/arch-guard.sh`；涉及审批代码时同步检查 `approval-module` skill 是否仍与代码一致。

---

## Wave 0 — 数据与协议基础设施

- [x] **T001**: Approval 决定交付 ORM 模型
  **文件**: `src/backend/bisheng/approval/domain/models/approval_decision_outbox.py`
  **逻辑**: 定义 `ApprovalDecisionOutbox`、状态常量和 `(tenant_id, instance_id, decision_version)` 唯一约束；包含 claim token/lease、retry、permanent failure 字段，使用 `JsonType`/portable column type，不引入业务 payload。
  **回滚**: 新表可由停服回滚流程 drop；不得修改既有 `approval_outbox` 数据。
  **依赖**: 无

- [x] **T002**: F045 邀请业务 ORM 模型
  **文件**: `src/backend/bisheng/permission/domain/models/resource_user_invite_request.py`
  **逻辑**: 定义 `ResourceUserInviteRequest` 与 `awaiting_approval/queued/applying/applied/failed/closed`；保存业务绑定、角色快照/指纹、执行结果和 `(tenant_id, business_key, active_marker)` 唯一约束，JSON 字段使用 `JsonType`。
  **回滚**: 新表可由停服回滚流程 drop；不提供开发数据 backfill。
  **依赖**: 无

- [x] **T003**: 重写未发布 F046/F047 DDL
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f046_knowledge_space_file_change_approval.py`
  **逻辑**: 在保持当前单一 Alembic head 的前提下，让未发布 revision 与 T001/T002/F046 Knowledge 模型一致；删除 `approval_outbox` deferred token/heartbeat DDL，新增两个新表的 portable DDL/索引/唯一约束；upgrade/downgrade 只含 DDL，使用共享存在性检查。
  **验证**: `uv run alembic heads` 仅一行；`test/database/test_alembic_single_head.py` 通过；人工复核 DM8 大写反射、索引等价与 downgrade 顺序。
  **依赖**: T001, T002

- [x] **T004**: Approval 公共端口与版本化 DTO
  **文件**: `src/backend/bisheng/approval/domain/ports/scenario_policy.py`, `src/backend/bisheng/approval/domain/ports/decision_subscriber.py`
  **逻辑**: 定义 `ApprovalSubmissionCommand/Result`、`ApprovalDecisionEvent`、`ApprovalScenarioPolicy`、`ApprovalDecisionSubscriber` 和协议版本；端口只引用 Approval 自有类型，不 import Permission/Channel/Knowledge。
  **依赖**: 无

- [x] **T005**: 跨域静态边界测试
  **文件**: `src/backend/test/approval/test_approval_business_boundary.py`
  **逻辑**: 静态扫描并先落红：approval/worker approval 禁止导入 F045/F046 业务 service；Permission/Knowledge 禁止导入 Approval ORM/Repository；只有 `bisheng/bootstrap/approval_scenarios.py` 可同时引用端口与业务实现。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-26
  **依赖**: 无

---

## Wave 1 — F025 通用 submission、终态和决定交付

- [x] **T006**: Policy/subscriber registry 测试
  **文件**: `src/backend/test/approval/test_approval_decision_registry.py`
  **逻辑**: 覆盖按 scenario 注册/读取、重复注册、缺 subscriber、completion mode 不匹配、协议版本不匹配和冻结后注册；失败必须可在启动阶段观察。
  **覆盖 AC**: AC-03, AC-26, AC-27
  **依赖**: T004

- [x] **T007**: Policy/subscriber registry 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_registry.py`
  **逻辑**: 扩展 F025 registry 保存版本化 policy/subscriber，仅暴露通用协议；保留三个已上线 handler 注册和原语义，支持装配完成后的完整性校验与 freeze。
  **测试**: T006 全部通过
  **依赖**: T004, T006

- [x] **T008**: caller-owned submission UoW 测试
  **文件**: `src/backend/test/approval/test_approval_submission_service.py`
  **逻辑**: 业务 request、instance、首节点 task、action log、instance binding 同提交/同回滚；空审批人形成通用异常；F045/F046 禁止 pass；service 不自行 commit，不创建原业务 outbox。
  **覆盖 AC**: AC-01, AC-04, AC-07, AC-09, AC-15, AC-27
  **依赖**: T004, T007

- [x] **T009**: Approval submission service 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_submission_service.py`, `src/backend/bisheng/approval/domain/repositories/approval_instance_repository.py`
  **逻辑**: 在 caller session 内复用场景/流程解析并写 Approval bundle，返回 binding 与 post-commit effects；Repository 只增加 session-bound 通用原子原语，不包含 F045/F046 分支。
  **测试**: T008 全部通过
  **依赖**: T008

- [x] **T012**: Decision outbox claim/lease Repository 测试
  **文件**: `src/backend/test/approval/test_approval_decision_outbox_repository.py`
  **逻辑**: 覆盖 pending claim、未过期 processing 不重领、lease 到期换 token、错误 token 不 ack、retryable 回 pending+next_retry、permanent 进 failed、delivered 幂等和租户隔离。
  **覆盖 AC**: AC-08, AC-10, AC-11, AC-12, AC-34
  **依赖**: T001

- [x] **T013**: Decision outbox Repository 实现
  **文件**: `src/backend/bisheng/approval/domain/repositories/approval_decision_outbox_repository.py`
  **逻辑**: 实现带行锁和 claim token 的 claim/ack/retry/fail/list-recoverable；显式 tenant 上下文校验，不用 JSON 查询或数据库专属 upsert。
  **测试**: T012 全部通过
  **依赖**: T012

- [x] **T010**: 所有审批终态统一决定事件测试
  **文件**: `src/backend/test/approval/test_approval_terminal_decision_outbox.py`
  **逻辑**: 覆盖最后节点 approve、reject、withdraw、异常 cancel、instance 批量决定和并发双决定；终态与唯一 decision outbox 同事务，失败同回滚；管理员不可绕过 F045 policy，F046 资格故障失败关闭。
  **覆盖 AC**: AC-01, AC-08, AC-09, AC-10, AC-15, AC-18, AC-23, AC-27
  **依赖**: T001, T004, T007, T013

- [x] **T011**: 终态 UoW 与 policy 前置校验实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_center_service.py`, `src/backend/bisheng/approval/domain/services/approval_exception_service.py`
  **逻辑**: 所有 F045/F046 终态入口复用同一锁序/UoW并写决定事件；`authorize_decision()` 在通用管理员代办判断之前执行；旧场景继续创建原 `approval_outbox`，新场景不进入 executing/executed/execute_failed。
  **测试**: T010 全部通过
  **依赖**: T010

- [x] **T014**: 决定交付 Service 测试
  **文件**: `src/backend/test/approval/test_approval_decision_delivery_service.py`
  **逻辑**: 覆盖 subscriber commit 后 ack 丢失、重复/延迟/乱序事件、未知 subscriber、协议版本、业务不存在、tenant/instance/fingerprint 不一致和临时数据库/broker失败分类；审批终态始终不回退。
  **覆盖 AC**: AC-08, AC-10, AC-11, AC-12, AC-21, AC-29, AC-30, AC-34
  **依赖**: T006, T013

- [x] **T015**: 决定交付 Service 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_decision_delivery_service.py`
  **逻辑**: claim 后构造版本化 event并调用 registry subscriber；subscriber 返回后按 claim token ack；区分 retryable/permanent，结构化日志携带四个关联 ID，不等待业务完成。
  **测试**: T014 全部通过
  **依赖**: T014

- [x] **T016**: Decision delivery Celery 测试
  **文件**: `src/backend/test/approval/test_approval_decision_delivery_worker.py`
  **逻辑**: 覆盖显式 tenant header、非法/缺失 tenant、ContextVar 设置与 finally 恢复、指数 backoff、lease reclaim 扫描、单事件失败不阻断后续事件；task ID 不作为完成证据。
  **覆盖 AC**: AC-10, AC-11, AC-30, AC-34
  **依赖**: T015

- [x] **T017**: Decision delivery Celery 实现
  **文件**: `src/backend/bisheng/worker/approval/decision_delivery_tasks.py`, `src/backend/bisheng/worker/approval/__init__.py`
  **逻辑**: 新增单事件交付和有界 recoverable outbox coordinator；走默认 `celery` 队列，headers→ContextVar，重试保留稳定 event ID。
  **测试**: T016 全部通过
  **依赖**: T016

- [x] **T018**: API/worker 同步装配测试
  **文件**: `src/backend/test/approval/test_approval_scenario_bootstrap.py`
  **逻辑**: API 与 Celery 创建入口调用同一无 I/O bootstrap；F045/F046 policy/subscriber/executor齐全；重复/缺失/版本错误使进程创建失败，三个旧场景仍注册原 handler。
  **覆盖 AC**: AC-03, AC-06, AC-26
  **依赖**: T007

- [x] **T021**: 通用 policy/reconcile 与查询隔离测试
  **文件**: `src/backend/test/approval/test_approval_policy_reconciliation.py`
  **逻辑**: F025 只接受业务域算好的 approver ID 集合，在 instance 锁内取消/新增 task并维护 approver_empty；列表/详情不扫描 Knowledge，历史终态 task不恢复决定资格，policy故障仅使决定失败关闭。
  **覆盖 AC**: AC-03, AC-05, AC-27, AC-28
  **依赖**: T007

- [x] **T022**: 通用 reconcile port 与 policy 决定接入
  **文件**: `src/backend/bisheng/approval/domain/services/approval_dynamic_assignee_service.py`, `src/backend/bisheng/approval/domain/services/approval_center_service.py`
  **逻辑**: 暴露 application-level `reconcile_assignees()`；移除查询前业务候选发现，任务查询只读 Approval；决定 UoW 调已注册 policy 实时校验并保持现有锁序/通知 effect。
  **测试**: T021 全部通过
  **依赖**: T021

- [x] **T023**: 已上线场景原 outbox 回归测试
  **文件**: `src/backend/test/approval/test_existing_scenario_outbox_regression.py`
  **逻辑**: 菜单、频道订阅、知识空间加入仍按 pass/flow、原 handler、原 outbox、异常和通知语义推进；不创建 decision outbox，不依赖新 subscriber。
  **覆盖 AC**: AC-06
  **依赖**: T011, T015

---

## Wave 2 — F045 邀请业务回归 Permission/资源授权域

- [x] **T078**: F045 token-safe 业务锁测试
  **文件**: `src/backend/test/permission/test_resource_user_invite_lock.py`
  **逻辑**: 覆盖稳定business key、token所有权释放、TTL、异常释放和锁失效时数据库唯一约束兜底；锁只降低争用，不作为正确性事实源。
  **覆盖 AC**: AC-14
  **依赖**: T002

- [x] **T079**: F045 token-safe 业务锁实现
  **文件**: `src/backend/bisheng/permission/domain/services/resource_user_invite_lock.py`
  **逻辑**: 将邀请锁放入Permission域，key只含tenant/resource type/resource id/target user；Lua/token-safe释放，所有异常路径可恢复，调用方仍处理唯一约束竞争。
  **测试**: T078 全部通过
  **依赖**: T078

- [x] **T024**: F045 Application Service 测试
  **文件**: `src/backend/test/permission/test_resource_user_invite_application_service.py`
  **逻辑**: 覆盖场景失败关闭、业务表先建后原子 submission、跨邀请人去重、active marker释放、failed占槽、角色快照/指纹、逐目标用户和待生效列表不扫描 Approval payload。
  **覆盖 AC**: AC-02, AC-07, AC-13, AC-14, AC-15, AC-19
  **依赖**: T002, T009, T079

- [x] **T025**: F045 Repository 与 Application Service 实现
  **文件**: `src/backend/bisheng/permission/domain/repositories/resource_user_invite_request_repository.py`, `src/backend/bisheng/permission/domain/services/resource_user_invite_application_service.py`
  **逻辑**: 业务唯一约束为最终去重，Redis锁只降争用；caller-owned session 内创建 request、调用 submission port、回填 instance；提供批量待生效查询和原审批结果业务重试。
  **测试**: T024 全部通过
  **依赖**: T024

- [x] **T026**: F045 policy/subscriber 测试
  **文件**: `src/backend/test/permission/test_resource_user_invite_approval_policy.py`
  **逻辑**: 被邀请人唯一 OR 审批、管理员不可代办、approved幂等置 queued并派发、reject/withdraw/cancel关闭、绑定/tenant/指纹错误永久拒绝、重复 event 与乱序 event 不重复执行。
  **覆盖 AC**: AC-11, AC-12, AC-15, AC-16, AC-17, AC-18, AC-26, AC-27
  **依赖**: T004, T025

- [x] **T027**: F045 policy 与决定 subscriber 实现
  **文件**: `src/backend/bisheng/permission/domain/services/resource_user_invite_approval_policy.py`, `src/backend/bisheng/permission/domain/services/resource_user_invite_decision_subscriber.py`
  **逻辑**: policy只生成安全快照/唯一本人审批人并做前置资格校验；subscriber仅按 business request ID锁权威申请，提交 queued/closed 后以稳定 request ID派发业务 task。
  **测试**: T026 全部通过
  **依赖**: T026

- [x] **T028**: ResourceGrantExecutor registry 测试
  **文件**: `src/backend/test/permission/test_resource_grant_executor_registry.py`
  **逻辑**: 覆盖 knowledge_space/channel executor 注册、重复/缺失类型启动失败、未知资源失败关闭，以及 registry 不 import 两个资源 owner 实现。
  **覆盖 AC**: AC-02, AC-03, AC-16, AC-26
  **依赖**: T004

- [x] **T029**: ResourceGrantExecutor 端口与 registry 实现
  **文件**: `src/backend/bisheng/permission/domain/ports/resource_grant_executor.py`, `src/backend/bisheng/permission/domain/services/resource_grant_executor_registry.py`
  **逻辑**: 定义稳定授权命令和权威读后校验结果；registry按 resource type分派，具体 Knowledge/Channel owner只由 composition root 注入。
  **测试**: T028 全部通过
  **依赖**: T028

- [x] **T030**: Knowledge 权限授权接入 F045 测试
  **文件**: `src/backend/test/permission/test_resource_authorization_invite_decoupling.py`
  **逻辑**: 新个人用户只创建 F045业务申请；部门/用户组、已有用户修改/移除保持直接授权；确认执行重读资源/用户/角色并经 `PermissionService.authorize`，副作用成功但 ack丢失可权威幂等确认。
  **覆盖 AC**: AC-13, AC-14, AC-16, AC-17, AC-18, AC-19
  **依赖**: T025, T029

- [x] **T031**: Knowledge 资源授权 Service 解耦
  **文件**: `src/backend/bisheng/permission/domain/services/resource_authorization_service.py`
  **逻辑**: 删除对 Approval invite service/handler 的 import和 payload查询，调用 F045 Application Service；实现/适配 knowledge_space grant executor并保留 F033/F044范围、PermissionService统一写入口与现有响应契约。
  **测试**: T030 全部通过
  **依赖**: T030

- [x] **T032**: Channel 授权接入 F045 测试
  **文件**: `src/backend/test/channel/test_channel_authorization_invite_decoupling.py`
  **逻辑**: 与知识空间一致覆盖新增个人用户建业务申请、direct grant边界、本人确认后的 owner授权、重复派发幂等、失败只写 F045业务状态。
  **覆盖 AC**: AC-13, AC-14, AC-16, AC-17, AC-18, AC-19
  **依赖**: T025, T029

- [x] **T033**: Channel 授权 Service 解耦
  **文件**: `src/backend/bisheng/channel/domain/services/channel_authorization_service.py`
  **逻辑**: 删除对 Approval invite实现的 import，调用 Permission F045 Application Service；实现/适配 channel grant executor，保留 F026 ReBAC/OpenFGA和既有直接授权行为。
  **测试**: T032 全部通过
  **依赖**: T032

- [x] **T034**: F045 业务执行 worker 测试
  **文件**: `src/backend/test/permission/test_resource_user_invite_worker.py`
  **逻辑**: headers→tenant ContextVar、queued claim、稳定 execution token、applying/applied/failed、权威读后校验、重试原 request、重复 task和 broker不确定结果幂等；不写 ApprovalException/Outbox。
  **覆盖 AC**: AC-02, AC-16, AC-17, AC-30, AC-34
  **依赖**: T027, T029

- [x] **T035**: F045 业务执行 worker 实现
  **文件**: `src/backend/bisheng/worker/permission/resource_user_invite_tasks.py`, `src/backend/bisheng/worker/permission/__init__.py`
  **逻辑**: 默认 `celery` 队列执行授权和业务重试；显式 tenant header，worker只调 F045 Application Service/GrantExecutor；业务结果和通知提交在 Permission域。
  **测试**: T034 全部通过
  **依赖**: T034

- [x] **T036**: F045 查询/API 合约测试
  **文件**: `src/backend/test/permission/test_resource_user_invite_api_contract.py`
  **逻辑**: 待生效列表从业务表读取并批量组合只读审批状态；业务重试只允许 approved+failed 原申请；响应保持前端既有字段，审批中心返回安全快照且无授权执行投影。
  **覆盖 AC**: AC-05, AC-17, AC-19, AC-24
  **依赖**: T025, T031, T033

- [x] **T037**: F045 API adapter 与响应 Schema
  **文件**: `src/backend/bisheng/permission/api/endpoints/resource_permission.py`, `src/backend/bisheng/permission/domain/schemas/resource_authorization_schema.py`
  **逻辑**: endpoint只委托业务 Service；待生效查询和业务重试使用 business request ID，批量组合 Approval只读状态，不暴露角色内部结构或以 payload作为事实源。
  **测试**: T036 全部通过
  **依赖**: T036

- [x] **T038**: F045 审批/业务通知边界测试
  **文件**: `src/backend/test/permission/test_resource_user_invite_notifications.py`
  **逻辑**: F025只发待办/审批决定通知；Permission只在授权成功/失败发业务通知；重复事件/task不重复通知，日志不含完整角色快照或用户敏感数据。
  **覆盖 AC**: AC-29, AC-30
  **依赖**: T027, T035

- [x] **T039**: F045 业务通知实现
  **文件**: `src/backend/bisheng/permission/domain/services/resource_user_invite_application_service.py`, `src/backend/bisheng/approval/domain/services/approval_notification_service.py`
  **逻辑**: 将授权生效/失败通知迁出 F025 outbox回调；F025保留审批通知模板与时机，结构化日志使用关联 ID且不记录完整业务 payload。
  **测试**: T038 全部通过
  **依赖**: T038

- [x] **T040**: 删除 Approval 域 F045 业务实现
  **文件**: `src/backend/bisheng/approval/domain/services/resource_user_invite_service.py`, `src/backend/test/approval/test_resource_user_invite_service.py`
  **逻辑**: 删除未上线的Approval邀请业务service和已被T024/T036替代的旧测试；F045业务事实只来自Permission request表。
  **验证**: T005, T023, T024, T026, T036 通过
  **依赖**: T031, T033, T037, T039

- [x] **T041**: 删除 Approval 域 F045 handler
  **文件**: `src/backend/bisheng/approval/domain/services/resource_user_invite_scenario_handler.py`, `src/backend/test/approval/test_resource_user_invite_handler.py`
  **逻辑**: 删除未上线的Approval邀请handler及旧handler测试；scenario preset保留，运行时只由注册policy/subscriber驱动。
  **验证**: T005, T006, T023, T024 通过
  **依赖**: T040

- [x] **T080**: 删除 Approval 邀请锁和旧事务投影用例
  **文件**: `src/backend/bisheng/approval/domain/services/approval_business_lock.py`, `src/backend/test/approval/test_approval_invite_repository_transactions.py`
  **逻辑**: 删除Approval域邀请锁及依赖Approval payload/instance作为邀请事实的旧测试；由T078/T024覆盖锁与业务事务。
  **验证**: T005, T024, T078 通过
  **依赖**: T041, T079

---

## Wave 3 — F046 saga 完全回归 Knowledge

- [x] **T042**: F046 policy/subscriber 测试
  **文件**: `src/backend/test/knowledge/test_file_change_approval_policy_subscriber.py`
  **逻辑**: strict owner/manager初始解析、实时决定资格、故障fail-closed、approved置 queued并派发、其他终态closed+cleanup、重复/乱序/绑定错误、业务失败不回写 Approval。
  **覆盖 AC**: AC-11, AC-12, AC-20, AC-21, AC-22, AC-23, AC-26, AC-27
  **依赖**: T004, T009

- [x] **T043**: F046 policy 与决定 subscriber 实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_approval_policy.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_decision_subscriber.py`
  **逻辑**: 从原 scenario handler提取纯业务 policy和幂等 subscriber；只按 request ID锁 Knowledge权威申请，提交 queued/closed后派发 Knowledge task，不完成/失败 F025 outbox。
  **测试**: T042 全部通过
  **依赖**: T042

- [x] **T044**: F046 submission UoW 改造测试
  **文件**: `src/backend/test/knowledge/test_file_change_submission_decoupling.py`
  **逻辑**: request/stage/footprint与 Approval bundle同事务绑定；initial approvers由 Knowledge传入；不创建原 approval outbox/deferred token；四类 action与既有冲突/权限规则不变。
  **覆盖 AC**: AC-02, AC-04, AC-07, AC-20, AC-25, AC-27
  **依赖**: T009, T043

- [x] **T045**: F046 Application Service/UoW 接 submission port
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_service.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_uow.py`
  **逻辑**: 移除 ApprovalGate/Deferred业务耦合，caller-owned UoW内先写 Knowledge request再调 submission service并回填；保留 stage/footprint、四动作和 post-commit通知。
  **测试**: T044 全部通过
  **依赖**: T044

- [x] **T046**: Knowledge 独立 saga 状态机测试
  **文件**: `src/backend/test/knowledge/test_file_change_execution_decoupling.py`
  **逻辑**: approved后 queued→applying→applied/failed/compensating；失败重试生成新 Knowledge token并复用 approval instance；upload/rename/move/delete完成判据、OLD/NEW_VIEW和发布门禁不变，任何分支不写 F025执行状态。
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-34
  **依赖**: T043, T045

- [x] **T047**: Coordinator 与 mutation executor 去 F025 化
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_execution_coordinator.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_mutation_executor.py`
  **逻辑**: token、step、watchdog、complete/fail/resume全部只推进 Knowledge request/step/footprint；删除 Approval session-bound completion/cutover依赖，保留权威读后校验与补偿锁序。
  **测试**: T046及既有 coordinator/mutation focused tests通过
  **依赖**: T046

- [x] **T048**: F046 Knowledge worker 归属测试
  **文件**: `src/backend/test/approval/test_file_change_execution_worker.py`, `src/backend/test/approval/test_file_change_compensation_scan.py`
  **逻辑**: 所有文件执行/ack/watchdog/补偿/stage/delete cleanup任务位于 worker/knowledge并走 `knowledge_celery`；headers→ContextVar；worker只调 Knowledge service，不写 Approval ORM。
  **覆盖 AC**: AC-02, AC-03, AC-20, AC-21, AC-22, AC-23, AC-30, AC-34
  **依赖**: T047

- [x] **T049**: 搬迁 F046 worker 任务
  **文件**: `src/backend/bisheng/worker/knowledge/file_change_tasks.py`, `src/backend/bisheng/worker/approval/file_change_tasks.py`
  **逻辑**: 将现有任务迁入 Knowledge worker，改为 Knowledge token/state，保留逐租户keyset、指数退避、幂等owner调用和四类coordinator；删除 approval worker旧模块。
  **测试**: T048 全部通过
  **依赖**: T048

- [x] **T050**: F046 worker 注册与队列测试
  **文件**: `src/backend/test/approval/test_file_change_approver_reconcile_worker.py`, `src/backend/test/approval/test_file_change_beat_schedule.py`
  **逻辑**: 校验任务导入、Beat schedule和显式 `knowledge_celery` route；decision delivery仍走默认queue；所有租户级派发携tenant header，单租户失败隔离。
  **覆盖 AC**: AC-20, AC-21, AC-30, AC-32
  **依赖**: T049

- [x] **T051**: F046 worker 注册与 route 实现
  **文件**: `src/backend/bisheng/worker/__init__.py`, `src/backend/bisheng/worker/config.py`
  **逻辑**: 导入新 Knowledge tasks、移除 approval/file_change imports，在现有task_routes上增精确Knowledge route；保留 workflow/default队列行为。
  **测试**: T050 全部通过
  **依赖**: T050

- [x] **T052**: parser/scheduler 去 Approval callback 测试
  **文件**: `src/backend/test/knowledge/test_file_change_parser_handoff_decoupling.py`
  **逻辑**: upload以正式文件图、FGA写入和普通解析调度接收为业务完成；后续解析结果只更新KnowledgeFile/Knowledge request发布门禁，不携F025 outbox/token callback，不回退approved。
  **覆盖 AC**: AC-03, AC-20, AC-21, AC-22, AC-25
  **依赖**: T047

- [x] **T053**: parser/scheduler callback 解耦实现
  **文件**: `src/backend/bisheng/worker/knowledge/file_worker.py`, `src/backend/bisheng/worker/knowledge/scheduler.py`
  **逻辑**: 将F046 callback上下文改为纯Knowledge request/token或普通解析生命周期；移除对 worker/approval file_change task的导入，保留发布门禁和幂等调度。
  **测试**: T052及既有 parse worker tests通过
  **依赖**: T052

- [x] **T054**: 动态 owner/manager 外部对账边界测试
  **文件**: `src/backend/test/permission/test_file_change_approver_reconcile_decoupling.py`
  **逻辑**: 权限写成功后由Permission事件触发Knowledge resolver再调F025 reconcile port；页面惰性和Beat补偿漏事件；普通审批列表不扫描Knowledge，former task取消后失去决定资格。
  **覆盖 AC**: AC-05, AC-27, AC-28
  **依赖**: T022, T043

- [x] **T055**: 权限事件与 F046 对账 dispatcher 解耦
  **文件**: `src/backend/bisheng/permission/domain/services/file_change_approver_reconcile_dispatcher.py`, `src/backend/bisheng/permission/domain/services/resource_authorization_service.py`
  **逻辑**: dispatcher只调用Knowledge resolver公开端口与F025 reconcile application port，不 import Approval Repository/ORM；显式tenant header，OpenFGA失败不伪造空集合。
  **测试**: T054 全部通过
  **依赖**: T054

- [x] **T056**: 移除 F025 Deferred/F046 特例回归测试
  **文件**: `src/backend/test/approval/test_approval_deferred_outbox.py`, `src/backend/test/approval/test_approval_worker_deferred.py`
  **逻辑**: F045/F046不再产生processing/deferred/executing/executed/execute_failed；异常retry不进入业务resume；三个旧场景原同步handler success/failed语义不变；approval worker无F046任务。
  **覆盖 AC**: AC-03, AC-06, AC-09, AC-17, AC-22, AC-24
  **依赖**: T047, T051

- [x] **T057**: Approval outbox 恢复为既有场景语义
  **文件**: `src/backend/bisheng/approval/domain/models/approval_instance.py`, `src/backend/bisheng/approval/domain/services/approval_outbox_service.py`
  **逻辑**: 删除仅供未上线F045/F046使用的 Deferred token/heartbeat/resume和无剩余消费者的processing/deferred状态；保留v2.6.0既有pending/success/failed handler执行、异常和通知行为。
  **测试**: T023, T056及原outbox focused tests通过
  **依赖**: T056, T051, T059

- [x] **T058**: 删除 Approval UoW/Exception 的 F046 适配
  **文件**: `src/backend/bisheng/approval/domain/services/approval_uow.py`, `src/backend/bisheng/approval/domain/services/approval_exception_service.py`
  **逻辑**: 移除 require/fail/complete deferred、cutover/purge和F046 execute_failed resume分支；保留通用submission、决定、异常retry/cancel能力。
  **测试**: T010, T056及原exception tests通过
  **依赖**: T057

- [x] **T059**: 删除 F046 runtime handler/factory 分支
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_scenario_handler.py`, `src/backend/test/knowledge/test_file_change_scenario_handler.py`
  **逻辑**: 删除未上线F046 runtime handler和已由T042/T046覆盖的旧测试；F046行为由装配后的policy/subscriber和Knowledge saga完成。
  **验证**: T005, T006, T018, T023, T042, T056 通过
  **依赖**: T043, T051, T056

- [x] **T081**: runtime factory 与动态 hook 清理
  **文件**: `src/backend/bisheng/approval/domain/services/approval_runtime_handler_factory.py`, `src/backend/test/approval/test_approval_runtime_dynamic_hooks.py`
  **逻辑**: factory只保留三个已上线handler；旧动态hook测试改为断言F045/F046由registry policy处理、查询不扫描业务域。
  **验证**: T005, T006, T021, T023, T042 通过
  **依赖**: T041, T059

- [x] **T019**: Composition root 与 API 启动装配
  **文件**: `src/backend/bisheng/bootstrap/approval_scenarios.py`, `src/backend/bisheng/main.py`
  **逻辑**: 新建唯一 composition root；同步构造并注册 F045/F046 policy/subscriber/resource executor，`create_app()` 在接收请求前调用并 freeze，注册过程不访问数据库/网络。
  **测试**: T018 API 用例通过
  **依赖**: T007, T018, T027, T029, T043, T081

- [x] **T020**: Celery 启动装配
  **文件**: `src/backend/bisheng/worker/main.py`, `src/backend/bisheng/worker/__init__.py`
  **逻辑**: `create_celery_app()` 在创建 worker app 前同步调用同一 bootstrap；注册失败阻止启动；导入 decision delivery 与 Knowledge/F045 业务任务。
  **测试**: T018 worker 用例通过
  **依赖**: T017, T018, T019, T035, T051

---

## Wave 4 — API/Client 状态分离与回归

- [x] **T060**: 审批 API 不再投影业务状态测试
  **文件**: `src/backend/test/approval/test_approval_query_business_independence.py`
  **逻辑**: F045/F046列表详情只查Approval快照/事实，Knowledge/Permission不可用仍可读取；响应不含`business_status_projection`，决定资格故障仍fail-closed；批量决定只返回审批终态。
  **覆盖 AC**: AC-05, AC-09, AC-24, AC-27
  **依赖**: T022, T059

- [x] **T061**: Approval query/schema 删除业务 projection
  **文件**: `src/backend/bisheng/approval/domain/services/approval_center_service.py`, `src/backend/bisheng/approval/domain/schemas/approval_center_schema.py`
  **逻辑**: 删除runtime handler业务projection hook和F046执行字段；保留安全detail/payload快照、流程节点和审批时间线。
  **测试**: T060 全部通过
  **依赖**: T060

- [x] **T062**: Knowledge API 业务状态与重试测试
  **文件**: `src/backend/test/knowledge/test_file_change_business_status_api.py`
  **逻辑**: 文件页返回queued/applying/applied/failed/closed及只属于Knowledge的failure/retry/cleanup；retry复用approved instance和原request；审批中心并发决定只生效一次。
  **覆盖 AC**: AC-21, AC-22, AC-23, AC-24, AC-25
  **依赖**: T047, T053

- [x] **T063**: Knowledge API/Service 状态分离实现
  **文件**: `src/backend/bisheng/knowledge/api/endpoints/knowledge_space_file_change.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_application_service.py`
  **逻辑**: 查询真实Knowledge business state，retry/cleanup/compensation只调Knowledge；审批决定仍委托F025公共instance/task端口，不写Approval ORM。
  **测试**: T062 全部通过
  **依赖**: T062

- [x] **T064**: Client 审批中心状态分离测试
  **文件**: `src/frontend/client/src/components/approval/ApprovalCenterDialog.test.tsx`, `src/frontend/client/src/components/approval/approvalCenterFileChangeUtils.test.ts`
  **逻辑**: 审批中心不解析/展示business projection或执行失败；F045/F046只显示审批快照和审批终态；决定后Knowledge页刷新事件仍可触发。
  **覆盖 AC**: AC-05, AC-09, AC-24, AC-29
  **依赖**: T061

- [x] **T065**: Client Approval API 类型与工具去 projection
  **文件**: `src/frontend/client/src/api/approval.ts`, `src/frontend/client/src/components/approval/approvalCenterFileChangeUtils.ts`
  **逻辑**: 删除`FileChangeBusinessStatusProjection`和响应字段解析；保留F046安全快照、批量审批以及刷新所需space ID。
  **测试**: T064 工具/类型用例通过
  **依赖**: T064

- [x] **T066**: Client 审批中心组件去业务执行展示
  **文件**: `src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx`, `src/frontend/client/src/components/approval/FileChangeBusinessProjection.tsx`
  **逻辑**: 删除业务projection渲染和执行失败文案分支；审批中心只渲染`FileChangeBusinessContent`安全快照与审批流程，删除无消费者组件。
  **测试**: T064 组件用例通过
  **依赖**: T064, T065

- [x] **T067**: Client 文件页业务状态测试
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/FileChangeApproval.test.tsx`
  **逻辑**: 文件页独立展示queued/applying/applied/failed/closed，failed可重试、closed清理；审批approved不伪装业务成功，业务失败不回到审批异常。
  **覆盖 AC**: AC-17, AC-22, AC-23, AC-24
  **依赖**: T063

- [x] **T068**: Client 文件页状态/重试实现
  **文件**: `src/frontend/client/src/pages/knowledge/hooks/useFileChangeApproval.ts`, `src/frontend/client/src/pages/knowledge/SpaceDetail/FileChangeApprovalDetail.tsx`
  **逻辑**: 只消费Knowledge业务状态与业务retry API；审批决定状态和执行状态分区展示，不从Approval详情读取projection。
  **测试**: T067 全部通过
  **依赖**: T067

---

## Wave 5 — 文档、E2E、发布与最终门禁

- [x] **T069**: 同步 F045/F046 今天态设计
  **文件**: `features/v2.6.0/045-personal-user-invite-confirmation/design.md`, `features/v2.6.0/046-knowledge-space-file-change-approval/design.md`
  **逻辑**: 用实现后的业务申请/decision delivery/Knowledge saga覆盖旧handler/Deferred口径，保留原产品规则与已知坑，不仅保留顶部override注释。
  **依赖**: T041, T059, T068

- [x] **T070**: 同步 approval-module skill
  **文件**: `.claude/skills/approval-module/SKILL.md`
  **逻辑**: 更新主流程、代码锚点、五场景、表、Celery队列、API/通知矩阵和调试指南；明确F045/F046走decision delivery且业务失败不形成execute_failed，Knowledge worker走knowledge_celery。
  **依赖**: T041, T051, T057, T059, T061

- [x] **T071**: F045 API E2E
  **文件**: `src/backend/test/e2e/test_e2e_personal_user_invite_confirmation.py`
  **逻辑**: 创建邀请→本人审批→决定交付→授权生效；管理员代办失败、重复邀请、reject/withdraw/cancel、授权失败后原审批重试、consumer停机恢复、ack丢失幂等。
  **覆盖 AC**: AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-29, AC-30, AC-34
  **依赖**: T020, T037, T039, T041

- [x] **T072**: F046 API E2E
  **文件**: `src/backend/test/e2e/test_e2e_f046_file_change_approval.py`, `src/backend/test/e2e/test_e2e_f046_file_change_visibility.py`
  **逻辑**: upload/rename/move/delete申请、动态owner/manager、决定交付、Knowledge执行/失败/重试/补偿、发布门禁；审批保持终态，former审批人不可决定，consumer/worker恢复不重复副作用。
  **覆盖 AC**: AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-27, AC-28, AC-29, AC-30, AC-34
  **依赖**: T020, T051, T055, T059, T063, T068

- [x] **T073**: 已上线审批场景 focused regression
  **文件**: `src/backend/test/approval/test_channel_subscription_approval_integration.py`, `src/backend/test/approval/test_knowledge_space_subscription_approval_integration.py`
  **逻辑**: 联同菜单审批现有测试验证三场景仍走原outbox/handler、通知和异常语义；运行`test/approval/`全量并区分基线失败与本次失败。
  **覆盖 AC**: AC-06
  **依赖**: T023, T057, T059

- [x] **T074**: 前端质量与页面人工回归
  **文件**: `features/v2.6.0/047-f046-approval-business-decoupling/e2e-checklist.md`
  **逻辑**: 记录并执行Client F045/F046/审批中心操作清单；从`src/frontend/`运行`pnpm lint`、`pnpm typecheck`及聚焦组件测试，验证三语言key parity且不新增硬编码中文。
  **覆盖 AC**: AC-05, AC-19, AC-24, AC-29
  **依赖**: T066, T068, T071, T072

- [x] **T075**: 数据库与双数据库门禁
  **文件**: `src/backend/test/approval/test_approval_dialect_compat.py`, `src/backend/test/database/test_alembic_single_head.py`
  **逻辑**: 验证decision/invite模型只用portable类型、唯一约束和行锁；运行Alembic单head测试，MySQL migration smoke，登记DM8中央回归项；downgrade仅删本次新对象/字段。
  **覆盖 AC**: AC-07, AC-08, AC-11, AC-31, AC-32
  **依赖**: T003, T013, T025

- [x] **T076**: 停服发布与恢复演练
  **文件**: `features/v2.6.0/047-f046-approval-business-decoupling/release-checklist.md`
  **逻辑**: 固化停API/Beat/worker、核对v2.6.0、只读检查两个scenario/instance/业务表/broker为零、迁移、先worker后API/Beat、smoke和回滚条件；非零即阻止标准发布，不提供旧task/token adapter。
  **覆盖 AC**: AC-31, AC-32, AC-33, AC-34
  **依赖**: T020, T051, T071, T072, T075

- [x] **T077**: 最终架构、文档与代码审查
  **文件**: `features/v2.6.0/047-f046-approval-business-decoupling/tasks.md`
  **逻辑**: 运行T005静态边界、`scripts/arch-guard.sh`、ruff/focused backend、前端质量、`/e2e-test`与`/code-review`；确认release-contract、F045/F046/F047 design和approval skill一致，记录实际偏差并完成清单。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-06, AC-26, AC-30, AC-31, AC-32, AC-33, AC-34
  **依赖**: T069, T070, T073, T074, T076

---

## AC 追溯索引

| AC | 测试 / 验收任务 |
|---|---|
| AC-01 | T005, T008, T010, T077 |
| AC-02 | T005, T024, T028, T034, T044, T048, T077 |
| AC-03 | T005, T006, T014, T018, T021, T028, T048, T052, T077 |
| AC-04 | T005, T008, T044, T077 |
| AC-05 | T021, T036, T054, T060, T064, T072, T074 |
| AC-06 | T018, T023, T056, T073, T077 |
| AC-07 | T008, T024, T044, T071, T072, T075 |
| AC-08 | T010, T012, T014, T071, T072, T075 |
| AC-09 | T008, T010, T056, T060, T064, T071, T072 |
| AC-10 | T010, T012, T014, T016, T071, T072 |
| AC-11 | T012, T014, T026, T042, T071, T072, T075 |
| AC-12 | T012, T014, T026, T042, T071, T072 |
| AC-13 | T024, T030, T032, T071 |
| AC-14 | T024, T030, T032, T071, T078 |
| AC-15 | T008, T010, T024, T026, T071 |
| AC-16 | T026, T028, T030, T032, T034, T071 |
| AC-17 | T026, T030, T032, T034, T036, T056, T067, T071 |
| AC-18 | T010, T026, T030, T032, T071 |
| AC-19 | T024, T030, T032, T036, T071, T074 |
| AC-20 | T042, T044, T046, T048, T052, T072 |
| AC-21 | T014, T042, T046, T048, T052, T062, T072 |
| AC-22 | T042, T046, T048, T052, T056, T062, T067, T072 |
| AC-23 | T042, T046, T048, T062, T067, T072 |
| AC-24 | T036, T046, T056, T060, T062, T064, T067, T072, T074 |
| AC-25 | T044, T046, T052, T062, T072 |
| AC-26 | T005, T006, T018, T026, T028, T042, T077 |
| AC-27 | T006, T008, T010, T021, T026, T042, T044, T054, T060, T072 |
| AC-28 | T021, T054, T072 |
| AC-29 | T014, T038, T064, T071, T072, T074 |
| AC-30 | T014, T016, T034, T038, T048, T050, T071, T072, T077 |
| AC-31 | T075, T076, T077 |
| AC-32 | T050, T075, T076, T077 |
| AC-33 | T076, T077 |
| AC-34 | T012, T014, T016, T034, T046, T048, T071, T072, T076, T077 |

---

## 实际偏差记录

> 只留一行指针，设计论证回写 `design.md`。推翻已确认决策时必须先暂停并重新确认。

- 为避免删除 F046 runtime handler 时出现可导入但不可启动的中间态，先完成 T019/T020 并验证 API/worker 共享 bootstrap，再原子执行 T059/T081；未改变已确认架构。
- T057 删除开发期 `PROCESSING/DEFERRED` 后，既有三态 outbox 以 `instance=executing + update_time` 表达租约，并在终态写入时对 `claimed_at` 做 CAS；同时强制 worker tenant header 与 outbox tenant 一致。未新增持久化状态或兼容字段。

## 最终验证记录（2026-08-13）

- T057/T058 聚焦回归：54 passed；Approval 生产代码中旧 Deferred API、状态与三个 outbox 字段静态扫描零命中。
- 决定 UoW、审批终态、三线上场景、方言与 Alembic single-head：50 passed；F045/F046 E2E 与同步 bootstrap：34 passed；跨域边界与 decision repository 单独运行：13 passed。
- `test/approval/` 全量：335 passed / 16 failed。16 项均为既有测试夹具未设置 tenant ContextVar、未 mock 新批量查询/UserDao、旧 admin `create_node` mock 或尝试外连 MySQL；T057/T058、F045/F046、三线上场景聚焦集合无失败。
- `ruff check`、`ruff format --check`、`scripts/arch-guard.sh`、`git diff --check` 通过。
- Client focused Jest：5 suites / 43 tests passed；changed-file ESLint 与 `pnpm check-i18n` 通过。Frontend Platform typecheck 通过；Client typecheck 仅剩 4 个与本功能无关的既有错误，已登记在 `e2e-checklist.md`。
- 人工页面验收与生产停服演练未冒充执行；操作步骤、零存量阻断条件和证据栏分别固化在 `e2e-checklist.md`、`release-checklist.md`。
