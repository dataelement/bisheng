# Tasks: F045 个人用户邀请本人确认后生效

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)（接手第一入口）
**版本**: v2.6.0（COFCO 0811 定制）

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 仅 PRD §1.2；同一资源同一用户的在途邀请不重复创建 |
| design.md | ✅ 已评审 | 用户确认当前分支重写版；场景不存在/关闭时新增个人用户降级为直接授权 |
| tasks.md | ✅ 已拆解 | `/sdd-review tasks`：LGTM；58 项、5 个 Wave |
| 实现 | ✅ 代码完成 | T001–T054 已完成；当前共 55 / 58 项完成，未完成项均为真实环境交付门禁 |
| E2E | ⚠️ 已生成待实跑 | API 自动化与人工清单已生成；本地无可用 API/default worker，4 项自动化 skip |

---

## 开发模式

- **后端 Test-First**：每个 Domain/API/Worker 测试任务先落红，再完成紧随其后的实现任务；新测试放在 `src/backend/test/{core,approval,permission,knowledge,channel,message,notification}/`。
- **仅 Client 前端**：只修改 `src/frontend/client/`；不修改 platform，不新增 Recoil、Context 或 UI/状态库。服务器状态用 react-query v4，本地权限草稿沿用 F044 hook。
- **无数据库迁移**：不新增表/列/索引；`processing` 只是既有 `String(32)` outbox 状态的新枚举值，`executing` 已存在。若实施发现必须 DDL，先停下更新 design 并重新确认。
- **Owner 边界**：Approval* 聚合与终态由 F025 Service/Repository 修改；频道授权写行为由 F026 `ChannelAuthorizationService` 修改；F044 create/settings 页面只做增量适配；F045 不新增旁路 DAO。
- **场景开关**：含新增个人用户的请求先检查场景；知识空间/频道授权在缺失/关闭时按既有实时校验降级为 direct，启用但本人确认流程非法时失败关闭。确认执行由业务域 worker 独占重试，禁止本次 FGA 写生成 `failed_tuple`。
- **Worker tenant**：发布 outbox 任务时沿用 `before_task_publish` 把当前 `tenant_id` 写入 Celery headers；worker `task_prerun` 恢复 `current_tenant_id` ContextVar。任务参数仍为 `outbox_id`，payload 不接受客户端 tenant。
- **共享文件回归**：`approval_gate.py`、`approval_center_service.py`、`approval_outbox_service.py`、`permission_service.py` 的默认行为必须由既有三场景/普通授权回归测试保护；F045 策略不得改变其他场景语义。
- **任务完成门禁**：每项完成后运行对应 focused test，并执行 `/task-review features/v2.6.0/045-personal-user-invite-confirmation <T-ID>` 后勾选。

---

## Tasks

### Wave 1 — 基础设施与可复用并发原语

- [x] **T001**: Approval 错误码与状态枚举
  **类别**: 基础设施
  **文件**: `src/backend/bisheng/common/errcode/approval.py`, `src/backend/bisheng/approval/domain/models/approval_instance.py`
  **逻辑**: 新增 F025 所有的 `ApprovalConfirmationFlowRequiredError`(18118)；为 `ApprovalOutboxStatus` 增加 `PROCESSING="processing"`。不改表结构，不修改既有错误码或状态值。
  **依赖**: 无

- [x] **T002**: 邀请锁与 outbox claim 配置
  **类别**: 基础设施
  **文件**: `src/backend/bisheng/core/config/settings.py`
  **逻辑**: 增加带默认值的 approval invite 配置：短业务锁 TTL、binding 锁 TTL/续租间隔、`outbox_claim_ttl_seconds`；claim TTL 必须校验为大于 approval Celery hard time limit 900 秒。省略 YAML 配置时行为可启动，不写环境专属值。
  **依赖**: 无

- [x] **T003**: Token-safe Redis 锁单元测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/core/test_token_safe_redis_lock.py`
  **逻辑**: 只写测试；以 fake async Redis 覆盖 `SET NX EX`、同 key 互斥、随机 token、Lua compare-and-delete、非 owner 不可释放、续租失败触发 lock-lost、异常退出释放、TTL 配置校验。
  **测试**: `test_lock_uses_set_nx_ex`, `test_release_compares_token`, `test_renewal_loss_fails_closed`, `test_claim_ttl_exceeds_worker_hard_limit`
  **覆盖 AC**: AC-05, AC-19, AC-22, AC-23
  **依赖**: T002

- [x] **T004**: Token-safe Redis 锁实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/core/lock/__init__.py`, `src/backend/bisheng/core/lock/token_safe_redis_lock.py`
  **逻辑**: 提供 async context manager；原子获取、token-safe Lua 释放/续租，锁忙和续租丢失抛明确异常。core 层只依赖 Redis/config/logging，不 import domain/api。
  **测试**: T003 全部通过
  **覆盖 AC**: AC-05, AC-19, AC-22, AC-23
  **依赖**: T003

- [x] **T005**: Relation binding 原子修改测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/permission/test_relation_binding_mutation_service.py`
  **逻辑**: 只写测试；mock relation store 与 T004 锁，覆盖知识空间/频道共用全局锁、并发修改不丢更新、快照恢复、锁丢失不继续 FGA 提交、相同 binding 幂等。
  **测试**: `test_mutations_share_global_lock`, `test_concurrent_mutations_preserve_both_bindings`, `test_restore_snapshot`, `test_lock_loss_aborts_commit`
  **覆盖 AC**: AC-15, AC-18, AC-19, AC-32
  **依赖**: T004

- [x] **T006**: Relation binding 原子修改服务
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/permission/domain/services/relation_binding_mutation_service.py`
  **逻辑**: 封装 `permission_relation_model_bindings_v1` 的锁内读改写、规范 key、快照恢复和 lock-lost 检查；复用 `relation_model_store`，不直接写 ORM。后续知识空间/频道所有 binding mutation 均调用本服务。
  **测试**: T005 全部通过
  **覆盖 AC**: AC-15, AC-18, AC-19, AC-32
  **依赖**: T005

- [x] **T007**: PermissionService caller-owned recovery 测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/permission/test_permission_service_batch_write.py`
  **逻辑**: 只扩测试；覆盖默认 authorize 失败仍登记 `failed_tuple` 的兼容行为，以及 `recovery_owner="caller"` 时失败抛出但不登记、部分 legacy alias 写成功可由调用者获知并补偿、重复写保持幂等。
  **测试**: `test_default_failure_records_failed_tuple`, `test_caller_owned_failure_does_not_record_failed_tuple`, `test_caller_owned_partial_failure_is_raised`
  **覆盖 AC**: AC-09, AC-15, AC-18, AC-19, AC-28
  **依赖**: T001

- [x] **T008**: PermissionService caller-owned recovery 实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/permission/domain/services/permission_service.py`
  **逻辑**: 给 `authorize/batch_write_tuples` 增加内部显式 recovery owner；默认参数保持现有 `failed_tuple` 行为，邀请确认路径可要求 raise 且不登记自动重试。仍统一经 PermissionService/OpenFGA，不把审批语义写入本服务。
  **测试**: T007 与既有 permission service 全部通过
  **覆盖 AC**: AC-09, AC-15, AC-18, AC-19, AC-28
  **依赖**: T007

### Wave 2 — F025 邀请场景、审批原子性与 Worker

- [x] **T009**: Approval 邀请 Repository 事务测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/approval/test_approval_invite_repository_transactions.py`
  **逻辑**: 只写测试；覆盖按 resource/status 查在途实例、跨 applicant 业务键查重、instance+单 task+log 原子创建、本人 approve/reject、applicant withdraw、outbox claim 的条件更新与并发唯一终态；SELECT 依赖 C3 tenant injection，不新增手写 tenant where。
  **测试**: `test_find_blocking_invite_ignores_applicant`, `test_create_bundle_rolls_back_together`, `test_decide_single_task_accepts_one_terminal`, `test_withdraw_pending_only`, `test_claim_outbox_once_and_reclaim_after_ttl`
  **覆盖 AC**: AC-02, AC-05, AC-06, AC-12, AC-19, AC-20, AC-21, AC-22, AC-23, AC-29
  **依赖**: T001, T002

- [x] **T010**: Approval 邀请 Repository 事务实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/approval/domain/repositories/approval_instance_repository.py`
  **逻辑**: 扩展 F025 Repository：`find_blocking_invite`、`list_resource_invites`、`create_instance_bundle`、`decide_single_task`、`withdraw_pending_instance`、`claim_outbox`。使用单 session 事务与条件状态/行锁，终态冲突返回未更新，不在 Repository 判断角色或资源权限。
  **测试**: T009 全部通过并保持既有 approval repository 调用兼容
  **覆盖 AC**: AC-02, AC-05, AC-06, AC-12, AC-19, AC-20, AC-21, AC-22, AC-23, AC-29
  **依赖**: T009

- [x] **T011**: `ResourceUserInviteService` 单元测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/approval/test_resource_user_invite_service.py`
  **逻辑**: 只写测试；mock T004/T010/Gate，覆盖业务键、首次角色快照/指纹、同资源同用户跨邀请人去重、不同资源独立、终态后可重邀、场景不存在/关闭 18106 且零副作用、目标用户/tenant/F033 按项失败。
  **测试**: `test_business_key_excludes_inviter`, `test_duplicate_returns_first_instance_and_role`, `test_terminal_invite_allows_new_instance`, `test_missing_or_disabled_scenario_returns_18106_before_side_effect`, `test_target_validation_is_per_item`
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-24, AC-25, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T004, T010

- [x] **T012**: 邀请业务锁与 Invite Service 实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_business_lock.py`, `src/backend/bisheng/approval/domain/services/resource_user_invite_service.py`
  **逻辑**: 锁键包含 tenant/resource/target；锁内持久查重并调用 Gate。构造 schema v1 payload、规范角色快照/SHA-256；场景前置门禁统一抛 18106 专用文案；重复返回 `invite_existing` 和首次快照，不修改原实例。
  **测试**: T011 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-24, AC-25, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T011

- [x] **T013**: 邀请场景 Handler 单元测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/approval/test_resource_user_invite_handler.py`
  **逻辑**: 只写测试；覆盖 title/detail、唯一 `invited_user`、本人 task 再校验、角色指纹、邀请人身份重建、资源/目标/范围实时校验、知识空间/频道执行分派、更新在途实例阻止旧失败重试、exact 授权幂等。
  **测试**: `test_resolve_only_target_user`, `test_execute_requires_target_approved_task`, `test_role_fingerprint_must_match`, `test_dispatches_to_resource_owner_service`, `test_newer_invite_blocks_old_retry`, `test_exact_effect_is_idempotent`
  **覆盖 AC**: AC-12, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T010, T012

- [x] **T014**: 邀请场景 Handler 实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/approval/domain/services/resource_user_invite_scenario_handler.py`
  **逻辑**: 实现场景展示、唯一处理人和 `requires_self_confirmation`/business-key dedupe/18106 message 策略；`on_approved` 校验本人 task 与快照后，按 resource type 调用两个 owner Service 的 confirmed command。确定失败抛业务异常，可重试补偿抛专用 retryable 异常。
  **测试**: T013 全部通过
  **覆盖 AC**: AC-12, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T013

- [x] **T015**: ApprovalGate 强制策略与原子建单测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/approval/test_approval_gate.py`
  **逻辑**: 只扩测试；handler-first，场景缺失/关闭均为带专用消息的 18106；pass、多节点、非 or、非唯一 target 为 18118；invite 使用跨 applicant statuses `pending/approved/executing`；实例/task/log 原子创建。既有三场景默认查重和 pass 行为保持。
  **测试**: `test_invite_disabled_fails_before_instance`, `test_invite_pass_route_rejected`, `test_invite_requires_single_or_target`, `test_invite_uses_business_key_dedupe`, `test_existing_scenarios_keep_default_policy`
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-05, AC-12, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29
  **依赖**: T010, T014

- [x] **T016**: ApprovalGate 策略扩展实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_gate.py`
  **逻辑**: 在查重前加载 handler policy；仅邀请场景改用业务键查重和强制流程校验，调用 T010 原子 bundle。场景二次检查沿用 18106 专用文案；其他 handler 保持现有 applicant 去重、pass/flow/exception 语义。
  **测试**: T015 与现有 approval gate 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-05, AC-12, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29
  **依赖**: T015

- [x] **T017**: ApprovalCenter 本人终态测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/approval/test_approval_center_decide_task.py`
  **逻辑**: 只扩测试；邀请场景管理员不可代办；approve/reject/withdraw 仅 pending；并发只接受一个终态；approve 原子创建 outbox；重复请求 18102；其他场景管理员/多节点行为不变。
  **测试**: `test_invite_admin_cannot_act_for_target`, `test_invite_approve_creates_outbox_atomically`, `test_invite_reject_withdraw_race_has_one_terminal`, `test_finished_invite_returns_18102`, `test_non_invite_admin_behavior_unchanged`
  **覆盖 AC**: AC-12, AC-20, AC-21, AC-22, AC-23, AC-29
  **依赖**: T010, T014

- [x] **T018**: ApprovalCenter 本人终态实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_center_service.py`
  **逻辑**: 根据 runtime handler policy 对邀请场景走 T010 单节点事务；强制 operator=approver=target，拒绝 admin 代办；withdraw 必须 applicant+pending。邀请 approved 只表示等待生效，不发送通用“授权成功”语义。其他场景路径不改。
  **测试**: T017 与 approval center 既有测试全部通过
  **覆盖 AC**: AC-12, AC-20, AC-21, AC-22, AC-23, AC-29
  **依赖**: T017

- [x] **T019**: ApprovalOutbox claim 与三态执行测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/approval/test_approval_outbox_service.py`
  **逻辑**: 只扩测试；覆盖 pending/failed 原子 claim、未过 TTL 拒绝并行、过 TTL 重领、success→executed、确定失败→execute_failed、补偿不确定→保持 processing/executing 并 retry、重复成功幂等。
  **测试**: `test_claim_runs_once`, `test_processing_reclaimed_only_after_ttl`, `test_retryable_keeps_executing`, `test_definitive_failure_marks_execute_failed`, `test_duplicate_success_is_idempotent`
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-22, AC-23, AC-29
  **依赖**: T002, T010, T014

- [x] **T020**: ApprovalOutbox claim 与三态执行实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_outbox_service.py`
  **逻辑**: 执行前调用 T010 claim；区分 success/definitive failure/retryable，维护 processing/executing/executed/execute_failed。写 handler 审计时不打印完整敏感 payload；非邀请 handler 的 bool tuple executor 保持兼容。
  **测试**: T019 全部通过
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-22, AC-23, AC-29
  **依赖**: T019

- [x] **T021**: 场景注册与默认种子测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/approval/test_approval_registry.py`, `src/backend/test/approval/test_init_default_approval_scenarios.py`
  **逻辑**: 只写测试；preset 暴露 `invited_user`；API registry/worker factory 都能构建 handler；默认租户首次初始化创建启用场景、catch-all flow route、单 or 节点；已有场景不覆盖、不重复。
  **测试**: `test_invite_preset_and_runtime_registered`, `test_seed_invite_single_or_node`, `test_seed_existing_invite_not_overwritten`
  **覆盖 AC**: AC-24, AC-25, AC-26, AC-27, AC-28, AC-29
  **依赖**: T014

- [x] **T022**: 场景 API/Worker 双注册实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_registry.py`, `src/backend/bisheng/approval/domain/services/approval_runtime_handler_factory.py`
  **逻辑**: 注册 `resource_user_invite_confirmation` preset 与 runtime handler；approver source 仅 `invited_user`。factory 用局部 import 构建两类资源依赖，避免模块 import cycle。
  **测试**: T021 注册断言通过
  **覆盖 AC**: AC-24, AC-26, AC-27, AC-28, AC-29
  **依赖**: T021

- [x] **T023**: 默认邀请场景幂等种子实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/common/init_data.py`
  **逻辑**: 在现有默认审批场景 seeds 中追加 F045；首次初始化创建启用场景、flow/version、唯一“被邀请用户确认”or 节点和 catch-all flow route；`(tenant,scenario_code)` 已存在时完整跳过，不覆盖管理员配置。
  **测试**: T021 seed 断言与现有种子测试全部通过
  **覆盖 AC**: AC-24, AC-25, AC-26, AC-29
  **依赖**: T021

- [x] **T024**: Approval Worker tenant/claim/retry 测试
  **类别**: Worker 测试
  **文件**: `src/backend/test/approval/test_approval_worker_tasks.py`
  **逻辑**: 只扩测试；发布时当前 tenant 进入 Celery headers，`task_prerun` 恢复 ContextVar 后再读 instance/资源；worker 消费三态结果，retryable 触发 Celery retry，setup failure 不能把已终态实例覆盖成失败。
  **测试**: `test_publish_carries_tenant_header`, `test_worker_context_restored_before_handler`, `test_retryable_execution_retries`, `test_setup_failure_preserves_terminal_instance`
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-22, AC-23, AC-29
  **依赖**: T020, T022

- [x] **T025**: Approval Worker claim/retry 实现
  **类别**: Worker 实现
  **文件**: `src/backend/bisheng/worker/approval/tasks.py`
  **逻辑**: 任务签名保留 `outbox_id`；依赖全局 `before_task_publish` headers 与 `task_prerun` ContextVar 恢复 tenant。调用 T020 claim/execute；retryable 抛 Celery retry，确定失败记录异常；不以 task id/入队成功当业务成功。
  **测试**: T024 与既有 worker tests 全部通过
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-22, AC-23, AC-29
  **依赖**: T024

- [x] **T026**: 邀请通知与外部转发测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/message/test_resource_user_invite_notifications.py`, `src/backend/test/notification/test_resource_user_invite_payload.py`
  **逻辑**: 只写测试；建单后通知目标用户并跳审批中心；消息失败不改变审批事实；executed 后通知邀请人生效，reject/withdraw/execute_failed 使用准确语义；action code 进入审批消息过滤和 E+ allowlist/template。
  **测试**: `test_pending_notifies_target`, `test_notification_failure_keeps_task`, `test_effective_only_after_executed`, `test_terminal_messages_are_distinct`, `test_eplus_payload_whitelisted`
  **覆盖 AC**: AC-03, AC-04, AC-13, AC-15, AC-16, AC-17, AC-18, AC-20, AC-21
  **依赖**: T016, T018, T020

- [x] **T027**: 审批邀请站内信实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_notification_service.py`, `src/backend/bisheng/message/domain/services/message_service.py`
  **逻辑**: 增加 `resource_user_invite_pending/effective/failed` action code；pending receiver=target，effective/failed receiver=inviter；消息只提醒/跳转，不改变 instance/task。发送失败记录日志但不降级授权。
  **测试**: T026 message 断言通过
  **覆盖 AC**: AC-03, AC-04, AC-13, AC-15, AC-16, AC-17, AC-18, AC-20, AC-21
  **依赖**: T026

- [x] **T028**: 邀请通知 E+ payload 实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/notification/external/_payload.py`
  **逻辑**: 将三个 action code 加入 forwardable allowlist 和模板映射；payload 只含资源名/审批跳转所需字段，不转发角色权限集合或敏感快照。
  **测试**: T026 external payload 断言通过
  **覆盖 AC**: AC-03, AC-04, AC-13, AC-16, AC-17, AC-18, AC-20, AC-21
  **依赖**: T026

- [x] **T029**: 同步 approval-module Skill
  **类别**: 文档/知识索引
  **文件**: `.claude/skills/approval-module/SKILL.md`
  **逻辑**: 实现完成后同步第四场景、handler 注册点、`invited_user`、本人-only、processing/executing 状态、outbox 三态、18118 与通知矩阵；只记录实际落地事实，不提前写未完成内容。
  **依赖**: T022, T025, T028

### Wave 3 — 两类资源授权、待生效投影与创建编排

- [x] **T030**: 知识空间邀请分类与确认执行测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/permission/test_resource_authorization_service.py`
  **逻辑**: 只扩测试；新增显式个人 grant 转邀请；部门/组、已有显式个人修改/revoke 直接执行；继承权限不算已有个人；场景 18106 在任何 direct/创建副作用前；confirmed command 双时点校验、binding 预写、caller-owned FGA、部分失败补偿/幂等；pending projection。
  **测试**: `test_new_direct_user_becomes_invite`, `test_department_group_and_existing_user_stay_direct`, `test_inherited_user_still_requires_invite`, `test_disabled_scenario_has_zero_side_effect`, `test_confirmed_grant_revalidates_and_compensates`, `test_list_merges_pending_instances`
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T006, T008, T012, T014

- [x] **T031**: 知识空间授权编排与响应 Schema 实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/permission/domain/services/resource_authorization_service.py`, `src/backend/bisheng/permission/domain/schemas/permission_schema.py`
  **逻辑**: `authorize()` 返回逐项 AuthorizationResult；预检 18106、按显式权限分类 direct/invite；direct binding 改走 T006。增加 `apply_confirmed_personal_user_grant()`，单 user、非递归、双时点校验、预写 binding、caller-owned FGA、验证补偿；列表合并 blocking instances。
  **测试**: T030 全部通过且普通资源授权回归不变
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T030

- [x] **T032**: 知识空间 authorize/list API 合约测试
  **类别**: 后端 API 测试
  **文件**: `src/backend/test/permission/test_resource_user_invite_permission_api.py`
  **逻辑**: 只写 HTTP 测试；POST 请求保持 grants/revokes，返回逐项结果；场景缺失/关闭 envelope 为 18106 专用文案且 data 无成功项；GET active+pending 字段；无管理权限/跨租户不可见。
  **测试**: `test_authorize_returns_item_results`, `test_disabled_scenario_returns_explicit_18106`, `test_permissions_expose_pending_readonly_fields`, `test_pending_is_tenant_scoped`
  **覆盖 AC**: AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-29, AC-30, AC-32
  **依赖**: T031

- [x] **T033**: 知识空间权限 Endpoint 接入结果
  **类别**: 后端 API 实现
  **文件**: `src/backend/bisheng/permission/api/endpoints/resource_permission.py`
  **逻辑**: authorize endpoint 返回 T031 AuthorizationResult；permissions endpoint 委托 Service 合并 pending，保持现有 envelope/认证/候选接口。不得在 endpoint 写 Approval ORM 或新增 403 业务分支。
  **测试**: T032 与既有 permission API tests 全部通过
  **覆盖 AC**: AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-29, AC-30, AC-32
  **依赖**: T032

- [x] **T034**: 频道邀请分类与确认执行测试
  **类别**: 后端 Domain 测试
  **文件**: `src/backend/test/channel/test_channel_authorization_service.py`
  **逻辑**: 只扩测试；与 T030 相同的分类，场景缺失/关闭时新增个人用户降级 direct，confirmed command 与 pending projection 保持；额外固化 creator 防护、channel tenant、grant-tier、原计数字段和 F026 通知语义。
  **测试**: `test_channel_new_user_becomes_invite`, `test_channel_direct_operations_unchanged`, `test_channel_disabled_scenario_degrades_to_direct_authorization`, `test_channel_confirmed_grant_compensates`, `test_channel_pending_projection`, `test_channel_counts_compatible`
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-27, AC-28, AC-29, AC-31, AC-32
  **依赖**: T006, T008, T012, T014

- [x] **T035**: 频道授权编排与响应 Schema 实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/channel/domain/services/channel_authorization_service.py`, `src/backend/bisheng/channel/domain/schemas/channel_authorization_schema.py`
  **逻辑**: F026 Service 增加 direct/invite 分类、启用场景门禁、缺失/关闭时 direct 降级、逐项结果、confirmed command 和 pending projection；所有 binding mutation 走 T006；保留 `synced_user_count/affected_member_count`、creator/tenant/grant-tier/通知兼容。
  **测试**: T034 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-27, AC-28, AC-29, AC-31, AC-32
  **依赖**: T034

- [x] **T036**: 频道 authorize/list API 合约测试
  **类别**: 后端 API 测试
  **文件**: `src/backend/test/channel/test_channel_authorization_api.py`
  **逻辑**: 只扩 HTTP 测试；POST 结果包含旧计数+逐项结果；场景缺失/关闭返回 direct applied 结果；GET pending 字段；跨租户和无管理权限拒绝；旧请求兼容。
  **测试**: `test_channel_authorize_returns_item_results`, `test_channel_disabled_scenario_returns_direct_authorization_result`, `test_channel_permissions_include_pending`, `test_channel_old_request_compatible`
  **覆盖 AC**: AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-29, AC-32
  **依赖**: T035

- [x] **T037**: 频道权限 Endpoint 接入结果
  **类别**: 后端 API 实现
  **文件**: `src/backend/bisheng/channel/api/endpoints/channel_manager.py`
  **逻辑**: authorize/list endpoint 透传 T035 结果，保持路径、认证、envelope、审计和候选查询不变；Endpoint 不跨 import permission API helper。
  **测试**: T036 与既有 channel API tests 全部通过
  **覆盖 AC**: AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-29, AC-32
  **依赖**: T036

- [x] **T038**: 知识空间创建邀请 Test-First
  **类别**: 后端 Domain/API 测试
  **文件**: `src/backend/test/knowledge/test_knowledge_space_creation_application_service.py`, `src/backend/test/knowledge/test_knowledge_space_create_initial_permissions_api.py`
  **逻辑**: 只扩测试；无 permissions 旧行为；有新增 user 时创建前检查场景，缺失/关闭则创建资源并按既有实时校验 direct 授权；启用态资源只建一次，个人逐项、direct 正常；mixed failure 保留资源和 results；恢复输入仅失败 grants。
  **测试**: `test_create_disabled_invite_scene_degrades_to_direct_authorization`, `test_create_mixed_direct_and_invites`, `test_create_partial_user_failure_keeps_resource`, `test_create_response_contains_item_results`
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-29, AC-30, AC-32
  **依赖**: T031, T033

- [x] **T039**: 知识空间创建编排结果实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_creation_application_service.py`, `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`
  **逻辑**: 拆分 direct 与个人 user 的 creation validation；场景启用时持锁进入本人确认，缺失/关闭时创建后调用 T031 的 direct 降级。`initial_permission_result` 保持 success/failed/error_code 并追加 counts/results；个人按项失败不重建/删除资源。
  **测试**: T038 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-29, AC-30, AC-32
  **依赖**: T038

- [x] **T040**: 频道创建邀请 Test-First
  **类别**: 后端 Domain/API 测试
  **文件**: `src/backend/test/channel/test_channel_creation_application_service.py`, `src/backend/test/channel/test_channel_create_initial_permissions_api.py`
  **逻辑**: 只扩测试；与 T038 相同，场景缺失/关闭时创建频道并按既有实时校验 direct 授权；mixed result 不重放 create；string channel id 和原 response 保持。
  **测试**: `test_channel_create_disabled_scene_degrades_to_direct_authorization`, `test_channel_create_mixed_invites`, `test_channel_create_partial_failure_keeps_channel`, `test_channel_create_response_item_results`
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-29, AC-32
  **依赖**: T035, T037

- [x] **T041**: 频道创建编排结果实现
  **类别**: 后端 Domain 实现
  **文件**: `src/backend/bisheng/channel/domain/services/channel_creation_application_service.py`, `src/backend/bisheng/channel/domain/schemas/channel_manager_schema.py`
  **逻辑**: 场景启用时门禁先于 `create_channel` 并持锁进入本人确认；缺失/关闭时创建后调用 T035 的 direct 降级。结果追加 counts/results 和兼容 error_code；部分失败保留频道且不重放订阅/同步副作用。
  **测试**: T040 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-29, AC-32
  **依赖**: T040

### Wave 4 — Client API、草稿与 F044 页面增量

- [x] **T042**: Client API 合约测试
  **类别**: 前端 Client 测试
  **文件**: `src/frontend/client/src/api/unifiedPermissionEntry.test.ts`
  **逻辑**: 先写失败测试；覆盖两类 authorize AuthorizationResult 映射、权限 pending 字段、两类 initial result counts/results、18106 status_message 保留、旧响应缺少新增字段时默认兼容。
  **覆盖 AC**: AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-32
  **依赖**: T033, T037, T039, T041

- [x] **T043**: Permission/Channel API Adapter 实现
  **类别**: 前端 Client 实现
  **文件**: `src/frontend/client/src/api/permission.ts`, `src/frontend/client/src/api/channels.ts`
  **逻辑**: 定义 camelCase AuthorizationResult/ItemOutcome/pending 字段；`authorizeResource`/`authorizeChannelApi` 返回数据对象；频道兼容旧计数；统一从 wrapped request 保留 18106 message，不新增业务 403 分支。
  **测试**: T042 对 permission/channel 的断言通过
  **覆盖 AC**: AC-03, AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-27, AC-28, AC-32
  **依赖**: T042

- [x] **T044**: Knowledge create API Adapter 实现
  **类别**: 前端 Client 实现
  **文件**: `src/frontend/client/src/api/knowledge.ts`
  **逻辑**: 扩展 `InitialPermissionResult` 映射 counts/results/errorCode；旧后端仅 status/error_code 时仍兼容；保留资源 id 和其他 F044 字段。
  **测试**: T042 knowledge create 断言通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-27, AC-32
  **依赖**: T042

- [x] **T045**: Pending 权限草稿 reducer 测试
  **类别**: 前端 Client 测试
  **文件**: `src/frontend/client/src/components/permission/usePermissionDraft.test.ts`
  **逻辑**: 先写失败测试；pending row 不可 change/remove/replace，永不生成 grant/revoke；active 行保持 touched diff；pending user key 可供 picker disabled IDs；creator 规则不回归。
  **覆盖 AC**: AC-05, AC-08, AC-11, AC-20, AC-21
  **依赖**: T043

- [x] **T046**: Pending 权限草稿 reducer 实现
  **类别**: 前端 Client 实现
  **文件**: `src/frontend/client/src/components/permission/usePermissionDraft.ts`
  **逻辑**: `PermissionDraftRow` 增加 authorizationStatus/approvalInstanceId；pending 与 creator 同为 reducer 级 immutable，change/remove/replace/diff 双重过滤；不发 HTTP、不新增状态库。
  **测试**: T045 全部通过
  **覆盖 AC**: AC-05, AC-08, AC-11, AC-20, AC-21
  **依赖**: T045

- [x] **T047**: Pending 权限编辑器组件测试
  **类别**: 前端 Client 测试
  **文件**: `src/frontend/client/src/components/permission/PermissionDraftEditor.test.tsx`
  **逻辑**: 先写组件测试；pending 显示“待生效”，relation disabled、无移除按钮；active/creator 保持原交互；点击/键盘均不能触发 onChange。
  **覆盖 AC**: AC-09, AC-10, AC-11
  **依赖**: T046

- [x] **T048**: Pending 权限编辑器实现
  **类别**: 前端 Client 实现
  **文件**: `src/frontend/client/src/components/permission/PermissionDraftEditor.tsx`
  **逻辑**: 使用现有 bs-ui/semantic tokens 增加待生效标签；pending relation/remove 禁用，保持 named export 和受控组件；不承载撤回或审批 API。
  **测试**: T047 全部通过
  **覆盖 AC**: AC-09, AC-10, AC-11
  **依赖**: T047

- [x] **T049**: 知识空间统一页面邀请测试
  **类别**: 前端 Client 测试
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.test.tsx`
  **逻辑**: 先写页面测试；create/edit 的 invite_created/invite_existing/failed 逐项反馈；18106 明确 toast 且不显示成功；pending 列表只读且选择器不可重复选；创建恢复仅提交 failed grants；同意/拒绝后刷新 active/pending。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-17, AC-18, AC-20, AC-21, AC-27, AC-28, AC-30, AC-32
  **依赖**: T043, T044, T048

- [x] **T050**: 知识空间统一页面邀请实现
  **类别**: 前端 Client 实现
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceSettings/useKnowledgeSpaceSettingsForm.ts`, `src/frontend/client/src/pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.tsx`
  **逻辑**: permission entry 映射 pending 字段；提交消费逐项结果并区分邀请/授权语义；18106 展示后端明确消息；disabled IDs 包含 active+pending；create recovery 缓存/重试 failed grants，不能重放已建邀请/direct。
  **测试**: T049 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-17, AC-18, AC-20, AC-21, AC-27, AC-28, AC-30, AC-32
  **依赖**: T049

- [x] **T051**: 频道统一页面邀请测试
  **类别**: 前端 Client 测试
  **文件**: `src/frontend/client/src/pages/Subscription/ChannelSettings/ChannelSettingsPage.test.tsx`
  **逻辑**: 先写页面测试；覆盖与 T049 相同语义，并固化频道 create 成功导航、permission_failed recovery、旧计数字段不影响 UI、信息源表单状态不被授权结果覆盖。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-17, AC-18, AC-20, AC-21, AC-27, AC-28, AC-32
  **依赖**: T043, T048

- [x] **T052**: 频道统一页面邀请实现
  **类别**: 前端 Client 实现
  **文件**: `src/frontend/client/src/pages/Subscription/ChannelSettings/useChannelSettingsForm.ts`, `src/frontend/client/src/pages/Subscription/ChannelSettings/ChannelSettingsPage.tsx`
  **逻辑**: 映射 pending、逐项反馈、18106、active+pending disabled IDs；create/edit 结果区分 invite/direct；authorizationRecovery 只存 failed grants，不重放 create、订阅或知识同步。
  **测试**: T051 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-17, AC-18, AC-20, AC-21, AC-27, AC-28, AC-32
  **依赖**: T051

- [x] **T053**: Client 中英文邀请文案
  **类别**: 前端 Client i18n
  **文件**: `src/frontend/client/src/locales/zh-Hans/translation.json`, `src/frontend/client/src/locales/en/translation.json`
  **逻辑**: 增加邀请已发送、已有待生效、待生效、部分失败、18106 明确拒绝及三个通知 action 的中英文 key；沿用现有 namespace，不硬编码组件文案。
  **手动验证**: 切换中/英文，create/settings/通知中心均无 key 泄漏，邀请文案不出现“授权成功”。
  **覆盖 AC**: AC-03, AC-04, AC-09, AC-10, AC-11, AC-13, AC-16, AC-17, AC-18, AC-20, AC-21, AC-27
  **依赖**: T027, T050, T052

- [x] **T054**: Client 日文邀请文案
  **类别**: 前端 Client i18n
  **文件**: `src/frontend/client/src/locales/ja/translation.json`
  **逻辑**: 与 T053 key 完全对齐并提供日文文案，保持三语 locale key 集合一致。
  **手动验证**: 切换日文，页面/通知无缺失 key，待生效与已生效语义可区分。
  **覆盖 AC**: AC-03, AC-04, AC-09, AC-10, AC-11, AC-13, AC-16, AC-17, AC-18, AC-20, AC-21, AC-27
  **依赖**: T053

### Wave 5 — E2E、全量回归与交付门禁

- [ ] **T055**: 生成并执行 F045 E2E 覆盖
  **类别**: E2E 测试
  **文件**: `src/backend/test/e2e/test_e2e_personal_user_invite_confirmation.py`, `features/v2.6.0/045-personal-user-invite-confirmation/e2e-checklist.md`
  **逻辑**: 调用 `/e2e-test features/v2.6.0/045-personal-user-invite-confirmation`；API E2E 覆盖场景门禁、一人一单、跨邀请人重复、本人 approve/reject、withdraw、双时点失败、tenant/F033；人工清单覆盖四个 F044 路由和真实 default worker。
  **执行记录（2026-08-10）**: 自动化与人工清单已生成，Ruff/py_compile 通过；连接本地 API 时 4 项因真实后端/default worker 不可用而 skip，`E2E_F045_ALLOW_SCENE_TOGGLE=1` 的 18106 场景开关用例未在独立租户实跑，因此本任务保持未完成。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T025, T029, T039, T041, T050, T052, T054

- [x] **T056**: 后端 focused/full regression
  **类别**: 验证
  **文件**: 无
  **逻辑**: 依次运行 `uv run pytest test/approval test/permission test/knowledge/test_knowledge_space_creation_application_service.py test/knowledge/test_knowledge_space_create_initial_permissions_api.py test/channel/test_channel_authorization_service.py test/channel/test_channel_authorization_api.py test/channel/test_channel_creation_application_service.py test/channel/test_channel_create_initial_permissions_api.py -q`；再运行可承受的 `uv run pytest test/ -m "not e2e"`。记录基线失败与 F045 失败边界。
  **执行记录（2026-08-10）**: 最终独立复跑为 approval 87/87、permission+knowledge 86/86（另主动排除 1 个 F044 既有 legacy subscription viewer 过滤用例）、channel+binding 62/62。任务指定组合套件 729 passed/42 failed，失败集中于历史 mock/DM8 driver 与上述既有用例。项目级运行 3600 passed/368 failed/130 errors/101 skipped/6 deselected；仓库部分 E2E 未标 marker，虽使用 `-m "not e2e"` 仍因本地 API 502 进入 error，其他失败主要为无数据库 URL/外部服务/历史基线。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T055

- [ ] **T057**: Client 回归、构建与四路由人工验证
  **类别**: 验证
  **文件**: 无
  **逻辑**: 在 `src/frontend/client` 运行 `pnpm test:ci` 与 `pnpm run build`；人工验证 `/workspace/knowledge/create`、`/workspace/knowledge/space/:spaceId/settings`、`/workspace/channel/create`、`/workspace/channel/:channelId/settings`。若 F044 的 `qrcode.react` 基线问题仍在，单独记录，不得写成通过。
  **执行记录（2026-08-10）**: F045 focused Client 5 suites/35 tests 与全部改动文件 ESLint 通过；三语新增 key 完整，locale build 与直接 Vite production build 成功。标准 `pnpm run build` 被 Codex 依赖状态检查的 ignored build scripts 拦截，命令产生的 lock/workspace 机械改写已恢复；四路由尚无可用运行环境完成人工验证，因此本任务保持未完成。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-16, AC-17, AC-18, AC-20, AC-21, AC-27, AC-28, AC-30, AC-31, AC-32
  **依赖**: T055

- [ ] **T058**: 架构、文档与代码审查门禁
  **类别**: 验证/交付
  **文件**: 无
  **逻辑**: 运行 `bash scripts/arch-guard.sh`、`git diff --check`、后端 ruff focused check；核对 release contract 与 approval-module skill 已同步；执行 `/code-review --base origin/feat/2.6.0-cofco`，修复 high/medium 问题并把实际实现偏差回写 design、此处只留指针。
  **执行记录（2026-08-10）**: 实现对账见 `design.md` §7.5；新 Python 文件严格 Ruff、全部改动 Python 文件在排除既有 baseline codes 后 Ruff 通过，Architecture Guard 与 `git diff --check` 均通过。跨模块审查发现的 outbox 原子终态、setup-failure claim 竞态及频道 direct binding 陈旧快照覆盖均已修复并补回归；generic knowledge direct 的既有 FGA/binding 补偿窗口记录在 `design.md` §8。release contract 与 approval-module skill 已同步。因 T057 真实四路由验证尚未完成，本任务保持未完成。
  **覆盖 AC**: AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖**: T056, T057

---

## AC 追溯索引

| AC | 主要测试任务 |
|---|---|
| AC-01 | T011, T015, T030, T034, T038, T040, T049, T051, T055 |
| AC-02 | T009, T011, T015, T030, T034, T038, T040, T049, T051, T055 |
| AC-03 | T011, T026, T030, T034, T038, T040, T042, T049, T051, T055 |
| AC-04 | T015, T026, T038, T040, T055 |
| AC-05 | T003, T009, T011, T015, T030, T032, T034, T036, T038, T040, T042, T045, T049, T051, T055 |
| AC-06 | T009, T011, T038, T040, T049, T051, T055 |
| AC-07 | T011, T030, T032, T034, T036, T038, T040, T042, T049, T051, T055 |
| AC-08 | T011, T030, T032, T034, T036, T038, T040, T042, T045, T049, T051, T055 |
| AC-09 | T007, T030, T032, T034, T036, T038, T040, T042, T047, T049, T051, T055 |
| AC-10 | T030, T032, T034, T036, T038, T040, T042, T047, T049, T051, T055 |
| AC-11 | T030, T032, T034, T036, T038, T040, T042, T045, T047, T049, T051, T055 |
| AC-12 | T009, T013, T015, T017, T055 |
| AC-13 | T026, T053, T054, T055 |
| AC-14 | T013, T019, T024, T030, T034, T055 |
| AC-15 | T005, T013, T019, T024, T026, T030, T034, T055 |
| AC-16 | T013, T019, T024, T026, T030, T034, T053, T054, T055 |
| AC-17 | T013, T019, T024, T026, T030, T034, T049, T051, T053, T054, T055 |
| AC-18 | T005, T007, T013, T019, T024, T026, T030, T034, T049, T051, T053, T054, T055 |
| AC-19 | T003, T005, T007, T009, T013, T019, T024, T030, T034, T055 |
| AC-20 | T009, T017, T026, T045, T049, T051, T053, T054, T055 |
| AC-21 | T009, T017, T026, T045, T049, T051, T053, T054, T055 |
| AC-22 | T003, T009, T017, T019, T024, T055 |
| AC-23 | T003, T009, T017, T019, T024, T055 |
| AC-24 | T011, T015, T021, T055 |
| AC-25 | T011, T015, T021, T055 |
| AC-26 | T013, T015, T021, T055 |
| AC-27 | T011, T013, T015, T021, T030, T032, T034, T036, T038, T040, T042, T049, T051, T053, T054, T055 |
| AC-28 | T007, T011, T013, T015, T021, T030, T032, T034, T036, T038, T040, T042, T049, T051, T055 |
| AC-29 | T009, T011, T013, T015, T017, T019, T021, T024, T030, T032, T034, T036, T038, T040, T055 |
| AC-30 | T011, T013, T030, T032, T038, T049, T055 |
| AC-31 | T011, T013, T030, T034, T055 |
| AC-32 | T005, T011, T013, T030, T032, T034, T036, T038, T040, T042, T049, T051, T055 |

---

## 实际偏差记录

> 只留一行指针，论证回写 [design.md](./design.md)；推翻已确认决策时先暂停并重新确认。

- 实现对账、原子 outbox/实时 tenant 与角色重校验等细化见 [design.md](./design.md) §7.5；已知 generic knowledge direct 补偿窗口见 §8。
