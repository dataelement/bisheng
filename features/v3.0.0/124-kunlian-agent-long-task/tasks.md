# Tasks 毕昇 Workflow 调用昆联 Agent 长任务与取消

- **Feature ID** F124（拟用，合入前复核）
- **Version** v3.0.0
- **关联** [规格](./spec.md)、[设计](./design.md)、[本期验证记录](./verification.md)、[F119 验证记录](../119-kunlian-platform-agent/verification.md)、[版本契约](../release-contract.md)。

## 1. 状态与批次

| 步骤 | 状态 |
| --- | --- |
| spec.md | 已确认 |
| design.md | 已确认 |
| tasks.md | 已拆解 |
| 实施与验证 | 16 / 20 项 Mock 任务通过。V-02 和 V-03 的隔离回归通过，V-01 有自动化证据，浏览器与完整本地栈验收待执行。V-04 为 `NOT_RUN`。 |

| 批次 | 任务 | 批次验收 |
| --- | --- | --- |
| W1 模式、版本与 Mock 契约 | T001–T004 | 4 / 4，E-001、E-002。显式异步绑定固定 V1，模拟远端按原关联查回。 |
| W2 启动、轮询与下游门禁 | T005–T009 | 5 / 5，E-002。重复投递和迟到结果的定向验证通过。 |
| W3 停止、超时与补偿 | T010–T016 | 7 / 7，E-002。现有停止服务、原会话状态读取和隔离补偿通过。 |
| W4 正常入口验收与兼容 | T017–T020 | 已有样例及 E-002 至 E-006 的自动化证据。实际浏览器发布、重连、停止与完整本地栈验收待执行。 |
| W5 正式契约与环境 | T021–T024 | T021–T022 为 `WAITING_EXTERNAL`，T023–T024 为 `NOT_RUN`。 |

`B/` 指 `src/backend/bisheng/`，`BT/` 指 `src/backend/test/workflow/`，`P/` 指 `src/frontend/platform/src/`，`C/` 指 `src/frontend/client/src/`。标为拟新增的文件名用于拆分任务时定位。

Mock 首轮使用隔离环境和已绑定的最小样例图。复用 F119 的执行行、节点和现有运行／停止入口。授权、幂等和竞争场景先补失败用例，各批结束更新本表及届时新增的 `verification.md`，记录命令、退出状态、覆盖项及环境边界。架构和回退按[设计 §6–§7](./design.md#6-已知坑与宪法检查)执行。

## 2. Mock 实施任务

### W1 模式、版本与 Mock 契约

- [x] **T001** [测试] 在 `BT/conftest.py` 复用 F119 的隔离存储，准备 A 发布／B 运行、可控时钟和独立连接。在 `BT/test_platform_agent_long_task_contract.py`（拟新增）补缺省同步、固定版本异步能力和 Mock 同键去重测试。Mock 远端账本与本地执行记录分开。
  - 覆盖 AC: AC-01, AC-02, AC-08。对应 REQ-01、REQ-02、REQ-07，V-01／V-02／V-03。依赖已确认设计。

- [x] **T002** [领域] 在 `B/workflow/domain/schemas/platform_agent.py` 与 `B/workflow/domain/clients/platform_agent.py` 增加显式执行模式、固定版本的长任务能力和内部 `start / lookup_start / get_status / get_result / cancel` 契约。旧图省略模式时沿用同步，真实未就绪时按原方式拒绝。
  - 对应 REQ-01、REQ-07，AC-01、AC-08，V-01／V-03。依赖 T001。

- [x] **T003** [领域] 扩展 `B/workflow/domain/clients/platform_agent_mock.py`。让隔离 Mock 按启动键／取消键查询和去重，提供延迟、丢响应、结果滞后、错误归属和乱序状态样例。模拟任务事实对不同执行实例可见，正式替换点保留 `# TODO [F124][EXT-01]` 至 `[EXT-03]`。
  - 对应 REQ-02、REQ-03、REQ-04、REQ-07，AC-02、AC-03、AC-04、AC-08，V-02／V-03。依赖 T002。

- [x] **T004** [领域] 在 `B/workflow/domain/services/platform_agent_service.py` 将模式及能力校验接入现有发布和调试绑定。缺省同步沿用 F119 原摘要，显式异步固定版本和输入输出 Schema，拒绝不支持异步的版本。联跑 T001 的契约测试。
  - 对应 REQ-01、REQ-06、REQ-07，AC-01、AC-07、AC-08，V-01／V-03。依赖 T002、T003。

### W2 启动、轮询与下游门禁

- [x] **T005** [测试] 在 `BT/test_platform_agent_long_task_run.py`（拟新增）先复现重复投递、同键异参、受理响应丢失、查回未知、结果滞后／错配和结果提交前撤权。核对模拟远端创建次数、同一 Run ID、输出资格及旧状态覆盖终态的风险。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-06, AC-07。对应 REQ-01、REQ-02、REQ-03、REQ-05、REQ-06，V-02。依赖 T001、T004。

- [x] **T006** [领域] 在 `B/workflow/domain/repositories/platform_agent.py` 扩展既有调用记录的 `long_task`。实现启动登记、发送许可、远端 ID 一次绑定、阶段领取与状态归并，以及原输出门禁需要的异步条件。用同一行检查领取者、停止标志和锁内截止，保存摘要和状态，沿用既有表结构。
  - 对应 REQ-02、REQ-03、REQ-04、REQ-05，AC-02、AC-03、AC-05、AC-06，V-02。依赖 T005。

- [x] **T007** [领域] 在 `B/workflow/domain/services/platform_agent_service.py` 接入异步启动、查回和有界轮询，按隔离 Mock 的活动长任务上限受理。只在原用户仍有权、原参数可用且契约允许时使用同一键重放。查询临时失败有界退避，识别人工等待、成功但结果未就绪和错配结果，输出前复核权限与 Schema。实际用户传递保留 `# TODO [F124][EXT-04]`。
  - 对应 REQ-01、REQ-02、REQ-03、REQ-05、REQ-06，AC-01、AC-02、AC-03、AC-06、AC-07，V-02。依赖 T006。

- [x] **T008** [测试] 在 `BT/test_platform_agent_long_task_run.py` 加真实图节点的竞争用例。用 F119 本地停止标记分别模拟停止先于输出提交、输出先于停止、停止发生在后续节点获准开始前以及结果晚于截止，断言输出变量和下游实际执行次数。远端取消另由 W3 验证。
  - 覆盖 AC: AC-01, AC-05, AC-08。对应 REQ-03、REQ-04、REQ-05、REQ-07，V-02。依赖 T006、T007。

- [x] **T009** [Worker] 在 `B/workflow/nodes/platform_agent/platform_agent.py` 和 `B/workflow/graph/graph_engine.py` 接入显式异步分支、原领取者输出和下游开始许可，走 F119 现有任务头到租户 ContextVar 的边界。沿用原图执行槽的有界等待。提交与后续节点开始分别同停止判定。
  - 对应 REQ-01、REQ-03、REQ-04、REQ-07，AC-01、AC-05、AC-08，V-02。依赖 T008。

### W3 停止、超时与补偿

- [x] **T010** [测试] 在 `BT/test_platform_agent_long_task_reconcile.py`（拟新增）用独立连接和可控时钟覆盖停止先于发送、停止时启动未知、取消响应丢失、受理后仍在运行、取消拒绝、不同截止、漏投及旧领取者迟到写回。撤权后验证取消请求不会发出，核对本地状态、远端事实和取消进度三者。
  - 覆盖 AC: AC-04, AC-05, AC-06, AC-07。对应 REQ-04、REQ-05、REQ-06，V-02。依赖 T006、T007。

- [x] **T011** [领域] 在 `B/workflow/domain/repositories/platform_agent.py` 将已授权主动停止及 4B 超时与取消意图同事务保存。重复触发复用取消键，普通内部清理只走本地规则。补齐取消确认窗口、领取和清理，保留阻止旧调用再启动的事实。
  - 对应 REQ-04、REQ-05，AC-04、AC-05、AC-06，V-02。依赖 T010。

- [x] **T012** [领域] 在 `B/workflow/domain/services/platform_agent_service.py` 收敛取消与只读查回。按原身份和 Run 操作，已知终态跳过发送。无 Run ID 时只做不会创建任务的查询，迟到结果只更新远端事实。分别处理取消受理、确认、拒绝及未确认。
  - 对应 REQ-02、REQ-04、REQ-05、REQ-06，AC-04、AC-05、AC-06、AC-07，V-02。依赖 T011。

- [x] **T013** [Worker] 在 `B/workflow/domain/repositories/platform_agent.py` 提供按可信租户和主键游标轮转的有界扫描，在 `B/worker/workflow/platform_agent_long_task.py`（拟新增）接入隔离候选任务。Celery headers 传可信租户并恢复 ContextVar，正文仅含执行和调用标识。提交后唤醒，漏投由扫描补偿，失联后只收敛状态，不恢复原图。验证已停与已失败记录仍可补偿。
  - 对应 REQ-04、REQ-05、REQ-06，AC-04、AC-05、AC-06、AC-07，V-02。依赖 T011、T012。

- [x] **T014** [测试] 在 `BT/test_platform_agent_long_task_entrypoints.py`（拟新增）先验证原会话停止与状态入口。覆盖不同用户／租户／接入方、撤权和来源变更、重连后不重复启动、停止通知投递失败、内部清理不发远端取消及缓存已消费仍可读摘要。
  - 覆盖 AC: AC-01, AC-04, AC-05, AC-07, AC-08。对应 REQ-01、REQ-04、REQ-05、REQ-06、REQ-07，V-01／V-02。依赖 T009、T013。

- [x] **T015** [应用] 在 `B/workflow/application/platform_agent.py` 和 `B/worker/workflow/redis_callback.py` 接通既有会话的长任务读视图与停止信号。对原执行复核归属和权限，输出脱敏的 `agent_long_task` 摘要。停止事实提交后再通知图和补偿，通知失败保留本地已停止的结果。
  - 对应 REQ-03、REQ-04、REQ-05、REQ-06，AC-01、AC-04、AC-05、AC-07，V-01／V-02。依赖 T014。

- [x] **T016** [入口] 在 `B/common/chat/clients/workflow_client.py` 和 `B/workflow/domain/services/published_workflow_service.py` 复用原浏览器动作与开放运行停止入口。按已授权的原会话和执行关联读写；重连不发起新运行，停止响应不等待远端。联跑 T014 测试，保持原停止响应形态。
  - 对应 REQ-01、REQ-03、REQ-04、REQ-06、REQ-07，AC-01、AC-04、AC-07、AC-08，V-01／V-02。依赖 T015。

### W4 正常入口验收与兼容

- [ ] **T017** [Platform 样例] 在本特性目录准备固定 V1 的 `mock-workflow.example.json`。通过现有 `P/pages/BuildPage/flow/FlowNode/component/PlatformAgentItem.tsx` 所在画布打开、保存及发布样例，验证保存后仍保留显式模式和既有变量映射，旧同步样例仍能打开。样例使用已绑定配置。
  - 对应 REQ-01、REQ-07，AC-01、AC-08，V-01／V-03。依赖 T004、T009。

- [ ] **T018** [Client] 在 `C/pages/appChat/useWebsocket.ts` 消费可选摘要并沿用原停止动作，由 `C/pages/appChat/ChatView.tsx` 在原会话展示进度和取消确认。停止后的摘要只更新对应执行的状态视图，有执行关联时按原执行重连，缺省摘要时保留旧行为。手动检查断线、重连与停止。
  - 对应 REQ-03、REQ-04、REQ-06、REQ-07，AC-01、AC-04、AC-07、AC-08，V-01／V-03。依赖 T016。

- [ ] **T019** [端到端测试] 在 `BT/test_platform_agent_long_task_e2e.py`（拟新增）通过既有会话入口验证 A 发布、B 运行、V2 发布后原 Run 仍按 V1、重连后进度及下游单次输出。再走原停止入口，验证本地先停止、远端随后确认和无下游输出。使用独立补偿执行实例验证漏投收敛并记录替身范围。
  - 覆盖 AC: AC-01, AC-04, AC-05。对应 REQ-01、REQ-03、REQ-04、REQ-05、REQ-06，V-01。依赖 T013、T016、T017、T018。

- [ ] **T020** [回归与记录] 复用 `BT/test_platform_agent_workflow_bridge.py` 及 F119 相关回归，核对同步调用、普通 Workflow、真实未就绪拒绝和来源隔离。汇总 V-01～V-03、静态检查和各批证据到 `verification.md`，正式接口与真实环境单独记状态。
  - 覆盖 AC: AC-08。对应 REQ-07，V-03。依赖 T019。

## 3. 正式契约与环境

- [ ] **T021** [正式契约] 在 `design.md` 核对昆联现有启动／查回、状态与结果、取消和实际用户传递能力，固化已确认映射及幂等窗口。状态 `WAITING_EXTERNAL`。
  - 对应 REQ-01、REQ-02、REQ-03、REQ-04、REQ-05、REQ-06，AC-01、AC-02、AC-03、AC-04、AC-06、AC-07，V-04 准备。依赖 T020 及 EXT-01 至 EXT-04。

- [ ] **T022** [正式适配] 在 `B/workflow/domain/clients/platform_agent.py` 及其正式 Provider 落点接入已确认契约，逐项处理 `# TODO [F124][EXT-01]` 至 `[EXT-04]`。候选文件与测试细分以正式契约为准。状态 `WAITING_EXTERNAL`。
  - 对应 REQ-01、REQ-02、REQ-03、REQ-04、REQ-06、REQ-07，AC-01、AC-02、AC-03、AC-04、AC-07、AC-08，V-04。依赖 T021。

- [ ] **T023** [受控环境] 在 `verification.md` 记录真实基础设施结果，验证 MySQL／中心 DM8 行锁、OpenFGA、Broker／Worker 漏投及并发容量、实际停止和回退。可先用 Mock 昆联隔离证明基础设施。状态 `NOT_RUN`。
  - 对应 REQ-02、REQ-04、REQ-05、REQ-06，AC-02、AC-04、AC-05、AC-06、AC-07，V-04。依赖 T020 与受控环境授权。

- [ ] **T024** [双方联调] 在 `verification.md` 按 `# TODO [F124][EXT-05]` 核对真实昆联环境、OpenAPI、固定版本、测试身份、实际启动去重、轮询、取消和超时审计。状态 `NOT_RUN`。
  - 对应 REQ-01、REQ-02、REQ-03、REQ-04、REQ-05、REQ-06，AC-01、AC-02、AC-03、AC-04、AC-06、AC-07，V-04。依赖 T022、T023 及 EXT-05。

## 4. 实际偏差记录

隔离 Mock 实施沿用已确认的停止判定、执行恢复和存储范围。审查后补齐截止判定、原执行查询隔离、停止后显式重跑与节点摘要顺序的回归证据。W4 浏览器和完整本地栈待执行，正式契约与真实环境沿用 W5 状态。[验证记录](./verification.md)
