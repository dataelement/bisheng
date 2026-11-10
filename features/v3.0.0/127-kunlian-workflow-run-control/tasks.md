# 昆联反向调用毕昇 Workflow 的运行控制任务

- **Feature ID** `F127`（拟用，合入前复核）
- **版本** `v3.0.0`
- **关联** [已确认规格](./spec.md) · [已确认设计](./design.md) · [版本契约](../release-contract.md)

## 1. 状态与批次验收

| 阶段 | 状态 |
| --- | --- |
| 规格与设计 | `CONFIRMED`，用户确认进入任务拆分。 |
| 任务计划 | 已确认，按四批完成实施与审查。 |
| Mock 实施 | `PASS`，19 / 19。 [验证记录](./verification.md) |
| 正式契约与适配 | T020、T021 为 `WAITING_EXTERNAL`。 |
| 真实环境验收 | T022（V-03）、T023（V-04）为 `NOT_RUN`，待执行。 |

| 批次 | 任务 | 前置 | 可验收出口 |
| --- | --- | --- | --- |
| **W1 · 取消与终态竞争** | T001–T007 | 已确认规格与设计 | V-01。可控时钟、独立事务和隔离 HTTP 证明取消、成功、超时与答复的先后裁决。重复取消或响应丢失后重试只产生一次有效操作。 |
| **W2 · 执行边界与跨 Worker 补偿** | T008–T013 | W1 | V-01、V-02。Worker A 在受理取消后退出，达到原执行截止时由 Worker B 确认同一会话终态。旧派发、旧领取和迟到输出均被拒绝。 |
| **W3 · 事件续读与权限** | T014–T018 | W1、W2 | V-02。事件可跨页重读，过期位置可按授权快照重建。逐项验证状态、结果、事件、追踪和取消的访问权限。 |
| **W4 · Mock 闭环与兼容回归** | T019 | W1–W3 | V-02。隔离 API、实际本地队列和独立 Worker 跑通固定版本、等待、取消、断线续读与终态，保留原反向调用和文本交互行为。 |
| **W5 · 正式契约与真实环境** | T020–T023 | 各任务前置 | 正式契约、受控基础设施和昆联联调分别记录。受控基础设施可先用 Mock，昆联验收使用正式接入。 |

`B/` 指 `src/backend/bisheng/`，`BT/` 指 `src/backend/test/workflow/`。新测试文件为实施落点。后端先写失败用例，再完成同批实现。复用 `invocation_registration_store`、F123 的原生等待点夹具及 F126 的本地 Redis 独立 Worker 方式。隔离装配使用临时数据库、回环队列及可控时钟。队列任务从可信 `tenant_id` 消息头建立租户 ContextVar，再核对原会话和接入范围。取消、事件与权限沿用[设计约束](./design.md)，实施完成后按批次记录证据到 `verification.md`。

## 2. Mock 任务

### W1 取消与终态竞争

- [x] **T001** [后端 Domain 测试] 在 `BT/test_kunlian_workflow_run_control_cancel.py` 复用独立 SQL 连接和可控时钟。参数化排队、等待输入、待恢复及活跃领取，覆盖取消与成功、截止及答复竞争，重复取消、提交回滚、晚到写入。核对事件和状态一起提交，原失败及超时终态保持稳定，原结果、截止及既有答复回执按裁决保留。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-04 · _Verification: V-01, V-02 的事件事务前置_ · _Depends: 无_
- [x] **T002** [后端 Domain] 在 `B/workflow/domain/schemas/kunlian_workflow_invocation.py` 定义受支持的 `run_control` 子记录及事件更新规则。用现有 JSON 记录保存 `format`、稳定追踪标识、递增序号、裁剪位置和最小取消回执。事件仅含安全字段。未知格式走明确拒绝，原请求摘要保持兼容。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-06_ · _Acceptance: AC-03, AC-04, AC-08_ · _Verification: V-01, V-02，复用 T001_ · _Depends: T001_
- [x] **T003** [后端 Domain] 在 `B/workflow/domain/repositories/kunlian_workflow_run.py` 扩展 `admit`、条件更新及终态材料裁剪。仅按服务端装配为新会话写控制标记，受理、领取、等待、答复、恢复、成功和失败各写相应事件。状态和事件同一次条件写入，回滚或竞争失败时两者均无提交。重放旧会话沿用原摘要和能力，终态保留控制记录及已受理答复回执。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-06_ · _Acceptance: AC-03, AC-04, AC-08_ · _Verification: V-01, V-02，复用 T001_ · _Depends: T001, T002_
- [x] **T004** [后端 Domain] 在 `B/workflow/domain/repositories/kunlian_workflow_run.py` 增加 `request_cancel` 及原领取者的取消确认。锁内复核归属、状态、领取标识和阶段期限。空闲阶段原子写取消受理与取消终态，活跃阶段先写 `CANCEL_REQUESTED`。复用 `finish`、`finish_resume` 的事务边界裁决取消与输出，原终态保持稳定。答案按原规则查回已受理回执，取消后无新推进或派发。
  - _Requirements: REQ-01, REQ-02, REQ-03_ · _Acceptance: AC-01, AC-02, AC-03_ · _Verification: V-01，联跑 T001_ · _Depends: T001, T003_
- [x] **T005** [后端 API 测试] 在 `BT/test_kunlian_workflow_run_control_api.py` 复用隔离 ASGI 装配，覆盖 `POST /cancel`、`GET ?view=status`、当前归属和 `use` 校验。验证 `202` 待确认、`200` 已终结、响应丢失重试及未装配旧会话的兼容口径。以无权身份尝试取消，核对运行无变化。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-06, AC-08 · _Verification: V-01, V-02_ · _Depends: T003_
- [x] **T006** [后端 Domain] 在 `B/workflow/application/kunlian_workflow_invocation.py` 接通服务端控制标记及 `cancel`、状态摘要。复用 `_authorized_row` 和真实用户 `use` 核验。隔离装配注入操作级策略，先接入 `cancel`、`status`、旧查询涉及的 `result`／`interaction`，并在提交答案前核验 `interaction`。权限不可判定时关闭访问。仓储再核对归属、期限和取消裁决。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06_ · _Acceptance: AC-01, AC-02, AC-06, AC-08_ · _Verification: V-01, V-02，联跑 T005_ · _Depends: T004, T005_
- [x] **T007** [后端 API] 在 `B/open_endpoints/api/endpoints/kunlian_workflow_runs.py` 接入隔离候选 `POST /cancel` 和 `GET ?view=status`。复用可信依赖、统一响应和安全错误，返回必要摘要及适用的 `cancel_state`，设置 `no-store`。默认旧查询继续走原有合同及所需授权。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06_ · _Acceptance: AC-01, AC-02, AC-03, AC-06, AC-08_ · _Verification: V-01, V-02，联跑 T005_ · _Depends: T005, T006_

**批次验收。** 在 `src/backend` 的项目 Python 环境联跑 `test_kunlian_workflow_run_control_cancel.py` 和 `test_kunlian_workflow_run_control_api.py`。核对数据库状态、输出、取消事件数及 HTTP 结果。成功先提交时保留原输出，取消先裁决时无迟到输出，已到期的未取消运行按原阶段超时。按批记录命令、结果、跳过原因和相关验收项。

### W2 执行边界与跨 Worker 补偿

- [x] **T008** [Worker 测试] 在 `BT/test_kunlian_workflow_run_control_worker.py` 用可控文本节点阻塞执行，覆盖首次执行、等待点写入失败、恢复材料装载前、恢复首节点和输出适配节点。以可信 `tenant_id` 头进入 ContextVar，检查取消先受理后无下一节点和无结果，原领取者能确认取消，旧未标记图保持原路径。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-06_ · 覆盖 AC: AC-01, AC-02, AC-08 · _Verification: V-01, V-02_ · _Depends: T004_
- [x] **T009** [后端 Domain] 在 `B/workflow/graph/workflow.py` 和 `B/workflow/graph/graph_engine.py` 增加可选节点入口检查并由 `_node_runner` 调用。核对同步及异步路径和输出适配节点。缺省不装配检查的既有图继续使用原运行行为。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-06_ · _Acceptance: AC-02, AC-08_ · _Verification: V-01, V-02，复用 T008_ · _Depends: T008_
- [x] **T010** [后端 Domain] 在 `B/workflow/domain/repositories/kunlian_workflow_run.py` 增加短事务节点准入检查。由 Worker 的可信租户 ContextVar 读取原会话，要求匹配活跃阶段、当前领取及有效期限。对取消中、已终结、过期或归属不符的读取关闭准入。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05_ · _Acceptance: AC-02, AC-03, AC-06_ · _Verification: V-01，复用 T008_ · _Depends: T004, T008_
- [x] **T011** [Worker] 在 `B/worker/workflow/kunlian_workflow_run.py` 为带控制标记的已领取运行注入 T010 检查。恢复前核验，再经图入口检查每个后续节点。图提前退出、等待写入未获准及最终提交均使用原领取执行取消确认。可信 `tenant_id` 由 Celery 头进入 ContextVar，旧任务派发协议继续沿用。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-06_ · _Acceptance: AC-01, AC-02, AC-03, AC-08_ · _Verification: V-01, V-02，联跑 T008_ · _Depends: T008, T009, T010_
- [x] **T012** [Worker 测试] 在 `BT/test_kunlian_workflow_run_control_e2e.py` 与 `BT/kunlian_workflow_run_control_worker.py` 复用本地队列、独立进程和原生输入夹具。Worker A 领取后停在可控节点，取消提交后退出。Worker B 用可信租户头进入 ContextVar，按隔离配置扫描原接入范围。核对原截止前仍待确认，达到原截止后原会话取消，重复扫描只有一个取消终态事件。旧消息无法领取，前序与下游节点的执行次数均不增加。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05_ · 覆盖 AC: AC-01, AC-02, AC-06 · _Verification: V-02_ · _Depends: T007, T011_
- [x] **T013** [后端 Domain] 在 `B/workflow/domain/repositories/kunlian_workflow_run.py` 接入 `reconcile` 的独立有界取消扫描。按可信租户 ContextVar、接入方、原截止和会话定位，锁内复核后提交一次取消确认。现有 `WorkflowInvocationService.reconcile` 继续负责调度待领取任务。扫描保留原超时与清理口径，取消中的运行不会补投为新执行。记录安全的确认来源和期限日志。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05_ · _Acceptance: AC-01, AC-02, AC-04, AC-06_ · _Verification: V-02，联跑 T012，续读由 T014、T019 验证_ · _Depends: T004, T011, T012_

**批次验收。** 先跑 Worker 定向用例，再运行隔离队列验收。记录不同 Worker 的进程标识、原会话、固定版本、截止时间及最终事件数。补偿确认前后均验证迟到任务无法推进。缺本地 Redis 或独立 Worker 时，队列验收保留 `NOT_RUN`，定向结果单列。

### W3 事件续读与权限

- [x] **T014** [后端 Domain 测试] 在 `BT/test_kunlian_workflow_run_control_events.py` 使用隔离会话和可控时钟，覆盖分页续读、重复查询不消费、空页、超过最新序号、时间和条数裁剪，以及过期后以授权 `resume_after` 重建位置。核对终态事件和状态快照一致。
  - _Requirements: REQ-01, REQ-04, REQ-05_ · 覆盖 AC: AC-04, AC-05 · _Verification: V-02_ · _Depends: T003, T013_
- [x] **T015** [后端 API 测试] 在 `BT/test_kunlian_workflow_run_control_permissions.py` 复用 T005 的隔离装配。用不同租户、用户、接入方、撤权、停用和权限未知逐项调用取消、状态、结果、事件与追踪。用状态权限、结果权限和追踪权限分离的身份核对投影，验证拒绝时无正文、游标或状态写入。旧查询的相关权限未知时返回整次失败。
  - _Requirements: REQ-01, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-05, AC-06, AC-07, AC-08 · _Verification: V-02_ · _Depends: T005, T007_
- [x] **T016** [后端 Domain] 在 `B/workflow/domain/repositories/kunlian_workflow_run.py` 实现授权后重读的会话快照和事件分页。一次快照、一份仓储时钟计算有效下界与当前序号，按 `seq > after` 取页。查询保持日志不变，游标过期、序号超前和会话过期分别按候选合同处理。终态超出保留期后复用既有材料清理。
  - _Requirements: REQ-01, REQ-04, REQ-05_ · _Acceptance: AC-04, AC-05, AC-06_ · _Verification: V-02，联跑 T014_ · _Depends: T003, T013, T014_
- [x] **T017** [后端 Domain] 在 `B/workflow/application/kunlian_workflow_invocation.py` 接入 `events`、`result`、`trace` 的独立授权与投影。复核已验证实际用户和精确接入方，按操作重读归属与保留期。状态和事件都授权时从同一快照返回 `resume_after`。结果沿用冻结 Schema，追踪只返回可信关联标识。权限未知时整次拒绝。
  - _Requirements: REQ-01, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-04, AC-05, AC-06, AC-07, AC-08_ · _Verification: V-02，联跑 T014、T015_ · _Depends: T006, T014, T015, T016_
- [x] **T018** [后端 API] 在 `B/open_endpoints/api/endpoints/kunlian_workflow_runs.py` 接入 `GET /events?after=&limit=`、`view=result` 与 `view=trace`，串接状态视图的授权续读位置。沿用 `no-store` 与安全错误包装，映射过期起点、超前序号、结果未就绪和控制不可用。保留[设计中的四处正式 TODO](./design.md#run-control-contract)，只装配隔离 Mock。
  - _Requirements: REQ-01, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-04, AC-05, AC-06, AC-07, AC-08_ · _Verification: V-02，联跑 T014、T015_ · _Depends: T007, T014, T015, T017_

**批次验收。** 联跑 `test_kunlian_workflow_run_control_events.py` 和 `test_kunlian_workflow_run_control_permissions.py`。用一条事件一页验证序号稳定、跨页无缺漏和断线重读，再缩短窗口验证过期重定位。通过隔离 HTTP 断言权限边界与错误码，核对拒绝不改变运行，也不返回部分敏感字段。

### W4 Mock 闭环与兼容回归

- [x] **T019** [Worker 端到端验收] 在 `BT/test_kunlian_workflow_run_control_e2e.py` 串联固定版本受理、原生等待、取消、断线续读和终态读回，复用 T012 已验证的实际本地队列和独立 Worker。可信 `tenant_id` 头进入 ContextVar。用另一次未取消的运行验证 V2 替换发布后由另一 Worker 恢复原 V1、旧幂等启动及答复回执。用无权身份查询同会话。写入 `verification.md`，记录相邻回归、架构守卫及明确的环境边界。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-01, AC-02, AC-04, AC-05, AC-06, AC-07, AC-08 · _Verification: V-02_ · _Depends: T012, T013, T018_

**批次验收。** 以隔离 API 和真实本地 Broker 运行 T019。用同一会话标识对照 API、持久记录和 Worker 记录。阶段末联跑受影响的 F122 固定版本、F123 原生输入及共享图边界的 F126 相关回归，并做定向 Ruff、架构守卫与差异检查。V-02 只有实际独立 Worker 和本地队列证据齐备才标通过。

## 3. 正式契约与真实环境

- [ ] **T020** [正式契约] 在 `design.md` 落档 `TODO [F127][EXT-01]`、`TODO [F127][EXT-02]`、`TODO [F127][EXT-03]`、`TODO [F127][EXT-04]` 的双方确认结果。确认可信实际用户与动作范围、取消受理和终态、游标保留与追踪关联、OpenAPI 及测试样例。当前 `WAITING_EXTERNAL`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-01, AC-03, AC-04, AC-06, AC-07_ · _Verification: V-04 准备_ · _Depends: 双方正式契约及样例_
- [ ] **T021** [正式适配] 待 T020 明确接口后，细化 `B/workflow/application/kunlian_workflow_invocation.py` 与 `B/open_endpoints/api/endpoints/kunlian_workflow_runs.py` 的正式接线和定向契约测试。先固化接口断言再替换 TODO，正式授权失败保持关闭。涉及新增权限动作、持久结构或运行范围变动时回到设计确认。当前 `WAITING_EXTERNAL`。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-01, AC-04, AC-06, AC-07, AC-08_ · _Verification: V-04_ · _Depends: T019, T020, 正式接入授权_
- [ ] **T022** [受控环境验收] 在 `verification.md` 记录受控 MySQL／DM8、OpenFGA、Broker 和独立 Worker 的运行证据，使用 Mock 调用协议验证行锁竞争、回滚、补偿、权限变化和期限。按可信 `tenant_id` 头建立 ContextVar，验证错误租户无法收敛原执行。当前 `NOT_RUN`，待执行。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-06 · _Verification: V-03_ · _Depends: T019, 受控基础设施及测试账号_
- [ ] **T023** [双方联调验收] 在 `verification.md` 记录真实昆联测试租户、固定版本和实际用户授权样例。验证取消、终态、断线续读及各投影权限，并保留失败与拒绝回执。当前 `NOT_RUN`，待执行。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06_ · 覆盖 AC: AC-01, AC-02, AC-04, AC-05, AC-06, AC-07 · _Verification: V-04_ · _Depends: T021, T022, 双方联调环境_

## 4. 实际偏差记录

任务拆分时无偏差。实施发生经确认的设计变更时，记录任务编号与对应设计章节。
