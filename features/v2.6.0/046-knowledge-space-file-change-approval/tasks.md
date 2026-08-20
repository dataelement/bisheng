# Tasks: 知识空间文件与文件夹变更审核

**关联规格**: [spec.md](./spec.md)
**关联设计**: [design.md](./design.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | F046，AC-01～AC-53 |
| design.md | ✅ 已评审 | 三轮代码对照审查后 LGTM |
| tasks.md | ✅ 已拆解 | 93 个唯一任务；依赖、粒度与 AC 追踪复审 LGTM |
| 实现 | 🔄 进行中 | 89 / 93 完成；偏差按 `docs/SDD-Guide.md` 处理 |

---

## 开发模式

- 按 Wave 推进；同一 Wave 中无文件交叉的任务可由子 agent 并行。
- 后端严格 Test-First：测试任务先落地并确认因缺少目标行为而失败，配对实现任务再转绿。
- 每个任务原则上只改 1～2 个文件；跨 Feature 只通过 owner Service 扩展，Approval* 写行为仍归 F025。
- Worker 参数显式携带 `tenant_id`，通过 Celery headers 传递并在 worker 入口恢复到 tenant ContextVar；Beat 跨租户枚举使用 `bypass_tenant_filter()`，逐租户设置 ContextVar。
- DM8、中间件与真实 OpenFGA/Milvus/ES 集成由 CI 验证；本地使用 mock/fake 覆盖事务、幂等和状态机，不以此标记测试降级。

---

## Wave 0：基础设施（无测试配对）

### 基础设施

- [x] **T001**: 策略与单空间配置 ORM 模型
  **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge_space_file_change_policy.py`
  **逻辑**: 定义 `KnowledgeSpaceFileChangePolicy/Setting`、命名唯一约束、双 DB 通用默认值和时间字段；policy 默认 `enabled=true,scope=per_space`，setting 默认需审。
  **依赖**: 无

- [x] **T002**: opaque 上传暂存 ORM 模型
  **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge_space_upload_stage.py`
  **逻辑**: 定义 stage 生命周期、服务端 object/name/size/hash、容量与清理索引；API schema 不得暴露 object name。
  **依赖**: 无

- [x] **T003**: 变更申请与 footprint ORM 模型
  **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge_space_file_change_request.py`
  **逻辑**: 定义 request、footprint、动作快照、审批实例关联、执行 token/摘要和资源/path 索引；bulk 写必须显式 tenant 条件。
  **依赖**: 无

- [x] **T004**: durable execution step ORM 模型
  **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge_space_file_change_execution_step.py`
  **逻辑**: 定义稳定 `(tenant,request,step)` 唯一键、attempt token、幂等键、dispatch/ack/补偿状态与重试游标。
  **依赖**: 无

- [x] **T005**: F046 Alembic migration 与模型导出
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f046_knowledge_space_file_change_approval.py`, `src/backend/bisheng/knowledge/domain/models/__init__.py`
  **逻辑**: 创建六张 F046 表/索引并给 F025 `approval_outbox` 增加 nullable deferred token/deadline/heartbeat 字段；upgrade/downgrade 兼容 MySQL/DM8，downgrade 遇 deferred 行拒绝；不 seed 租户数据。
  **依赖**: T001, T002, T003, T004

- [x] **T006**: 错误码与公共 DTO
  **文件**: `src/backend/bisheng/common/errcode/knowledge_space.py`, `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_file_change_schema.py`
  **逻辑**: 落地 18072～18076；定义 policy、stage、逐项 mutation、详情、批量审批、cursor 响应 DTO，禁止接收 tenant_id/object_name。
  **依赖**: 无

---

## Wave 1：F025 原子能力与动态审批人

### 后端 Domain Service（Test-First）

- [x] **T007**: ApprovalGate session-bound UoW 测试
  **文件**: `src/backend/test/approval/test_approval_gate_uow.py`
  **逻辑**: 故障注入验证 instance/tasks/log 与 F046 request 同提交或同回滚，post-commit effect 不提前执行；Gate 派发的每个 Celery effect 都断言 tenant_id header 来自当前 ContextVar。
  **覆盖 AC**: AC-11, AC-28, AC-29, AC-31
  **依赖**: T005

- [x] **T008**: ApprovalGate UoW 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_uow.py`, `src/backend/bisheng/approval/domain/services/approval_gate.py`
  **逻辑**: 新增 session-bound Gate bundle API，repository 写入不自行 commit；返回提交后通知/任务 effect。所有 Celery effect 从当前 ContextVar 取 tenant_id 并显式写入 task headers。
  **测试**: T007 全部通过
  **依赖**: T007

- [x] **T009**: 决策、撤回与异常入口原子锁测试
  **文件**: `src/backend/test/approval/test_approval_decision_uow.py`
  **逻辑**: 覆盖 instance-first 锁序、task/instance 两入口先对账后重读、OR sibling、withdraw/cancel 并发及 F045 自确认回归；Center 提交后的 outbox/通知 Celery effect 必须携当前 tenant_id header。
  **覆盖 AC**: AC-29, AC-30, AC-32, AC-36, AC-37
  **依赖**: T008

- [x] **T085**: Approval repository session-bound 原子原语
  **文件**: `src/backend/bisheng/approval/domain/repositories/approval_instance_repository.py`
  **逻辑**: 为 T009 提供同一 session 下的 instance/task/exception/outbox FOR UPDATE、批量状态迁移和 action log 写入；方法不得自行 commit，固定锁序为 instance→current tasks→open exception/outbox。
  **测试**: T009 全部通过 repository 故障注入部分
  **依赖**: T009

- [x] **T010**: ApprovalDecisionUnitOfWork 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_center_service.py`
  **逻辑**: 基于 T085 抽取 `_decide_locked_task` 和 instance 决策入口；在一个 UoW 内完成 reconcile→重读当前 task→资格校验→task/sibling/instance/log/exception/outbox，提交后 effects；所有 Celery effect 携 tenant_id header；F045 专用分支保持。
  **测试**: T009 全部通过
  **依赖**: T085

- [x] **T011**: 动态审批人和 approver_empty 测试
  **文件**: `src/backend/test/approval/test_dynamic_approver_service.py`
  **逻辑**: 移除旧 task、新增新 task、不复活历史、并发幂等、空集合单异常、strict resolver 故障不误建异常。
  **覆盖 AC**: AC-14, AC-23, AC-28, AC-29, AC-30, AC-34
  **依赖**: T010

- [x] **T012**: 动态审批人原子 Service
  **文件**: `src/backend/bisheng/approval/domain/services/approval_dynamic_assignee_service.py`, `src/backend/bisheng/approval/domain/services/approval_exception_service.py`
  **逻辑**: 实例锁内 diff pending tasks、ensure/resolve approver_empty、action log 与新增任务 post-commit 通知。
  **测试**: T011 全部通过
  **依赖**: T011

- [x] **T013**: 动态候选发现、可见性与异常策略测试
  **文件**: `src/backend/test/approval/test_approval_runtime_dynamic_hooks.py`
  **逻辑**: 无历史 task 的新 manager 在 list/count/unread 前被发现；former manager 不可看详情；F046 禁 assign/flow/skip/manual-complete，仅 strict retry/cancel。
  **覆盖 AC**: AC-14, AC-23, AC-28, AC-30, AC-34, AC-36
  **依赖**: T012

- [x] **T014**: runtime hooks 与查询前动态发现实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_runtime_handler_factory.py`, `src/backend/bisheng/approval/domain/services/approval_center_service.py`
  **逻辑**: 扩展 discover/reconcile/authorize/filter/projection/exception policy hooks；list/count/unread 先有界发现、对账再查询。
  **测试**: T013 全部通过
  **依赖**: T013

- [x] **T015**: Deferred outbox 状态机测试
  **文件**: `src/backend/test/approval/test_approval_deferred_outbox.py`
  **逻辑**: 普通 claim 排除 deferred；heartbeat/watchdog/complete/fail/resume 锁序；resume 新 token、旧 ack 失效、旧 handler 默认 Completed。
  **覆盖 AC**: AC-15, AC-16, AC-17, AC-18, AC-24, AC-32, AC-48
  **依赖**: T005, T010

- [x] **T016**: Deferred outbox Service 与模型字段实现
  **文件**: `src/backend/bisheng/approval/domain/models/approval_instance.py`, `src/backend/bisheng/approval/domain/services/approval_outbox_service.py`
  **逻辑**: 增加 `status=deferred`、token/deadline/heartbeat；普通 claim 只取 pending/failed/过期 processing 且永远排除 deferred。提供 heartbeat/complete/fail/resume：均按 instance→outbox 锁序并校验当前 token；watchdog 仅在 deadline/heartbeat 超时后 fail；resume 生成新 token，以 handler `prepare_resume(session,new_token)` 在同一 UoW 恢复业务 steps 和 instance/outbox，提交后才补投。
  **测试**: T015 全部通过
  **依赖**: T015

- [x] **T091**: Approval worker Deferred 结果集成测试
  **文件**: `src/backend/test/approval/test_approval_worker_deferred.py`
  **逻辑**: 仅验证 consumer：worker 从 tenant_id header 恢复 ContextVar；对 Completed 走原成功路径，对 Deferred 原子持久化后停止；retry worker/普通 claim 不重领，watchdog 校验 token。producer header 已由 T007/T009 Test-First 覆盖。
  **覆盖 AC**: AC-15, AC-16, AC-17, AC-24, AC-32, AC-48, AC-53
  **依赖**: T016

- [x] **T092**: Approval worker Deferred 结果处理
  **文件**: `src/backend/bisheng/worker/approval/tasks.py`
  **逻辑**: 识别 handler `Completed/Deferred`；Deferred 仅保存 token/deadline 并由 coordinator/watchdog 驱动，普通 retry 过滤；Celery headers 的 tenant_id 在入口恢复 ContextVar。
  **测试**: T091 全部通过
  **依赖**: T091

- [x] **T017**: 固定系统场景与管理旁路测试
  **文件**: `src/backend/test/approval/test_file_change_scenario_registry.py`
  **逻辑**: ensure 幂等；场景固定 enabled/catch-all/单 OR/owner+manager；管理 API 不可禁用、删除或改 route/flow/node；并预先编写默认启动/新租户 bootstrap 用例供 T093 转绿。策略保存与首次 mutation 分别由 T049/T027 Test-First 覆盖。
  **覆盖 AC**: AC-06, AC-28, AC-29, AC-42
  **依赖**: T006

- [x] **T018**: 固定场景 preset 与管理保护实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_registry.py`, `src/backend/bisheng/approval/domain/services/approval_scenario_admin_service.py`
  **逻辑**: 注册 `knowledge_space_file_change_request`，提供 lazy ensure，并在所有配置写入口拒绝固定场景变更。
  **测试**: T017 的 preset/ensure/管理旁路用例通过；默认启动/新租户用例留给 T093
  **依赖**: T017

- [x] **T093**: 默认启动与新租户场景 bootstrap
  **文件**: `src/backend/bisheng/common/init_data.py`, `src/backend/bisheng/tenant/domain/services/tenant_service.py`
  **逻辑**: 默认数据初始化与租户创建成功事务后分别调用 T018 的幂等 ensure；失败显式告警/回滚相应初始化，不复制 preset 构造逻辑。策略保存由 T050 调用 ensure，首次有效需审 mutation 由 T028 在 Gate 前调用 ensure。
  **测试**: T017 的默认启动/新租户/四入口 bootstrap 用例通过
  **依赖**: T018

---

## Wave 2：知识域策略、暂存、申请与审批 handler

### 后端 Domain Service（Test-First）

- [x] **T019**: 租户策略与空间配置测试
  **文件**: `src/backend/test/knowledge/test_file_change_policy_service.py`
  **逻辑**: 默认值、保存失败不生效、关闭再开启保留 setting、all/per-space、私密免审、tenant 隔离、policy 行并发 ensure。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-39, AC-53
  **依赖**: T001, T006

- [x] **T020**: 策略 Repository 与 Service
  **文件**: `src/backend/bisheng/knowledge/domain/repositories/knowledge_space_file_change_repository.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_policy_service.py`
  **逻辑**: 无 root fallback；ensure insert 冲突用 savepoint 重试后 FOR UPDATE；只读取当前 tenant。
  **测试**: T019 全部通过
  **依赖**: T019

- [x] **T021**: upload stage 生命周期与容量测试
  **文件**: `src/backend/test/knowledge/test_knowledge_space_upload_stage.py`
  **逻辑**: opaque id、元数据持久化、同 upload 幂等、hash 变化新 stage、attach/consume/cleanup 容量锁和 object name 不泄露。
  **覆盖 AC**: AC-12, AC-13, AC-18, AC-19, AC-20, AC-21, AC-27, AC-53
  **依赖**: T002, T020

- [x] **T022**: upload stage Repository 与 Service
  **文件**: `src/backend/bisheng/knowledge/domain/repositories/knowledge_space_upload_stage_repository.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_upload_stage_service.py`
  **逻辑**: 服务端生成 upload_id/hash，policy 行锁下容量预占/释放，合法状态迁移与短时预览授权。
  **测试**: T021 全部通过
  **依赖**: T021

- [x] **T023**: request/footprint 冲突 Repository 测试
  **文件**: `src/backend/test/knowledge/test_file_change_request_repository.py`
  **逻辑**: tenant 条件、版本 sibling、父子双向、目标祖先、跨空间固定锁序及活跃/可对账状态集合分离。
  **覆盖 AC**: AC-11, AC-31, AC-43, AC-45, AC-50, AC-52, AC-53
  **依赖**: T003, T005

- [x] **T024**: request/footprint Repository 实现
  **文件**: `src/backend/bisheng/knowledge/domain/repositories/knowledge_space_file_change_request_repository.py`, `src/backend/bisheng/knowledge/domain/repositories/knowledge_space_file_change_footprint_repository.py`
  **逻辑**: 空间升序行锁、标准化 footprint、path LIKE 转义与活跃 instance join；不在 JSON 上查询。
  **测试**: T023 全部通过
  **依赖**: T023

- [x] **T025**: strict owner/manager resolver 测试
  **文件**: `src/backend/test/knowledge/test_file_change_approver_resolver.py`
  **逻辑**: 有效 userset 展开、去重/排除申请人、FGA 故障 fail-closed 且不回退 membership、确实空集合才无人审批。
  **覆盖 AC**: AC-09, AC-14, AC-23, AC-28, AC-30, AC-36
  **依赖**: T006

- [x] **T026**: strict resolver 实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_approver_resolver.py`
  **逻辑**: 通过 PermissionService/OpenFGA 权威解析当前有效 owner/manager；基础设施失败抛 18076。
  **测试**: T025 全部通过
  **依赖**: T025

- [x] **T027**: 变更申请编排 UoW 测试
  **文件**: `src/backend/test/knowledge/test_file_change_request_service.py`
  **逻辑**: 先权限、再私密/owner直通、再策略；request+footprint+Gate 原子；同批逐项独立；无权限不建审批；既有租户首次有效需审 mutation 在 Gate 前调用 ensure。
  **覆盖 AC**: AC-07, AC-08, AC-09, AC-10, AC-11, AC-26, AC-31, AC-40, AC-43, AC-45, AC-49, AC-52
  **依赖**: T008, T018, T020, T022, T024, T026

- [x] **T028**: KnowledgeSpaceFileChangeService 实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_service.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_uow.py`
  **逻辑**: 落地策略判断、空间锁、冲突检查、Gate bundle、逐项 direct/pending/invalid 与 post-commit 首次通知；首次判定需审时在 Gate 前幂等 ensure 固定场景，覆盖既有未初始化租户。
  **测试**: T027 全部通过
  **依赖**: T027

- [x] **T029**: F046 scenario handler 测试
  **文件**: `src/backend/test/knowledge/test_file_change_scenario_handler.py`
  **逻辑**: title/detail/action snapshot、strict approver、former 可见性、候选发现、异常 policy、各终态清理钩子。
  **覆盖 AC**: AC-14, AC-20, AC-21, AC-23, AC-28, AC-30, AC-34, AC-51
  **依赖**: T012, T014, T016, T026, T028

- [x] **T030**: F046 scenario handler 与 runtime 注册
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_scenario_handler.py`, `src/backend/bisheng/approval/domain/services/approval_runtime_handler_factory.py`
  **逻辑**: 实现全部 runtime hooks；知识侧只调用 F025 原子 Service，不直接写 Approval*。
  **测试**: T029 全部通过
  **依赖**: T029

---

## Wave 3：发布门禁与可恢复执行 Saga

### 后端 Domain Service（Test-First）

- [x] **T031**: 同事务 add_file 与上传执行状态测试
  **文件**: `src/backend/test/knowledge/test_file_change_upload_executor.py`
  **逻辑**: 正式 file/request 关联同提交；提交前不派 FGA/解析；解析/索引 ack 前 deferred；失败 resume 新 token 且不重审。
  **覆盖 AC**: AC-12, AC-13, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-32
  **依赖**: T016, T022, T030

- [x] **T032**: add_file_in_uow 与 upload executor 实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_mutation_executor.py`
  **逻辑**: 新增 session-bound 注册路径，同事务关联 request；提交后创建 durable FGA/parse/index/vector steps并返回 Deferred。
  **测试**: T031 全部通过
  **依赖**: T031

- [x] **T033**: publication/deletion guard 合同测试
  **文件**: `src/backend/test/knowledge/test_file_change_visibility_guards.py`
  **逻辑**: parsing 文件与 cutover 后删除残留按 tenant/space 批量排除；申请人/当前审核人独立预览；普通用户不泄露名称。
  **覆盖 AC**: AC-13, AC-14, AC-15, AC-16, AC-17, AC-22, AC-23, AC-24, AC-47
  **依赖**: T024, T032

- [x] **T034**: publication/deletion guard Service
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_publication_guard.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_deletion_guard.py`
  **逻辑**: 提供批量 unpublished/deleted ids、filter 与 stakeholder require；不替代 ReBAC。
  **测试**: T033 全部通过
  **依赖**: T033

- [x] **T035**: children/search 正式读路径门禁测试
  **文件**: `src/backend/test/knowledge/test_file_change_children_search_guard.py`
  **逻辑**: WAITING/PROCESSING 和删除残留不进入 children/search，审批前正式 rename/move/delete 仍按旧名称/位置可用。
  **覆盖 AC**: AC-13, AC-15, AC-22, AC-33, AC-43, AC-45, AC-47
  **依赖**: T034

- [x] **T036**: children/search 门禁集成
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_file_visibility_service.py`
  **逻辑**: 在 cursor/filter 后批量组合 publication/deletion guard，保持 F027 分页协议和权限过滤。
  **测试**: T035 全部通过
  **依赖**: T035

- [x] **T037**: RAG 与 citation 门禁测试
  **文件**: `src/backend/test/knowledge/test_file_change_rag_citation_guard.py`
  **逻辑**: 索引前后双过滤、citation resolve、预览/下载均不泄漏未发布或已 cutover 删除资源。
  **覆盖 AC**: AC-13, AC-14, AC-15, AC-17, AC-22, AC-24, AC-47
  **依赖**: T034

- [x] **T038**: RAG 与 citation 门禁实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_file_visibility_service.py`
  **逻辑**: 在检索 prefilter/post-filter 和 citation/preview 授权中组合两类 guard，保持 F029 accessScope 语义。
  **测试**: T037 全部通过
  **依赖**: T037

- [x] **T039**: F030 OpenAPI 门禁测试
  **文件**: `src/backend/test/knowledge/test_file_change_v2_api_guard.py`
  **逻辑**: v2 filelib 列表/详情/检索对未发布与删除残留不可见，tenant 和代用户权限不退化。
  **覆盖 AC**: AC-13, AC-15, AC-17, AC-24, AC-47, AC-53
  **依赖**: T034

- [x] **T040**: F030 OpenAPI 门禁集成
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`
  **逻辑**: 在 `/api/v2/filelib` type=3 列表/详情/检索分派及知识空间检索结果统一组合 publication/deletion guard；漏传 tenant/user 时拒绝而非 fallback。
  **测试**: T039 全部通过
  **依赖**: T039

- [x] **T041**: rename/move durable Saga 测试
  **文件**: `src/backend/test/knowledge/test_file_change_rename_move_saga.py`
  **逻辑**: 每 step crash gap、稳定幂等键、影子/可逆步骤、末端名称/位置 cutover、目标变化重验与补偿。
  **覆盖 AC**: AC-32, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52
  **依赖**: T004, T016, T024, T032

- [x] **T042**: rename executor 与 step Repository
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_mutation_executor.py`, `src/backend/bisheng/knowledge/domain/repositories/knowledge_space_file_change_execution_step_repository.py`
  **逻辑**: 先实现 rename durable steps：稳定幂等键、chunk/index 影子更新、读后校验和末端 DB name cutover；文件夹一次申请覆盖子树。
  **测试**: T041 的 rename 用例通过
  **依赖**: T041

- [x] **T086**: move executor durable steps
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_mutation_executor.py`, `src/backend/bisheng/knowledge/domain/repositories/knowledge_space_file_change_execution_step_repository.py`
  **逻辑**: 增量实现 move 的版本链、目标 parent tuple、标签、跨空间存储/索引步骤；完成外部准备与读后校验后末端切换 DB 位置，失败按 manifest 补偿。
  **测试**: T041 的 move/跨空间/补偿用例通过
  **依赖**: T042

- [x] **T043**: delete prepare/cutover/purge 测试
  **文件**: `src/backend/test/knowledge/test_file_change_delete_cutover.py`
  **逻辑**: prepare 零破坏；DB delete+guard+instance 同事务；cutover 前全读路径可用，之后立即不可见；物理 purge 最终重试。
  **覆盖 AC**: AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-32, AC-47, AC-48, AC-49, AC-50, AC-52
  **依赖**: T034, T086

- [x] **T044**: delete cutover executor
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_mutation_executor.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_deletion_guard.py`
  **逻辑**: 实现零破坏 prepare manifest，以及 cutover UoW 原子删除正式 DB、激活 guard、完成 F025 deferred；cutover 前任何失败保持资源可用。
  **测试**: T043 的 prepare/cutover/回滚用例通过
  **依赖**: T043

- [x] **T087**: delete durable purge 与残留门禁
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_mutation_executor.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_deletion_guard.py`
  **逻辑**: cutover 提交后以 durable steps 幂等清理 FGA/MinIO/ES/Milvus；未清残留始终被 guard 排除，失败持续重试/告警且不复活资源。
  **测试**: T043 的 purge/残留/重试用例通过
  **依赖**: T044

- [x] **T045**: execution coordinator/ack/resume 测试
  **文件**: `src/backend/test/knowledge/test_file_change_execution_coordinator.py`
  **逻辑**: 同代补投、旧 token ack、读后校验、heartbeat/deadline、resume 联动、Completed/Deferred/compensating 投影。
  **覆盖 AC**: AC-15, AC-16, AC-17, AC-18, AC-24, AC-32, AC-44, AC-46, AC-48
  **依赖**: T016, T086, T087

- [x] **T046**: execution coordinator 实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_execution_coordinator.py`
  **逻辑**: 实现 step dispatch/ack/reconcile、同代补投/旧代忽略、权威读后校验及 F025 heartbeat/complete/fail 调用。
  **测试**: T045 的 dispatch/ack/heartbeat/complete/fail 用例通过
  **依赖**: T045

- [x] **T088**: resume 与统一业务状态投影
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_execution_coordinator.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_scenario_handler.py`
  **逻辑**: 实现 session-bound `prepare_resume`，新 token 下原子恢复未完成 steps；统一 pending/parsing/parse_failed/execute_failed/published 投影，不允许 executed+parsing 组合。
  **测试**: T045 的 resume/token/projection 用例通过
  **依赖**: T046

- [x] **T047**: 部门知识空间私密约束测试
  **文件**: `src/backend/test/department/test_department_space_private_forbidden.py`
  **逻辑**: 部门空间创建/更新为 private 均拒绝，普通空间 private 及历史数据不被静默改写。
  **覆盖 AC**: AC-39, AC-41, AC-42
  **依赖**: T006

- [x] **T048**: 部门空间私密约束实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  **逻辑**: 两条权威写入口服务端校验绑定；不只依赖前端隐藏。
  **测试**: T047 全部通过
  **依赖**: T047

---

## Wave 4：后端 API 与 Worker

### 后端 API（Test-First）

- [x] **T049**: 管理策略 API 测试
  **文件**: `src/backend/test/knowledge/test_file_change_policy_api.py`
  **逻辑**: GET/PUT policy、space settings 分页、管理员权限、保存失败、tenant 参数拒绝与隔离；策略保存成功调用 ensure，保存回滚不得留下半场景。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-53
  **依赖**: T020

- [x] **T050**: 管理策略 endpoints
  **文件**: `src/backend/bisheng/knowledge/api/endpoints/knowledge_space_file_change.py`, `src/backend/bisheng/knowledge/api/router.py`
  **逻辑**: 实现 `GET|PUT /api/v1/knowledge/space/admin/file-change-policy`、`GET /api/v1/knowledge/space/admin/file-change-settings?keyword=&page=&page_size=`、`PUT /api/v1/knowledge/space/admin/file-change-settings/{space_id}`；使用 UnifiedResponseModel，body 仅含 `enabled/scope` 或 `approval_required`，tenant/admin 从依赖注入获取；策略保存事务成功时幂等 ensure 固定场景。
  **测试**: T049 全部通过
  **依赖**: T018, T049

- [x] **T051**: mutation 逐项响应 API 测试
  **文件**: `src/backend/test/knowledge/test_file_change_mutation_api.py`
  **逻辑**: files/folder-upload/rename/move/delete/batch-rename/batch-delete 混合 direct/pending/invalid，单项失败不回滚。
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-11, AC-12, AC-26, AC-27, AC-31, AC-43, AC-45, AC-49, AC-50, AC-52
  **依赖**: T028, T032, T086, T087

- [x] **T052**: 现有 mutation endpoints 接入编排
  **文件**: `src/backend/bisheng/knowledge/api/endpoints/knowledge.py`, `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`
  **逻辑**: `/api/v1/knowledge/upload` multipart 创建 stage 并返回 `upload_id`；接入 `POST .../files`、`POST .../folders/upload`、`PUT .../files/{id}`、`PUT .../folders/{id}`、`DELETE .../files/{id}`、`DELETE .../folders/{id}`、`POST .../files/move`、`POST .../files/batch-delete`，新增 `POST .../files/batch-rename`。上传 body 只传 upload_id；单条返回 decision envelope，批量返回 direct/pending/invalid 分组。
  **测试**: T051 全部通过
  **依赖**: T051

- [x] **T053**: 待审批上传/详情/审批 API 测试
  **文件**: `src/backend/test/knowledge/test_file_change_api.py`
  **逻辑**: cursor 列表、详情/预览、withdraw/cleanup、retry-ingest、批量 approve 部分失败最新状态和 former 审核人拒绝。
  **覆盖 AC**: AC-14, AC-16, AC-17, AC-18, AC-20, AC-21, AC-23, AC-30, AC-33, AC-34, AC-36, AC-37, AC-38, AC-51, AC-53
  **依赖**: T030, T034, T088

- [x] **T054**: 待审批与批量审批 endpoints
  **文件**: `src/backend/bisheng/knowledge/api/endpoints/knowledge_space_file_change.py`, `src/backend/bisheng/knowledge/api/router.py`
  **逻辑**: 落地 `GET .../file-changes/uploads`、`GET .../file-changes/{request_id}`、`GET .../{request_id}/preview`、`POST .../{request_id}/retry-ingest`、`DELETE .../{request_id}`、`POST .../file-changes/batch-approve`；batch body 仅允许 instance IDs 或 request IDs 二选一，响应 `successCount/failureCount/items(latestStatus,error,retryable)`。
  **测试**: T053 全部通过
  **依赖**: T053

### Worker（Test-First）

- [x] **T055**: 审批对账 Worker 测试
  **文件**: `src/backend/test/approval/test_file_change_approver_reconcile_worker.py`
  **逻辑**: 权限事件、惰性与 Beat 三层触发；跨租户游标、单租户失败隔离、默认队列、former/new manager 通知幂等。
  **覆盖 AC**: AC-14, AC-23, AC-28, AC-29, AC-30, AC-34, AC-36, AC-53
  **依赖**: T012, T014, T030

- [x] **T056**: 审批对账 Worker 实现
  **文件**: `src/backend/bisheng/worker/approval/file_change_tasks.py`, `src/backend/bisheng/worker/approval/__init__.py`
  **逻辑**: task headers 携 tenant_id，入口恢复 ContextVar；Beat bypass 枚举后逐 tenant 调 F025 动态 Service，指数 backoff。
  **测试**: T055 全部通过
  **依赖**: T055

- [x] **T089**: owner/manager 权限变更触发测试
  **文件**: `src/backend/test/permission/test_file_change_approver_reconcile_triggers.py`
  **逻辑**: 通用 authorize、direct permission sync、部门/SSO 清理在事务成功后仅对受影响知识空间投递一次对账；事务回滚不投递，投递失败不回滚权限写。
  **覆盖 AC**: AC-14, AC-23, AC-28, AC-30, AC-34, AC-36, AC-53
  **依赖**: T056

- [x] **T090**: owner/manager 权限变更触发实现
  **文件**: `src/backend/bisheng/permission/domain/services/resource_authorization_service.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  **逻辑**: owner/manager relation 写成功后以 post-commit effect 投递 T056；direct sync、部门管理员同步和 SSO/组织清理统一经过同一 helper，参数通过 Celery headers 携 tenant_id。
  **测试**: T089 全部通过
  **依赖**: T089

- [x] **T057**: Deferred watchdog/step/cleanup Worker 测试
  **文件**: `src/backend/test/approval/test_file_change_execution_worker.py`
  **逻辑**: deferred 不被普通 claim；heartbeat 超时 fail；step 补投/ack；stage 与 purge cleanup 幂等且不假成功。
  **覆盖 AC**: AC-15, AC-16, AC-17, AC-18, AC-20, AC-21, AC-24, AC-27, AC-32, AC-48, AC-53
  **依赖**: T022, T088, T092

- [x] **T058**: Deferred/step/cleanup Worker 实现
  **文件**: `src/backend/bisheng/worker/approval/file_change_tasks.py`, `src/backend/bisheng/worker/knowledge/file_worker.py`
  **逻辑**: 默认 celery 队列编排 watchdog/coordinator/cleanup；knowledge worker 回传稳定 step key/token，headers→tenant ContextVar。
  **测试**: T057 全部通过
  **依赖**: T057

- [x] **T059**: Beat 配置注册测试
  **文件**: `src/backend/test/approval/test_file_change_beat_schedule.py`
  **逻辑**: 对账、deferred watchdog、step 补偿、stage/purge 清理均注册非空 schedule 且单次 Beat 触发。
  **覆盖 AC**: AC-18, AC-21, AC-24, AC-28, AC-30, AC-32, AC-53
  **依赖**: T056, T058

- [x] **T060**: Beat schedule 实现
  **文件**: `src/backend/bisheng/core/config/settings.py`, `src/backend/bisheng/worker/__init__.py`
  **逻辑**: 注册四类补偿任务，保持默认 celery 队列；不得按 worker 副本重复跨租户扫描。
  **测试**: T059 全部通过
  **依赖**: T059

---

## Wave 5：Frontend Platform

### 前端 Platform

- [x] **T061**: Platform 策略 API client
  **文件**: `src/frontend/platform/src/controllers/API/knowledgeSpaceFileChange.ts`
  **逻辑**: 定义 policy/setting 类型和四个请求；使用封装 request，不接受 tenant_id。
  **依赖**: T050

- [x] **T062**: Platform 策略配置组件
  **文件**: `src/frontend/platform/src/pages/KnowledgePage/FileChangeApprovalSettings.tsx`
  **逻辑**: 总控、all/per-space、keyword/page 表格、私密行禁用、部门空间提示；保存成功才更新基线。
  **依赖**: T061

- [x] **T063**: Platform 页面入口集成
  **文件**: `src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpace.tsx`, `src/frontend/platform/src/pages/KnowledgePage/index.tsx`
  **逻辑**: 将租户级总控和按空间配置嵌入 `/build/client` 的“知识空间”配置页并接入底部统一保存；移除 `/filelib` 的独立设置 Tab，不改变既有知识库详情主流程。
  **依赖**: T062

- [x] **T064**: Platform 配置组件测试
  **文件**: `src/frontend/platform/src/test/fileChangeApprovalSettings.test.tsx`
  **逻辑**: 默认值、未保存不生效、保存失败、关闭再开、私密禁用、tenant_id 不上行。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-39, AC-41, AC-53
  **依赖**: T063

- [x] **T065**: Platform 中英知识空间文案
  **文件**: `src/frontend/platform/public/locales/zh-Hans/knowledge.json`, `src/frontend/platform/public/locales/en-US/knowledge.json`
  **逻辑**: 增加策略、范围、保存、私密/部门提示和错误文案。
  **依赖**: T062

- [x] **T066**: Platform 日文知识空间文案
  **文件**: `src/frontend/platform/public/locales/ja/knowledge.json`
  **逻辑**: 与 T065 key 完全一致，禁止 fallback 硬编码中文。
  **依赖**: T065

---

## Wave 6：Frontend Client

### 前端 Client

- [x] **T067**: Client API 类型与请求封装
  **文件**: `src/frontend/client/src/api/knowledge.ts`, `src/frontend/client/src/api/approval.ts`
  **逻辑**: 定义 upload_id、逐项 mutation、file change view、cursor、详情、retry、cleanup、batch approve 类型和请求。
  **依赖**: T052, T054

- [x] **T068**: 上传 hook 迁移 opaque upload_id
  **文件**: `src/frontend/client/src/pages/knowledge/hooks/useFileUpload.ts`
  **逻辑**: multipart 后提交 upload_id；逐文件 direct/pending/invalid；注册重试复用 upload_id，不把 pending 插入正式列表。
  **依赖**: T067

- [x] **T069**: 上传 hook 测试
  **文件**: `src/frontend/client/src/pages/knowledge/hooks/useFileUpload.test.ts`
  **逻辑**: 混合批次、超时重试幂等、pending 独立列表、内容变化新 upload、解析重试不重审。
  **覆盖 AC**: AC-12, AC-13, AC-18, AC-19, AC-20, AC-21, AC-27, AC-49
  **依赖**: T068

- [x] **T070**: rename/move/delete hooks 逐项决策
  **文件**: `src/frontend/client/src/pages/knowledge/hooks/useFileManager.ts`, `src/frontend/client/src/pages/knowledge/hooks/useKnowledgeMove.ts`
  **逻辑**: 只对 direct/deleted/renamed/moved 更新 UI；pending 保留资源并刷新 approval view；invalid 单项反馈。
  **依赖**: T067

- [x] **T071**: mutation hooks 测试
  **文件**: `src/frontend/client/src/pages/knowledge/hooks/useFileManager.test.ts`
  **逻辑**: 删除不乐观移除 pending；批量部分失败不回滚成功；审批锁禁用重复操作；移动/重命名保留旧值。
  **覆盖 AC**: AC-22, AC-25, AC-26, AC-31, AC-37, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-52
  **依赖**: T070

- [x] **T072**: 文件变更状态与权限 hook
  **文件**: `src/frontend/client/src/pages/knowledge/hooks/useFileChangeApproval.ts`
  **逻辑**: 批量合并列表 enrichment、动态 canApprove、根/继承锁、详情刷新和 batch approve 部分结果。
  **依赖**: T067

- [x] **T073**: 正式文件表格/卡片审批状态
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/FileTable.tsx`, `src/frontend/client/src/pages/knowledge/SpaceDetail/FileCard.tsx`
  **逻辑**: 仅根资源显示审批中；申请人/当前审核人可打开动作详情；祖先锁时菜单禁用，普通用户不见审批字段。
  **依赖**: T070, T072

- [x] **T074**: 待审批上传面板
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/PendingFileChangesPanel.tsx`
  **逻辑**: 独立展示 pending/parsing/parse_failed/execute_failed，支持筛选、预览、清理、retry 与当前审核人多选通过。
  **依赖**: T072

- [x] **T075**: 动作详情与批量反馈组件
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/FileChangeApprovalDetail.tsx`
  **逻辑**: 展示 rename/move/delete 待生效值、申请/执行失败原因；批量反馈成功/失败数和每项 latestStatus/retryable，停留当前页。
  **依赖**: T072

- [x] **T076**: Approval Center 处理后停留待办
  **文件**: `src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx`
  **逻辑**: 成功后移除当前 pending、自动选下一条或空状态；展示 business projection；不得携旧 task 自动切 processed。
  **依赖**: T067

- [x] **T077**: Client 审批状态交互测试
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/FileChangeApproval.test.tsx`, `src/frontend/client/src/components/approval/ApprovalCenterDialog.test.tsx`
  **逻辑**: 标签/动作/继承锁、动态审批、former 不可见、批量部分失败、解析状态、Approval Center 下一条行为。
  **覆盖 AC**: AC-14, AC-16, AC-17, AC-23, AC-30, AC-31, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-43, AC-45, AC-50, AC-51, AC-52
  **依赖**: T073, T074, T075, T076

- [x] **T078**: Client 中英文文案
  **文件**: `src/frontend/client/src/locales/zh-Hans/translation.json`, `src/frontend/client/src/locales/en/translation.json`
  **逻辑**: 待审/解析/失败、动作详情、锁、批量结果、清理/retry 文案 key 对齐。
  **依赖**: T073, T074, T075

- [x] **T079**: Client 日文文案
  **文件**: `src/frontend/client/src/locales/ja/translation.json`
  **逻辑**: 与 T078 key 完全一致，禁止 fallback 硬编码中文。
  **依赖**: T078

---

## Wave 7：E2E、回归与文档同步

### E2E / 集成测试

- [x] **T080**: F046 API E2E 主路径
  **文件**: `src/backend/test/e2e/test_e2e_f046_file_change_approval.py`
  **逻辑**: 双租户策略、editor/owner/manager、四动作、folder subtree、direct/pending、动态审批人、部分批量、执行失败/resume。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-18, AC-20, AC-21, AC-22, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-34, AC-36, AC-37, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-48, AC-49, AC-50, AC-52, AC-53
  **依赖**: T048, T052, T054, T060, T090

- [x] **T081**: F046 发布与可见性 E2E
  **文件**: `src/backend/test/e2e/test_e2e_f046_file_change_visibility.py`
  **逻辑**: 审批前无正式行；parsing/parse_failed；children/search/F030/RAG/citation/preview；delete cutover 前后；former manager 可见性。
  **覆盖 AC**: AC-13, AC-14, AC-15, AC-16, AC-17, AC-19, AC-22, AC-23, AC-24, AC-30, AC-33, AC-47, AC-51
  **依赖**: T036, T038, T040, T052, T054, T058

- [x] **T082**: 前端 E2E 与人工验证清单
  **文件**: `features/v2.6.0/046-knowledge-space-file-change-approval/e2e-checklist.md`
  **逻辑**: 使用 `/e2e-test` 产出 Platform `/build/client`“知识空间”配置页与 Client 空间页/审批中心的账号矩阵、操作步骤、预期状态和截图点；不保存密码。
  **覆盖 AC**: AC-04, AC-12, AC-14, AC-16, AC-17, AC-23, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-41, AC-43, AC-45, AC-50, AC-51, AC-52, AC-53
  **依赖**: T064, T077, T080, T081

### 文档与回归

- [x] **T083**: 审批模块 skill 同步
  **文件**: `.claude/skills/approval-module/SKILL.md`
  **逻辑**: 更新动态候选发现、Decision UoW、Deferred outbox、固定场景 exception policy、默认队列/通知矩阵和 F046 代码锚点。
  **依赖**: T018, T030, T060, T088, T090, T092

- [x] **T084**: F025/F027/F029/F030/F034/F044 回归集合
  **文件**: `features/v2.6.0/046-knowledge-space-file-change-approval/regression-checklist.md`
  **逻辑**: 记录聚焦 pytest、前端测试/构建、arch-guard、git diff check、DM8/中间件 CI 项与结果；特别验证 F045 邀请确认和无需审核直通。
  **覆盖 AC**: AC-06, AC-10, AC-15, AC-24, AC-28, AC-29, AC-35, AC-41, AC-42, AC-47, AC-53
  **依赖**: T080, T081, T083

---

## AC 追踪汇总

| AC | 主要自动化任务 |
|---|---|
| AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07 | T019, T049, T064, T080 |
| AC-08, AC-09, AC-10, AC-11 | T027, T051, T080 |
| AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21 | T021, T031, T033, T037, T053, T069, T080, T081 |
| AC-22, AC-23, AC-24, AC-25, AC-26, AC-27 | T033, T043, T051, T053, T071, T080, T081 |
| AC-28, AC-29, AC-30, AC-31, AC-32 | T009, T011, T013, T023, T027, T041, T043, T045, T080 |
| AC-33, AC-34, AC-35, AC-36, AC-37, AC-38 | T053, T077, T080, T081, T082 |
| AC-39, AC-40, AC-41, AC-42 | T019, T047, T064, T080 |
| AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52 | T023, T027, T035, T041, T043, T051, T053, T071, T077, T080, T081 |
| AC-53 | T019, T021, T023, T039, T049, T053, T055, T057, T059, T064, T080, T082 |

---

## 实际偏差记录

| 日期 | 任务 | 偏差 | 处理/确认 |
|---|---|---|---|
| 2026-08-10 | T006 | 本 worktree 缺少 `src/backend/bisheng/config.yaml`，现有 pytest 在 conftest 导入阶段 `FileNotFoundError`，未进入用例 | 已完成 schema/errcode import smoke、py_compile、changed-file ruff 与 diff check；保留为环境基线，集成阶段配置测试环境后补跑 |
| 2026-08-10 | T026 | 现有 `PermissionService.get_resource_permissions()` 会吞掉 FGA 故障并且不能权威展开 userset，原限定的 knowledge resolver 单文件无法区分“权威空集合”和“基础设施故障” | 经整合审查扩展最小 owner scope：PermissionService strict API + GrantSubjectQueryRepository 批量租户受限展开 + permission 回归测试；禁止 membership 降级与 N+1 |
| 2026-08-10 | T014 | 原文件清单未包含动态候选的持久化查询；仅在 Center 保存进程内游标会被多 worker/重启破坏，且前批可能长期遮挡后批 | 最小扩展 `KnowledgeSpaceFileChangeRequestRepository` 的 tenant-bound `NOT EXISTS pending task` 候选查询；查询前有界分批对账，不保存进程内游标 |
| 2026-08-10 | T028 | 上传注册超时重试需按暂存记录恢复原 request/instance，原任务文件清单未包含该仓储查询 | 最小扩展 `KnowledgeSpaceFileChangeRequestRepository.get_by_upload_stage_id(..., for_update)`；申请 UoW 必须由组装层注入 Knowledge owner 的 authorizer、footprint resolver、direct executor 和 notifier，禁止默认空 footprint |
| 2026-08-10 | T030 | 上传审批终态清理需持久化 request cleanup marker，而原任务文件清单未包含 request repository/save 和 Gate snapshot 的不透明 stage 引用 | 最小扩展 request repository `save()`，Gate payload 仅增加 opaque `upload_id`（不含 object key）；handler 先 request=cleanup pending，再调 owner UploadStageService.cleanup，成功后 success，失败保留 pending 供补偿 |
| 2026-08-10 | T056 | 仅修改 Worker 无法实现持久化跨进程游标和完整 runtime handler 调用，也无法遵守 worker→service→repository 分层 | 最小扩展 request repository 的 tenant-bound F046 活跃申请 keyset 查询、scenario handler 的 space/tenant 有界对账入口，并同步 approval-module 对账代码锚点；Worker 不直接读写 Approval* |
| 2026-08-10 | T034 | 为避免 guard 在 request/正式文件/step/footprint 上逐资源 N+1，原任务文件清单不足以提供批量真值查询 | 最小扩展 request/footprint/mutation repository 的显式 tenant+space 批量读；SQL 不查 JSON，publication 固定两次查询、deletion 固定两次查询；共享目录只在已发布 child 存在时解除目录门禁 |
| 2026-08-10 | T032 | 原两个 Service 文件无法在遵守 C1 的同时实现正式 File/Document/V1/request/step 同事务、提交后副作用和解析跨 fair/direct 稳定幂等 | 最小扩展 session-bound mutation/step repository 以及 scheduler/file-worker/Lua owner 链路；执行前复用 Knowledge owner 的 `upload_file` permission-id 语义并重验空间/原目录/用户与租户配额，不将自定义模型固定为 `can_edit` |
| 2026-08-10 | T090 | 原文件清单未覆盖部门管理员/SSO、调岗、账号删除和批量 owner transfer 的真实 OpenFGA 写入路径，且 FGA 与 binding DB 无共享事务 | 新增无 Approval 写入的统一 dispatcher；单条在 `PermissionService.authorize` 权威 FGA 成功后触发，部门/SSO/批量迁移按 space 去重；FGA 成功但 binding 失败仍投，FGA 失败不投，broker 失败由 lazy/Beat 补偿；tenant header 显式且无 root fallback |
| 2026-08-10 | T038 | 原任务文件清单无法覆盖 citation shared accessScope 与真实 preview/download/batch-download 入口 | 最小扩展 `citation_resolve_service.py` 和 `knowledge_space_service.py`；F046 hard deny 在 shared 元数据分层前丢弃整条 citation，preview/download 始终先过既有 ReBAC/下载权限再组合 guard，缺 knowledgeId 批量回查避免 N+1 |
| 2026-08-11 | T036 | 正式 children/search 接入 hard deny 后，原逐目录计数路径会泄露隐藏文件数量；直接排除全部 hidden ids 又可能产生超长参数或物化完整子树 | 页内目录以 portable `UNION ALL` 每 100 个目录聚合，hidden ids 每 500 条显式 tenant 查询后扣减；同一请求缓存 guard 结果，verified global super 仅在显式 admin-scope child tenant 下放行，普通 tenant mismatch 失败关闭 |
| 2026-08-11 | T040 | 原任务列出 `filelib.py`，但 type=3 列表/关键词搜索已由 T035/T036 的 Knowledge owner Service 统一门禁；在 endpoint 重复过滤会增加查询，真实缺口仅为 OpenAPI retrieval 仍绕过统一检索门禁 | 不改 endpoint，最小修正 `KnowledgeSpaceChatService` 的 type=3 分派复用 `_retrieve_and_filter`，统一 primary/ReBAC/publication/deletion 的索引前和结果后过滤；更新 F030 过时 mock 并保留代用户、显式 tenant 失败关闭测试 |
| 2026-08-11 | T042, T086 | 原任务文件清单未包含正式资源 owner Repository，Service 内直接写 File/Document/Version 会违反 C1，也无法保证末端 cutover 与 request/step 同事务 | 最小扩展 session-bound `KnowledgeSpaceMutationRepository`：rename/move 先持久化不可变 manifest，外部步骤只接受 read-after-verified 回执，末端同事务再次重验当前 strict 权限、空间状态、资源/子树/版本链完整集合后切换 DB；跨租户版本 sibling 与不完整 document 集合失败关闭 |
| 2026-08-11 | T042, T058 | 原步骤集无法表达跨 MySQL/DM8、OpenFGA、ES、Milvus 的连续旧视图与 DB 提交后的可恢复残留清理；task id 也不能作为 owner 完成证据 | 最小扩展 token-bound `ProductionMutationStepOwner`、durable `OLD_VIEW/NEW_VIEW` read projection、双 parent prepare、DB+phase+F025 terminal 同 UoW 与 `continue_post_cutover_cleanup()`；cleanup 成功才退役 footprint，失败由 APPLIED+active Beat candidate 幂等续跑；rename NEW_VIEW cleanup 前以新→旧查询扩展保持召回 |
| 2026-08-11 | T044, T087 | 删除 cutover 需与 F025 deferred 完成同事务，原文件清单不足以表达全局锁序和 purge 后停止历史门禁扫描的持久化真值 | 最小扩展 F025 session-bound completion、mutation/footprint owner repository 与 strict FGA delete API；固定 `instance→outbox→request→space/resource→steps` 锁序，cutover 前二次重验，purge 失败保留 active footprint 门禁，全成功后退役 footprint 避免历史线性扫描 |
| 2026-08-11 | T052 | 原任务文字把 opaque stage 上传写为无空间参数的 `/knowledge/upload`，但该路径还被工作流/模型等非知识空间上传复用，无法安全绑定 stage.space_id | 仅将现有知识空间专用 `/knowledge/upload/{space_id}` 迁移为 opaque `upload_id`，保留共享 `/knowledge/upload` 旧语义；后续 T067/T068 同步迁移 Client，发布时前后端必须一起交付 |
| 2026-08-11 | T046, T088 | 单一 coordinator 文件无法闭环 execute_failed 从 F025 异常 API 到新 token 步骤恢复和提交后补投的公共契约 | 最小扩展 scenario handler 的 `prepare_resume/dispatch_resumed_execution` 与 F025 ExceptionService 分流；approver_empty 仅动态对账，execute_failed 仅走 Deferred resume；步骤按依赖逐个放行，DB cutover 永不进通用 broker，FAILED 代必须生成新 token 后才能继续 |
| 2026-08-11 | T053, T054 | 原 API 任务文件清单没有知识域列表/详情 owner Service，endpoint 直接拼 Approval/Knowledge ORM 会违反 C1，且无法批量投影解析状态 | 新增 `KnowledgeSpaceFileChangeApplicationService` 与 request repository 的显式 tenant+space 只读 join/批量投影；Approval 仍由 F025 写入，former 审核人 known-ID 按 not_found 处理，正式文件状态同时校验 tenant 与预期 space，列表固定批量查询无逐行 N+1 |
| 2026-08-11 | T068, T069 | 既有 `useFileUpload.ts` 在接入 staged upload 后超过前端单文件 600 行上限，且上传注册/结果分组与 UI 状态职责混杂 | 抽出 `useKnowledgeStageUpload.ts` 和 `fileUploadUtils.ts`；原 hook 保持 277 行，文件/文件夹注册均以原 upload_id 幂等重试，pending 只触发独立待审批刷新 |
| 2026-08-11 | T070, T071 | 既有 rename/delete mutation 编排实际位于 `useFileUpload.ts`，原任务指定 `useFileManager.ts` 会继续混合上传、变更决策和 UI 状态职责 | 按 react-component-refactor 指引抽出 `useKnowledgeFileMutations.ts` 与纯函数 `fileMutationUtils.ts`；single/batch/move 仅对 direct/completed 项更新 UI，pending 保留旧资源并刷新审批视图，新增 8 条聚焦测试覆盖逐项结果和根/继承锁 |
| 2026-08-11 | T077 | 本地 Client Jest 的默认 jsdom 在 suite 收集前因既有可选依赖 `canvas.node` 缺失失败，无法执行 Radix Dialog 组件交互 | 保留组件交互测试供正常 CI 环境执行，不 skip/不伪造；把 task 选择和 business projection 拆为纯函数并以 node 环境 7 条测试验证，SpaceDetail 6 条纯投影测试和聚焦 ESLint 均通过 |
| 2026-08-11 | T080, T081, T082 | 本地没有经明确授权的 live 双租户、Celery、RAG、解析失败注入和部门空间测试环境，不能把用例收集等同于端到端验收 | 14 条 E2E 成功收集，默认无 `E2E_F046_ENABLED=1` 时全部显式 skip 且不写 API；清理仅限本进程唯一 RUN_PREFIX，清单记录环境前置、账号矩阵和截图点，真实验收留给具备依赖的环境 |
| 2026-08-11 | T060 | 用户确认上传沿用统一临时桶流程且应用不管理 unbound tag | upload 流式写临时 bucket；申请绑定后以 `attaching` + post-commit/Beat 幂等复制到永久 bucket；未绑定 orphan 由临时 bucket 生命周期删除，应用仅对账 stage 元数据与配额 |
