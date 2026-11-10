# Tasks 毕昇 Workflow 调用昆联 Agent 的长任务挂起与恢复

- **Feature ID**: F126（拟用，合入前复核）
- **Version**: v3.0.0
- **Mode**: Mock 优先，分批实施
- **关联**: [已确认规格](./spec.md) · [已确认设计](./design.md) · [版本契约](../release-contract.md)

## 1. 状态与批次验收

| 阶段 | 状态 |
| --- | --- |
| 规格与设计 | `CONFIRMED`，用户确认进入任务拆分。 |
| 任务计划 | T001–T028 已实施。 |
| Mock 实施 | `COMPLETE`，28 / 28。V-01～V-04 已通过本地及隔离 Mock 验证。见[验证记录](./verification.md)。 |
| 正式适配 | T029–T030 为 `WAITING_EXTERNAL`，保留全部正式接口 TODO。 |
| 环境验收 | T031（V-05）与 T032（V-06）为 `NOT_RUN`，待执行。 |

| 批次 | 任务 | 前置 | 批次验收 |
| --- | --- | --- | --- |
| **W1 · 持久挂起与执行槽释放** | T001–T006 | 已确认规格与设计 | V-01 已通过。同一个单执行槽 Worker 在原 Run 仍为 `RUNNING` 时完成同队列第二条 Workflow，首条执行保持等待且无下游输出。见 E-002。 |
| **W2 · 短任务查询与漏投补偿** | T007–T010 | W1 | V-03 的 W2 范围已通过。启动查回沿用原键，漏投后按原派发 ID 补投，原截止不变。见 E-004、E-005。 |
| **W3 · 跨 Worker 恢复与单次输出** | T011–T017 | W2 | V-02 和 V-03 的 W3 范围已通过。A 退出并发布 V2 后，B 接管已过期的原派发并继续原 V1 和原 Run。提交前回滚不留消息，提交后丢通知可按同一 ID 读回一条持久输出。见 E-006～E-008。 |
| **W4 · 停止、超时与取消确认** | T018–T020 | W2、W3 | V-03 已通过。覆盖等待、领取与提交阶段的裁决，取消受理、确认、拒绝和未确认分别记录。见 E-009、E-010。 |
| **W5 · 会话、授权与兼容回归** | T021–T028 | W1–W4 | V-04 已通过。隔离双前端验收固定 V1、等待、刷新重连、单次输出、停止、重跑与无权拒绝。后端回归覆盖历史、按会话取消息和相邻流程。见 E-011～E-013。 |
| **W6 · 正式契约与真实环境** | T029–T032 | 各任务前置 | 正式契约确认和接线与环境验收分开记录。V-05 受控基础设施可继续使用 Mock Agent；V-06 使用真实昆联接口。两项当前均待执行。 |

`B/` 指 `src/backend/bisheng/`，`BT/` 指 `src/backend/test/workflow/`，`C/` 指 `src/frontend/client/`。所有新文件均为实施时的计划落点。后端行为先写测试。运行期只显式装配隔离 Mock 队列，Worker 一律按 Celery 可信 `tenant_id` 头建立 ContextVar，再核对原执行及实际用户。原权限规则、数据表和普通流程保持兼容。涉及公共权限、表结构或已确认决策的变更，按[项目 SDD 流程](../../../docs/SDD-Guide.md)先确认。

## 2. Mock 实施任务

### W1 持久挂起与执行槽释放

- [x] **T001** [后端测试] 在 `BT/test_platform_agent_long_task_resume_wait.py` 复用 4B 的 Mock 账本和时钟、4C 的真实线性图夹具。覆盖已发布普通异步图、V1 冻结、非法图形、旧路径、等待写入失败、启动响应未知、Run 与期限绑定、停在 Agent 前且无下游输出。
  - _Requirements: REQ-01, REQ-02, REQ-07_ · 覆盖 AC: AC-01, AC-07 · _Verification: V-01, V-04 的定向前置_ · _Depends: 无_
- [x] **T002** [Worker 测试] 在 `BT/test_platform_agent_long_task_resume_e2e.py` 和 `BT/platform_agent_long_task_resume_worker.py` 准备真实本地 Broker、单独 Worker 进程及进程外可控 Mock 账本。通过可信租户任务头发起两条 Workflow。第一条停在已持久化等待且远端未就绪，第二条在同一队列由同一个单执行槽 Worker 完成。任务及进程证据见 E-002。
  - _Requirements: REQ-01, REQ-02_ · 覆盖 AC: AC-01 · _Verification: V-01_ · _Depends: T001_
- [x] **T003** [后端 Domain] 在 `B/workflow/domain/schemas/platform_agent.py` 和 `B/workflow/graph/platform_agent_long_task_resume.py` 实现普通异步线性图判定及窄快照适配。复用 Agent 前静态边界和线性快照校验。保存并校验图摘要、版本、执行、节点、变量、历史和步数，限制输出为线性图内的纯文本。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-07_ · _Acceptance: AC-01, AC-02, AC-07_ · _Verification: V-01, V-02，复用 T001_ · _Depends: T001_
- [x] **T004** [后端 Domain] 在 `B/workflow/application/platform_agent.py` 和 `B/workflow/domain/repositories/platform_agent.py` 接入内部受理判定。仅在隔离 Mock 同时启用 `enable_long_tasks` 与 `enable_long_task_resume`，且使用有会话的已发布入口时走 4D。复用 Flow 行锁和版本快照，固化 `START` 的 4D 标记、原版本与可信浏览器来源。快照、可核对启动记录及等待事实由原执行行保存，等待落库与结束原派发同事务。
  - _Requirements: REQ-01, REQ-02, REQ-06, REQ-07_ · _Acceptance: AC-01, AC-06, AC-07_ · _Verification: V-01，联跑 T001_ · _Depends: T001, T003_
- [x] **T005** [后端 Domain] 在 `B/workflow/domain/services/platform_agent_service.py` 将 4D 的启动阶段与 4B 的节点内轮询分开。按隔离装配启用，沿用 4B 的固定版本、输入校验、原启动键、许可和时限。受理后提交 `POLL_WAIT`，发送后响应未知时提交 `START_CHECK`，原截止只设一次。沿用正式来源失败规则，保留 `# TODO [F126][EXT-01]`。
  - _Requirements: REQ-01, REQ-02, REQ-04, REQ-07_ · _Acceptance: AC-01, AC-04, AC-07_ · _Verification: V-01, V-03，联跑 T001_ · _Depends: T001, T004_
- [x] **T006** [Worker] 在 `B/worker/workflow/tasks.py` 和 `B/worker/workflow/platform_agent_long_task_resume.py` 接通首次执行。由 Celery 租户头建立 ContextVar，运行真实图到 Agent 前并保存等待点。等待提交后发送摘要、结束任务并释放执行槽。挂起记录可跨进程读取，普通旧流程沿原出口执行。
  - _Requirements: REQ-01, REQ-02, REQ-07_ · _Acceptance: AC-01, AC-07_ · _Verification: V-01，联跑 T001, T002_ · _Depends: T002, T003, T004, T005_

**批次验收。** 先跑 T001 的定向 pytest，再用 T002 的真实本地队列验收 V-01。记录同队列、单槽 Worker 的身份、两条任务完成时序、原 Run 未就绪及原执行无输出。只有状态模拟或同进程调用时，V-01 保持 `NOT_RUN`。

### W2 短任务查询与漏投补偿

- [x] **T007** [后端测试] 在 `BT/test_platform_agent_long_task_resume_reconcile.py` 用独立事务、持久 Mock 账本和可控时钟测试查回与轮询。注入启动发送后丢回执或 Worker 失联、等待落库后漏唤醒、结果就绪后漏投。覆盖重复租约、过期响应、错配 Run／版本、无效输出、结果暂不可用、终态及撤权拒绝。
  - _Requirements: REQ-03, REQ-04, REQ-06_ · 覆盖 AC: AC-03, AC-04, AC-06 · _Verification: V-03_ · _Depends: T006_
- [x] **T008** [后端 Domain] 在 `B/workflow/domain/repositories/platform_agent.py` 扩展 4D 分页扫描和短任务租约。识别 `RUNNING` 中已发许可但失联的启动记录，在同一行校验租约、关联和期限。可信结果和唯一 `LONG_TASK_RESUME` 派发一起提交。待领取或失联的恢复派发可按同一 ID 补投，过期轮询不得覆盖终态。
  - _Requirements: REQ-01, REQ-03, REQ-04_ · _Acceptance: AC-02, AC-03, AC-04_ · _Verification: V-03，联跑 T007_ · _Depends: T007_
- [x] **T009** [后端 Domain] 在 `B/workflow/domain/services/platform_agent_service.py` 接通单次短任务查回及轮询。按原实际用户核验 Workflow 和 Agent 权限，HTTP 在锁外，回写复核租约、Run 和 Schema。查回失败按原期限收敛，普通异步收到人工输入时走明确失败。保留 `# TODO [F126][EXT-01]` 和 `# TODO [F126][EXT-02]`。
  - _Requirements: REQ-03, REQ-04, REQ-06_ · _Acceptance: AC-03, AC-04, AC-06_ · _Verification: V-03，联跑 T007_ · _Depends: T007, T008_
- [x] **T010** [Worker] 在 `B/worker/workflow/platform_agent_long_task.py` 接入 4D 按租户扫描、提交后唤醒、短任务及原派发补投。Celery 可信租户头进入 ContextVar 后才读取执行，消息仅带必要执行／调用／派发标识。W2 使用投递夹具验证，实际恢复任务在 W3 显式注册后接通。
  - _Requirements: REQ-03, REQ-04, REQ-06_ · _Acceptance: AC-03, AC-04, AC-06_ · _Verification: V-03，联跑 T007_ · _Depends: T007, T008, T009_

**批次验收。** 用 T007 注入两个漏投窗口和旧租约。核对补偿能从持久记录找回原 Run、复用同一恢复派发，始终使用原截止。W2 只验收查回、就绪和补投，实际接管及输出由 W3 证明。

### W3 跨 Worker 恢复与单次输出

- [x] **T011** [Worker 测试] 在 `BT/test_platform_agent_long_task_resume_e2e.py` 及其 Worker 夹具按可信任务头传租户。Worker A 挂起退出后发布 V2，Worker B 在独立进程从本地 Redis 队列消费原派发。覆盖过期领取接管、通知丢失、原节点、原变量、原 Run 和单次持久输出。旧领取者、损坏快照及恢复前撤权由 T012 的定向用例覆盖。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-06_ · 覆盖 AC: AC-02, AC-03, AC-06 · _Verification: V-02, V-03_ · _Depends: T002, T010_
- [x] **T012** [后端测试] 在 `BT/test_platform_agent_long_task_resume_output.py` 验证纯文本暂存、消息 `flush` 后回滚、租约接管和授权读回，并覆盖损坏快照与撤权拒绝。提交后通知丢失在 T011 注入，重复派发不会新增消息或再次发送通知。
  - _Requirements: REQ-03, REQ-04_ · 覆盖 AC: AC-02, AC-03 · _Verification: V-03_ · _Depends: T008_
- [x] **T013** [后端 Domain] 在 `B/workflow/domain/repositories/platform_agent.py` 完成 `LONG_TASK_RESUME` 领取及过期接管。原派发 ID 不变，新领取得到新的所有权标识。状态更新、失败清理和输出按同一标识、租约、原截止及执行行判断。已持久输出只回读回执，损坏材料结束为可查询失败。
  - _Requirements: REQ-03, REQ-04_ · _Acceptance: AC-02, AC-03_ · _Verification: V-02, V-03，联跑 T011_ · _Depends: T008, T011_
- [x] **T014** [后端 Domain] 在 `B/chat_session/domain/repositories/workflow_output_repository.py` 与 `B/chat_session/application/workflow_output.py` 增加会话侧事务端口。纯文本按原聊天消息形态和叶租户写入，带内部 4D 关联标记。仅在调用方的 SQL 会话内 `flush` 并返回 `message_id`，提交权归调用方，现有消息写入入口继续服务旧流程。
  - _Requirements: REQ-03, REQ-06, REQ-07_ · _Acceptance: AC-02, AC-03, AC-06, AC-07_ · _Verification: V-03，联跑 T012_ · _Depends: T012_
- [x] **T015** [后端 Domain] 在 `B/workflow/application/platform_agent.py` 与 `B/workflow/domain/repositories/platform_agent.py` 协调最终输出事务。锁内复核领取、期限和停止状态，调用 T014 在同一事务写一条消息及节点／执行成功与回执。提交失败不留下消息或成功事实。提交后保留稳定回执并清理暂存材料。
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-02, AC-03, AC-05, AC-06_ · _Verification: V-03，联跑 T012_ · _Depends: T012, T013, T014_
- [x] **T016** [后端 Domain] 在 `B/workflow/nodes/platform_agent/platform_agent.py` 与 `B/worker/workflow/redis_callback.py` 接入 4D 恢复结果和纯文本暂存分支。原 Agent 节点读取已核验结果并写入图变量，暂存输出不对外可见。使用 T015 的持久消息 ID 在提交后通知，通知失败可从授权后的回执补读，旧路径继续使用既有输出门禁。
  - _Requirements: REQ-03, REQ-04, REQ-07_ · _Acceptance: AC-02, AC-03, AC-07_ · _Verification: V-02, V-03，联跑 T011, T012_ · _Depends: T003, T011, T012, T015_
- [x] **T017** [Worker] 在 `B/worker/workflow/platform_agent_long_task_resume.py` 和 `B/worker/workflow/tasks.py` 注册隔离恢复任务。可信租户头进入 ContextVar 后，按原派发领取、核验实际用户和资源权限，使用既有 4D 快照适配文件恢复冻结图及上下文。完成原 Agent 与后续纯文本节点后走 T015 提交。失效任务不得终结新领取者的任务或清除会话引用。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-06_ · _Acceptance: AC-02, AC-03, AC-06_ · _Verification: V-02, V-03，联跑 T011, T012_ · _Depends: T010, T011, T013, T015, T016_

**批次验收。** 用 T011 记录 A 退出、B 接管、V1／V2 发布记录、节点次数和原 Run。用 T012 核对一个派发、一次持久输出、一个稳定消息 ID，分别保留提交前回滚和提交后通知遗漏证据。可重算范围限于尚未持久化的纯文本。

### W4 停止、超时与取消确认

- [x] **T018** [后端测试] 在 `BT/test_platform_agent_long_task_resume_stop.py` 用独立连接和可控时钟验证停止／完成竞争、轮询和恢复超时、重复停止、取消补投、取消受理与确认以及远端迟到结果。覆盖停止先提交、消息先提交和租约已失效三种输出时序。
  - _Requirements: REQ-04, REQ-05_ · 覆盖 AC: AC-03, AC-05 · _Verification: V-03_ · _Depends: T017_
- [x] **T019** [后端 Domain] 在 `B/workflow/domain/repositories/platform_agent.py` 将 4D 的停止、超时和终态清理并入原执行行裁决。停止先发生时关闭恢复与输出资格并写一份取消意图，输出先提交时保留成功和消息回执。原截止不续期，确认远端终态只更新允许核对的远端事实。
  - _Requirements: REQ-04, REQ-05_ · _Acceptance: AC-03, AC-05_ · _Verification: V-03，联跑 T018_ · _Depends: T015, T018_
- [x] **T020** [Worker] 在 `B/workflow/domain/services/platform_agent_service.py` 复用现有 4B 取消及 Worker 漏投扫描。Celery 租户头进入 ContextVar 后核验原关联和实际用户，在独立核对窗口处理未知启动、受理、确认、拒绝及未确认。保持迟到结果隔离，保留 `# TODO [F126][EXT-03]`。
  - _Requirements: REQ-04, REQ-05, REQ-06_ · _Acceptance: AC-03, AC-05, AC-06_ · _Verification: V-03，联跑 T018_ · _Depends: T010, T018, T019_

**批次验收。** 用 T018 检查原执行终态、消息行数、原截止与远端取消意图次数。停止或超时先提交时下游输出为零；成功先提交时输出保持一条。报告取消受理与远端确认的独立证据。

### W5 会话、授权与兼容回归

- [x] **T021** [后端测试] 在 `BT/test_platform_agent_long_task_resume_entrypoints.py` 和 `BT/test_platform_agent_long_task_resume_history.py` 覆盖现有会话 WS、历史和按会话取消息。验证同会话刷新或 Redis 引用丢失时仍读原执行，显式执行错配及其他用户／租户／接入方拒绝。撤权、停用或权限未知时拒绝缓存和历史内容，未标记历史及 4C 原行为可用。
  - _Requirements: REQ-01, REQ-02, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-05, AC-06, AC-07 · _Verification: V-04_ · _Depends: T017, T020_
- [x] **T022** [后端 API] 在 `B/workflow/application/platform_agent.py` 扩展受保护状态／输出定位。显式 ID 只查指定执行；缺引用时仅定位同一授权会话的唯一活跃 4D 记录，首次打开可回读原终态。按可信连接、租户、实际用户、Workflow 和 Agent 权限核验状态、停止及结果。保留 `# TODO [F126][EXT-04]`。
  - _Requirements: REQ-01, REQ-02, REQ-05, REQ-06_ · _Acceptance: AC-05, AC-06, AC-07_ · _Verification: V-04，联跑 T021_ · _Depends: T020, T021_
- [x] **T023** [后端 API] 在 `B/common/chat/clients/workflow_client.py` 和 `B/workflow/domain/services/platform_agent_service.py` 接通原 `check_status`、`initial_open` 和 `stop`，对 4D 返回带期限与状态版本的安全摘要。WS 缓存补读走 T022 的授权，旧连接帧及旧执行不得影响新执行。主动重跑走原启动动作，断线及刷新保留原状态。
  - _Requirements: REQ-01, REQ-02, REQ-05, REQ-06, REQ-07_ · _Acceptance: AC-05, AC-06, AC-07_ · _Verification: V-04，联跑 T021_ · _Depends: T021, T022_
- [x] **T024** [后端 Domain] 在 `B/chat_session/domain/chat.py` 与 `B/chat_session/application/workflow_output.py` 增加 4D 历史消息输出保护。识别内部标记和持久消息回执，序列化前经 T022 校验授权并移除内部标记。缺主体、关联错配或权限不明时拒绝返回该条内容，普通历史读取维持现有口径。
  - _Requirements: REQ-06, REQ-07_ · _Acceptance: AC-06, AC-07_ · _Verification: V-04，联跑 T021_ · _Depends: T014, T021, T022_
- [x] **T025** [后端 API] 在 `B/chat_session/api/endpoints/chat.py` 与 `B/chat_session/api/endpoints/session.py` 将可信请求主体交给 T024，覆盖历史和按会话取消息两个正常入口。核查 OpenAPI、导出等其他可返回 4D 正文的既有调用是否经 T024 统一拒绝或授权。发现绕过时记录确切调用路径并补定向用例，按设计边界处理后才勾选。
  - _Requirements: REQ-06, REQ-07_ · _Acceptance: AC-06, AC-07_ · _Verification: V-04，联跑 T021_ · _Depends: T021, T024_
- [x] **T026** [前端 Client 测试] 在 `C/src/pages/appChat/agentInteraction.test.tsx` 复用现有 WebSocket 夹具，覆盖同执行刷新、旧状态帧拒绝、普通等待无表单、停止后继续显示取消核对，以及按消息 ID 合并通知和历史。
  - _Requirements: REQ-01, REQ-02, REQ-05, REQ-07_ · 覆盖 AC: AC-05, AC-07 · _Verification: V-04_ · _Depends: T023_
- [x] **T027** [前端 Client] 在 `C/src/pages/appChat/useWebsocket.ts` 和 `C/src/pages/appChat/ChatView.tsx` 复用长任务摘要和停止展示，按同次执行与状态版本归并重连状态。沿用消息 ID 去重和既有取消状态文案，兼容缺少 4D 可选字段的帧。
  - _Requirements: REQ-01, REQ-02, REQ-05, REQ-07_ · _Acceptance: AC-05, AC-07_ · _Verification: V-04，联跑 T026_ · _Depends: T023, T026_
- [x] **T028** [浏览器验收] 在本特性目录新增 `mock-workflow.example.json` 与 `e2e-checklist.md`。复用 Platform 现有异步节点配置发布固定 V1。在隔离 Client 验证等待、刷新、停止、原结果回读、显式重跑与无权拒绝。复核 V-01、V-02 的原进程证据；代码变更影响对应验收时再复跑该项。
  - _Requirements: REQ-01, REQ-02, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-05, AC-06, AC-07 · _Verification: V-04，引用 V-01, V-02_ · _Depends: T002, T011, T020, T023, T025, T027_

**批次验收。** 执行 T021、T026 的定向测试及 T028 的双前端闭环。阶段末跑一次相关回归，覆盖 F119 同步、未启用的 F124 普通异步、F123 原生输入和 F125 单文本交互，并检查相关 Ruff、前端类型及架构守卫。缺独立队列、账号或浏览器时，对应验收保持待执行，组件证据单列。

## 3. 正式接口与环境任务

- [ ] **T029** [正式契约] 在 `design.md` 记录 `EXT-01`～`EXT-05` 的双方确认结果，核对原启动查回、固定版本、轮询与限流、取消语义、实际用户及联调样例。接口确认可与 Mock 并行，`WAITING_EXTERNAL`。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_ · _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06_ · _Verification: V-06 准备_ · _Depends: 双方正式契约和样例_
- [ ] **T030** [后端 Domain] 在 `B/workflow/domain/clients/platform_agent.py` 与契约确认后的正式 Provider 落点替换对应 `# TODO [F126][EXT-01]`～`[EXT-04]`。按确认后的合同先写定向断言，再接正式实现。正式失败明确返回错误，Mock 装配保持隔离。`WAITING_EXTERNAL`。
  - _Requirements: REQ-01, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_ · _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07_ · _Verification: V-06_ · _Depends: T028, T029，正式适配获授权_
- [ ] **T031** [受控环境验收] 在实施期 `verification.md` 记录受控 MySQL／中央 DM8、OpenFGA、Broker 与独立 Worker 的验证。使用隔离 Mock Agent 验证双库行锁和跨域输出事务、并发接管、漏投、撤权、取消和按设计关闭入口回退。`NOT_RUN`，待执行。
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-05, AC-06, AC-07 · _Verification: V-05_ · _Depends: T028，受控基础设施可用_
- [ ] **T032** [双方联调验收] 在实施期 `verification.md` 记录真实昆联接口、固定版本、原实际用户和 `# TODO [F126][EXT-05]` 样例证据。验证启动查回、等待和原 Run 恢复、取消与结果竞争及撤权拒绝。`NOT_RUN`，待执行。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07_ · 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07 · _Verification: V-06_ · _Depends: T029, T030, T031，双方联调环境可用_

## 4. 验证记录与偏差

每批在实施期新增或更新 `verification.md`，写入实际命令或浏览器步骤、退出结果、验收覆盖、替身和跳过范围。标记任务完成以对应可执行证据为准，同一代码状态下复用已有结果。代码检查、独立本地进程、受控基础设施、真实昆联联调分别记账。

W1 复用图引擎已有的 Agent 前静态中断参数，4D 用独立派发标记选择执行分支。真实队列验证中，测试生产者在独立进程加载 Celery，避开 pytest 根夹具的 Celery 替身。没有改变已确认的运行语义。影响已确认行为或设计决策的变化先回到规格或设计评审。
