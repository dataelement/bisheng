# Design 毕昇 Workflow 调用昆联 Agent 的长任务挂起与恢复

- **Feature ID**: F126（拟用，合入前复核）
- **Version**: v3.0.0
- **Status**: W1–W3 已完成隔离 Mock 验收，W4 起待执行
- **Mode**: Mock 优先
- **更新**: 2026-11-09
- **关联**: [已确认规格](./spec.md) · [4B 长任务](../124-kunlian-agent-long-task/design.md) · [4C 人工输入](../125-kunlian-agent-interaction/design.md) · [版本契约](../release-contract.md)

## 1. 目标与边界

已发布 Workflow 在普通异步 Agent 受理后保存等待点，结束当前 Celery 执行任务。短任务查询原 Agent Run，结果就绪后由独立 Worker 从原节点继续，并将纯文本输出持久化一次。

首轮为隔离 Mock、有会话的 Client 运行页和「开始 → 平台 Agent → 输出 → 结束」线性图。只接入一个异步、关闭人工输入的 Agent，输出为无文件、无引用、无后续交互的纯文本。已有同步、旧异步、4A、4C 和开放运行入口走各自路径。通用图和节点副作用重放、SSE／回调以及对外 Session 取消分属后续范围。

## 2. 关键约束与架构检查

- 以已发布的原 Workflow、Agent 版本和原实际用户恢复。Worker 可更换，执行 ID、节点序号、Agent Run 与截止时间保持原值。
- 继续使用既有 `workflow_platform_agent_execution` 和聊天消息表。4D 扩展调用及派发的版本化 JSON。候选设计无表结构变更和历史迁移。执行、停止和输出在同一执行行裁决，轮询、权限请求和消息推送在事务外完成。
- 遵循[宪法 C1–C8](../../../docs/constitution.md)。应用端口负责授权与协调，领域服务负责 Provider 行为，仓储负责双库事务，聊天消息写入仍由会话侧承接。Worker 通过可信租户作用域读取原执行，再校验实际用户及资源权限。现有前端 WebSocket 负责状态与消息消费。进程内图对象和 Redis 引用可重建，数据库是跨 Worker 恢复依据。日志与任务消息只保存必要关联和稳定错误类别。
- 本轮只在明确装配的隔离 Mock 队列启用。受控 MySQL／DM8、OpenFGA 及正式昆联环境另行验收。

## 3. 方案选择

| 决策 | 选定方案、依据与备选 | 复核条件 |
| --- | --- | --- |
| D-01 挂起边界 | 使用 4C 已验证的 Agent 前静态检查点。启动由 4D 执行器调用 4B 的输入解析、版本核对和幂等能力。挂起提交后直接结束图执行任务。4B 的节点内有界轮询仍占执行槽，节点内动态中断有重入启动和节点回调的风险。 | 扩展到分支、循环或多 Agent 时重新验证检查点形态和可恢复节点。 |
| D-02 领取与调度 | 执行行保存等待、下次轮询、租约与恢复派发。复用 4B 的按租户扫描和提交后唤醒，短任务执行单次查回、轮询或取消。恢复派发使用固定 ID，每次领取生成新所有权标识。仅靠延时消息无法覆盖事务提交后漏投，4C 的已领取任务也没有可直接复用的失联接管语义。 | 扫描开销、租约竞争或记录体积影响容量时复核索引和调度存储，涉及结构变化另行确认。 |
| D-03 单次输出 | 4D 恢复分支先把核验结果和 Output 节点生成的纯文本留在本次执行上下文，待线性图结束后，同事务写入一条聊天消息并提交执行终态。现有回调直接调用 `ChatMessageDao.insert_one` 并独立提交，若继续沿用，消息落库后、执行确认前退出会造成重复输出。 | 扩展到附件、引用或有外部副作用的节点前，先定义对应事务或幂等边界。 |
| D-04 启用与兼容 | 隔离装配拟使用内部 `enable_long_task_resume`，与 `enable_long_tasks` 同时启用。仅兼容图和已发布浏览器会话受理 4D，受理后在原 `START` 派发内固化模式和 Workflow 版本。没有 4D 标记的记录仍走旧路径。直接替换所有 `async` 会扩大到未验证图及旧任务。 | 正式契约与受控验证通过后，再确认正式启用策略和运行中的记录如何平滑收尾。 |

## 4. 系统现状与目标流程

W1 已接通 4D 隔离受理、Agent 前检查点与启动后挂起。普通 4D 执行在提交 `POLL_WAIT` 或 `START_CHECK` 后结束原任务，会话传输继续使用运行中状态及普通长任务摘要。W2 已接通租户扫描、短任务租约及恢复补投。W3 已接通独立 Worker 接管、原图恢复、纯文本与执行终态同事务提交，以及授权回执读回。恢复阶段用仅在进程内暂存纯文本的回调，提交前不发送节点事件或输出。浏览器和普通会话历史读取的 4D 接线留在 W5。见[验证记录](./verification.md)。

### 4.1 当前落点

| 当前模块 | 可复用能力与边界 |
| --- | --- |
| [4B 领域服务](../../../src/backend/bisheng/workflow/domain/services/platform_agent_service.py) | `_run_long` 核验冻结版本、输入、实际用户和调用键，再进入 `_poll_long`。`reconcile_long` 已有取消及 4C 回执补偿，4D 的普通等待轮询尚需接入。 |
| [4C 图快照](../../../src/backend/bisheng/workflow/graph/platform_agent_interaction.py) · [4A 线性快照](../../../src/backend/bisheng/workflow/graph/kunlian_interaction.py) | 已有检查点、变量、历史、步数和下一节点校验。4C 的绑定依赖交互节点识别，4D 复用下层通用校验并单独识别普通异步线性图。 |
| [执行仓储](../../../src/backend/bisheng/workflow/domain/repositories/platform_agent.py) · [Worker](../../../src/backend/bisheng/worker/workflow/tasks.py) | `prepare_execution` 在 Flow 行锁内受理。`claim_dispatch`、`request_stop` 和 `output_scope` 使用执行行锁。4C 只允许特定交互恢复派发，4D 增加普通恢复领取与失效判定。 |
| [会话应用端口](../../../src/backend/bisheng/workflow/application/platform_agent.py) · [浏览器状态与停止](../../../src/backend/bisheng/common/chat/clients/workflow_client.py) | `long_status`、`stop_long` 已服务普通异步摘要和取消。4C 已有缺失 Redis 引用与 `initial_open` 的保护，4D 扩展此类保护到普通挂起记录。 |
| [平台 Agent 节点](../../../src/backend/bisheng/workflow/nodes/platform_agent/platform_agent.py) · [输出回调](../../../src/backend/bisheng/worker/workflow/redis_callback.py) · [聊天消息 DAO](../../../src/backend/bisheng/database/models/message.py) | Agent 节点由输出门禁写入变量。`RedisCallback.on_output_msg` 在聊天消息独立提交后推送。4D 使用独立执行分支缓存输出，并把消息写入交给会话侧事务端口。 |

### 4.2 受理、等待与接管

1. **受理与启动。** 应用层在普通浏览器发布会话校验归属及 Workflow `use`。在既有 Flow 行锁内确认 `FlowVersion` 和冻结图摘要，固化 `START` 的模式、原版本与可信浏览器来源。执行器运行至 Agent 前，保存带版本的检查点。沿用 4B 的启动键、参数摘要和启动预算。检查点及可核对的启动记录在发远端请求前持久化。明确未发送与发送事实未知分别记录。启动响应丢失时优先按原键查回，只有 Provider 明确允许时才同键同参重放。
2. **提交等待并结束任务。** 启动已受理时校验 Run ID 和版本。在同一行事务保存 Run、检查点、截止时间与下次查询时间，将图执行设为 `WAITING`，并把 `START` 派发置为完成。启动仍待核对时可进入 `START_CHECK`，仅由短任务查回并建立原 Run 关联。事务提交后发送摘要、唤醒补偿。Worker 直接返回，避免落入原图自动继续或通用终态清理。会话保留原执行引用，摘要使用远端等待而非 `INPUT`。
3. **短任务查询。** 按既有执行主键游标分页扫描 4D 活跃记录，在可信租户作用域领取一次轮询租约。单次远端查询在锁外完成。行锁内校验租约、原 Run、版本与期限，更新进度和下次时间。结果结构有效时在同一事务保存结果并登记唯一 `LONG_TASK_RESUME` 派发。响应超时、状态乱序或结果暂不可用时沿用原期限；明确失败、取消、无效输出或普通异步收到 `WAITING_INPUT` 时收敛为可查询终态。通知丢失由下一次有界扫描补齐。
4. **独立 Worker 恢复。** 按持久化派发领取，新领取者取得唯一所有权标识及有限租约。复核实际用户、当前 Workflow 和 Agent 权限、来源策略及冻结快照，恢复原节点、变量、历史和步数。只允许从保存的 Agent 前边界消费已核验结果，Agent 节点的恢复分支读取该结果。原 START 节点和 Agent 启动均不再执行。租约过期时只有尚未完成持久输出的派发可被接管，旧领取者的状态、终态和输出提交必须被拒绝。
5. **持久化输出。** 4D 只允许同次恢复产生一个合格的纯文本输出。恢复中的节点状态和输出暂存于当前任务，正常到达结束节点后再次复核权限，在执行行锁内重读时钟，校验派发所有权、租约、原截止与停止标志。会话侧事务端口使用仓储传入的同一 SQL 会话写入既有聊天消息，`flush` 取得 `message_id`，由外层一次提交消息、节点成功、执行成功及回执。该端口沿用现有消息字段和租户归属，由会话侧仓储封装写入，独立的 `ChatMessageDao.insert_one` 保留原调用。Redis 与 WebSocket 在提交后按稳定 `message_id` 通知。通知遗漏时从已授权的历史或回执补读同一条消息，重复通知按 `message_id` 合并。提交前进程退出只会重算受限的纯文本，提交后接管只读回执。

启动阶段先写入检查点和发送许可，再发出请求。补偿扫描还需识别停在 `RUNNING` 的 4D 启动记录。只有启动领取失效且发送许可已发放时才接管查回，防止在请求在途时另发启动。若记录表明尚未发放发送许可，按原启动窗口收敛为明确未发送。接管后，旧启动任务的响应只能在当前核对规则下处理，不能重新开启执行或覆盖绑定。

4D 聊天消息在既有 `extra` 中带内部版本标记和执行关联，执行记录保留同一 `message_id`。会话服务对 4D 记录在响应序列化前复用 Workflow 应用端口核验原会话、实际用户、租户、当前 Workflow 与 Agent 权限，移除内部标记。缺少调用主体、找不到匹配执行或权限不确定时禁止返回该条内容。`/chat/history`、按会话取消息和其他会返回该消息正文的路径均纳入接入核查。WebSocket 从 Redis 发送补回的输出前使用同一判断，避免历史接口或缓存绕过授权。未带 4D 标记的历史消息沿用现有读路径。

### 4.3 持久状态与竞争裁决

`calls[call_key].long_task` 保留 4B 的远端状态、原启动关联和取消状态，拟增加 `resume` 子记录。子记录含 `format`、阶段、原检查点、轮询时间和租约、核验后的结果、恢复派发 ID、单调状态版本及最终消息回执。续跑领取写入原 `dispatches`，保持一个逻辑派发，领取标识与调用 ID 分开。队列消息只传 `execution_id`、`call_key` 及所需 `dispatch_id`，可信租户来自既有任务头。

| 4D 阶段 | 有效转移 |
| --- | --- |
| `START_CHECK` | 启动响应未知或发送后失联，按原键在启动核对期限内查询。查到原 Run 后进入 `POLL_WAIT`。核对失败时给出明确状态，停止后只允许 4B 的有限取消核对。 |
| `POLL_WAIT` | 已绑定 Run 并等待终态。每次仅一个有效轮询租约，结束后释放执行槽。可信成功结果进入 `RESUME_READY`，可查询的远端失败、取消或本地超时进入 `TERMINAL`。 |
| `RESUME_READY`／`RESUMING` | 一个逻辑恢复派发。并发领取互斥，未领取漏投可重发，已领取且失效时可由新领取者接管。纯文本最终提交前始终以当前所有权和期限为准。 |
| `TERMINAL` | 停止、超时、失败或成功均关闭恢复资格，清理检查点和临时结果，保留最小终态、回执和 4B 取消核对信息。晚到远端终态只更新允许核对的远端事实。 |

采用 4B Mock 的原总等待窗口、单请求上限和独立取消窗口。建议首轮扫描沿用 4B 的 1 秒间隔，轮询与恢复租约按各阶段剩余时间截断。等待、补投、接管和刷新均沿用首次受理的截止时间。时钟在取得行锁后读取，网络与消息推送放在锁外。复用线性检查点现有 JSON 上限，结果按现有载荷限制核验。损坏快照、错配绑定、越权或超期不能生成下游输出。

停止仍走现有 Workflow 会话的 `stop` 动作。4D 会话先定位并授权原执行，再复用 `request_stop`。锁内先关闭恢复和输出许可，已绑定的 Run 复用 4B 取消意图，未知启动按原键核对。取消与输出提交共用最终裁决。输出事务先提交时保留原成功及消息回执；停止或超时先提交时回滚后到的输出。远端接受取消与最终取消分别显示。权限不可用时允许在原期限内重新核验，明确撤权或停用则停止相应受保护操作。超过期限后本地终态保持稳定。

## 5. 已知坑与落点

| 风险 | 影响和处理 |
| --- | --- |
| 只保存图检查点 | `restore_linear_wait` 同时恢复变量、历史、步数。否则 Agent 恢复后下游可能引用到空值，节点序号也会漂移。 |
| `WAITING` 同时被人工输入使用 | Worker 从 4D 持久标记选择分支，`WorkflowClient` 读 4D 状态时返回普通 `WAITING_RESULT`。避免复用原生表单、4C 提交或进程内 `_global_workflow` 续跑。 |
| 4C 的恢复领取失联只核对远端 | 4D 需要可回收租约及旧所有权检查。`claim_dispatch`、失败清理和最终输出均校验当次领取；旧 Worker 不能关闭新恢复任务或清除它的会话引用。 |
| 聊天消息和成功状态分别提交 | 4D 由会话侧事务端口和执行仓储共同提交。验证任务退出位置覆盖输出前、事务提交前、事务已提交但未推送。避免重复或丢失持久输出。 |
| 断线、刷新和主动停止会经过相近入口 | `WorkflowClient` 在连接绑定的会话查找 4D 事实。被动断线释放连接资源，初次页面打开读原终态，主动停止只作用于指定执行；显式重跑可新建执行。 |

## 6. 契约、落点和正式替换

| 方向与契约 | 设计落点与调用方 |
| --- | --- |
| 浏览器 `check_status`／`stop` | [WorkflowClient](../../../src/backend/bisheng/common/chat/clients/workflow_client.py) 通过 [应用端口](../../../src/backend/bisheng/workflow/application/platform_agent.py) 解析当前可信执行。显式 ID 只查该执行；引用丢失时在已授权的同一 Workflow／会话内查唯一活跃 4D 执行，首次打开可回读最近一次已确认终态，存在歧义时返回稳定错误。无需新增 HTTP 路由。 |
| `processing/info.agent_long_task` 与输出消息 | 沿用 `execution_id`、`agent_run_id`、`local_state`、`remote_state`、`cancel_state`、`progress`。4D 可附加 UTC `expires_at` 和整数 `status_version`，Client 按执行及版本忽略旧摘要。输出沿用既有 `message_id`。状态、输出和历史仍受会话及实际用户权限约束。 |
| 执行受理、轮询、恢复 | [应用端口](../../../src/backend/bisheng/workflow/application/platform_agent.py) 与 [领域服务](../../../src/backend/bisheng/workflow/domain/services/platform_agent_service.py) 延用原授权和 Provider 端口；[仓储](../../../src/backend/bisheng/workflow/domain/repositories/platform_agent.py) 增加 4D 等待、短任务租约和提交裁决。拟新增 `workflow/graph/platform_agent_long_task_resume.py` 和 `worker/workflow/platform_agent_long_task_resume.py` 承载窄快照适配和执行器，由[既有 Worker](../../../src/backend/bisheng/worker/workflow/tasks.py)及[补偿装配](../../../src/backend/bisheng/worker/workflow/platform_agent_long_task.py)显式注册。 |
| 会话持久输出 | 拟在 `chat_session/domain/repositories/workflow_output_repository.py` 提供使用调用方事务的纯文本输出写入，再由 `chat_session` 应用端口供 4D 协调。复用现有聊天消息模型与类型，ORM 仅在仓储内。[会话历史服务](../../../src/backend/bisheng/chat_session/domain/chat.py)及[会话读取入口](../../../src/backend/bisheng/chat_session/api/endpoints/session.py)核查 4D 消息的读取范围。`RedisCallback` 只对 4D 的提交后消息做转发。历史内容和最终通知共用同一数据库消息 ID。 |
| 底层依赖 | Celery/Broker 的投递可重复，扫描必须接管漏投。Redis 可能丢引用或通知，数据库是持久事实。LangGraph 版本或快照结构变化时，拒绝不兼容快照并在设计复核后更新格式。MySQL／DM8 事务及 OpenFGA 判定须经受控环境验收。 |

| 正式替换 | 待确认内容 |
| --- | --- |
| `# TODO [F126][EXT-01]` | 确认 4B Provider 原启动查回、幂等键作用域和允许同键重放的条件。 |
| `# TODO [F126][EXT-02]` | 固定版本与 Run 的可信表示、状态及结果 Schema、轮询频率、限流、阶段期限及保留期。 |
| `# TODO [F126][EXT-03]` | 确认取消受理、终态、拒绝及完成竞争的对账规则。 |
| `# TODO [F126][EXT-04]` | 确认原实际用户的查询及取消授权，优先核对现有 SSO Access Token 或受信委托的适用范围、有效期与撤权。 |
| `# TODO [F126][EXT-05]` | OpenAPI 或 Schema、测试地址、固定版本、允许／拒绝账号和长任务失败样例。正式适配失败返回明确错误。 |

## 7. 验证与可观测性

| 需求与验收 | 设计落点 | 计划验证 |
| --- | --- | --- |
| REQ-01、REQ-02 · AC-01 | D-01、D-04，受理与等待事务 | V-01 在真实本地队列只启动一个并发为 1 的 Workflow Worker。Mock Agent 保持运行中，把另一条 Workflow 任务投到同队列，核对同一个 Worker 在原 Run 未就绪时完成第二个任务。 |
| REQ-01、REQ-03、REQ-04 · AC-02、AC-03 | D-01～D-03，快照、补投和接管 | V-02 记录 Worker A 退出，发布 V2，再由独立 Worker B 恢复固定 V1。核对运行 ID、节点序号、前序节点、远端启动及唯一输出。V-03 注入保存后漏投、旧租约和错误快照。 |
| REQ-03、REQ-04 · AC-04 | 4B 启动键、轮询及终态门禁 | V-03 使用可控时钟和固定 Mock 账本核对启动查回、错配、无效输出及结果暂不可用。 |
| REQ-05、REQ-06 · AC-05、AC-06 | 行锁裁决、实际用户和取消补偿 | V-03 注入停止／完成竞争、临界到期、输出前退出和消息提交后通知丢失。V-04 对 WebSocket、会话历史和按会话取消息验证其他会话、用户、租户与撤权拒绝。 |
| REQ-01、REQ-02、REQ-07 · AC-07 | 会话状态和原路径兼容 | V-04 从 Client 验证重连、刷新原终态、停止和显式重跑，回归 F119／F123／F125 及未启用的 4B。 |
| 正式门槛 | 第 6 节契约与基础设施 | V-05 双库、OpenFGA 和受控队列回归，V-06 真实昆联联调。两项独立记录，均为 `NOT_RUN`。 |

浏览器验收沿用 4C 的隔离方式。以 A 发布者、B 有 Workflow `use` 权限的测试账号以及另一无权读取原会话的账号执行。在隔离 Platform 发布固定 V1，从隔离 Client 打开 `/workspace/app/<conversationId>/<workflowId>/10`，启动后保持 Mock Run 未就绪。另起会话走等待中停止与刷新。记录 Worker 标识、原执行／派发／Run、下游输出计数及最终消息 ID。V-01～V-04 的本地队列、故障注入和浏览器均已通过。正式环境待执行。详见[验证记录](./verification.md)。

日志区分挂起、领取／租约过期、补投、输出裁决及取消核对。使用执行、派发、Run 和消息关联，省略令牌、快照、完整输入及结果。验收分别记录任务执行结束、同队列第二个任务完成和同次恢复三类证据。

## 8. 关闭入口与回退

停用时先关闭新的 4D 受理，保留同版本 Worker 和扫描处理已有 4D 记录。已挂起运行按原记录恢复或使用现有停止入口取消，等待本地终态与补偿窗口收敛后再移除隔离任务注册。旧版本 Worker 只接收旧队列或无 4D 标记的执行，避免混跑。涉及通用图、存储结构或公共权限行为的变更回到规格与设计确认。

## 修订历史

| 日期 | 变更 | 依据 |
| --- | --- | --- |
| 2026-11-09 | 设计初稿，完成规格、现有入口和架构约束对照。 | 4D 规格已确认，进入设计。 |
| 2026-11-09 | 同步 W1 的持久等待、Worker 任务退出和单执行槽验收。 | T001–T006 验证通过。 |
| 2026-11-09 | 同步 W2 的原启动查回、轮询租约、结果与派发同事务及限频补投。 | T007–T010 验证通过。 |
| 2026-11-09 | 同步 W3 的过期接管、纯文本事务和授权回执读回。 | T011–T017 验证通过。 |
