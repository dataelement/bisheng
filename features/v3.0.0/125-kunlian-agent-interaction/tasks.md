# Tasks 毕昇 Workflow 调用昆联 Agent 的人工输入与恢复

- **Feature ID**：F125（拟用，合入前复核）
- **Version**：v3.0.0
- **关联**：[规格](./spec.md) · [已确认设计](./design.md) · [版本契约](../release-contract.md)

## 1. 状态与批次

| 阶段 | 状态 |
| --- | --- |
| 规格与设计 | 已确认。设计中的跨进程探针只证明静态检查点可恢复。 |
| 任务进度 | Mock 任务 27 / 27。T001–T027 已完成。 |
| 验证 | V-01 完整隔离 Mock 浏览器链路、V-02 隔离跨 Worker、V-03 定向及相关回归已通过。V-04 为 `NOT_RUN`。见[验证记录](./verification.md)。 |

| 批次 | 任务 | 批次验收 |
| --- | --- | --- |
| W1 等待点保存 | T001–T008 | 已完成隔离 Mock 验证。等待态和恢复材料一起提交，原派发结束且下游执行次数为零。直接成功路径输出一次。见 E-001～E-003。 |
| W2 提交幂等与跨 Worker 恢复 | T009–T013 | 已完成隔离验收。并发答案只创建一个派发，回执可按原关联查回。独立 Worker B 在 V2 发布后按原 V1 和同一 Run 恢复，只输出一次。见 E-004～E-006。 |
| W3 停止、超时与补偿 | T014–T016 | 已完成隔离 Mock 验证。覆盖停止与提交竞争、各阶段截止、原派发补投、已领取任务失联和迟到结果拦截。见 E-007～E-009。 |
| W4 浏览器闭环与兼容 | T017–T027 | 已通过隔离浏览器验收。Platform 发布固定 V1；Client 刷新后提交并输出一次，等待时停止并确认远端取消，停止后刷新保持原终态。见 E-018～E-020。 |
| W5 正式适配与真实验证 | T028–T031 | T028–T029 等双方确认，状态为 `WAITING_EXTERNAL`。T030–T031 分别验证受控基础设施和昆联真实联调，状态为 `NOT_RUN`。 |

`B/` 指 `src/backend/bisheng/`，`BT/` 指 `src/backend/test/workflow/`，`P/` 指 `src/frontend/platform/`，`C/` 指 `src/frontend/client/`。候选新文件以“拟新增”标记。后端按测试先行推进。各批通过后更新本表和实施阶段新增的 `verification.md`，记录实际命令或操作、退出状态、覆盖、替身范围和跳过原因。

Mock 使用已有执行表和显式隔离装配，复用 4A、4B 测试夹具。回退按[设计 §6](./design.md#6-正式替换点与已知边界)执行，先关新受理并让已受理执行收敛。运行记录只新增有版本的 JSON 子结构，保留既有权限归属及普通流程入口。

## 2. Mock 实施任务

### W1 等待点保存

- [x] **T001** [后端测试] 在 `BT/test_platform_agent_interaction_contract.py` 复用 4B 的可控时钟、Agent 账本和运行人夹具。验证未启用交互时的兼容默认值、固定版本能力、单文本表单以及原 Run 的提交键与受理证据。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-08_ · 覆盖 AC: AC-01, AC-03, AC-08 · _Verification: V-03_ · _Depends: 无_
- [x] **T002** [后端 Domain] 在 `B/workflow/domain/schemas/platform_agent.py` 和 `B/workflow/domain/clients/platform_agent.py` 定义显式 `allow_interaction`、版本 `supports_interaction`、可信等待表单、提交与只读查回契约。继续区分已受理、拒绝与未知。旧图默认关闭，正式来源未就绪时仍拒绝运行。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-06, REQ-08_ · _Acceptance: AC-01, AC-03, AC-05, AC-08_ · _Verification: V-03，联跑 T001_ · _Depends: T001_
- [x] **T003** [后端 Domain] 在 `B/workflow/domain/clients/platform_agent_mock.py` 增加明确标识的固定版本交互样例。沿用 4B 账本，在原 Run、交互修订和提交键下模拟接受、拒绝、丢回执及结果等待。保留 `# TODO [F125][EXT-01]` 和 `# TODO [F125][EXT-02]`。
  - _Requirements: REQ-02, REQ-03, REQ-06, REQ-08_ · _Acceptance: AC-01, AC-03, AC-05, AC-08_ · _Verification: V-03，联跑 T001_ · _Depends: T002_
- [x] **T004** [后端测试] 在 `BT/test_platform_agent_interaction_wait.py` 用真实最小图和 `long_agent_store` 定义等待点用例。覆盖不支持的图或版本、原派发归属、下一节点与快照校验、等待保存失败不发布表单，以及未进入等待时沿原门禁输出。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-08_ · 覆盖 AC: AC-01, AC-02, AC-08 · _Verification: V-02、V-03_ · _Depends: T003_
- [x] **T005** [后端 Domain] 在 `B/workflow/graph/kunlian_interaction.py` 和 `B/workflow/graph/platform_agent_interaction.py` 复用 4A 的有界 JSON、引擎兼容及检查点装载。4C 快照独立绑定执行、冻结图、版本和 Agent 节点，保存开始节点变量、计数与记忆配置。拒绝未知版本、挂起写入、错误下一节点和超限快照。4A 原校验口径继续生效。
  - _Requirements: REQ-02, REQ-04, REQ-08_ · _Acceptance: AC-01, AC-02, AC-08_ · _Verification: V-02、V-03，联跑 T004_ · _Depends: T004_
- [x] **T006** [后端 Domain] 在 `B/workflow/graph/graph_engine.py` 与 `B/workflow/nodes/platform_agent/platform_agent.py` 接入仅对 4C 图启用的 Agent 前静态中断。复用节点变量解析，允许原节点从内部执行上下文消费已核验结果并走现有输出门禁。普通图及未启用 4C 的节点沿原执行路径。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-08_ · _Acceptance: AC-01, AC-02, AC-08_ · _Verification: V-02、V-03，联跑 T004_ · _Depends: T005_
- [x] **T007** [后端 Domain] 在 `B/workflow/domain/services/platform_agent_service.py` 与 `B/workflow/domain/repositories/platform_agent.py` 校验发布图和版本能力，受理时同 Flow 行锁核对当前版本、图摘要并保存原绑定。复用 4B 启动键和轮询，4C 的可信等待结果在同一执行行保存快照、表单、截止并结束旧派发。旧模式遇到远端等待维持原行为。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-08_ · _Acceptance: AC-01, AC-02, AC-08_ · _Verification: V-03，联跑 T004_ · _Depends: T003, T005_
- [x] **T008** [Worker] 在 `B/worker/workflow/tasks.py` 和 `B/worker/workflow/platform_agent_interaction.py` 接通首次执行。以 Celery 可信租户头建立 ContextVar，到达 Agent 前检查点后驱动原启动及轮询。等待提交成功才发布提示并退出任务，运行对象不留作恢复依据。若直接取得结果则从该点继续一次输出。
  - _Requirements: REQ-01, REQ-02, REQ-04_ · _Acceptance: AC-01, AC-02_ · _Verification: V-02、V-03，联跑 T004_ · _Depends: T006, T007_

**批次验证。** 在 `src/backend` 使用 Python 3.11 与隔离配置，对 T001、T004 的文件执行定向 pytest。确认等待材料、执行状态和原派发收敛一致，普通模式与不可交互版本按原行为处理。W1 的状态断言只记为隔离证据。

### W2 提交幂等与跨 Worker 恢复

- [x] **T009** [后端测试] 在 `BT/test_platform_agent_interaction_submit.py` 用独立连接、时钟与 Mock 账本验证本地受理和远端提交。覆盖并发同键同答案、同键异参、换键消费、无效答案或旧修订、回执丢失及错配结果。区分远端拒绝、未知、结果不可用和新的第二次交互。
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-07_ · 覆盖 AC: AC-03, AC-05, AC-07 · _Verification: V-03_ · _Depends: T008_
- [x] **T010** [后端 Domain] 在 `B/workflow/domain/repositories/platform_agent.py` 按原执行锁校验当前交互、修订与截止，一次写入答案、摘要、固定远端提交键和唯一 `INTERACTION_RESUME` 派发。实现原回执重放、冲突拒绝和领取交接。新派发接管原调用的执行权限，逻辑调用标识保持原值。
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-07_ · _Acceptance: AC-02, AC-03, AC-05, AC-07_ · _Verification: V-03，联跑 T009_ · _Depends: T009_
- [x] **T011** [后端 Domain] 在 `B/workflow/domain/services/platform_agent_service.py` 接通向原 Run 提交、未知回执查回及同键安全重放。只有可信回执可确认本次受理。受理后按原 Run 轮询并验证版本和 Schema，过滤原交互的旧等待帧。各阶段沿用一次设定的截止及发送许可。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_ · _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07_ · _Verification: V-03，联跑 T009_ · _Depends: T003, T010_
- [x] **T012** [后端测试] 在 `BT/test_platform_agent_interaction_e2e.py` 与 `BT/platform_agent_interaction_worker.py` 复用 4A 子进程夹具和真实图。通过可信租户头进入独立 Worker，使用同一隔离数据库和独立于进程的 Mock Run 账本。断言 A 退出、期间发布 V2、B 仍从 V1 接续。模拟恢复前撤权、快照损坏及旧派发，核对受保护请求次数。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-05_ · 覆盖 AC: AC-01, AC-02, AC-04 · _Verification: V-02_ · _Depends: T008, T011_
- [x] **T013** [Worker] 在 `B/worker/workflow/platform_agent_interaction.py` 与 `B/worker/workflow/tasks.py` 接通恢复派发。在 Celery 可信租户头对应的 ContextVar 下复核会话、原用户、当前权限与冻结绑定。领取后先恢复快照，再向原 Run 提交并在原 Agent 节点续跑。失效派发、损坏快照或撤权均禁止发送或输出。
  - _Requirements: REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-04, AC-05_ · _Verification: V-02、V-03，联跑 T012_ · _Depends: T005, T010, T011, T012_

**批次验证。** 运行 T009 的故障注入用例和 T012 的独立进程验收。保存两个 Worker 的退出及领取证据，核对一份持久等待点、同一执行／Run／交互、一次有效提交、一次 Agent 启动和一次下游输出。设计探针和同进程调用不计作 V-02。

### W3 停止、超时与补偿

- [x] **T014** [后端测试] 在 `BT/test_platform_agent_interaction_reconcile.py` 用不同连接和确定性传输拦截点覆盖停止先于发送许可、提交在途、成功结果迟到、各阶段到期、旧领取者和补偿漏投。断言停止前未获许可的答案无远端提交，停止后迟到结果无下游输出。
  - _Requirements: REQ-04, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-04, AC-05, AC-06, AC-07 · _Verification: V-03_ · _Depends: T013_
- [x] **T015** [后端 Domain] 在 `B/workflow/domain/repositories/platform_agent.py` 与 `B/workflow/domain/services/platform_agent_service.py` 统一 4C 阶段期限、发送、停止、就绪及输出的锁内门禁。Mock 分别使用 120 秒人工等待、30 秒排队及提交核对、30 秒结果等待，取消核对沿用 4B。到期或停止按 4B 建一个取消意图，禁止旧响应恢复本地执行。终态清理明文答案、表单与快照，保留最小回执和远端事实。保留 `# TODO [F125][EXT-03]`。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_ · _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-07_ · _Verification: V-03，联跑 T014_ · _Depends: T010, T011, T014_
- [x] **T016** [Worker] 在 `B/worker/workflow/platform_agent_long_task.py` 与 `B/worker/workflow/platform_agent_interaction.py` 增加 4C 阶段扫描和唤醒。沿用可信 Celery 租户头 → ContextVar。仅补投未领取的原派发，已领取失联任务有界核对并收敛。使用原 Run 和原取消键，保持原任务失联后图执行不重放。
  - _Requirements: REQ-04, REQ-06, REQ-07, REQ-08_ · _Acceptance: AC-02, AC-05, AC-06, AC-07_ · _Verification: V-03，联跑 T014_ · _Depends: T013, T015_

**批次验证。** 运行 T014 的定向用例，检查远端提交／取消次数、相同派发的补投和旧领取拒绝。分别报告人工等待、提交核对、结果等待和取消确认的结果。隔离账本与双连接证据不代替 MySQL／DM8 行锁或实际 Broker 验收。

### W4 浏览器闭环与兼容

- [x] **T017** [后端测试] 在 `BT/test_platform_agent_interaction_entrypoints.py` 验证真实会话处理入口。覆盖显式原执行 ID、Redis 引用丢失、其他用户／租户／接入方、原用户撤权或停用、原生输入兼容、已停止会话及答案日志脱敏。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-07, REQ-08_ · 覆盖 AC: AC-01, AC-03, AC-04, AC-06, AC-08 · _Verification: V-03_ · _Depends: T013, T016_
- [x] **T018** [后端 API] 在 `B/workflow/application/platform_agent.py` 扩展注入的应用端口。按可信会话和执行定位查询、受理及停止，核验原实际用户、Workflow `use` 及 Provider 的当前操作权限。显式执行仅查原执行，无 Redis 引用时仅定位同一授权会话的唯一活跃 4C 执行。响应只含安全摘要和授权可读表单。保留 `# TODO [F125][EXT-04]`。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-07_ · _Acceptance: AC-01, AC-03, AC-04, AC-06_ · _Verification: V-03，联跑 T017_ · _Depends: T010, T016, T017_
- [x] **T019** [后端 API] 在 `B/common/chat/clients/workflow_client.py` 与 `B/common/chat/clients/base.py` 接入 `check_status` 的 4C 分支、`agent_interaction_submit` 和原停止动作。仅委托应用端口，提交日志只留白名单字段，原始答案不进入整帧日志。4C 待办查询不触发普通自动运行和原生表单重发，恢复后接回同一执行的既有输出流。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-07, REQ-08_ · _Acceptance: AC-01, AC-03, AC-04, AC-06, AC-08_ · _Verification: V-03，联跑 T017_ · _Depends: T018_
- [x] **T020** [前端 Platform 测试] 在 `P/src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.test.tsx` 验证固定版本支持、隔离可用性和异步模式三项均满足时才可启用交互。验证换版本后重新校验，旧配置缺省关闭，原输入映射兼容。
  - _Requirements: REQ-01, REQ-08_ · 覆盖 AC: AC-01, AC-08 · _Verification: V-03_ · _Depends: T002, T007_
- [x] **T021** [前端 Platform] 在 `P/src/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.tsx` 与 `P/src/types/flow/index.ts` 接入版本能力及显式启用控件。能力不足时拦截发布并给出说明，固定版本变化后重新校验。节点缺省关闭。
  - _Requirements: REQ-01, REQ-08_ · _Acceptance: AC-01, AC-08_ · _Verification: V-03，联跑 T020_ · _Depends: T020_
- [x] **T022** [前端 Platform] 在 `P/src/pages/BuildPage/flow/FlowNode/Parameter.tsx` 接入节点参数读写。显式启用才保存 `allow_interaction`，关闭时移除该参数，保持原 `execution_mode`、固定版本、输入映射和输出变量。打开旧图按缺省关闭读取，不批量转换已有节点。
  - _Requirements: REQ-01, REQ-08_ · _Acceptance: AC-01, AC-08_ · _Verification: V-01、V-03_ · _Depends: T021_
- [x] **T023** [前端 Platform] 在 `P/public/locales/{zh-Hans,en-US,ja}/flow.json` 补齐启用、版本不支持与兼容提示的三语键，沿用 `flow.platformAgent` 命名。
  - _Requirements: REQ-01, REQ-08_ · _Acceptance: AC-01, AC-08_ · _Verification: V-03，三语键一致性_ · _Depends: T021_
- [x] **T024** [前端 Client 测试] 在 `C/src/pages/appChat/agentInteraction.test.tsx` 用现有 WebSocket 测试方式覆盖待办提示、断线恢复、重复提交沿用提交 ID、旧状态帧、停止后表单关闭及原生输入隔离。
  - _Requirements: REQ-02, REQ-03, REQ-06, REQ-07, REQ-08_ · 覆盖 AC: AC-01, AC-03, AC-05, AC-06, AC-08 · _Verification: V-03_ · _Depends: T019_
- [x] **T025** [前端 Client] 在 `C/src/pages/appChat/useWebsocket.ts` 与 `C/src/pages/appChat/ChatView.tsx` 接入 4C 会话状态和纯文本 `WorkflowForm`。按执行、交互及状态版本处理重连和旧帧。提交 ID 随该次答案操作复用，受理、停止或超时后关闭表单，分别展示本地受理、远端进度与取消状态。
  - _Requirements: REQ-02, REQ-03, REQ-06, REQ-07, REQ-08_ · _Acceptance: AC-01, AC-03, AC-05, AC-06, AC-08_ · _Verification: V-01、V-03，联跑 T024_ · _Depends: T019, T024_
- [x] **T026** [前端 Client] 在 `C/src/locales/{zh-Hans,en,ja}/translation.json` 补齐等待输入、提交未知、拒绝、超时和不支持后续交互的三语提示。取消文案复用现有 4B 键。
  - _Requirements: REQ-02, REQ-06, REQ-07, REQ-08_ · _Acceptance: AC-01, AC-05, AC-06, AC-08_ · _Verification: V-03，三语键一致性_ · _Depends: T025_
- [x] **T027** [浏览器验收] 使用 [示例图](./mock-workflow.example.json) 与 [验收清单](./e2e-checklist.md)，从 Platform 发布固定 V1。Client 刷新同一会话后提交一次并输出一次；另一会话等待时停止，远端确认取消，刷新后仍保留原终态。实际操作、运行关联和结果见 E-018。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-07, REQ-08_ · 覆盖 AC: AC-01, AC-06, AC-08 · _Verification: V-01_ · _Depends: T013, T016, T019, T022, T023, T025, T026_

**批次验证。** 先运行 T017 的后端会话测试、T020 的 Platform Vitest、T024 的 Client Jest，以及三语检查。按 T027 在隔离 API／Worker／Redis 与双前端环境完成浏览器验收。阶段末只跑一次相关回归，包含 F119 同步、F124 普通异步、F123 原生输入和既有会话停止，再执行相关 Ruff、架构守卫和差异检查。缺少完整隔离栈时，自动化证据与浏览器 `NOT_RUN` 分开记录。

## 3. 正式适配与真实环境

- [ ] **T028** [正式契约] 与昆联确认现有能力、表单及提交协议、幂等与安全查回、阶段期限和实际用户权限。将 `EXT-01` 至 `EXT-04` 的确认结果回写 `design.md`，并确定可复用 T001 的正式契约样例。状态 `WAITING_EXTERNAL`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-05, REQ-06, REQ-07_ · _Acceptance: AC-01, AC-03, AC-04, AC-05, AC-06_ · _Verification: V-04 准备_ · _Depends: T027，双方契约确认_
- [ ] **T029** [后端 Domain] 在 `B/workflow/domain/clients/platform_agent.py` 和待正式契约确定的 Provider 文件中接入已确认的能力，复用 T001 契约断言。逐项处理 `# TODO [F125][EXT-01]` 至 `[EXT-04]`。正式失败保持明确失败，不能降级为 Mock。状态 `WAITING_EXTERNAL`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08_ · _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-08_ · _Verification: V-04_ · _Depends: T028_
- [ ] **T030** [受控环境验收] 使用受控 MySQL／中心 DM8、OpenFGA、Broker／独立 Worker 验证执行行锁、并发提交、补投、跨 Worker 恢复、撤权、停止与回退。允许先用昆联 Mock 验证真实基础设施，结果写入 `verification.md`。状态 `NOT_RUN`。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06 · _Verification: V-04_ · _Depends: T027，受控环境可用_
- [ ] **T031** [双方联调验收] 按 `# TODO [F125][EXT-05]` 取得专用环境、固定版本和授权／拒绝样例。用真实昆联接口核对同一 Run、表单、提交去重、回执查回、停止及超时。双方证据单独写入 `verification.md`。状态 `NOT_RUN`。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06 · _Verification: V-04_ · _Depends: T029, T030，双方测试环境及样例_

## 4. 实际偏差记录

W1 为落实设计 §4.1 的浏览器会话准入，在 `B/workflow/application/platform_agent.py` 增加一处内部受理标记传递。该标记来自现有浏览器会话入口，其他调用保持原签名路径。后续偏差按 [SDD 指南](../../../docs/SDD-Guide.md) 记录。

W2 为落实设计 §4.1 和 §4.4，在 Mock Provider 声明同键安全重放能力，在等待点保存原回调来源。早期 W1 等待点按普通浏览器来源恢复。
