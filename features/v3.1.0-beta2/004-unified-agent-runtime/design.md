# Design: 日常对话与深度研究统一（F004-unified-agent-runtime）

> **本文档定位 — Why this How。** 需求见 [spec.md](./spec.md)。本文写在实现之前，所以 §4 分成“今天的代码”和“目标形态”两部分；实现后覆盖更新，只保留当天状态。
>
> **证据标注**：每条理由后面标【实测】【读码】或【未验证】。【实测】指 `src/backend/scripts/spike_unified_runtime/README.md` 里的脚本结果；【读码】指在 `origin/feat/3.1.0-beta2`（49ecbd659f）上读到的代码；【未验证】是假设，实现前必须先验证。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [prototype/index.html](./prototype/index.html)
**版本**: v3.1.0-beta2
**最后更新**: 2026-11-19（已实施，114 实测中；§4 的“目标”即当前实现，与代码不符处以 §5 和修订历史为准）

---

## 1. 目标与非目标

- **目标**：工作台的直接回答和深度研究共用一个 agent 内核、一个事件通道、一个会话线程。两者只在“是否挂载计划能力”上不同。运行与 HTTP 连接解耦，所以用户可以在运行中插话、断线后续看。
- **非目标**：
  - 不统一两种回答方式的落库结构（见决策 8）。
  - 不引入 async subagents 和 LangGraph Agent Server（见决策 5）。
  - 不改工作流、助手、桌面端 DeepSeek Harness 的执行链路。
  - 不做界面上直接编辑计划条目。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md` C1–C8，不在此重抄。本特性特有的约束：

| # | 约束 | 来源 |
|---|---|---|
| K1 | 直接回答的首字符时间不能比今天慢（AC-34）。今天它在 API 进程内执行，不排队。114 上不带附件的请求，准备阶段（收到请求到发出模型请求）中位数 0.16 秒、p90 1.34 秒；模型自身的首 token 中位数 1.40 秒。所以统一内核能增加的准备时间只有约 0.1 秒的余量。 | spec；【读码】`workstation/domain/services/chat_service.py:1863`；【实测】S5 |
| K2 | 开放 API 深度研究接口的契约不变（AC-39）。它按 `session_version_id` 查任务，与工作台共用 `submit_task_turn` 和同一个 worker。 | 【读码】`open_api/domain/services/task_mode_service.py:341` |
| K3 | deepagents 0.7.39 要求 `langchain>=1.5.0`、`langchain-core>=1.8.1`。升级连带移动 18 个包、新增 4 个包（`httpx2`、`httpcore2`、`httpx2-jsfetch`、`truststore`，许可证为 BSD-3-Clause 与 MIT）。每个被移动的包都取了被强制的最低版本，其中 `anthropic` 0.106→0.120、`pydantic` 2.12.4→2.12.5、`certifi`→2026.10.19、`miniopy-async`→1.23.6。 | 【实测】T003：逐个把包钉回原版本，求解器都报冲突 |
| K4 | DM8 上不能在高频路径整行重写大 JSON。高频状态放 Redis，按节流落库。 | 【读码】`src/backend/AGENTS.md` Known Pitfalls |
| K5 | 多节点：API 节点与 worker 节点不共享本地磁盘（C8）。本地 `file_dir` 只是缓存，MinIO `workspace/` 才是真源。 | 【读码】`linsight/AGENTS.md` |
| K6 | checkpointer 是自研 `PlainRedisCheckpointer`，TTL 7 天，从不裁剪。超过 7 天的会话没有 checkpoint。 | 【读码】`linsight/domain/services/checkpointer.py:58` |
| K7 | `langgraph-api` 的许可证是 Elastic-2.0。 | 【实测】S4 |
| K8 | 新用到的 Redis 命令必须是 5.0 即有的核心命令，不能依赖模块。随产品交付的 Redis 是 7.0.4。客户自带的 Redis（代码支持 Cluster 与 Sentinel）没有文档写明最低版本。同一会话的全部键必须带同一个 hash tag（`{会话 id}`），否则 Lua 脚本在 Cluster 上跨槽报错。 | 已核实（T001，2026-11-18）：`docker/.env.example:23` 与 `docs/architecture/08-deployment.md:12` 写明 `redis:7.0.4`；compose 用 `redis-users.acl` 挂 ACL 文件（`docker/docker-compose.yml`），ACL 文件要求 Redis ≥ 6.0；DSH 额度模块已在生产路径使用 Stream 与 hash tag（`dsh/infrastructure/lua/admit.lua:63` 的 `XADD`、`dsh/domain/services/projection.py:71` 的 `XREADGROUP`、`dsh/infrastructure/quota_redis.py:79`）。【未验证】客户自带 Redis 的实际版本；P1 上线说明需写明“Redis ≥ 5.0” |

---

## 3. 方案对比与选定

### 决策 1：一个内核工厂，两个档位

- **备选**：
  - A. 把 `create_linsight_agent` 泛化成统一工厂，用档位参数区分：`direct`（不挂计划能力、精简提示词）和 `planned`（挂计划能力和规划提示词）。
  - B. 保留两个内核，只抽出共用的工具装配。改动小，但 ask_user、技能、工作区要在日常内核里重做一遍，插话也要做两遍。
  - C. 自研 agent 循环，不依赖 deepagents。完全可控，但放弃压缩、容错、技能、文件系统等约 12 个已调好的中间件。
- **选定**：A
- **原因**：AC-05、AC-43 至 AC-48 要求两种方式的能力相同。任务模式的中间件栈已经处理了大量模型不规范行为（非法 JSON、截断、工具循环），这些经验写在 `linsight/AGENTS.md`，B 和 C 都要重新踩一遍。【读码】`agent_factory.py:1631` 起的中间件列表。
- **何时该重新考虑**：`direct` 档的首字符时间实测比今天慢，且定位到是 deepagents 中间件本身的开销（而不是可延后的初始化）。

### 决策 2：deepagents 升到 0.7.x，显式启用 `TodoListMiddleware`

- **备选**：
  - A. 升到 0.7.39，`planned` 档传入 `TodoListMiddleware()`，`direct` 档不传。
  - B. 留在 0.6.12。0.6.12 的 `write_todos` 是默认挂载的，`direct` 档要额外想办法去掉它。
- **选定**：A，并且作为独立的第一个任务波次先做、先回归，不和功能改动混在一起。
- **原因**：
  - 0.7.39 下 `todos` 状态增量的结构与 0.6.12 逐字段相同，`_diff_todos` 不用改。【实测】S1
  - 仓库用到的 57 个框架符号在 0.7.39 全部存在。【实测】S2
  - 0.7 默认系统提示词从 7588 字符降到 1421 字符，按需挂载正好对应两个档位。【实测】S1
  - 代价是 K3 的连带升级，以及两处输出格式变化（空目录 `ls`、`read_file` 的行号格式）。【实测】S2
- **何时该重新考虑**：在 langchain 1.5 下跑 `test/linsight/` 全量出现无法在一个波次内修完的回归。【实测】T004/T005（2026-11-18）：`test/linsight test/workstation test/open_api` 升级前 3322 通过、117 失败、10 错误；升级并适配后 3325 通过、117 失败、10 错误，逐用例对比没有新增失败，也没有原先失败的用例变成通过（通过数多 3 个 = 新增 7 个测试 − 删除 4 个旧测试）。适配涉及四处行为变化，见 §5 坑 13 至坑 16。

### 决策 3：直接回答在 API 进程内后台执行，深度研究进 worker

- **备选**：
  - A. `direct` 档在收到请求的 API 进程里起一个与连接无关的后台协程；`planned` 档沿用 Linsight worker 队列。两者写同一个事件通道。
  - B. 全部进 worker。拓扑最简单，但每个 worker 进程有并发上限（`worker.py:451` 的 Semaphore），短问答要和长任务抢名额、排队。
  - C. `direct` 档继续绑在 HTTP 请求里执行（今天的做法）。断线即中断，无法插话，无法续看。
- **选定**：A
- **原因**：K1。B 让一句话的问答受长任务排队影响；C 不满足 AC-12、AC-31。A 的后台协程把事件写进 Redis，所以用户重连到任一节点都能续看（AC-33）。
- **worker 也能执行 `direct` 档**：内核工厂不关心进程。API 进程只是 `direct` 档的快速通道；凡是不由用户请求直接触发的 `direct` 运行（见决策 9 的“接力运行”和下面的孤儿恢复），都投进 worker 队列。
- **API 进程被杀时的处理**：会话的运行锁是一个短租约（建议 30 秒），由运行中的协程每 10 秒续租。进程死掉后租约自己过期，不需要任何读取端在场。下一次有人访问这个会话时（发送消息或订阅事件），发送入口的 Lua 发现“状态是运行中但租约已过期”，就把那次运行标为失败、发 `run_failed` 事件；收件箱里若有未读消息，按决策 9 的接力规则投给 worker。这样不会出现“锁不释放、消息进了收件箱没人读”。
- **停止与恢复跨节点**：停止请求写一个按运行 id 的 Redis 停止标记，运行中的协程每秒检查一次（沿用 `task_exec.py:203` 终止监控的做法），所以请求落在哪个节点都生效。`direct` 运行的 ask_user 恢复不走 worker 队列：回答经发送入口到达某个 API 节点，该节点用 checkpoint 上的 `Command(resume=...)` 在本进程继续。
- **不沿用 worker 的启动清理**：那段逻辑按 `linsight:task:owner:{svid}` 和节点心跳判活（`linsight/domain/utils.py:805-840`）。`direct` 运行不建 `linsight_session_version` 记录（见决策 7），所以不会被它扫到。
- **何时该重新考虑**：`direct` 运行里代码执行等重操作挤占 API 进程的事件循环，影响其他接口的延迟。那时把“会调用代码执行器的 `direct` 运行”改投 worker。

### 决策 4：事件通道用 Redis Stream，客户端用可续传的 SSE

- **备选**：
  - A. 每个会话一个 Redis Stream（`XADD` 带 `MAXLEN`）。客户端用一条 SSE 订阅，游标是 Stream 的条目 id，放在 `Last-Event-ID`。
  - B. 沿用今天任务模式的 Redis List + 广播弹出（`task_message_broadcast.py`）。它是弹出式消费，事件被一个连接取走后其他连接要靠广播才能拿到，断线重连不能从指定位置补读。
  - C. 统一到 WebSocket。双向，但插话走普通 POST 就够了；WebSocket 在客户的网关和 WAF 上更容易被拦。
- **选定**：A
- **原因**：AC-31（断线后补全）和“两个标签页一致”（spec §3）都需要“从某个位置重读”，Stream 原生支持，List 不支持。`MAXLEN` 同时解决 `linsight/AGENTS.md` 记录的“事件速率高时撑爆 Redis 内存”。SSE 是日常对话今天已在用的通道。
- **Stream 只保存进行中的那次运行，不是历史库**：
  - 逐字的 `text`、`thinking` 事件先在服务端按 50 毫秒合并再写入，减少条目数。
  - 每次运行另有一份“当前累计状态”存在 Redis（已输出的文字、计划、文件列表），落库投影器按节流把它写库。
  - 客户端打开会话时先用现有的历史接口读已落库的内容，再从“当前运行的起点”订阅 Stream。
  - 如果客户端带来的游标早于 Stream 现存的最早条目（被 `MAXLEN` 裁掉了），服务端先发一个 `resync` 事件，内容是那份累计状态，客户端用它整体替换本地的当前运行，再继续接收增量。AC-31 由“历史接口 + `resync` + 增量”三者共同满足。
  - 运行结束后 Stream 保留 1 小时供晚到的重连使用，之后过期；此后一律读落库内容。
- **何时该重新考虑**：K8 核实后发现有客户的 Redis 低于 5.0。那时退回 B，并用“序号 + 列表区间读取”自己实现游标。

### 决策 5：插话用自研收件箱，不用 async subagents

- **备选**：
  - A. 每个会话一个 Redis 收件箱。一个 `before_model` 中间件在每次模型调用前取出全部消息，作为 `HumanMessage` 注入。
  - B. 中断重启：收到插话就取消当前运行，带着新消息重新开始。实现简单，但会打断正在执行的一步（违反 AC-15），长工具调用的结果作废。
  - C. deepagents async subagents：主 agent 把活派给后台子 agent，自己保持可对话。
- **选定**：A
- **原因**：
  - A 的机制已验证：注入的消息排在上一步工具结果之后，进入会话状态；最后一次模型调用期间到达的消息留在收件箱不丢。【实测】S3
  - C 在不部署 Agent Server 时不可用：省略 `url` 会去导入 `langgraph_api`，没装就抛 `TypeError`；该包是 Elastic-2.0 许可证（K7），通知与唤醒只在官方 Agent Server 上可用，多项功能仍是 beta。【实测】S4
- **已知限制**：收件箱只在主图的模型调用之间被读取。主 agent 正在等一个长工具调用或一个子代理返回时，插话要等它返回才被读到。这符合 AC-15 的字面要求，但用户感受到的延迟取决于那一步的时长。
- **何时该重新考虑**：用户反馈“等一步做完”太久，需要真正的并行。那时评估 async subagents，前提是解决 K7 的许可证问题和多部署一个服务的交付成本。

### 决策 6：改计划由模型执行，并修正计划条目的对齐算法

- **备选**：
  - A. 用户插话后，模型自己调用 `write_todos` 改写计划。同时把 `_diff_todos` 改成两趟匹配。
  - B. 后端提供“改计划”接口，直接改写图状态里的 `todos`。结果确定，但模型不知道计划变了，要另外通知它；spec 也已排除界面直接编辑。
- **选定**：A
- **原因**：计划和执行由同一个模型掌握，不会出现“状态改了、模型还按旧计划做”。
- **必须同时修的既有缺陷**：`_diff_todos` 把“精确匹配”和“按位置匹配”放在同一趟循环里。在中间插入一条时，新条目按位置占用下一条的 id，其后未改动的条目全部换 id，违反 AC-09。改写、追加、删除三种情况是对齐的。改法是先对全部条目做精确匹配，再对剩余条目按位置匹配。【实测】S3b
- **改写前的文字与已取消的条目（AC-10、AC-11）**：今天 `_diff_todos` 的改写分支让数据库行的 `task_data` 跟随新文案，旧文案被覆盖（`stream_event_mapper.py:366-371`）。改为在 `task_data` 这个已有的 JSON 字段里增加 `previous_name`，只保留最近一次改写前的文字；`plan` 事件同时带上它。被模型从计划里去掉的条目，今天已经落成 `TERMINATED` 状态并保留行（同文件的 `terminated_events`），界面把它显示为“已取消”。两者都不需要改表结构。
- **提示词改动**：现有提示词要求“只翻转 status，不改写已有文案”（`agent_factory.py:208`、`:243`）。要改成“只有用户要求时才改写文案”。
- **真实模型的表现**：【实测】S3c（T009，2026-11-18，114，deepagents 0.6.12）。deepseek-v4.1-flash 与 qwen3.8-max 各跑 5 次，10 次都在读到插话后的下一次模型调用里用 `write_todos` 把第 3 条改成做 PPT，前两条的 task id 都没变。这个结果有四个限制。① 114 的工作台只配了 2 个模型，计划里的“3 个模型”没有做到。② 插话都发生在计划刚写出、还没开始执行的时候，没有测执行到一半的插话。③ 脚本的系统提示词明确写了“用户要求调整计划时调用 `write_todos`，只改用户要求改的条目”，现行深度研究提示词写的是“只翻转 status，不改写已有文案”（`agent_factory.py:243`），P2 必须改这句，改完要重测。④ qwen3.8-max 有 1 次第一版计划的三条文字全是空字符串，第二版才有文字；这次按位置对齐，结果正确，但空文字计划本身是模型输出缺陷，P2 要在事件映射处暴露出来。若以后某个模型的成功率低，按根 `AGENTS.md` §7 的“surface model misbehaviour, don't fall back”原则处理：把现象暴露出来，不加静默兜底。
- **何时该重新考虑**：多个主力模型都不能稳定改写计划。那时转向 B。

### 决策 7：会话线程从“每轮一个”改成“每个会话一个”

- **今天**：`thread_id = session_version_id`，每提交一轮深度研究就新建一个版本、一个线程；新一轮靠 `_seed_workspace_from_previous` 把上一轮的文件拷进新工作区。直接回答没有线程，每轮从 `ChatMessage` 取最近 10 条重建历史。【读码】`task_exec.py:1564`、`chat_service.py` 的 `get_chat_history`
- **备选**：
  - A. `thread_id = 会话 id`，工作区是 `workspace/{会话 id}/`。`planned` 运行仍然建一条 `linsight_session_version` 记录作为运行身份；`direct` 运行不建，它的运行 id 是一个 UUID，记在会话的 Redis 状态和回答行的 `extra` 里。
  - B. 保持每轮一个线程，轮与轮之间拷贝文件、拼接历史摘要。
- **选定**：A
- **原因**：AC-04 和 AC-26 要求同一会话里先后的运行互相可见，不分回答方式。A 让这一点成为线程的自然结果；B 需要在两种方式之间再写一套上下文搬运。`planned` 运行保留 `linsight_session_version`，是为了 K2：开放 API 仍按它查任务。`direct` 运行不建这条记录，是为了不让 worker 的启动清理把它当成无主任务。
- **今天还有第二条路径**：`/workbench/continue` 在同一个 `session_version_id`、同一个线程上追加一轮（`worker.py:60-63`）。它证明了“同一线程跨多轮运行”在现有 checkpointer 上是可行的。【读码】
- **升级瞬间的在途任务**：升级前已经停在“等待用户回答”的任务，checkpoint 在旧线程（`thread_id = session_version_id`）上。恢复时按运行记录里保存的线程 id 定位；没有保存线程 id 的旧记录一律按 `session_version_id` 处理。它恢复并结束之后，该会话的下一次运行才进入会话线程。
- **工作区键变更的影响面**：`WorkspaceBackend(svid=...)`、预览与下载接口、`seed_workspace_from_previous(src_svid, dst_svid)` 今天都按 `svid` 寻址（`task_exec.py:1288-1318`）。要做三件事：把 `WorkspaceBackend` 的参数从 `svid` 泛化成工作区前缀；把拷贝函数泛化成“前缀到前缀”；`final_result/{svid}/` 交付快照保持按运行存放不变，开放 API 的文件接口继续读它。这是 P1 里工作量最大的一项。
- **两个档位在同一线程上交替运行**：`planned` 档的状态里有 `todos` 通道，`direct` 档没挂 `TodoListMiddleware`。用同一个 checkpointer 在一个线程上依次跑 planned → direct → planned，三次都正常完成，后一次运行的模型能看到前面运行的全部消息。【实测】S6。上一次 `planned` 运行留下的 `todos` 在下一次 `planned` 运行开始时是否需要清空，属于产品行为，按“每次运行一份新计划”处理，由事件映射器按运行重建。
- **K6 带来的问题与处理**：checkpoint 7 天过期。运行开始时如果线程没有 checkpoint（过期的会话，或统一之前创建的会话），就按今天直接回答的方式从 `ChatMessage` 重建历史，并用泛化后的工作区拷贝函数把最近一个版本的工作区接过来。这同时满足 AC-40。
- **何时该重新考虑**：长会话的 checkpoint 体积失控。目前的依据是 `DeepAgentState` 用 `DeltaChannel` 存消息，105 上实测 15 个根 checkpoint 共 0.1 MB（`linsight/AGENTS.md`），但那是单轮数据；跨多轮的增长【未验证】。

### 决策 8：不统一落库结构，只统一事件

- **备选**：
  - A. 事件通道统一；落库继续各用各的：`direct` 运行把回答和过程写进 `ChatMessage`（今天日常对话的格式），`planned` 运行写 `linsight_execute_task` 和 `linsight_session_version`（今天任务模式的格式）。由两个“落库投影器”消费同一个事件流。
  - B. 新建统一的运行事件表，两种方式都写它，旧表停用。
- **选定**：A
- **原因**：AC-40 要求旧会话原样可看；K2 要求开放 API 的查询不变；K4 说明新增一张高频写的表在 DM8 上有风险。A 不需要数据迁移，回滚只是切回旧通道。
- **代价**：两种方式的历史回看仍然走两套读取接口。这是有意保留的重复。
- **何时该重新考虑**：出现第三种回答方式，或需要跨两种方式统一检索过程记录。

### 决策 9：一个“发送消息”入口，由服务端原子地决定是开始运行还是进收件箱

- **备选**：
  - A. 客户端永远调用同一个发送接口。服务端用一段 Redis Lua 脚本读取会话的运行状态，原子地走四个分支之一：
    - **空闲** → 占用运行锁，开始新运行，返回“已开始”。
    - **运行中且租约有效** → 消息进收件箱，返回“已排队”。
    - **等待用户回答** → 把消息当作对问题的回答，恢复那次运行，返回“已开始”（spec §3 第 4 条）。
    - **运行中但租约已过期** → 按决策 3 标记失败，然后按“空闲”处理。
  - 运行结束时用另一段 Lua 原子地“把状态改回空闲并检查收件箱”。收件箱非空时开始一次**接力运行**：档位、工具、知识库取收件箱里第一条消息携带的设置（每条消息都带着发送时的开关状态，AC-01）；接力运行统一投进 worker 队列，不管上一次运行在哪里执行。
  - B. 客户端自己判断当前是否在运行，分别调用“发送”和“插话”两个接口。
- **选定**：A
- **原因**：AC-17 和 spec §3 第一条要求“消息要么被本次运行读取，要么触发新运行”。B 在运行恰好结束的瞬间会丢消息或同时起两次运行。A 把判断放在同一个原子操作里。运行锁沿用现有的 `linsight:run_lock:{id}` 思路（`task_exec.py:80`），键改按会话，并从 4 小时固定 TTL 改成决策 3 的短租约。
- **何时该重新考虑**：无。这是正确性要求。

### 决策 10：文件在写出时发事件，工作区按需创建

- **备选**：
  - A. `WorkspaceBackend` 在写入 `output/` 成功后发一个 `file` 事件；代码执行器把产物同步到工作区后同样发事件。`direct` 档的工作区和本地缓存目录在第一次文件操作时才创建。
  - B. 沿用今天的做法：运行结束时扫描目录，一次性登记（`utils.py:518` 的 `get_final_result_file`）。
- **选定**：A，并保留 B 作为运行结束时的对账。
- **原因**：AC-24 要求文件写完 5 秒内可见。按需创建是为了 K1：不涉及文件的问答不付出建目录、同步工作区的时间。
- **与 F016 的关系**：F016 把直接回答的生成文件登记在回答行的 `files` 字段。本设计在运行结束时继续写这个字段，所以历史消息的展示和审计下载接口不变；实时可见由 `file` 事件提供。
- **何时该重新考虑**：无。

### 决策 12：附件不在首次模型调用之前同步解析

- **今天**：直接回答在调用模型之前同步解析全部附件（`_process_agent_files`，`chat_service.py:1717`），把文本内联进提示词。114 日志里带附件的请求，准备阶段中位数 9.91 秒、p90 95.70 秒，而不带附件的是 0.16 秒。模型自身的首 token 两者相同（约 1.3 秒）。【实测】S5
- **证据的局限**：37 个带附件的样本里有 36 个来自 2026-10-26 同一天，很可能是一批集中测试，文件类型和并发情况不代表日常使用。“解析发生在模型调用之前且是同步的”由代码确认；“中位数约 10 秒”这个量级只说明方向，不能当作基线。
- **备选**：
  - A. 附件进工作区的 `uploads/`，解析在上传时就开始（深度研究已有 `upload-file` 与 `file-parsing-status` 两个接口）。运行开始时不等解析：agent 用 `read_file` 按需读取；解析还没完成的文件，读取时等待并发出“正在读取附件”的事件。
  - B. 保持同步解析，只在解析期间发一个进度事件。实现最小，首字符时间不变，只是用户知道在等什么。
- **选定**：A，分两步落地：P1 先做 B（事件通道一建好就能发进度），P3 做 A。
- **原因**：这是直接回答里唯一一段量级远大于模型首 token 的等待。A 同时消除两种回答方式在文件处理上的重复（日常内联文本，深度研究用工作区）。
- **代价**：模型要多一次工具调用才能看到附件内容，短文档的总耗时可能变长。小文件（建议以字符数为界）仍可内联。阈值【未验证】。
- **何时该重新考虑**：按日常使用的附件重新测量后，同步解析的中位数在 1 秒以内。那时只保留 B。

### 决策 11：前端用一个事件模型和一个 store，叶子组件复用

- **备选**：
  - A. 新建一个按会话组织的运行 store（Zustand，client 的 Recoil 已冻结不加新状态），由一条 SSE 喂数据。现有叶子组件（`PinnedTaskPanel`、`ExecutionTimeline`、`ClarifyCard`、`WorkspacePanel`、`ToolCallDisplay`）改为读新 store。去掉 `linsight_task_handoff` 和任务 WebSocket。
  - B. 保留两套状态，在上层加适配。改动小，但“运行中可发送”要同时改两套守卫，两个标签页一致也要做两遍。
- **选定**：A，按界面切换，不按状态镜像：会话页整体改读新 store，同一时间只有新 store 持有会话页的运行进度；`/linsight/:id` 独立页继续用 Recoil 和旧 WebSocket，只做历史回看。`client/AGENTS.md:21` 禁止在 Recoil 与 Zustand 之间镜像同一状态，这个切法不产生镜像。
- **新增依赖**：client 目前没有 `zustand`，需要加入（MIT 许可证）。
- **原因**：今天消息在 `useAiChat` 的 `useState` 里，任务进度在 Recoil `linsightMapState` 里，由 SSE 和 WebSocket 两条通道分别写入。【读码】`hooks/useAiChat.ts`、`hooks/Websocket/index.tsx`。AC-12、AC-13、AC-14 的状态要跨这两套才能算出来。
- **何时该重新考虑**：第一步完成后发现旧组件的数据形状无法由新事件完整表达。

---

### 决策 13：统一运行时默认开启，不做灰度，不提供管理界面开关（用户决定，2026-11-19）

- **备选**：
  - A. 开关默认关闭，运维按租户逐个打开（原方案，§4.6 的“P1 用一个配置开关按租户切换新旧通道”）。
  - B. 默认开启。存量用户（含开源版）升级后自动走新链路，不需要任何手动操作；管理界面不加开关。
- **选定**：B。
- **实现**：`unified_runtime_enabled` 的缺省值改为开启。没有工作台配置记录、记录里没有这个键、值不是布尔、读取配置失败，都按开启处理。只有记录里显式存了 JSON `false` 才走旧通道。管理端保存工作台配置时，原记录没有这个键就不写入这个键，原记录有显式值就原样保留。
- **前端怎么知道**：`GET /api/v1/workstation/config` 用 `exclude_unset` 输出，记录里没有这个键时原本不会带出这个字段，前端的 `=== true` 判断就落到旧协议。所以该接口显式写入解析后的值（`config.py`，回归 `test_config_knowledge_permission.py`）。
- **保留显式 `false` 的原因**：它是不经界面的应急回退手段（直接改 `tenant_workstation_config` / `config` 表里 `workstation` 记录的 JSON）。它不是灰度入口，产品上不对外说明。
- **由此带来的后果**：
  - 待定事项里以“开关关闭时行为不变”为前提的结论不再是用户默认看到的行为，旧通道只在显式回退时运行。
  - 仍用旧协议的客户端（桌面端、未升级的前端静态资源、直接调旧接口的集成方）升级后端后默认对上新链路，待定事项 3、4 描述的情形会直接出现在这些客户端上。
  - 旧通道的代码在默认配置下不再被执行。是否删除旧通道与显式回退，见 §8。
- **何时该重新考虑**：出现必须按租户回退的线上问题，且改库不可接受时。
- **2026-11-20 更新（用户决定）**：开关 `unified_runtime_enabled` 已整体删除，上面“实现”“前端怎么知道”“保留显式 `false` 的原因”三条不再适用。现在没有不改代码的回退手段。配置里残留的这个键被忽略，下次保存工作台配置时消失；存了 `false` 的租户升级后直接走新链路（回归：`test_removed_runtime_switch_key.py`）。登录态请求全部进 `run_send.unified_send`，分流条件只剩 `session_subject is None`。删除与保留的范围见 §8 第一条。

### 决策 14：开放 API 的日常对话也走统一运行时，按 AC-39 保持契约（用户决定，2026-11-20）

- **目标**：开放 API 的日常对话（`POST /api/v2/workstation/chat/completions`，不带 `run_mode=task`）不再使用旧的日常 agent 循环 `_agent_stream_chat_completion`。验收以 AC-39 为准：请求格式、响应格式和状态含义不变。
- **直观做法**：让开放 API 和登录态一样调用 `unified_send`，再在两头修补差异。
- **实际做法**：开放 API 调用 `unified_send` 时带上 `session_subject`。发送入口按下面七条处理这类请求。
  1. **不能协商新协议**：即使请求带了协商头，也按旧帧格式应答。开放 API 没有订阅事件的入口。
  2. **会话归属按主体**：新会话用 `session_subject.stamp` 打上主体；已有会话用 `get_subject_session` 校验，不匹配返回 HTTP 404，与旧循环一致。附件和生成文件用主体的 `storage_partition`。这个分区写进 `bisheng:run:direct:{cid}`，接力运行和崩溃后补写回答行时读回。
  3. **消息只开新运行**：派发脚本增加“独占提交”。会话正在运行或等待回答时，独占提交返回 `busy`，消息不进收件箱，也不当作回答。会话里有未读消息时，独占提交照常启动它们的接力运行，自己仍返回 `busy`。发送入口每 0.5 秒重试一次，最多等 60 秒，超时返回新错误码 12048（`ConversationBusyError`）。顺序调用的客户端在上一轮刚结束时发下一条，也是靠这条等待拿到自己的回答。
  4. **无人值守**：运行上下文的 `unattended=True` 让会话模型带上 `api_meta.channel=open_api_v2`。agent 因此不挂 `ask_user`，也不挂收件箱中间件，提示词改为“不提问，写明所做假设”。这与开放 API 深度研究（F073）的规则相同。
  5. **部门名额在响应开始前占用**：请求先取执行租约。被拒时只回一帧 12045 错误，不建会话、不写任何行。拿到的租约交给运行，由运行续期并在结束时释放（`execution_lease_id`）。没有启动运行的路径由请求自己释放。
  6. **不挂技能、不用长期记忆**：与旧循环相同，`skills=[]`，不传 `memory_register`。
  7. **错误码沿用统一运行时**（用户决定）：运行失败时 error 帧的信封字段不变，`status_code` 按模型错误分类给出，例如 11090/11091。`data` 多出 `error_code`、`detail`、`reference_id`。
- **接受的差异**（用户决定，与网页端一致）：历史从 checkpoint 读，不再取最近 10 条；最大迭代次数用深度研究的配置；附件内联上限是单文件 4000 字、总计 15000 字；工具结束帧里的输出截到 8000 字（落库的回答行保留完整输出）；会出现 `read_attachments`、`ls` 等新的工具帧；客户端断开时回答记为“已停止”，不是错误；标题在发送时生成；部门名额被拒时不再留下问题行；视频封面的 `question/update` 帧不再发出。帧的格式和字段名不变，只是内容不同。
- **同时补上的两处回归**（对网页端同样生效，用户决定）：直接回答链路没有使用管理员配置的工作台系统提示词，也没有记日常对话的应用遥测。现在 `direct_run.workbench_system_prompt` 读取工作台配置的 `systemPrompt`，替换 `{cur_date}`，把旧的“逐字复制来源 id”引用规则换成编号规则，再以“管理员设定的回答要求”一节接在平台规则之后，冲突时以平台规则为准。运行结束（完成或失败）时记 `APPLICATION_ALIVE` / `APPLICATION_PROCESS` 两条遥测。
- **代价**：同一会话里开放 API 的请求要串行，旧循环允许并行。会话被一个长时间运行的深度研究占着时，开放 API 的请求 60 秒后失败。
- **何时该重新考虑**：开放 API 需要插话、提问或订阅事件时，给开放 API 单独设计运行协议，不再走旧帧格式。

## 4. 系统现状与目标形态

### 4.1 今天的数据流

**直接回答**：`POST /api/v1/workstation/chat/completions` → `stream_chat_completion`（`chat_service.py:2872`）→ `_agent_initialize_chat`（配置、会话、附件转正、建模型）→ `_prepare_tools`（逐个初始化）→ 有工具时 `create_react_agent` + `astream_events`，没有工具时直接调用模型流式输出（`chat_service.py:2364-2395`、`:2613`） → 同一个 HTTP 响应里的 SSE → 结束时 `build_answer_row` 写 `ChatMessage`。

**深度研究**：同一个入口带 `task_mode=true` → `_task_mode_stream_completion` 建会话版本 → 服务端 `submit_task_turn` 入队（`task_submit_service.py:109-114`）→ SSE 发 `linsight_task_handoff` → Linsight worker `process_one_item` → `create_linsight_agent` + `astream` → `StreamEventMapper` → Redis List → WebSocket `task-message-stream` → 前端 Recoil。

### 4.2 目标数据流

```
发送消息 ──▶ 发送入口（决策 9：原子判断）
              ├─ 有运行在进行 ──▶ 收件箱（Redis List）──▶ 收件箱中间件在下次模型调用前注入
              └─ 没有运行 ──▶ 建运行记录（linsight_session_version）
                              ├─ direct 档 ──▶ API 进程内后台协程
                              └─ planned 档 ──▶ Linsight worker 队列
                                   │
                    统一内核工厂（决策 1）+ 会话线程（决策 7）
                                   │
                    StreamEventMapper ──▶ 事件流（Redis Stream，决策 4）
                                   │                    │
                         落库投影器（决策 8）      SSE（可续传）──▶ 前端运行 store（决策 11）
```

### 4.3 对外可见的契约（目标）

| 契约 | 形式 | 说明 |
|---|---|---|
| 发送消息 | `POST /api/v1/workstation/chat/completions`（沿用） | 请求体不变。响应分两种：新客户端带协商头时返回 JSON `{run_id, disposition: "started"｜"queued"｜"blocked", message_id}`；不带协商头时保持今天的流式响应（服务端替它订阅事件流并转成旧格式）。 |
| 订阅事件 | `GET /api/v1/workstation/conversations/{id}/events`（新增，SSE） | 支持 `Last-Event-ID` 续传。按会话归属校验权限。 |
| 回答提问 | 统一链路：发送入口（会话处于等待回答时，下一条消息即回答）。旧通道沿用 `/api/v1/linsight/workbench/user-input` | 两种档位共用。 |
| 排队位置 | `GET /api/v1/workstation/conversations/{id}/queue-position`（新增，AC-36） | 本人可查。返回 `{run_id, position}`；会话没有排队中的深度研究时 `position` 为 null。`position` 与旧接口 `/linsight/workbench/queue-status` 的 `index` 同义（从 1 起）。 |
| 停止 | `POST /api/v1/workstation/conversations/{id}/stop`（新增）。旧通道沿用 `/api/v1/linsight/workbench/terminate-execute` | 两种档位共用。服务端按会话当前持有者停止，不读请求体里的 `run_id`。 |
| 文件下载地址 | `GET /api/v1/workstation/conversations/{id}/files/{file_id}/url`（新增） | 只接受本会话工作区登记过的文件 id，不接受调用方给的对象键；本人或审计可取。 |
| 协议选择 | 无 | 开关已删除（决策 13 的 2026-11-20 更新）。会话页总是带 `X-BS-Run-Protocol: 2`。不带该头的请求仍由统一发送入口按旧帧格式应答，桌面端在用；client 前端已没有不带该头的发送（§8 第四轮）。开放 API 的日常对话也经过统一发送入口，总是按旧帧格式应答（决策 14）。 |
| 开放 API | `/api/v2/workstation/*` | 请求、响应格式和状态含义不变（AC-39）。新增一种失败：会话 60 秒内没有空闲，返回 12048（决策 14）。 |

事件的统一外形：`{id, run_id, seq, type, data, ts}`。`type` 的取值：

| type | 含义 | 今天的对应物 |
|---|---|---|
| `run_started` / `run_finished` / `run_failed` / `run_stopped` | 运行生命周期 | `final_result`、`error_message`、`task_terminated`；日常的 `final` |
| `queued` | 排队位置（AC-36） | `QueueCard` 的数据 |
| `text` / `thinking` | 回答文字与思考 | `agent_answer`、`agent_thinking` |
| `tool_call` | 工具调用的开始与结果 | `agent_tool_call`、`task_execute_step` |
| `plan` | 计划条目的新增、改写、状态变化、取消 | `task_generate`、`task_start`、`task_end` |
| `steer_accepted` / `steer_read` | 插话已入收件箱 / 已被读取（AC-13、AC-14） | 无 |
| `ask_user` / `ask_user_answered` | 提问与回答 | `user_input`、`user_input_completed` |
| `file` | 一个交付文件可用（AC-24） | 无（今天只在结束时给出） |

关键事件的 `data` 字段：

| type | data |
|---|---|
| `plan` | `{items: [{id, content, previous_content?, status}]}`，`status` 取 `pending` / `in_progress` / `completed` / `cancelled`。每次发完整的计划，不发差量 |
| `steer_accepted` / `steer_read` | `{message_id}` |
| `ask_user` | `{call_id, questions: [{question, options[]}]}`（沿用今天 `user_input` 的结构） |
| `file` | `{file_id, name, path, size, source}` |
| `queued` | `{position}` |
| `run_failed` | `{code, reason, detail, reference_id}`（沿用深度研究现有的报错卡结构） |
| `resync` | `{text, thinking, plan, files, pending_question?, ended, status, unread_messages}`。不含工具调用，也不含收件箱状态（§5 #27） |

发送接口的协商头是 `X-BS-Run-Protocol: 2`。错误码：“已排队”是成功响应里的 `disposition`，失败沿用深度研究已有的错误码。唯一新增的是 12048（`ConversationBusyError`，决策 14），只有开放 API 的日常对话会返回它。

运行相关的 Redis 键（同一会话的键都带 hash tag `{会话 id}`，K8）：

| 键 | 类型 | 内容 | 过期 | 定义处 |
|---|---|---|---|---|
| `bisheng:run:state:{cid}` | Hash | 会话的运行状态：status、run_id、profile、lease_until | 7 天，每次写入续期 | `run_lease.py` |
| `bisheng:run:stop:{run_id}` | String | 停止请求 | 1 小时 | `run_lease.py` |
| `bisheng:run:inbox:{cid}` | List | 收件箱：运行期间发来的消息 | 7 天 | `run_dispatch.py` |
| `bisheng:run:pending:{cid}` | Hash | 尚未被读取的消息 | 7 天 | `run_dispatch.py` |
| `bisheng:run:pending_index` | ZSet | 有待处理消息的会话索引，供巡检恢复过期运行 | 不过期，条目随处理移除 | `run_dispatch.py` |
| `bisheng:run:events:{cid}` | Stream | 事件流，`MAXLEN` 2000 | 运行中 24 小时；停在提问上 7 天加 1 小时；结束后 1 小时 | `run_event_stream.py` |
| `bisheng:run:snapshot:{cid}` | Hash | 当前运行的快照，供 `resync` | 与事件流相同 | `run_event_stream.py` |
| `bisheng:run:steer:{cid}` | Hash | 插话消息 id 到问题行 id 的绑定，及已读标记 | 7 天 | `run_message_persist.py` |
| `bisheng:run:relay_read:{cid}` | Hash | 接力运行要标记为已读的消息 | 7 天 | `run_message_persist.py` |
| `bisheng:run:direct:{cid}` | Hash | 最近一次 direct 运行的落库所需信息与 `answer_saved` 标记 | 7 天 | `run_message_persist.py` |
| `bisheng:run:memory_turn:{run_id}` | String | 运行的记忆回合 id，供恢复时使用 | 7 天 | `direct_run_turn.py` |


### 4.4 没有单独决策的 AC 由谁承接

| AC | 承接方式 | 证据等级 |
|---|---|---|
| AC-06 | 开关显示沿用前端按 `linsight_task_mode` 权限判断；发送入口在服务端对 `task_mode=true` 再校验一次同一权限 | 已核实（T008）：工作台入口与 `/linsight/workbench/*` 都没有校验。`workstation/api/endpoints/chat.py:98` 只有登录依赖；`chat_service.py:2929` 到 `task_submit_service.py:36` 只查项目和邀请码；`linsight.py:184`、`:294`、`:368`、`:436` 只有 `get_login_user`。只有开放 API 代用户调用时校验（`open_api/.../task_mode_service.py:145`，调用 `auth.py:891` 的 `assert_effective_web_menu_contains`）。发送入口实现（T030 一组）要新加这次校验，并补“无权限用户发 `task_mode=true` 被拒绝”的测试 |
| AC-22 | `planned` 运行等待回答时协程结束、租约释放（今天的 park-and-release）；`direct` 运行等待回答时同样结束协程。部门并发沿用 `DepartmentFlowService.ensure_lease`，只在运行中持有 | 【读码】`task_exec.py:1927` |
| AC-23 | 开放 API 的无人值守运行不挂 `ask_user`，也不挂收件箱中间件 | 【读码】`unattended_run.py:20` |
| AC-27 | 交付文件写在主桶 `workspace/` 下，主桶没有生命周期规则；下载链接按需签名，不保存长期链接 | 【读码】F016 的转正逻辑 |
| AC-28 | 工作区文件的预览与下载接口按会话归属校验；审计下载沿用 F016 的接口 | 【读码】`resolve_attachment_url` |
| AC-32 | `run_failed` 事件的 `reason`、`reference_id` | 沿用 61f9ef5e99 的报错卡 |
| AC-36 | 会话页在进行中的深度研究回合还没有任何输出时，每 5 秒调 `GET /conversations/{id}/queue-position`，位置大于 0 时显示排队卡片（“排队中，第 N 位”）。取消排队用输入框的停止按钮，卡片不另放取消按钮 | 位置的算法复用 `LinsightQueue.index`，与旧的 `/linsight/workbench/queue-status` 一致 |
| AC-38 | 发送入口在消息进收件箱之前执行输入检测（`evaluate_workbench_user_text`），所以插话与普通消息走同一检测；输出检测放在事件映射之后、写入事件流之前 | 【读码】`chat_service.py:1890` |
| AC-43 | 知识库检索工具由统一工厂装配，权限范围由工具实例闭包携带，与今天两条链路相同 | 【读码】`linsight/AGENTS.md` Prompt / tool wiring |
| AC-49 | 把日常对话的读图组件（`VisionToolBindWrapper`、`KbImageStage`）接入统一工厂 | 已核实（T008）：部分能。日常对话的读图不是外层循环，是“callable model 包装器 + `view_image` 工具”（`common/image_view/vision_llm.py:465`、`chat_service.py:2376`），每个请求新建 `ImageRegistry`（`chat_service.py:1951`），看图模型是独立配置 `workbench.image_read_model`（`image_view/loop.py:398`）。深度研究靠主模型的 `visual` 标志（`agent_factory.py:1957`），`read_file` 直接返回图片块（`workspace_backend.py:460`），由 `binary_content_guard.py:245`、`:319` 两个中间件拦截与挪位。接入方式：把包装器改写成一个 `awrap_model_call` 中间件并自带 `view_image` 工具，`ImageRegistry`、`annotate`、`fetch`、`tool`、`loop.py` 的判定函数直接复用。四个阻碍点见 §5 坑 12 |
| AC-50 | 记忆的存储不动，只把两处接线合并为一处 | 【读码】 |

### 4.5 关键模块职责（目标）

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `linsight/domain/services/agent_factory.py` | 统一内核工厂，按档位组装中间件、工具、提示词 | 不知道运行在哪个进程里 |
| 收件箱中间件（新增，放 `linsight/domain/services/`） | 模型调用前取出收件箱消息并注入，发 `steer_read` | 不判断消息内容，不改计划 |
| 运行调度（新增，放 `workstation/domain/services/`） | 决策 9 的原子判断；按档位把运行交给后台协程或 worker 队列 | 不执行 agent |
| `linsight/domain/services/stream_event_mapper.py` | 把图的输出映射成 §4.3 的事件；修正后的 `_diff_todos` | 不落库 |
| 事件流读写（新增） | `XADD` / `XREAD`、游标、`MAXLEN`、心跳 | 不解释事件含义 |
| 落库投影器（两个） | 把事件按档位写进 `ChatMessage` 或 `linsight_*` 表，按节流落库 | 不向客户端推送 |
| `linsight/domain/services/workspace_backend.py` | 工作区读写；写入 `output/` 后发 `file` 事件 | 不决定哪些文件算交付物以外的规则 |
| 前端运行 store（新增） | 按会话保存消息、计划、文件、运行状态；由 SSE 驱动 | 不直接发 HTTP（C7） |

### 4.6 分期

| 期 | 内容 | 用户可见的变化 |
|---|---|---|
| P0 | 依赖升级（决策 2）+ 全量回归；`_diff_todos` 两趟匹配 | 无 |
| P1 | 统一内核工厂、会话线程、事件流与 SSE、发送入口。旧 WebSocket 与旧流式响应由事件流转译，前端不改 | 无（行为等价） |
| P2 | 收件箱中间件、`steer_*` 事件、提示词改动；前端运行 store 与运行中可发送 | 可以插话、改计划 |
| P3 | 直接回答挂工作区与技能、`file` 事件、首字符提速项 | 直接回答能力补齐，文件实时出现 |
| P4 | 前端删除 handoff 与任务 WebSocket；`/linsight/:id` 降为只读 | 界面按原型统一 |

每一期都能独立上线和回滚。P1 用一个配置开关按租户切换新旧通道。**（2026-11-19 起由决策 13 取代：默认开启，不按租户灰度。）****（2026-11-20：开关已删除，不能再靠配置回滚。）**

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `_diff_todos` 在计划中间插入一条时会让后面的条目全部换 id | 用户改计划后，任务面板把状态显示在错误的行上 | `stream_event_mapper.py:_diff_todos`，改两趟匹配；回归用 `s3b_diff_todos_alignment.py` |
| 2 | deepagents 0.7 默认不挂 `TodoListMiddleware`，而且要从 `langchain.agents.middleware` 导入，不是从 `deepagents` | 升级后计划面板整体消失，没有任何报错 | `agent_factory.py` 的 `planned` 档 |
| 3 | 0.7 的 `read_file` 输出从 `     1\t内容` 变成 `@@ lines 1-2 of 2 @@\n内容`，空目录 `ls` 从 `[]` 变成 `No files found` | 解析这些输出的代码和提示词示例静默失效 | P0 回归时全仓搜索这两种格式的依赖 |
| 4 | 省略 `url` 的 `AsyncSubAgent` 不会报“未配置”，而是在第一次调用时抛 `TypeError: 'NoneType' object is not callable` | 误以为是自己代码的空指针 | 本期不使用；见决策 5 |
| 5 | 收件箱只在主图的模型调用之间被读取，子代理运行期间不读 | 误以为插话丢了；或者在子代理的中间件里再加一个收件箱，导致同一条消息被两处消费 | 收件箱中间件只挂主图；前端用“已发送，排队处理中”如实显示 |
| 6 | 人机交互工具必须是 `async def`，否则 `interrupt()` 不生效 | `direct` 档新挂的 `ask_user` 不暂停，模型把问题当正文输出后结束 | 复用现有 `ask_user`（`agent_factory.py:1003`），不新写 |
| 7 | checkpointer 从不裁剪，摘要中间件不删消息 | 改成每会话一个线程后，以为长会话会被自动压缩 | 决策 7 的“何时重新考虑”；P1 要加 checkpoint 体积的观测 |
| 8 | worker 的启动清理把“没有 `linsight:task:owner:{svid}` 键的 IN_PROGRESS 记录”判为无主并标失败（`linsight/domain/utils.py:805-840`）。`linsight/AGENTS.md` 里“不检查归属”的说法已过时 | 如果 `direct` 运行也建 `linsight_session_version` 记录，任何一个 worker 重启都会把正在进行的直接回答标成失败 | 决策 7：`direct` 运行不建该记录；决策 3：用短租约判活 |
| 11 | 后端日志已经为每次模型调用记录 `BS_METRIC domain=model_invoke ... ttft_ms=`，每个请求有跟踪号 | 为了测首字符时间去给服务打点、重启，或者去伪造登录 | `scripts/spike_unified_runtime/s5_first_char_timing_from_logs.py` 直接读日志 |
| 9 | 直接回答今天每次模型调用都查一次 DSH 额度，深度研究每轮只查一次 | 统一后额度口径不一致（AC-37）；直接回答多轮工具调用时每轮多一次查询 | 统一为每次运行开始时查一次（`admit_round`） |
| 10 | 代码执行器的产物先写到本地 `file_dir`，再同步到 MinIO | `direct` 运行在 API 节点执行、恢复时落到另一个节点，本地文件不在 | 复用 `_sync_workspace_originals`；不依赖本地目录跨运行存在 |
| 12 | 日常对话的读图组件有四处与统一工厂不兼容：① 它为了补注入 `view_image` 调用，要先缓冲并静音模型输出（`vision_llm.py:338`、`:404`）；② `ImageRegistry` 与已看图片队列是进程内状态，不进 checkpoint；③ 深度研究的检索工具不登记 `⟦img#N⟧`；④ 它和 `ModelContentGuardMiddleware` 都会把图片挪到用户消息，视觉开关也是两套（独立看图模型与主模型 `visual`） | 直接把包装器套在工厂的模型外面：流式正文被缓冲，首字符变慢；等待回答后恢复或换节点时图片编号全部失效；同一张图被挪两次 | T059 改写为 `awrap_model_call` 中间件。图片编号与像素都不进图状态：编号在每次模型调用时从线程消息重建（同样的消息得到同样的编号），本进程没取过的像素重新取，所以运行换节点恢复后编号不变（`kb_image_middleware.py` 模块说明；2026-11-19 按代码更正，原文写的是“写进图状态”）。只保留一处挪位。挂载条件统一为“主模型 `visual` 为真，或配置了看图模型”。预计新增约 400 行与配套测试【估算，未实测】 |
| 13 | deepagents 0.7 新增 `delete` 文件工具。`WorkspaceBackend` 没有重写它，继承来的 `FilesystemBackend.delete` 删的是 worker 本机磁盘上的路径，不动对象存储 | 模型调用 `delete` 后 `ls` 仍能看到文件；路径写错时删到工作区以外 | `agent_factory._workspace_file_tools` 把文件工具限定为工作区实现的 6 个，主图和子代理都替换。`test_deepagents_07_compat.py::test_planned_graph_has_write_todos` 守护。统一工厂（T020）要沿用 |
| 14 | deepagents 0.7 不再追加英文基础提示词。原来“把英文基础提示词替换成中文”的中间件找不到替换目标，只打一条警告就放行 | 升级后深度研究悄悄丢掉中文基础要求（出错时先分析、不重复重试等） | 删掉该中间件，由 `base_prompt.with_base_prompt` 直接拼在主图系统提示词末尾，位置与原来相同。`test_base_prompt_zh.py` 用真实图断言模型恰好收到一次 |
| 15 | langchain 1.5 的摘要生成失败改为抛异常，并给摘要模型套了 3 次重试；1.3 是返回 `Error generating summary` 字符串。deepagents 0.7 的 `_offload_to_backend` 多了 `session_id` 参数，历史文件名从线程 id 改为生成的会话 id；`_intercept_large_tool_result` 少了 `runtime` 参数 | F087 的“摘要失败重试一次”失效：失败不再被识别，或一次失败最多打 6 次模型调用；工具结果卸载直接报 `TypeError` | `context_budget.py`：把摘要模型换回不带重试的原模型，重试仍由 BiSheng 的两次循环负责，异常与“too long to summarize”都算失败；两个签名按新版调整 |
| 16 | deepagents 0.7 遇到超窗时先裁剪尾部，裁剪后没有变短就直接抛 `ContextOverflowError`，不再重试一次 | 历史很短的子代理超窗时只调用 1 次模型就结束，测试剧本里多出来的回复被主图吃掉 | 行为可接受（子代理仍以“未完成”说明返回主任务）。`test_context_overflow_flow.py` 的子代理剧本补了 3 次读页，让压缩有内容可裁 |
| 17 | `create_linsight_agent` 按模型的 provider 名在进程内注册一个全局 profile（去掉框架自带的摘要中间件）。测试里不同文件的脚本化模型类同名时 provider 名相同 | 新测试先跑，之后别的文件直接调用 `create_deep_agent` 就报“assembled outside bisheng_summarization” ；单独跑能过，合起来才失败 | 每个用 `create_linsight_agent` 的测试模型都通过 `_get_ls_params` 给自己起独立的 `ls_provider` |
| 18 | 来源表中间件（`LinsightCitationSourceMiddleware`）在每次模型调用的消息列表末尾追加一条 user 角色消息，原来的挂载条件只看“有检索工具且启用编号”。F075 明确日常对话不注入来源表，旧日常对话从未有过 | `direct` 档共用工厂后每次模型调用都多一条最多 150 行的 user 消息；114 上模型把表头里的 `[Sn]` 当作用户的话向用户复述，前端只转换带数字的编号，`[Sn]` 原样显示 | `agent_factory.py`：来源表只在 `planned` 档挂载（主图与 researcher 相同）；`direct` 档用不提来源表的尾部提示 `_DIRECT_CITATION_TAIL_HANDLES_ZH`；表头、补编号提醒、尾部提示都不再出现字面 `[Sn]`。回归：`test_agent_factory_profiles.py::test_source_table_is_for_deep_research_only`。114 实测（2026-11-18，同一问题同一模型，各 1 次，天气题改动后 3 次）：回复正文引用数 6 → 5/6/3；写 HTML 的问题，文件内编号 201 → 122（39 个不同来源）。中间一版把 `direct` 档尾部提示写成“回答中”，同一问题的 HTML 里编号为 0：日常编号规则只说“回答中”，尾部提示是唯一要求在文件里写编号的地方，所以 `_DIRECT_CITATION_TAIL_HANDLES_ZH` 必须保留“写交付物正文”。对照实验（2026-11-19，114，两组代码只差是否在 `direct` 档挂来源表，每组天气题 5 次 qwen3.8-max、HTML 题 3 次 DeepSeek-flash）：天气题正文引用，有表 7/5/6/7/7，无表 6/8/5/7/5；HTML 题正文引用，有表 2/20/0，无表 8/14/8；HTML 文件内编号，有表 235/115/92，无表 287/220/158；派调研子代理的次数，有表 2/3，无表 1/3。没有观察到去掉来源表使引用减少，也没有观察到它使模型更常派子代理 |
| 19 | deepagents 0.7 拒绝同一轮里对同一路径的并行写操作（`Error: parallel file mutations to the same path are not allowed.`），只放行第 1 个。`LinsightToolLoopBreaker` 把这一批被拒的调用算作连续失败 | 模型一轮并行发 9 个 `edit_file` 改同一文件，8 个被拒，循环保护判定“连续 8 次失败”并中止运行，已写好的文件随失败的回复一起交付（114 会话 e9134062，run edcbf900） | `tool_loop_middleware.py:_trailing_tool_failure_run` 改为按轮计数：一条 AIMessage 的一批工具结果算一轮，整批都是错误才算该工具失败 1 次，批内有任何成功就结束连续失败。软提示与硬中止都用这个计数。两档共用。回归：`test_tool_loop_middleware.py::test_parallel_refusals_in_one_turn_are_not_a_failure_run` |
| 20 | 事件订阅如果用 `XREAD BLOCK`，每个打开的会话页（含停在提问上的会话）会长期占住共享异步 Redis 连接池的一条连接；池上限 100，超限直接抛错而不排队 | 单个 API 进程约 100 个同时在线的会话页后，该进程所有 Redis 调用开始失败，续租失败使正在回答的运行被判失败。决策 13 默认开启后每个日常对话都走订阅 | `run_event_stream.py:read`：`follow=True` 改为每 `FOLLOW_POLL_SECONDS`（0.1 秒）非阻塞读一次，等待期间不占连接。回归：`test_run_event_stream.py::test_follow_never_holds_a_connection_in_a_blocking_read`。代价：事件到达浏览器最多晚 0.1 秒。未做压测 |
| 21 | 深度研究的三条执行路径（新一轮、回答提问后的恢复、继续）里，原来只有新一轮会被停止打断；恢复与继续是裸的 `astream` 循环。同时看守协程一看到停止标记就退出，不再续租 | 用户回答澄清问题后再点停止，运行继续执行；30 秒后租约过期，下一条消息开出新运行，旧运行继续往新运行的事件流、线程、工作区里写，读走新运行的收件箱，结束时还向新运行的流写 `run_stopped` | `task_exec.py`：三条路径共用 `_run_until_terminated`（每 0.5 秒看一次终止标记，置位就取消流）与 `_stream_agent`。看守协程在停止后继续续租，直到运行写完终止事件并释放会话；只有租约丢失才提前退出。驱动锁按运行 id 比较后删除。租约丢失的运行不再读收件箱。回归：`test_planned_run_unified.py` 的 4 个 stop/lease 用例。后果：停止后的运行如果取消不掉，会话保持被占用，不会在 30 秒后自动放开 |
| 22 | 深度研究把本轮附件从 `workspace/{svid}` 合并进会话工作区时，目标已有同名对象就跳过 | 同一会话第二次上传改过内容的同名文件，agent 读到的是第一次的版本，没有任何报错。旧链路每轮是新工作区，不会这样 | `workspace_backend.copy_workspace_prefix(replace_older=True)`：源对象的 `last_modified` 晚于目标才替换，两个时间都来自对象存储，不依赖节点时钟；只有 `_merge_run_uploads` 传 `True`，接管上一版本文件的调用仍然从不覆盖。直接回答的附件路径直接写会话工作区，没有这个问题。回归：`test_workspace_prefix.py` 的 4 个用例。残留：agent 在后一次附件解析之后、合并之前写了同名 `uploads/` 文件时，附件被跳过 |
| 23 | planned 运行和接力运行在入队之前就用 4 小时的排队租约预占了会话。浏览器补发的 start-execute 不带 run_id | “预占成功到入队成功”之间任何一步失败，会话被一个不存在的运行占住 4 小时，期间发不了新消息 | 带 `run_id` 的 `submit_task_turn` 入队失败不再吞异常：版本标记失败，抛 11130，由 `_send` 与 worker 现有的 except 释放。`run_dispatch._release_reservation` 处理 `_enqueue`、`_handle_expired`、`_queue_position` 失败。释放用 `release` 而不是 finish 脚本，收件箱保留，下一条消息重新发起接力。回归：`test_run_dispatch.py`、`test_task_submit_service.py`、`test_unified_run_api.py` 各有用例 |
| 24 | 事件流和快照按会话建 key，不按 run。接手的运行写 `run_started` 会清空流 | 失去租约的 direct 运行无条件写终止事件，会让接手运行的订阅者提前结束；什么都不写，则无人接手时浏览器一直等，已生成的文字不落库 | `RunLeaseService.reclaim`：状态仍是 running 且 run_id 是自己时才重新取得租约，只用于收尾。成功则 `DirectRunner._end_lost` 写 `run_failed`（11091，`lease_expired`），部分回答连同工具和文件落成失败行。失败则什么都不写，缓冲文字也丢弃（`EventWriter.discard`）。残留：从租约失效到被发现最长约 10 秒，这期间旧运行仍可能往已被接手的流里写事件。`DirectRunProjector.aclose` 没有生产调用方，接上它会在进程被取消时写出两行 |
| 25 | planned 运行的 run_id 与会话版本的对应关系是：版本 id 等于 run_id，或 `api_meta["run_id"]` 等于 run_id。开放 API 与 `/workbench/*` 可以在运行停靠或排队期间给同一会话新增版本 | 按“会话最新版本”取记录时，回答提问会恢复错的运行，停止会终止别的入口的版本 | `run_send._enqueue_planned_resume` 与停止路径都用 `task_exec._find_run_record` 按 run_id 定位，找不到就报错。`submit_task_turn` 带 `run_id` 时在入队前把它写进 `api_meta`，排队中的运行也能找到 |
| 26 | 等待回答的状态保留 7 天，事件流和快照原先 24 小时过期。快照里有四样东西不在 checkpoint 中：待回答的问题、direct 停靠前的文字和文件、`ask_user_answered` 的 call_id、planned 的计划行 id | 停靠超过 24 小时后，重开页面没有提问卡片，direct 停靠前的文字永久丢失；订阅端在“无流且运行未结束”时每 50ms 空转 | 追加事件的 Lua 在快照有 `pending_question` 时用 `PARKED_TTL_SECONDS`（7 天加 1 小时），回答或终止后回到原 TTL，只影响停在提问上的运行。`follow_run_events` 的无流等待改为从 50ms 退避到 1 秒。残留：升级前已停靠的运行不会被延长；排队很久的 planned 运行首个事件最多晚 1 秒 |
| 27 | `run_finished` 与接力运行的 `run_started` 可能在同一渲染批次到达；`resync` 快照不含工具调用和收件箱状态 | 页面靠“看到运行结束”来冻结消息行时，旧行一直指向 live 运行，显示成空白加载气泡。重同步按快照重建会清掉已显示的工具行，排队标记不消失 | 前端 store 新增 `replacedRuns`，在运行被替换的四处保留旧运行的最后状态，页面据此冻结旧行。同一运行的 `resync` 保留本地工具行，thinking 只追加缺失的后缀。排队标记以历史行的 `extra.queued` 为准，在重同步后和运行结束后对账，只清不设。残留：断线期间错过的工具调用无法补回，要补需后端把工具调用写进快照 |
| 28 | 已结束运行的事件流会重放 1 小时，停止时退回的未读消息每次重进页面都会再到达；服务端已删除这些问题行 | 按“列表里是否还有该行”判断是否退回输入框时，只要历史重载先发生，文字就被丢弃 | 前端用 localStorage 记录本浏览器已退回过的消息 id（键 `bs:run:returnedHandled`，最多 200 个）。残留：文字进输入框后刷新仍会丢（输入框草稿不持久化）；换浏览器在 1 小时内打开会再收到一次；localStorage 不可用时刷新后会重复填入 |
| 29 | 后端没有“重新生成”语义：`isRegenerate` 无任何读取，每次请求都新插一条问题行 | 统一运行时下“重新生成”和失败卡片的“重试”如果仍走旧协议，会在运行 store 之外另开一条流，输入框看起来可用但按 Enter 无反应 | `useAiChat.regenerate` 在统一运行时下取原问题文字，走普通发送，效果是新增一条用户消息并开始新运行，不重新附带附件。是否需要真正的同级重新生成由产品决定（§8） |
| 30 | 前端每个文本增量都重建全部思考段和工具调用的事件对象并排序 | 长回答时 CPU 占用随事件数增长，下游所有工具行都重渲染 | `hooks/runAgentEvents.ts`：文本增量直接返回上次的事件数组；思考增量或工具帧只为变化的一项新建对象；缓存是以 store 对象为键的 WeakMap，不保留历史帧。未做 CPU 实测对比 |
| 31 | 深度研究的流式正文原来不经过句柄转换：直接回答在 `DirectTurn.rewrite` 里把 `[Sn]` 换成引用标记，深度研究的 `_UnifiedRun.emit` 把模型原文直接写进事件流 | 回答生成过程中用户看到 `[S1]` 原文，结束后换成存库的正式回答才变成角标。114 实测（2026-11-19，会话 `96757276…`）：句柄表有 S1–S5，17 个 `text` 事件里有 9 处 `[Sn]`、0 个标记 | 转换逻辑抽成 `text_handle_rewriter.TextHandleRewriter`，两种档位共用；`_UnifiedRun` 在 `_create_agent` 建好引用范围后 `bind_citation_scope`，逐字引用约定（scope 未启用）时不转换。回归 `test/linsight/test_text_handle_rewriter.py`；114 复测见 verification-final.md §7 |
| 32 | 中间件在 `model` 节点里自己调用的模型（`KbImageViewMiddleware._describe` 的看图模型），其 token 同样出现在 `stream_mode="messages"` 里，统一映射器按主图正文发成 `text` | 主模型不能读图、配了看图模型时，看图模型对图片的描述会作为回答显示给用户。langchain 1.5 的摘要调用自带 `nostream` 标签，不受影响；`vision_llm.py` 用 `callbacks: []` 自行避开 | 该调用加 `tags=[TAG_NOSTREAM]`。原理用最小脚本验证（节点内未打标签的 `ainvoke` 会进入 messages 流，打标签后不会）；114 未配看图模型，未在环境中复现。回归 `test_unified_citation_image_memory.py::test_image_reading_model_describes_pictures_for_a_text_model` |
| 33 | 深度研究提交时，`run_dispatch.submit` 算出的排队位置放在 `SubmitResult.events` 的 `queued` 事件里，但只有直接回答把 `initial_events` 写进事件流，深度研究这条路径从来没写；位置也只在提交时算一次 | 会话页收不到排队位置，排队中的回合看起来像卡住（AC-36 不成立） | 不靠事件：新增 `GET /conversations/{id}/queue-position`，按会话当前的运行记录找到版本，再用 `LinsightQueue.index` 现算；前端在回合没有输出时轮询。回归：`test_unified_queue_position.py`、`useRunQueuePosition.test.ts` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 发送、订阅、回答、停止（§4.3） | HTTP API | client 前端（桌面端内嵌的网页会话也经由它访问） |
| 旧流式响应、旧 WebSocket `task-message-stream` | HTTP / WS（P4 前保留） | 尚未升级的客户端 |
| `/api/v2/workstation/*` | 开放 API（日常对话自决策 14 起也由统一运行时执行） | 外部集成方 |
| 事件外形 `{id, run_id, seq, type, data, ts}` | 数据格式 | 前端运行 store、两个落库投影器 |
| 统一内核工厂 | 内部 Python 接口 | 工作台运行调度、开放 API 的 `submit_task_turn` |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| deepagents 0.7.x / langchain 1.5 / langgraph 1.2 | 第三方库 | 中间件钩子的执行顺序、`todos` 通道的结构变化会让映射器失效；升级只按 `--upgrade-package "pkg==ver"` 逐个做 |
| Redis（Stream、List、Lua） | 中间件 | K8：版本低于 5.0 不支持 Stream |
| `ChatMessage` 的消息 JSON 结构 `{msg, events}` 与 `files` 字段 | 隐式数据契约（F016、会话导出、审计） | 落库投影器必须保持这个结构 |
| `linsight_execute_task`、`linsight_session_version` | 表结构 | 开放 API 与历史回看都读它们 |
| MinIO 主桶 `workspace/` 与 `chat/` 前缀 | 对象存储 | 工作区真源；`file` 事件和 7 天后的下载（AC-27）都依赖它。对象不存在时 MinIO 抛异常而不是返回空 |
| 引用编号表 `linsight:cite_handles:<会话 id>` | Redis 键 | 两种档位共用，编号不能重置（AC-41） |
| F132 记忆的两处接线（`daily_memory.py`、`memory_turns.py`） | 内部接口 | 统一工厂后只保留一处，另一处的调用方要同步改 |
| DSH 额度（`chat_credits.admit_round`） | 内部接口 | 口径变化要与 DSH 的计费审计对齐 |

---

## 7. 测试与可观测

- **单元**：`_diff_todos` 的四种改写；收件箱中间件的注入顺序与不丢失；发送入口两段 Lua 的并发（同一会话并发发送 N 条，断言恰好一次运行、其余进收件箱）；事件流游标续读。
- **集成**：用脚本化模型跑完整的 `direct` 与 `planned` 运行，断言事件序列；同一会话先 `direct` 后 `planned`，断言后者读到前者的消息与文件。
- **回归**：P0 在升级前后对 `test/linsight/` 取同一选择集做差分，不看绝对失败数。
- **端到端**：按 SDD 流程在 design 确认后生成 `test-cases.md`，实现后跑 `/e2e-test`。多节点行为（AC-33）在两节点环境上验证，单机 compose 不算。
- **手动验证**（在 `src/backend/` 下执行；脚本不连接任何环境，不需要账号）：`.venv/bin/python scripts/spike_unified_runtime/s1_todo_and_tool_output.py`、`s3_inbox_middleware.py`、`s3b_diff_todos_alignment.py`；交互对照 `prototype/index.html`。
- **观测**：每次统一运行时的执行在结束时输出一行 `BS_METRIC domain=agent_run`（`linsight/domain/services/run_metrics.py`，T038）。字段：`profile`（direct / planned）、`status`（finished / failed / stopped / waiting / lease_lost / unknown）、`resume`、`prep_ms`（发送入口接受消息到第一次模型请求，含 `queue_ms`）、`queue_ms`（接受消息到执行开始）、`steer_wait_ms`（本次执行内插话从入箱到被读取的最长等待）、`steer_count`、`checkpoint_bytes`（线程最新 root checkpoint 的序列化字节数，不是线程在 Redis 的总占用）、`total_ms`。开关关闭的旧路径不输出这一行。

### 实现后的待定事项（Wave 1–4 留下，按是否需要产品决定分组）

需要用户决定的：

1. **`planned` 接力运行不能执行。** 用户在运行中发的消息在运行结束时仍未读，且要以深度研究档接力时，没有代码从收件箱消息创建 `linsight_session_version`。worker 现在写 `run_failed`（`relay_not_supported`）并丢弃未读消息。P2 的收件箱中间件会在运行中读走消息，这个分支只在“运行结束瞬间才到达的消息”上触发。
2. **用户停止的回答行标记。** 现在沿用今天的做法，写成错误行（`stream interrupted`）。是否给“用户停止”单独的标记。
3. **未改造前端的三种情形**（开关打开但前端仍用旧协议）：运行中再发消息只收到结束帧、没有回答；`direct` 运行遇到 ask_user 时旧帧里没有对应帧，用户看不到问题；敏感词拦截在新协议下仍返回旧 SSE。P4 前端切换后前两项不再出现。
4. **开关开启后，开放 API 或 `/workbench/start-execute` 在同一会话已有运行时再提交，会以“会话被占用”失败。** 今天两次运行互不影响。是否改为排队。
5. **旧终止接口不动会话租约。** 运行挂起时用旧接口终止，会话停在 waiting，之后的消息被当成回答。P2 的停止接入（T050）要同时调 `RunLeaseService.request_stop`。

6. **停止时收件箱里还有未读消息**：现在停止后会立刻启动一次接力运行处理它们。是否改为停止时丢弃或保留排队。
7. **运行中发的消息带附件或换了模型**：收件箱只带文字与设置快照，附件不被读取，接力运行沿用上一次 `direct` 运行的模型。是否在运行中禁用上传，或让收件箱带上这些字段。
8. **界面与原型的差异**（T049、T050）：提问卡片在输入框上方而不在气泡内；卡片保留“跳过”与关闭；等待回答时计划面板没有“等你回答后继续”；停止后的输入框占位文案与说明行未做；停止请求失败时没有提示。
9. **回答提问是否扣深度研究邀请额度**：开关打开时，回答会先过 `allowInviteSend()`。
10. **排队文案的英文与日文**（"Sent. Waiting to be processed" / 「送信しました。処理待ちです」）待确认。

11. **直接回答的文件直接存在会话工作区**（T055）：回答行的 `files` 指向 `workspace/{会话}/output/...`，不再复制一份。之后的运行覆盖同一路径时，旧回答下载到的是新内容。是否在运行结束时为每个回答保留一份副本。
12. **附件读不了时运行继续**（T057）：结束帧带 `failed`，模型输入写明哪些附件未能解析。P1 的行为是运行失败。
13. **运行结束时仍在解析的附件在后台继续解析**（T057）：用户停止后解析仍占用资源；好处是之后的运行能读到文件。
14. **附件内联阈值的默认值没有实测依据**（T057，决策 12）：单文件 4000 字符、总量 15000 字符，配置项 `linsight.direct_attachment_inline_chars`、`linsight.direct_attachment_inline_total_chars`。需在 114 实测后确定。
15. **开关开启时会话页的旧任务回合少了三个动作**（T061）：“重试”、排队卡片的“取消”、旧提问卡片。这三个动作走旧通道，该页已不建 WebSocket。是否用新通道重做“重试”。
16. **读图由模型自行决定**（T059）：统一运行时不再在问题需要看图时强制调用 `view_image`。真实模型是否会主动调用未验证。
17. ~~**`direct` 运行不写引用审计日志行**（`log_citation_audit`，T059）。是否补上。~~ 已实现：`run_projector_direct.py` 调 `direct_run_turn.log_citation_audit`，输出 `[daily-citation-audit]`（2026-11-19 在 114 日志中确认）。
18. **视觉模型的图片附件不进入工作区 `uploads/`**（T057）：之后的运行只能从对话历史看到它，不能用 `read_file` 读取。
19. **“查看代码和输出”对历史消息也显示**（T060）：开关开启后，历史里存有参数或结果的通用工具行都会出现这个展开。
20. **已结束的深度研究回合与直接回答用不同的组件渲染**（T061）：历史接口对 task 行不返回事件序列，回看仍走 `TaskTurnPanel`。

#### 待定事项的决定（2026-11-18，用户逐项确认）

下表的编号对应上面的第 1–20 条。“状态”列写明代码是否已按决定修改。

| 编号 | 决定 | 状态 |
|---|---|---|
| 1 | 以深度研究档接力：从收件箱消息创建新的 `linsight_session_version` 并排进 worker 队列，不再丢弃消息 | 已实现（Wave 5） |
| 2 | “用户停止”单独标记：回答行记录 stopped，界面显示“已停止”，不显示错误样式 | 已实现（Wave 5） |
| 3 | 前两种情形在前端切换后不再出现，不处理。敏感词拦截改为返回新协议的事件（未单独询问用户，按技术一致性处理） | 已实现（Wave 5） |
| 4 | 同一会话已有运行时，开放 API 与 `/workbench/start-execute` 的再次提交改为排队，不返回“会话被占用” | 已实现（Wave 5） |
| 5 | 旧终止接口同时调用 `RunLeaseService.request_stop`（缺陷修复，未单独询问用户） | 此前已实现（T050 的 `_request_unified_stop`）；本表原先的状态有误 |
| 6 | 停止后不启动接力运行；未读消息的文字退回输入框 | 已实现（Wave 5）。2026-11-19 起，是否已退回按本浏览器 localStorage 的记录判断（§5 #28） |
| 7 | 运行中禁用上传附件与切换模型 | 已实现（Wave 5） |
| 8 | 补三项：计划面板的“等你回答后继续”、停止后的输入框占位文案、停止请求失败的提示。提问卡片的位置与“跳过”按钮不改 | 已实现（Wave 5） |
| 9 | 回答提问不扣深度研究邀请额度，回答路径不经过 `allowInviteSend()` | 已实现（Wave 5） |
| 10 | 英文改为 "Sent — queued"；日文保留「送信しました。処理待ちです」 | 已修改 |
| 11 | 运行结束时为本次生成的文件保留一份副本，回答行指向副本 | 已实现（Wave 5） |
| 12 | 保留现在的行为：附件读不了时运行继续，界面提示失败的附件。界面验证时确认提示可见 | 无需改代码 |
| 13 | 保留现在的行为：运行结束后附件在后台继续解析 | 无需改代码 |
| 14 | 在 114 实测后确定阈值（未单独询问用户，本身就是测量事项） | 待实测 |
| 15 | 只用新通道重做“重试”；排队卡片的“取消”与旧提问卡片不补 | 已实现（Wave 5） |
| 16 | 保持由模型自行决定；在 114 用带图的知识库问题实测调用率，调用率低再恢复强制调用 | 待实测 |
| 17 | `direct` 运行补写引用审计日志行 | 已实现（Wave 5） |
| 18 | 视觉模型的图片附件也写入工作区 `uploads/`，写入在后台执行 | 已实现（Wave 5） |
| 19 | 保持现状：历史工具行也显示“查看代码和输出” | 无需改代码 |
| 20 | 保持现状：已结束的深度研究回合继续用 `TaskTurnPanel` 渲染（未单独询问用户；改动需要历史接口返回事件序列，不在本期范围） | 无需改代码 |

#### Wave 5 实现后新出现的待定事项与已知限制（2026-11-18）

需要用户决定的：

21. **持有会话的运行停在提问等待时，排队的开放 API 提交会一直等。** 用户不回答也不停止，排队的提交就不执行（第 4 条的排队实现）。是否给等待加超时。
22. **“重试”新增一条用户消息并开始新的运行**，不在原版本里续跑；使用输入框当前的模型、技能、工具与知识库，不重新附带原回合的附件。更早的失败回合也显示“重试”。
23. **工作区面板在两个回答先后写同一路径时列出两个同名条目**（各自的副本）。是否按工作区路径合并成一个。
24. **新增文案待确认**：`runComposer.uploadLocked`、`runComposer.modelLocked`、`runComposer.stopFailed` 的中文，以及本轮全部新增键的英文与日文，都是 agent 自拟。
25. **“等你回答后继续”替换了计划面板的标题**，没有按原型做成“计划 + 状态”两段，也没有做暂停行的橙色圆环（新增视觉样式需设计确认）。停止说明行只在有计划面板时出现。
26. **上传入口的禁用原因写在菜单行的描述里**，没有用 Tooltip。

技术上已知、尚未处理的：

- 接力运行的模型取会话最近一次深度研究版本的模型；多条未读消息合成一个版本，工具、技能、知识库取第一条消息的设置。
- 开关开启但前端仍用旧 SSE 时，关闭流触发的停止也把回答行写成 stopped。
- 回答行由另一个进程补写时（`_persist_from_snapshot`），不带文件、不做副本、不写引用审计日志行。
- 文件副本在终止事件之前做，对象存储慢时终止事件相应推迟。副本失败的文件保持指向工作区对象并写错误日志。
- 终止事件先于回答行落库，这之间点击文件卡片会得到 404，随后的历史重载会恢复。
- 视觉模型的图片附件被下载两次（一次进模型输入，一次写入工作区）。
- `resync` 不带失败的 `code`、`reason`、`detail`，此时失败行显示通用错误文案。运行快照在结束 1 小时后过期，过期后未读消息无法退回。
- 退回输入框只恢复文字，不恢复附件（运行中已禁用上传，列表应为空）。
- worker 的等待项扫描循环（每 30 秒）在开关关闭的租户上也运行，只对空集合做一次读取。
- Wave 5 的全部改动只经过脚本化模型、fakeredis 与内存对象存储的测试，界面没有在浏览器里运行过。

#### 114 首次真实运行后的修正（2026-11-18）

- **直接回答在真实环境必然失败，已修复**（f6f2976952）：延迟准备工作区的代码给 `ToolExecutor` 包装对象赋值 `executor` 失败。测试用的替身工具没有这层包装。回归测试改用真实的 `ToolExecutor`。
- **失败回答的展示**（e27fe50950）：直接回答的未分类失败改发 `chat_unknown`，卡片显示“回复生成失败”；历史接口不再把详情换成占位符 "Request failed."，详情脱敏后返回；故障标识可复制并说明用途。
- **用户决定（2026-11-18）**：上一条的文案与详情对开关关闭时的旧日常对话同样生效，保持，不限定到新链路。这是“开关关闭时行为不变”的一处已确认的例外。
- 未处理：不带 `[SQL: …]` 包装的裸 SQL 语句脱敏规则识别不了；直接回答的未知失败仍带错误码 11091；限流与超时类失败不显示故障标识和详情。

Wave 1–4 留下、技术上已知、尚未处理的：

- 真实模型在新规划提示词下的插话改写成功率未重测（需 114 与真实模型）。
- `direct` 运行选中技能时，每次执行都重新拷贝全部候选技能包，没有跨执行的快照。
- 知识库图片供代码沙箱使用的通道（`kb_image_stage`）没有接入 `direct` 运行。
- 完整工具结果只给落库投影器；旧 SSE 帧里的工具结果仍截断到 8000 字符。
- 附件读取等待只包住 backend 的异步方法；代码执行器的同步 `run()` 在延迟准备包装下直接抛错（统一运行时只走异步路径）。
- 前端判断“已落库的 task 行是否就是当前运行”要多请求一次 `session-version-list`，因为事件里没有 `run_id` 与 `session_version_id` 的对应关系。
- 重新打开会话时，`/linsight/:id` 独立页的只读状态本次没有再验证。
- Wave 3、Wave 4 的全部能力只经过脚本化模型与内存替身的单元测试，没有连接真实的 MySQL、Redis、MinIO、代码执行器与模型，界面没有在浏览器里运行过。**在 T039、T051、T062 的人工步骤完成之前，开关不能对真实用户打开。**（2026-11-19：决策 13 把缺省值改为开启，所以这句话的含义变为“这些人工步骤完成之前，本分支不能合入发版线”。114 已有真实运行，见 §5 第 18、19 条与 verification-final.md。）

### 尚未完成的验证

| 项 | 影响什么 | 状态 |
|---|---|---|
| 直接回答首字符时间的分段计时 | AC-34、AC-35 的阈值；决策 3、决策 10、决策 12 | 已做（S5，基于 114 的历史日志，48 个请求）。两处不足：没有“不勾选任何工具”的样本；带附件的样本集中在一天。统一内核自身增加多少准备时间要等 P1 有了可运行的实现再测 |
| 真实模型收到插话后改写计划的成功率 | 决策 6 | 已做（S3c，T009）。2 个模型各 5 次，10 次成功。未覆盖：第 3 个模型、执行到一半的插话、现行深度研究提示词。P2 改完提示词后重测 |
| langchain 1.5 下 `test/linsight/` 全量回归 | 决策 2 | 已做（T004/T005）。逐用例对比无新增失败。本地没有中间件，依赖数据库与对象存储的用例在升级前后都失败，这部分要靠 CI 的集成测试覆盖 |
| 私有化客户的最低 Redis 版本 | 决策 4 | 已做（T001）。随产品交付的是 7.0.4，仓库内没有低于 5.0 的受支持环境，决策 4 不变。客户自带 Redis 的版本仓库里查不到，靠 P1 上线说明约束 |
| 跨多轮的 checkpoint 体积增长 | 决策 7 | 未做 |
| 服务端是否已校验深度研究权限；两套读图实现能否合并 | AC-06、AC-49 | 已做（T008）。权限：工作台两个入口都没校验，需新加。读图：部分能合并，结论与阻碍点见 §4.4 的 AC-49 行与 §5 坑 12 |

---

## 8. 后续改进 / 不打算做的事

- **旧通道删除（2026-11-20 已做一轮）**：
  - 已删：开关及其读取点；`_task_mode_stream_completion` 与入队失败后依赖浏览器 start-execute 的分支；worker 的 `_legacy_session_run_lock` 与旧线程的工作区接管 `_seed_workspace_from_previous`；前端会话页的交接帧处理、附件解析轮询、旧的停止分支。
  - 第三轮（2026-11-20）：开放 API 的日常对话迁到统一运行时（决策 14），旧的日常 agent 循环 `_agent_stream_chat_completion` 及只被它使用的函数随之删除。
  - 仍可达而保留：不带协商头的 SSE 兼容应答；`/linsight/workbench/*` 接口与任务 WebSocket（`/linsight/:id` 历史页跟进本人进行中的任务时在用）；`task_exec.py` 里未在会话线程上的分支（升级前建的记录续跑时走）。
  - 第二轮（2026-11-20，用户确认）：`/linsight/new` 不再能提交。进入这个地址时，前端新建对话、打开「深度研究」并跳到 `/c/new`。`/linsight/:id` 只读，没有输入框。前端删除了提交流水线（`useLinsightSubmit`、`submissionState`、`TaskModeInput`、`TaskModeChatInput` 及只被它们使用的组件）。分享页上的深度研究回合只显示快照：不开任务 WebSocket，不轮询排队，不提供回答提问和停止。后端的 `/linsight/workbench/submit` 与 `start-execute` 不再有 client 前端调用，接口本身保留，因为桌面端是否在用没有核实。
  - 第四轮（2026-11-21，用户决定订阅页 AI 助手改用运行协议 2）：核实发现订阅页 AI 助手的两个调用方都传文章 id，实际走的是频道文章问答 `/api/v1/channel/chat/completions`（独立服务，不在 F004 范围）；面板里用 `useAiChat` 的“工作台模式”和“文件问答模式”都到不了（知识库文件问答由 `FileAiDock` 直接用 `useFileChat`）。删掉这两个模式后，client 前端已没有不带协商头的发送，`useAiChat` 的旧发送路径（`beginStream`、`useAiChatSSE`、`getSSEUrl`）随之删除，`useAiChat` 从 1281 行减到约 730 行。同时补了一个改动前就有的缺口：会话页删除一个正在回答的会话时，前端先请求停止该会话的运行，否则运行会继续往已删除的会话里写回答。
  - 未追完：桌面端宿主的“运行中会话”列表只在发送请求进行期间包含该会话；请求返回后运行仍在继续时，宿主看不到它。这是运行协议 2 上线后就有的缺口，不是第四轮引入的。
  - 未追完：`agent_factory.py` 里按有无收件箱区分的图片中间件条件与两套计划措辞；`copy_workspace_prefix` 的 `only_if_empty` 默认路径。
  - worker 的运行作用域依赖 Redis。旧锁在 Redis 不可用时放行的行为已不存在。

- **重新生成**（用户决定，2026-11-21）：就是把原问题再发一次（§5 #29），不做“同一问题下生成另一个回答”。

- **真正的并行与后台任务**：等 async subagents 稳定、且许可证与部署成本可接受时再评估（决策 5）。
- **统一落库结构**：见决策 8 的触发条件。
- **界面直接编辑计划**：等“发消息改计划”的使用数据出来后再决定。
- **子代理运行期间读取插话**：见坑 5，本期不做。
- **等待用户回答的保留期限**：7 天，与 checkpoint 的 TTL 相同（spec §3 最后一条）。到期后按决策 7 的无 checkpoint 路径重建。要更长的保留期就得先改 checkpoint 的 TTL 和 Redis 容量规划。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-17 | 初版（未实施） | spec 确认后进入设计 |
| 2026-11-18 | 回填首字符计时（S5）：K1 写入基线；新增决策 12（附件解析前移） | 用户要求先补计时 |
| 2026-11-17 | 独立评审后修订：决策 9 增加“等待回答”和“租约过期”分支与接力运行；决策 3 改用短租约判活；决策 7 明确 `direct` 运行不建 `linsight_session_version`、在途任务与工作区键的处理；决策 4 增加 `resync`；补充事件字段与 AC 承接表；更正 3 处与代码不符的陈述 | `/sdd-review design` |
| 2026-11-18 | §5 增 #18：`direct` 档不再注入来源表；提示词里去掉字面 `[Sn]` | 114 实测会话 9d256fd6 的回复向用户提到 `[Sn]` |
| 2026-11-19 | §5 #18 补 114 实测数字；增 #19（并行写同一文件被循环保护中止，未处理） | 用同一问题重放对照会话 |
| 2026-11-19 | §5 #19 已处理：连续失败按轮计数 | 用户确认修复 |
| 2026-11-19 | §5 #18 补有表/无表对照实验数字 | 用户要求两种配置各跑几次 |
| 2026-11-19 | 新增决策 13：统一运行时默认开启，不做灰度，不提供管理界面开关 | 用户决定 |
| 2026-11-19 | 代码审查（`/sdd-code-review`）后的修正：配置接口总是返回开关值；事件订阅改轮询（§5 #20）；接力失败事件脱敏；§4.3 补停止、文件下载地址、协议选择三行；更正坑 12 与待定事项 17 | 四路审查结论 NEEDS_FIX |
| 2026-11-19 | §5 增 #21（恢复/继续路径可被停止打断）、#22（同名附件以较新的为准） | 代码审查的两个 HIGH |
| 2026-11-19 | §5 增 #23–#30（排队租约释放、租约失效收尾、按 run_id 定位版本、停靠运行的流 TTL、运行替换与重同步、退回消息去重、重新生成、事件列表增量）；§4.3 补 `resync` 字段与 Redis 键表；新增 upgrade.md | 修复代码审查剩余的 9 个 MEDIUM |
| 2026-11-19 | §5 增 #31（深度研究流式正文的 `[Sn]` 未转换）、#32（看图模型输出进入回答流）；verification-final.md 增 §7 | 用户要求把独立特性 F005 的两点补进 F004 |
| 2026-11-20 | 删除开关 `unified_runtime_enabled` 与只有它能到达的旧通道代码；决策 13、§4.3、§4.6、§8 同步 | 用户决定 |
| 2026-11-20 | §8 记录第二轮删除：`/linsight/new` 改为跳到会话页并打开深度研究；分享页的深度研究回合改为只读快照 | 用户确认决策 11 的落地方式 |
| 2026-11-20 | 新增决策 14：开放 API 日常对话迁到统一运行时；补回工作台系统提示词与日常对话遥测；新增错误码 12048；§4.3、§6.1、§8 同步 | 用户要求删掉开放 API 的旧 agent 逻辑，验收以 AC-39 为准 |
| 2026-11-21 | 用户决定：订阅页 AI 助手改用运行协议 2（落点是删掉到不了的工作台模式与前端旧发送路径）、实现 AC-36 排队位置、重新生成保持“再发一次”；§4.3 增排队位置接口，§4.4 增 AC-36，§5 增 #33，§8 记第四轮 | 用户决定 |
