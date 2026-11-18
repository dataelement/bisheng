# Design: 日常对话与深度研究统一（F004-unified-agent-runtime）

> **本文档定位 — Why this How。** 需求见 [spec.md](./spec.md)。本文写在实现之前，所以 §4 分成“今天的代码”和“目标形态”两部分；实现后覆盖更新，只保留当天状态。
>
> **证据标注**：每条理由后面标【实测】【读码】或【未验证】。【实测】指 `src/backend/scripts/spike_unified_runtime/README.md` 里的脚本结果；【读码】指在 `origin/feat/3.1.0-beta2`（49ecbd659f）上读到的代码；【未验证】是假设，实现前必须先验证。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（尚未创建） · [prototype/index.html](./prototype/index.html)
**版本**: v3.1.0-beta2
**最后更新**: 2026-11-17（初版，未实施）

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
| 发送消息 | `POST /api/v1/workstation/chat/completions`（沿用） | 请求体不变。响应分两种：新客户端带协商头时返回 JSON `{run_id, disposition: "started"｜"queued", message_id}`；不带协商头时保持今天的流式响应（服务端替它订阅事件流并转成旧格式）。 |
| 订阅事件 | `GET /api/v1/workstation/conversations/{id}/events`（新增，SSE） | 支持 `Last-Event-ID` 续传。按会话归属校验权限。 |
| 回答提问 | 沿用 `/api/v1/linsight/workbench/user-input` | 两种档位共用。 |
| 停止 | 沿用 `/api/v1/linsight/workbench/terminate-execute` | 两种档位共用，改按运行 id 生效。 |
| 开放 API | `/api/v2/workstation/*` | 不变。 |

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
| `resync` | `{text, thinking, plan, files, pending_question?}` |

发送接口的协商头是 `X-BS-Run-Protocol: 2`。错误码：本设计不新增业务错误码；“已排队”是成功响应里的 `disposition`，失败沿用深度研究已有的错误码。实现中如发现确需新增，按 release-contract 的规则先核对占用再登记。

### 4.4 没有单独决策的 AC 由谁承接

| AC | 承接方式 | 证据等级 |
|---|---|---|
| AC-06 | 开关显示沿用前端按 `linsight_task_mode` 权限判断；发送入口在服务端对 `task_mode=true` 再校验一次同一权限 | 已核实（T008）：工作台入口与 `/linsight/workbench/*` 都没有校验。`workstation/api/endpoints/chat.py:98` 只有登录依赖；`chat_service.py:2929` 到 `task_submit_service.py:36` 只查项目和邀请码；`linsight.py:184`、`:294`、`:368`、`:436` 只有 `get_login_user`。只有开放 API 代用户调用时校验（`open_api/.../task_mode_service.py:145`，调用 `auth.py:891` 的 `assert_effective_web_menu_contains`）。发送入口实现（T030 一组）要新加这次校验，并补“无权限用户发 `task_mode=true` 被拒绝”的测试 |
| AC-22 | `planned` 运行等待回答时协程结束、租约释放（今天的 park-and-release）；`direct` 运行等待回答时同样结束协程。部门并发沿用 `DepartmentFlowService.ensure_lease`，只在运行中持有 | 【读码】`task_exec.py:1927` |
| AC-23 | 开放 API 的无人值守运行不挂 `ask_user`，也不挂收件箱中间件 | 【读码】`unattended_run.py:20` |
| AC-27 | 交付文件写在主桶 `workspace/` 下，主桶没有生命周期规则；下载链接按需签名，不保存长期链接 | 【读码】F016 的转正逻辑 |
| AC-28 | 工作区文件的预览与下载接口按会话归属校验；审计下载沿用 F016 的接口 | 【读码】`resolve_attachment_url` |
| AC-32 | `run_failed` 事件的 `reason`、`reference_id` | 沿用 61f9ef5e99 的报错卡 |
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

每一期都能独立上线和回滚。P1 用一个配置开关按租户切换新旧通道。

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
| 12 | 日常对话的读图组件有四处与统一工厂不兼容：① 它为了补注入 `view_image` 调用，要先缓冲并静音模型输出（`vision_llm.py:338`、`:404`）；② `ImageRegistry` 与已看图片队列是进程内状态，不进 checkpoint；③ 深度研究的检索工具不登记 `⟦img#N⟧`；④ 它和 `ModelContentGuardMiddleware` 都会把图片挪到用户消息，视觉开关也是两套（独立看图模型与主模型 `visual`） | 直接把包装器套在工厂的模型外面：流式正文被缓冲，首字符变慢；等待回答后恢复或换节点时图片编号全部失效；同一张图被挪两次 | T059 改写为 `awrap_model_call` 中间件。`ImageRegistry` 的内容按运行写进图状态。只保留一处挪位。挂载条件统一为“主模型 `visual` 为真，或配置了看图模型”。预计新增约 400 行与配套测试【估算，未实测】 |
| 13 | deepagents 0.7 新增 `delete` 文件工具。`WorkspaceBackend` 没有重写它，继承来的 `FilesystemBackend.delete` 删的是 worker 本机磁盘上的路径，不动对象存储 | 模型调用 `delete` 后 `ls` 仍能看到文件；路径写错时删到工作区以外 | `agent_factory._workspace_file_tools` 把文件工具限定为工作区实现的 6 个，主图和子代理都替换。`test_deepagents_07_compat.py::test_planned_graph_has_write_todos` 守护。统一工厂（T020）要沿用 |
| 14 | deepagents 0.7 不再追加英文基础提示词。原来“把英文基础提示词替换成中文”的中间件找不到替换目标，只打一条警告就放行 | 升级后深度研究悄悄丢掉中文基础要求（出错时先分析、不重复重试等） | 删掉该中间件，由 `base_prompt.with_base_prompt` 直接拼在主图系统提示词末尾，位置与原来相同。`test_base_prompt_zh.py` 用真实图断言模型恰好收到一次 |
| 15 | langchain 1.5 的摘要生成失败改为抛异常，并给摘要模型套了 3 次重试；1.3 是返回 `Error generating summary` 字符串。deepagents 0.7 的 `_offload_to_backend` 多了 `session_id` 参数，历史文件名从线程 id 改为生成的会话 id；`_intercept_large_tool_result` 少了 `runtime` 参数 | F087 的“摘要失败重试一次”失效：失败不再被识别，或一次失败最多打 6 次模型调用；工具结果卸载直接报 `TypeError` | `context_budget.py`：把摘要模型换回不带重试的原模型，重试仍由 BiSheng 的两次循环负责，异常与“too long to summarize”都算失败；两个签名按新版调整 |
| 16 | deepagents 0.7 遇到超窗时先裁剪尾部，裁剪后没有变短就直接抛 `ContextOverflowError`，不再重试一次 | 历史很短的子代理超窗时只调用 1 次模型就结束，测试剧本里多出来的回复被主图吃掉 | 行为可接受（子代理仍以“未完成”说明返回主任务）。`test_context_overflow_flow.py` 的子代理剧本补了 3 次读页，让压缩有内容可裁 |
| 17 | `create_linsight_agent` 按模型的 provider 名在进程内注册一个全局 profile（去掉框架自带的摘要中间件）。测试里不同文件的脚本化模型类同名时 provider 名相同 | 新测试先跑，之后别的文件直接调用 `create_deep_agent` 就报“assembled outside bisheng_summarization” ；单独跑能过，合起来才失败 | 每个用 `create_linsight_agent` 的测试模型都通过 `_get_ls_params` 给自己起独立的 `ls_provider` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 发送、订阅、回答、停止（§4.3） | HTTP API | client 前端（桌面端内嵌的网页会话也经由它访问） |
| 旧流式响应、旧 WebSocket `task-message-stream` | HTTP / WS（P4 前保留） | 尚未升级的客户端 |
| `/api/v2/workstation/*` | 开放 API | 外部集成方 |
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
17. **`direct` 运行不写引用审计日志行**（`log_citation_audit`，T059）。是否补上。
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
| 6 | 停止后不启动接力运行；未读消息的文字退回输入框 | 已实现（Wave 5） |
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
- Wave 3、Wave 4 的全部能力只经过脚本化模型与内存替身的单元测试，没有连接真实的 MySQL、Redis、MinIO、代码执行器与模型，界面没有在浏览器里运行过。**在 T039、T051、T062 的人工步骤完成之前，开关不能对真实用户打开。**

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
