# Design: 长期记忆

> **本文档定位 — 现状快照（Why this How）**。`spec.md` 回答做什么，本文回答为什么这么实现，`tasks.md` 是流水账。实现变化时覆盖更新本文，只留今天的状态。

**关联**: [spec.md](./spec.md) · [discovery.md](./discovery.md) · [tasks.md](./tasks.md)（待写）
**版本**: v3.0.0（开发基线）
**最后更新**: 2026-11-13（第 5 稿）
**状态**: 已实现（2026-11-13，无人值守开发，分支 `feat/v3.0.0/132-long-term-memory`）。§4.5 是实现后的现状；§4.1–§4.3 的数据流、表与职责与实现一致，Wave 0 的修订见 §9 末 R1–R9。以下为当初的设计说明：设计草稿第 4 稿，已按三轮 design 审查修订，待用户确认。第三轮审查的结论是：原 6 个高严重度问题已解决或由待验证项覆盖，新发现的问题已在本稿处理，本稿未再做全量复审。§10 列出的待验证项要在编码最前面用小实验确认，结论写回本文。本功能尚未编码：§4.1–§4.3 是**目标形态**，§4.4 是**已取证的接入点现状**（基线 `feat/3.0.0@741662475b`）。实现后按实际覆盖更新。

---

## 1. 目标与非目标

- **目标**：新增后端领域模块 `memory`，为日常模式、深度研究、助手、工作流四类场景提供同一套"按用户隔离的长期记忆"：统一的写入、读取、启用判定和数据生命周期。四类场景只在各自的接入点调用它，不各自实现记忆。
- **非目标**：
  - 不做通用的 agent 记忆框架，不向外暴露 LangGraph `BaseStore` 接口。
  - 不改造四类场景各自的会话与消息存储结构。
  - 不改动"历史聊天记录"（会话内上文）的行为。
  - spec「本次明确排除」的全部条目。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md` C1–C8，不在此重抄。下表是本功能特有的约束。

| # | 约束 | 证据 | 对设计的影响 |
|---|---|---|---|
| K1 | 同一个用户的记忆会被多种进程同时读写：API 副本、Celery worker（工作流在这里执行）、深度研究 worker（自研 Redis 队列，不是 Celery） | C8；`worker/workflow/tasks.py:62`；`linsight/worker.py` | 任何记忆状态都不放本地盘或进程内存；深度研究的接入不能依赖 Celery 信号 |
| K2 | 整理用的大模型由客户自行接入，多数不是最强的一档 | 调研结构版 §3.3 | 整理范围由程序给定；长度、密钥类内容等硬规则由代码判定 |
| K3 | 常驻记忆每轮都读 | spec AC-51 | 读取路径不做向量检索，不整行重写大 JSON（DM8 上会耗尽 undo，见 `src/backend/AGENTS.md`） |
| K4 | 租户自动过滤不等于"当前租户"：对普通用户注入的是**可见租户的 IN 列表**，对全局超管**整个跳过**，并且只拦截 SELECT | `core/database/tenant_filter.py:219`、`:221-222`、`:231-243` | 记忆的读和写都必须显式按 `tenant_id = 当前租户 AND user_id = 本人` 过滤，不能依赖自动过滤。这是对 C3 的一处显式例外，见决策 9 |
| K5 | 新增 `config.yaml` 顶层键会让旧镜像拒绝启动 | `src/backend/AGENTS.md` 配置契约 | 部署级参数放数据库里的运行期配置 |
| K6 | 主体类型只在 API 入口可知。工作流节点、消息落库回调、深度研究 worker、Beat 任务手里只有一个整型 `user_id`；用户表没有主体类型列；免登录链接的配置里也带一个 `user_id` | `open_api/domain/services/identity_service.py:67-81`；`workflow/nodes/base.py:39`；`public_endpoints/domain/services/guest_link.py:35,72` | 不能在下游凭 `user_id` 判定"是不是一个确定的自然人"。资格必须在入口判定并持久化，下游只查结果，查不到即不工作。并且登录用户与开放 API 的调用会汇到同一批 Service 函数（如 `stream_chat_completion`），所以登记必须做在 **endpoint 层**，不能做在共用的 Service 里 |
| K7 | 各场景会把工具调用的入参和返回落库，而且落点不止一处：日常模式写进 `chatmessage.message` 的 `events`；助手有两条路径，一条由 `run()` 的返回值构造 tool_call、tool_result 行，另一条由 LangChain 回调直接插入 `category=tool` 的行并经 WebSocket 下发；深度研究把步骤的 `params` 与 `output` 写进 `linsight_execute_task.history`，持分享链接的非本人可以原样读到 | `workstation/domain/services/chat_service.py:2311-2319`、`:2343-2344`、`:2557-2560`；`common/chat/client.py:391-405`；`api/v1/callback.py:472-495`、`:523-545`、`:572-585`；`linsight/domain/services/stream_event_mapper.py:631`、`:662`、`:700-712`；`linsight/api/endpoints/linsight.py:579-615` | 记忆工具的入参与返回如果照常落库，管理员翻会话就能看到记忆原文，违反 AC-09。记忆工具的事件必须在落库前脱敏 |
| K8 | 助手的 agent 在一个 WebSocket 连接内只构建一次，提示词和工具列表在连接期内固定 | `common/chat/client.py:235-256` | 常驻记忆和开关状态不能在构建时确定，必须每轮在调用时处理 |
| K9 | 深度研究的轮次落在日常会话的同一个 `chat_id` 里；任务行在开始时插入空占位、完成时原地更新；**追问轮不插新行，而是原地更新同一个任务行，追问的问题也不落消息表** | `linsight/domain/services/workbench_impl.py:345-355`、`:402`；`linsight/domain/utils.py:975-992`、`:1007-1019`；`linsight/api/endpoints/linsight.py:327-378` | 整理登记按 `chat_id` 一行；深度研究不能用消息 id 当水位，要以"任务轮"为整理单位 |
| K14 | 助手与工作流的 client 建连 URL 不带 `chat_id`，`chat_id` 由连接内的首条消息送达；处理这些消息的 `ChatClient`、`WorkflowClient` 在 `common/` 下，同时服务登录态、免登录链接和开放 API 的 WebSocket。登录态路径上工作流实际执行的图也来自客户端消息 | `client/src/pages/appChat/useChatHelpers.ts:52`；`common/chat/client.py:361-372`；`common/chat/clients/workflow_client.py:97-98`、`:171-179`；`public_endpoints/api/endpoints/assistant.py:45`；`open_endpoints/api/endpoints/assistant.py:160` | 登记不能在 endpoint 里凭 URL 完成；应用开关不能信任客户端送来的图 |
| K10 | 助手和工作流的会话不刷新 `message_session.update_time` | 只有工作台与深度研究调 `touch_session` | 安静期用记忆自己的登记判定 |
| K11 | 平台没有硬删除账号的路径；工作流删除是硬删 `flow` 行；助手没有版本表 | 全仓无删除用户实现；`database/models/flow.py:211`；全仓无 `assistant_version` | 账号删除时的清除本期不做（spec AC-100 已移出）；来源名称写入时快照；助手开关就地保存 |
| K12 | 用户表没有时区字段，现有提示词里的日期用服务器时间 | `chat_service.py:2105`；`linsight/domain/task_exec.py:1595` | AC-14 需要新的时区来源 |
| K13 | 消息渲染有三套：client 日常模式（SSE，自有气泡）、client 应用聊天（WebSocket，`@bisheng/chat` 共享组件）、platform 管理端查看会话 | 取证 §4.4 | 操作提示与归因要接三处：日常模式气泡、应用聊天、深度研究结果面板；管理端那一套不接 |

**权限（C4）的适用结论。** 记忆管理接口只作用于调用者本人，不存在"对某个资源授权"的对象，不走资源授权，由登录态确定主体。助手记忆开关与工作流记忆开关是应用配置的一部分，沿用应用现有的编辑权限检查，不新增权限动作。

**模块编码。** 申请 **121**（memory）。已按 C5 的命令重新推导占用清单，121 空闲。落码时同批回写 C5 表、`release-contract.md` 与三语 `packages/locales/src/api_errors/`。

---

## 3. 方案对比与选定

### 决策 1：自有领域服务，不以 LangGraph `BaseStore` 为核心抽象

- **备选**：
  - A. 实现一个 `BaseStore` 后端，业务通过它读写。《memory 技术路线调研》§1 推荐的路线。
  - B. 新建 DDD 模块 `bisheng/memory/`，以 `MemoryService` 为唯一入口，条目是有状态的领域对象。
- **选定**：B
- **原因**：`BaseStore` 的写语义是按 key 整值覆盖，没有"取代并保留旧条目""删除可撤销""来源标记""常驻"这些状态，而 spec 的 AC-22、AC-25、AC-92 都依赖它们。把状态塞进 `value` 字典等于在 `BaseStore` 上再写一层领域服务，`BaseStore` 自身不带来复用：四个接入点里只有深度研究用 deepagents，它也不通过 store 读写记忆。调研推荐 A 时的范围是"日常模式个人记忆、冲突时覆盖旧事实"，现在范围不同。
- **何时该重新考虑**：需要让第三方 LangGraph 图直接读写平台记忆时，在 `MemoryService` 之上加一个只读适配器。

### 决策 2：关系表是唯一事实源，Milvus 与 ES 只存可重建的派生索引

- **备选**：A. 关系表存条目，Milvus/ES 存索引，检索结果一律回表校验。B. 只用 Milvus + ES，把条目存在向量库的标量字段里。
- **选定**：A
- **原因**：取代、删除、撤销恢复必须是事务性的，并立即对所有读取途径生效（AC-91）。向量库和 ES 做不到与关系库同事务。回表校验让索引滞后或损坏只导致少召回，不导致读到已删除或别人的条目。DM8 环境下也不依赖其原生向量能力（技术路线调研 §6）。
- **何时该重新考虑**：单用户条目数达到回表成为瓶颈的量级时。

### 决策 3：详情是写一次不改的对象，不复用深度研究的工作区后端

- **备选**：A. 把 `WorkspaceBackend` 抽到公共层，详情作为可编辑文件。B. 详情作为不可变对象直接存 MinIO。
- **选定**：B（用户已于 2026-11-13 确认）
- **原因**：spec 把"编辑"定义为新条目取代旧条目（AC-25、AC-89），一条详情创建后永不修改，A 方案要防的"读整份、改、写回"并发覆盖不存在。`WorkspaceBackend` 与深度研究耦合很深（对象键前缀固定、write/edit 会改写引用标记、内置技能只读目录），抽公共层的工作量因此省掉。
- **对象键**：`memory/{tenant_id}/{user_id}/{item_id}.md`。`item_id` 由应用侧在落库前生成（UUID），所以可以先写对象再插行。
- **何时该重新考虑**：产品要求模型像操作文件那样逐段编辑一份长记忆时。

### 决策 4：删除是软删除，清空是硬删除

- **备选**：A. 删除即物理删除行与详情对象。B. 删除只改状态，行与详情对象保留；清空才物理删除。
- **选定**：B
- **原因**：AC-22 要求撤销"忘掉"后条目恢复为有效。A 方案下详情对象已删，恢复出来的行指向不存在的对象。B 方案下撤销只是把状态改回去。"不可再读"（AC-26、spec §0 的"删除"）由所有读取途径只认 `status='active'` 保证。
- **撤销的边界**（都返回带原因码的失败，不做部分恢复）：
  - 目标条目已被"清空"物理删除。
  - 撤销"更正"时，新条目已经被再次取代或删除。
  - 同一次操作已经撤销过。
- **清空**（AC-93）物理删除该用户在当前租户的全部行（含已被取代、已删除的）、详情对象与索引。顺序：先删索引和对象，最后删行；中途失败可重入。
- **何时该重新考虑**：合规要求"用户删除即物理擦除"时，改为删除后定时物理清理，并给撤销设时限。这会改 spec。

### 决策 5：显式写入同步落行、同步建索引，索引失败不影响写入成功

- **备选**：A. 写入工具把请求投给后台任务。B. 请求线程内同步完成校验、落行、建索引。
- **选定**：B
- **原因**：AC-24 要求同一会话下一轮可读，AC-21、AC-23 要求只有真实成功才出提示，都要同步知道结果。
- **并发安全**来自操作本身：新增是 INSERT；更正和忘掉是带状态条件的 UPDATE（`WHERE id=? AND tenant_id=? AND user_id=? AND status='active'`），影响行数为 0 即判定目标已变，返回失败。没有读改写。
- **索引**：行提交后同步写 ES 与 Milvus，embedding 调用设 3 秒超时。任一失败或超时不回滚行，把条目的 `index_state` 置为 `pending`，由对账任务重试。检索时把该用户 `index_state='pending'` 的有效条目**全部**作为候选排在融合结果之后（上限 20 条，不做匹配），所以索引未建好的新条目不会被漏掉。
- **软删除与索引**：条目被取代或删除时同步删除其索引项；撤销恢复时重新建索引，失败同样置 `pending`。
- **代价**：两个会话同时"记下"同一件事会产生两条内容相同的条目，由下一次整理合并（AC-47）。
- **何时该重新考虑**：embedding 调用的延迟让显式写入明显变慢时，把向量索引改为异步，关键词索引保持同步。

### 决策 6：资格在 endpoint 层判定并持久化，下游只查登记

- **备选**：
  - A. 每个接入点自己从手头的 `user_id` 判断能否使用记忆。
  - B. 在 endpoint 层调用 `MemoryGate.open(chat_id, login_user, timezone)`，把"这个会话属于哪个自然人、在哪个租户"写进 `memory_session_cursor`。下游（Service、节点、回调、worker、Beat）按 `chat_id` 查这一行，查不到即不工作。
- **选定**：B
- **原因**：K6。下游拿不到主体类型；登录用户和开放 API 的调用又共用同一批 Service 函数，在 Service 里登记会把服务账号当成自然人，违反 AC-10 与候选 INV-44。B 的失败方向是关闭：任何没有经过登记的路径，记忆都不工作。
- **资格规则**（用户已于 2026-11-13 裁定开放 API 本期不支持记忆）：**只有以登录态进入的自然人用户有资格**。开放 API 的全部调用（服务账号自身身份、代表某个平台用户、个人访问令牌、只带外部用户标识、托管应用身份）和免登录链接都没有资格。
- **调用 `open` 的入口**（都在 endpoint 层，都要求登录态）：
  - 日常模式对话：`workstation/api/endpoints/chat.py:97`。
  - 深度研究：`linsight/api/endpoints/linsight.py` 的提交（`:174` 一带）、`/workbench/continue`（`:327`）、`/workbench/user-input`（`:390`）；从日常入口转入任务模式的情况已被上一条覆盖。
  - 助手与工作流：`chat_id` 不在建连时可知（K14）。做法是登录态的 WebSocket endpoint 在创建客户端对象时**传入一个登记回调**，客户端在拿到或切换 `chat_id` 时调用它。回调由 `memory` 提供、由 endpoint 注入，`common/` 里的客户端只持有一个可调用对象，不引用 `memory`。免登录与开放 API 的 endpoint 不传回调，所以它们的连接无论怎么切换会话都不会被登记。
- **`open` 要核对会话归属**：`chat_id` 对应的会话已存在时，它的所属用户必须是当前登录用户，否则不登记。这防止知道他人 `chat_id` 的人抢先登记，使对方的会话失去记忆。
- **不调用 `open` 的入口**：`open_endpoints/` 与 `open_api/` 下的全部入口（含 `open_endpoints/api/endpoints/workstation.py:66-97`、`open_api/domain/services/task_mode_service.py:292-307`、`assistant/domain/services/published_assistant_service.py`）；`/api/v3` 免登录入口；无人值守运行（`unattended_run`）。
- **没有 `chat_id` 的运行**：工作流评测（`evaluation_service.py:194-202`）、助手与工作流的调试运行，`chat_id` 为空且不落消息。它们没有登记行，记忆不工作。这是预期行为。
- **登记行的写入规则**：
  - 不存在时创建：写入 `tenant_id`（当前租户）、`user_id`，并把水位初值设为该会话**当前最大的消息 id**。所以登记之前的历史消息永不整理（AC-40）。
  - 已存在且 `tenant_id`、`user_id` 都相同：只在时区变化时更新。绝大多数轮次是零写入。
  - 已存在但 `tenant_id` 或 `user_id` 不同（例如用户调岗后打开旧会话）：不覆盖，把该行置为 `eligible=false`。这个会话此后不再使用记忆，未整理的旧对话也不再整理。
- **下游以登记行为准**：登记行上的 `tenant_id`、`user_id` 是在有可靠登录上下文的 endpoint 写入的。下游（worker、节点、整理任务）直接用行上的值构造 `MemoryContext`，不再与当时的租户上下文变量比对，因为 worker 里的租户上下文不保证已设置（`workflow/nodes/base.py:45-48` 的注释）。
- **这一行同时承载**：会话的时区（决策 13）、整理水位与状态（决策 7）。
- **何时该重新考虑**：平台给运行时统一下传主体对象时，可以去掉这层持久化，并重新评估开放 API 的支持。

### 决策 7：自动整理由"会话登记 + Celery Beat 扫描"触发，按用户串行

- **备选**：A. 每轮结束投一个 `countdown=安静期` 的任务。B. 每轮结束更新登记行；Beat 定时扫描，按用户投整理任务。
- **选定**：B
- **原因**：
  - 深度研究 worker 不是 Celery（K1），发不了 `countdown` 任务，但能写一行数据库。
  - A 在长会话里每轮产生一个大概率被放弃的任务，Redis 重启会丢未到期任务；登记表持久，满足 AC-45。
  - 仓库没有"去抖"任务的先例；Beat 遍历全租户有先例（`worker/linsight/personal_skill_sweep.py:120-137`）。
- **运行语义**：
  - **粒度**：一个任务处理一个用户在一个租户内**所有到期的会话**，不是一个会话一个任务。这样同一用户不会因抢锁而每周期只处理一个会话。
  - **锁**：`(tenant_id, user_id)` 维度的 Redis 锁，带持有者令牌，TTL 10 分钟，任务运行中定时续期；释放时校验令牌（先例 `worker/information/redis_lock.py:46`）。取不到锁就结束，登记行保持待处理。
  - **状态**：登记行 `state ∈ {idle, pending, running}`。每轮结束置 `pending`。任务开始把选中的行置 `running` 并写 `locked_at`。`running` 且 `locked_at` 早于锁 TTL 的行在下次扫描时视为 `pending`（任务崩溃后的自愈）。
  - **水位**：任务开始时对每个会话取一次"当前最大可整理消息 id"作为本次终点；处理期间到达的新消息留给下一次。水位不越过未完成的深度研究任务行（K9）：遇到 `category='task'` 且未到终态的行，终点停在它之前。
  - **原子性**：一个会话的"条目落库 + 取代关系 + 水位推进"在同一个数据库事务里提交。索引在提交后做（决策 5 的失败处理）。中途崩溃重跑不会重复落条目。
  - **失败与退避**：失败时 `fail_count+1`，下次可调度时间为 `min(2^n × 扫描周期, 2 小时)`，成功清零。失败计入指标（AC-45）。"没有可用的整理模型"也按失败处理并计数，但不无限重试到刷屏：同一原因连续失败只记录首次与之后每小时一次的日志。
- **同一行的并发写**：`open`、`end_turn`、Beat、整理结束四者都写登记行，全部用**按列的条件更新**，不做读改写。水位只增不减：任何更新都写成 `watermark = 两者中较大者`。`end_turn(enabled=true)` 执行 `last_message_id = 较大者, state = 'pending'`；`end_turn(enabled=false)` 执行 `last_message_id = 较大者, watermark = 较大者`。整理结束时执行 `watermark = max(现值, 本次终点), state = 'idle' WHERE last_message_id <= 本次终点`；条件不成立说明整理期间有新消息，只推进水位、保持 `pending`。
- **场景与应用的来源**：登记行不存场景。整理时从 `message_session` 的 `flow_type`、`flow_id` 得到场景与应用，从消息的 `category='task'` 识别深度研究轮次，据此做启用判定并填写条目的来源标记。
- **深度研究以"任务轮"为整理单位，不用消息 id**（K9）。追问轮不产生新消息行，按消息 id 推进的水位在首轮之后就越过了任务行，追问轮永远不会被整理。所以：
  - 消息水位只管非任务消息，整理时跳过 `category='task'` 的行。
  - 深度研究每一轮（首次提交与每次追问）结束时，本轮记录表里有一行该轮的概要（决策 15），上面带 `consolidated` 标志。整理任务处理该用户所有未整理的深度研究轮，逐轮读取这一轮的问题与结果，处理后置位。
  - 一轮的问题与结果从深度研究自己的存储里按轮读取。追问的问题存在哪里、能否按轮取出，是**待验证 V7**。
  - 仍在进行中或停在"等待用户补充"的轮不整理；它结束时才会有 `end_turn`。超过 24 小时未结束的轮放弃整理。
- **只整理启用之后的对话（AC-40）与关闭后不再整理（AC-41）**：
  - 每轮结束时接入点都调 `MemoryActivity.end_turn(chat_id, last_message_id, enabled)`。`enabled=true` 置 `pending`；`enabled=false` 直接把水位推进到 `last_message_id`，即这轮被跳过，永不整理。
  - 任务开始时对每个会话重新过一次启用判定。判定为关，或会话已软删除（`message_session.is_delete`），就把水位推进到当前终点并置 `idle`，不整理。
  - 用户"清空"记忆时，把他在当前租户所有登记行的水位推进到当前，否则清空之前的对话会在下次整理时重新生成条目。
- **队列**：`bisheng.worker.memory.*` 走默认 `celery` 队列，不新增队列（否则现场要改 worker 启动参数）。
- **何时该重新考虑**：扫描周期带来的延迟不可接受，或单次扫描过长时，按租户分片。

### 决策 8：常驻记忆是条目上的标志位，带入时读缓存

- **备选**：A. 每个用户一行大文本，每轮直接取。B. 条目表上 `pinned` 与 `pin_order`；带入时查常驻条目并渲染，结果缓存。
- **选定**：B
- **原因**：A 是 K3 禁止的形态，并与"条目是唯一事实源"冲突。B 下常驻是条目的属性，AC-91 自动成立。
- **缓存的正确性**：
  - 版本号存在关系库，不存在 Redis：`memory_user_setting.rev`，任何使该用户条目变化的操作在**同一个事务**里把它加一。Redis 重启或淘汰不会让版本回退。
  - 缓存键：`tenant_id + user_id + rev + 用户时区下的日期 + 场景类别`。日期进键，所以事件时间一过午夜就不再被带入（AC-94）；另设 1 小时 TTL 兜底。
  - 每轮带入的代价：读一行 `memory_user_setting`（取 `rev` 与开关），再读一次 Redis。
  - `memory_user_setting` 的行在首次需要时创建（唯一键 `tenant_id + user_id`，并发创建时捕获唯一键冲突后重读）。没有行等同于 `enabled=true, rev=0`。
  - 缓存未命中、重新生成常驻文本时，同时写一行 `memory_resident_snapshot`（该用户在这个 `rev` 和日期下带入了哪些条目）。它每个版本每天只写一次，供归因展示"本轮带入的常驻记忆"。
- **谁常驻**：
  - 显式写入与手动新增的事实类、偏好类条目默认 `pinned=true`，`pin_order` 排在最前。所以刚记下的条目在同一会话下一轮必然在常驻里（AC-24）。
  - 经验类条目永不 `pinned`（AC-54）。它在日常模式和助手里的"可读"靠检索；在深度研究里靠 AC-55 的单独带入。
  - 自动整理新增的条目是否常驻、以及到达上限时合并或移出谁，由整理决定（AC-63）。
- **上限**：渲染时按 `pin_order` 取到条数或字数上限为止，不截断单条（AC-53）。
- **经验类的带入（AC-55）**：深度研究任务开始时，取该用户有效的经验类条目，按"最近被读时间、记录时间"降序，取到独立的上限为止。
- **何时该重新考虑**：常驻条目需要按场景差异化排序时。

### 决策 9：记忆的读写一律显式按"当前租户 + 本人"过滤，不依赖租户自动过滤

- **备选**：A. 依赖 `tenant_filter` 自动注入。B. repository 层每个查询和写操作都显式带 `tenant_id = 当前租户 AND user_id = 本人`。
- **选定**：B
- **原因**：K4。自动过滤给普通用户的是可见租户的 IN 列表，给全局超管的是不过滤。用户从根租户调到子租户后，根租户仍在其可见集合内，A 方案下他在根租户的旧记忆仍可读，违反 AC-06。超管用自己的记忆时会读到所有租户里同 `user_id` 的行。
- **"当前租户"的取值**：一轮开始时从租户上下文取（`get_current_tenant_id()`），写进 `MemoryContext` 并沿用到该轮结束；后台任务取登记行上的 `tenant_id`。
- **与 C3 的关系**：C3 写"不要手写 `WHERE tenant_id`"，其目的是防止遗漏隔离。本功能的隔离比自动过滤更严，手写是加强而不是绕过。新表仍登记进 `tenant_filter`，自动过滤作为第二道。**这是一处显式例外，用户已于 2026-11-13 同意**（§9），并登记在 `release-contract.md` 的 F132 段。
- **强制方式**：凡是读写条目、用户设置、本轮记录、常驻快照的 repository 方法，签名都必须接收 `MemoryContext`，没有不带上下文的重载。有一条测试用全局超管身份和"可见多租户"身份各跑一遍隔离用例。
- **例外的边界**。下列方法没有 `MemoryContext`，各自的隔离方式如下，除此之外不允许再有：

| 方法 | 为什么没有上下文 | 靠什么隔离 |
|---|---|---|
| 按 `chat_id` 读登记行（`MemoryGate.resolve`） | 上下文正是由它产生的 | 按主键取一行，用行上的 `tenant_id`、`user_id` 构造上下文。行只能由登录态 endpoint 的 `open` 写入，`open` 写入时用的是当前登录用户与当前租户，并核对了会话归属 |
| Beat 扫描到期登记行 | 跨租户枚举 | 包在 `bypass_tenant_filter()` 里，只读 `chat_id`、`tenant_id`、`user_id`，随后按租户设置上下文再投任务 |
| 索引对账、遗留记录清理 | 后台维护 | 同上，逐租户设置上下文后再用带上下文的方法处理 |
| `memory_metric_daily` 的写入 | 没有用户维度 | 只含计数，带 `tenant_id` |
- **何时该重新考虑**：`tenant_filter` 提供"严格等于当前租户"的模式时，改用它。

### 决策 10：一个工具工厂，三个场景复用；记忆工具的事件落库前脱敏

- **选定**：`memory/domain/services/tools.py` 的 `build_memory_tools(ctx) -> list[BaseTool]` 返回两个 `StructuredTool`：
  - `memory_write(action, content, target_id?, type?, event_time?)`，`action ∈ {remember, correct, forget}`
  - `memory_search(query, limit?, detail_ids?)`
- **被否方案**：做成平台"工具"由作者勾选。否决原因是 AC-77 要求助手记忆开启后无须另配，并且它会把记忆带进 `ToolExecutor` 的权限与配置体系。
- **脱敏（K7）**：凡是把工具调用落库或下发给前端的地方，对名称以 `memory_` 开头的工具做统一处理：入参与返回替换为 `{"redacted": true, "item_ids": [...], "op": ...}`。本人需要看原文时，前端拿 `item_ids` 向记忆接口取。这样任何原样返回消息的接口里都没有记忆原文（AC-09）。
  - **落点清单**（每一处都要调同一个脱敏函数）：
    - 日常模式：`chat_service.py:2311-2319`（入参）、`:2343-2344`（返回）。
    - 助手路径一：`common/chat/client.py:391-405`，行由 `AssistantAgent.run()` 的返回值构造，`run()` 返回前脱敏。
    - 助手路径二：`api/v1/callback.py` 的工具回调（`:472-495` 下发、`:523-545` 与 `:572-585` 落库）。回调拿到的是原始入参，必须在回调处理器里脱敏。**待验证 V1**。
    - 深度研究：`linsight/domain/services/stream_event_mapper.py:631`、`:662`、`:700-712`，步骤事件写入 `linsight_execute_task.history` 之前脱敏。上下文压缩还会把线程里的历史消息写成工作区文件（`linsight/domain/utils.py:104-117`、`context_budget.py:144`），其中的记忆工具消息同样要处理。**待验证 V3**。
  - 这只保护工具事件。模型在**回答正文**里复述的记忆内容不做遮盖（spec §3 已声明）。
  - 有一条测试对上述每个落点的落库结果做断言；新增落库路径而没有脱敏，这条测试要能失败。
- **脱敏对历史回放的影响**：助手下一轮会把历史里的工具消息回放给模型（`client.py:270-306`）。回放的是脱敏后的内容，所以上一轮检索到的非常驻条目不会留在上文里，模型需要时会再检索一次。显式写入的条目是常驻的，不受影响（AC-24 仍成立）。回放时把脱敏后的工具结果渲染成一句中性说明（"记忆操作已完成"），避免模型把 `redacted` 当成异常。
- **其它带出途径**：`BISHENG_AGENT_DUMP`、`BISHENG_RECORD_HISTORY` 两个调试开关会把提示词与消息写到本地文件，回调还会以 debug 级别记录工具入参与输出。三者默认关闭，属于运维人员主动开启的调试手段，本期不处理，记入 §8。
- **同名工具**：`memory_` 是保留前缀。助手作者配置的工具若与记忆工具同名，以记忆工具为准并记录一条告警日志（spec §3 指向此处）。
- **何时该重新考虑**：平台统一了工具调用事件的落库格式时，把脱敏挪到那一层。

### 决策 11：常驻记忆和工具在"调用时"注入，不在 agent 构建时

- **备选**：A. 拼进系统提示词、构建 agent 时加工具。B. 每轮调用模型时注入。
- **选定**：按场景不同：
  - **日常模式**：每轮都重新拼提示词和工具（`chat_service.py:2013`、`:2099-2111`），直接在这两处加，天然每轮。无工具时走直连 `astream` 的分支（`:2407-2411`）也带上常驻记忆。
  - **助手**：agent 在连接内只建一次（K8），连接持有的助手对象也不重读。所以每轮开始时：
    1. 从数据库重读该助手的 `memory_enabled`（一次按主键的查询），不用连接里缓存的对象。
    2. 做启用判定。结果与上一轮不同（开或关发生变化）时，在 `AssistantAgent` 内部重建 agent，使工具列表与当前状态一致（AC-72、AC-74）。
    3. 常驻记忆作为一条系统消息加入输入。它在 `trim_messages`（`assistant_agent.py:548-572`）**之后**插入，否则超长裁剪会从头部先把它丢掉。两种执行器都接受输入里的系统消息（ReAct 的历史占位符、function call 的 `create_react_agent`）。多条系统消息在各模型端点上的兼容性是**待验证 V5**。`run()` 返回前把这条注入的系统消息从结果里剔除：`client.py:393-400` 用 `result[len(chat_history):-1]` 切出新增消息，多出一条会让偏移错一位。
  - **深度研究**：新增一个中间件，在 `wrap_model_call` 里追加常驻记忆与经验类条目。文本在**任务开始时取一次**并保存在本次运行的对象里，之后每次模型调用追加同一段，不重取，所以不破坏提示词前缀缓存，也符合 AC-51"任务开始时带入"。它排在引用与语言两个尾部中间件之前，那两个保持在最末（`agent_factory.py:222-259`、`:1559-1564`）。
- **原因**：
  - 助手：AC-51 每轮带入、AC-74 下一轮按新状态，构建时注入都做不到。
  - 深度研究：首条消息有两处拼装（`task_exec.py:1600` 与续轮的 `:701-703`），写进消息的文本会留在检查点线程里。中间件注入不进线程历史，两处拼装也都覆盖。
- **已知的不一致**：深度研究里 `memory_search` 的返回是工具消息，会进入检查点线程（Redis，7 天）并在续轮时回给模型。所以一条记忆被删除后，在**已经检索过它的那个任务线程**里仍可能对模型可见。常驻记忆没有这个问题。这一点记入 spec §3 的已知限制。
- **何时该重新考虑**：助手改为每轮构建 agent 时，可以简化回提示词注入。

### 决策 12：检索 = ES 关键词 + Milvus 向量，自己做融合，回表为准

- **选定**：
  - ES 索引 `bisheng_memory_item`，Milvus collection `bisheng_memory_item_{embedding_model_id}`，全部租户共用。名字带 `memory` 前缀，与知识库的 collection 命名空间分开。
  - 过滤条件由 `memory/domain/services/index.py` 里**唯一的一个函数**从 `MemoryContext` 生成（`tenant_id`、`user_id`），两路检索都只能经过它。
  - 融合用倒数排名融合，在 `index.py` 里自己实现。不复用 `core/vectorstore/multi_retriever.py`：它只是把多个向量库的原始分数合并排序，关键词分数与向量相似度不可比，并且任一路失败就整体抛错。
  - 结果的 id 回关系表按决策 9 的条件再取一次，以回表为准。
- **降级与失败**：
  - 租户没有配置 embedding：只走关键词，这是正常状态，不计失败。
  - 一路不可达：用另一路，计一次"降级"指标。
  - 两路都不可达：抛错。模型工具把错误返回给模型并按 AC-61 记录；检索节点按 AC-84 以失败结束。
  - 索引里没有某条目不算失败（决策 5 的 `pending` 并入已覆盖）。
- **embedding**：取租户的知识库默认 embedding（`llm/domain/services/llm.py:1248`）。租户更换 embedding 模型后，旧 collection 不再使用：对账任务发现条目的 `index_model_id` 与租户当前模型不一致时重建其索引。
- **接口隔离**：`MemoryService` 与检索只依赖 `memory/domain/ports.py` 里的 `MemoryIndex`、`DetailStore`、`MemoryLLM` 三个接口，真实实现与测试替身都实现它们。服务与索引实现之间因此没有循环依赖，标〔测〕的验收标准可以不依赖中间件。
- **被否方案**：每个用户一个 collection。collection 数量随用户数增长，不可行。
- **何时该重新考虑**：评测显示检索质量不足时，加重排一路。

### 决策 13：时区由客户端上报一次，随会话登记保存，取不到用部署默认值

- **备选**：A. 给用户表加时区设置。B. 每个对话请求都带上时区。C. 客户端加载后把浏览器的 IANA 时区上报给记忆接口（值变化时才上报），存进 `memory_user_setting.timezone`；入口调 `MemoryGate.open` 时把它抄到登记行。
- **选定**：C
- **原因**：K12。A 需要一个新的用户设置项，超出本功能范围。B 要改日常模式、应用聊天（WebSocket）、深度研究三种入口的请求，还要让时区穿过任务队列。C 只有客户端一处上报；工作流节点、深度研究 worker、整理任务都从登记行读时区。
- **回落顺序**：本会话登记的时区 → `memory_user_setting.timezone` → 部署默认时区。
- **何时该重新考虑**：平台增加用户级时区设置时，改读那个设置。

### 决策 14：密钥类内容的拒绝由确定性规则完成

- **备选**：A. 调用模型做内容审查。B. 代码规则。
- **选定**：B。`MemoryService` 在任何写入途径落库前过同一个 `SensitiveContentGuard`：密钥与令牌的常见前缀和高熵串、18 位身份证号校验位、银行卡号 Luhn 校验、"密码是/password:"一类的赋值句式。命中即拒绝并返回原因码。
- **原因**：AC-16 标〔测〕，AC-89 的管理页新增需要确定性的接受或拒绝。A 每次写入多一次模型调用且结果不确定。
- **已知限制**：规则会漏报（例如没有任何特征的短口令）。
- **何时该重新考虑**：漏报造成实际事故时，在规则之后加一道可选的模型审查。

### 决策 15：操作提示与归因的数据单独成表，按"轮"记录，只对本人返回

- **备选**：A. 写进 `chatmessage.extra` 或消息体。B. 新表，由记忆模块自己的接口返回，接口内校验请求人就是记忆的主人。
- **选定**：B
- **原因**：A 下这些数据随消息被三套渲染读到，要在每一套里分别过滤。B 下其他接口不含这些数据，隔离做在数据访问层。引用角标也是独立成表（`message_citation`）。
- **按轮而不是按消息**：写入工具在回答生成的中途被调用，那时回答的消息行还没有插入。所以每轮开始生成一个 `turn_id`，写进 `MemoryContext`；记录先挂在 `turn_id` 上，回答落库后再补 `message_id`。
- **一轮里写什么**：
  - 每次显式写入一行：操作类型、新条目 id、被取代或被忘掉的条目 id。
  - 本轮只要调用过检索，一行：取回的条目 id 列表。
  - 本轮带入了常驻记忆，不单独写行，只在上面任一行或"本轮概要行"里记下 `resident_rev` 与日期，指向 `memory_resident_snapshot`（决策 8）。
  - 没有显式写入也没有检索的一轮，只写一行概要（`turn_id`、`resident_rev`、日期）。
- **各场景补 `message_id` 的落点**：

| 场景 | 落点 | 说明 |
|---|---|---|
| 日常模式 | `chat_service.py:2558-2575`（正常）、`:1955-1980`（中断） | 中断路径是同步函数，只能用同步 DAO，`bind_turn` 与 `end_turn` 都要提供同步实现 |
| 助手 | `common/chat/client.py:427-428`（回答落库）、`:337-354` 与 `:461-465`（中断落库） | `client.py` 在 `common/` 下，不得引用 `memory`。做法是 `AssistantAgent` 增加一个方法 `after_answer_persisted(message_id, interrupted)`，由 `client.py` 在落库后调用。`client.py` 本来就持有并调用 `AssistantAgent`，不新增依赖方向 |
| 深度研究 | 每一轮（首次提交与每次追问）开始时建本轮概要行 | 多轮共用同一个任务消息行（K9），所以深度研究的操作提示与归因按 `turn_id` 取，不按 `message_id`。前端每一轮的结果面板要拿得到该轮的 `turn_id`：**待验证 V7** |
| 工作流 | 不记录 | spec 规定工作流的最终输出不做归因；记忆检索节点不写本轮记录，只计指标 |

- **遗留记录**：进程崩溃会留下没有 `message_id` 的记录。前端在会话进行中按 `turn_id` 取，所以当场的操作提示与撤销不受影响；刷新后按 `message_id` 取不到，这一轮的提示丢失，条目本身不受影响（管理页可见可删）。没有 `message_id` 且超过一天的记录由定时任务清理。
- **清空**时，该用户在当前租户的本轮记录与常驻快照一并删除。
- **流式信号**：日常模式新增 SSE category `memory`；助手走同名的 WebSocket 消息；深度研究在 `MessageEventType` 里加一个事件。信号只带 `turn_id` 和"有操作提示/有归因"的标志，不带原文。
- **每轮的数据库代价**（日常模式，记忆已启用）：读 3 次（登记行、用户状态、`memory_user_setting`）；写 3 次小行（本轮概要一次插入、`bind_turn` 一次更新、`end_turn` 一次更新）。`open` 在登记行已存在且时区未变时不写。常驻快照每个版本每天写一次。这些都是定长小行的单行操作，不触及 K3 禁止的大 JSON 整行重写。
- **何时该重新考虑**：平台统一了"消息附属数据"的存储时。

### 决策 16：归因只列检索取回的条目；常驻记忆整份可查看

- **备选**：A. 让模型用句柄标注它用了哪几条常驻记忆。B. 检索取回的逐条列出；常驻记忆给一个入口整份查看。
- **选定**：B（用户已于 2026-11-13 确认，spec AC-87 已按此改写）
- **原因**：A 要在三套互不通用的引用机制上各做一遍句柄转换，并且标注是否准确无法保证。B 完全由系统确定，可自动化测试。
- **何时该重新考虑**：用户反馈"分不清哪条常驻记忆起了作用"成为主要问题时。

### 决策 17：三处开关存储在各自对象的现有配置里，没有租户级开关

| 开关 | 存储 | 说明 |
|---|---|---|
| （没有租户级开关） | — | 用户于 2026-11-13 裁定去掉。工作台配置里只有一个与记忆有关的字段：`WorkstationConfig.memory_model_id`（整理使用的模型，见决策 18），沿用 `POST/GET /api/v1/workstation/config/daily` 与现有读写入口，不新开配置键 |
| 我的记忆 | 新表 `memory_user_setting`，一人一租户一行 | 同一行还有 `rev` 与 `timezone`。没有行时按 `enabled=true`，所以升级后每个用户默认是开（AC-76） |
| 助手记忆 | `assistant` 表新列 `memory_enabled`，`server_default` 为关 | 助手没有版本表，保存即生效（spec AC-71 已据此订正） |
| 工作流记忆 | 开始节点的参数 `memory_enabled`，存在 `flow_version.data` 里 | 随版本走；参数缺失视为关 |

- **被否方案**：保留租户级开关（第 4 稿的做法）。用户裁定去掉，后果是租户管理员不能在租户范围内关闭记忆；要整体停掉后台整理，只能用部署配置里的自动整理总开关（决策 19），它不影响显式写入与读取。
- **工作流运行时怎么拿到这些值**：工作流实例化时（`GraphEngine.init_nodes`）按 `flow_id` 查一次上线版本的开关，连同本次运行的 `chat_id` 一起放进 `graph_state` 的只读字段。节点自身没有 `chat_id` 属性，这是它取得 `chat_id` 的途径（**待验证 V4**）。记忆检索节点和消息落库回调都从 `graph_state` 读。整理任务判定"现在是否仍开启"时读该工作流当前上线版本的开始节点参数。
- **启用判定**：`MemoryGate.resolve(chat_id, scene, app_enabled) -> MemoryContext | None`。顺序：登记行存在且有资格（决策 6）→ 用户未停用 → 我的记忆 → 应用开关。一轮开始时取一次，沿用到该轮结束（AC-74）。
- **应用开关的取值**：都以数据库为准，不信任运行时手头的对象。助手每轮重读 `assistant.memory_enabled`（决策 11）。工作流读该工作流**当前上线版本**的开始节点参数：登录态路径上实际执行的图来自客户端消息（K14），客户端可以自带一个开关为开的图，所以不能读正在执行的图。记忆检索节点执行时如果数据库里的开关是关，按未启用处理，输出空数组。
- **每轮的查询代价**：见决策 15 末尾的统计。
- **何时该重新考虑**：每轮三次小查询成为可测的延迟时，把登记行与用户设置合并缓存。

### 决策 18：整理用的模型由租户指定，调用按租户计量

- **选定**：
  - 工作台配置里有"记忆整理使用的模型"（`WorkstationConfig.memory_model_id`，AC-106）。未指定时用工作台模型列表的第一个。两者都没有时整理任务按失败处理并计数，不静默跳过。
  - 整理的模型调用与记忆的 embedding 调用，以记忆主人的 `user_id` 发起，标记一个新的应用类型"记忆"，记入现有的 token 用量记录。
- **额度（用户已于 2026-11-13 裁定）**：整理与记忆 embedding 的调用**不计入用户个人额度**，只按租户记录用量。现有模型调用会经过额度检查（DSH 积分等，`dsh/domain/services/chat_credits.py:20-23`），记忆的调用要绕开个人额度扣减这一步；如果调用仍被其他机制拒绝，按整理失败处理并计数。
- **备选**：整理固定用系统默认模型，不给配置。否决原因是后台整理是持续成本，应当能指到便宜的模型。
- **何时该重新考虑**：平台有统一的"后台任务模型"配置时，改读那个配置。

### 决策 19：部署级参数放数据库里的运行期配置，代码自带默认值

- **选定**：`initdb_config` 的新键 `memory`，用 `settings.aget_from_db("memory")` 读。缺键时该方法返回空字典，所以**默认值写在代码里**，`initdb_config.yaml` 里的条目只是文档作用。

| 参数 | 初值 | 说明 |
|---|---|---|
| 常驻记忆条数上限 | 60 | 未经评测校准 |
| 常驻记忆字数上限 | 6000 | 未经评测校准 |
| 深度研究带入经验类条目上限 | 20 条且 2000 字 | 未经评测校准 |
| 安静期 | 30 分钟 | |
| 扫描周期 | 5 分钟 | 整理延迟的下限是安静期加一个扫描周期 |
| 整理锁 TTL | 10 分钟 | |
| 默认时区 | `Asia/Shanghai` | |
| 自动整理总开关 | 开 | |

- **备选**：放 `config.yaml`。否决原因见 K5。
- **何时该重新考虑**：评测集给出校准值后更新初值。

### 决策 20：指标用 Redis 计数、定时落库

- **备选**：A. 每次事件直接写库。B. Redis 计数，Beat 任务定时落到 `memory_metric_daily`。
- **选定**：B
- **原因**：K3。每轮带入几十条就更新几十行是不可接受的热写。
- **各指标的来源（AC-102）**：
  - 显式写入、自动整理、手动新增的新增条数，被取代与被删除的条数：事件发生时在 Redis 计数。不从条目表聚合，因为"清空"会物理删除行，事后聚合会丢数。
  - 被带入、被检索返回的条目数；带入失败、检索失败、详情读取失败、整理失败、检索降级的次数：Redis 计数。
  - 从未被带入也未被检索返回的条目数：条目上的 `last_read_at` 为空。Redis 里维护"今日被读条目集合"，定时任务批量更新这一列。
  - 详情被取回过的比例：条目上的 `detail_read_at`，同样由定时任务从 Redis 集合批量更新。
  - 用户撤销次数：事件发生时在 Redis 计数，理由同上。
- **何时该重新考虑**：需要分钟级的指标时。

### 决策 21：实体关系表本期不建

- **备选**：A. 按 PRD D2 建空表。B. 不建。
- **选定**：B（用户已于 2026-11-13 确认，改判 PRD D2）
- **原因**：空表没有读者和写者，却要在两套方言上维护迁移并登记进租户过滤。避免回填靠的是条目表字段写全，条目表本期已带作用域、两组时间、取代关系、来源。
- **何时该重新考虑**：开始做实体关系抽取时。

### 决策 22：账号删除时的清除本期不做

- **事实**：全仓没有硬删除用户的实现（K11）。
- **选定**：本期不实现任何由系统发起的记忆清除。spec AC-100 已移出，编号保留不复用。
- **被否方案**：先做一个没有调用方的清除方法加运维脚本。用户于 2026-11-13 否决。
- **何时该重新考虑**：平台增加账号删除功能时。届时清除要覆盖条目、详情对象、两类索引、用户设置、会话登记、决策 15 的表，并且是唯一需要跨租户的写操作。

---

## 4. 系统现状（接手必读）

### 4.1 目标数据流

**入口登记**
`登录态的 endpoint → MemoryGate.open(chat_id, login_user, timezone) → 按决策 6 的规则创建、更新或关闭 memory_session_cursor 的一行`

**一轮开始**
`MemoryGate.resolve(chat_id, scene, app_enabled) → 得到 MemoryContext（含 tenant_id、user_id、时区、turn_id）或 None → 非 None 时：MemoryService.resident(ctx) 给出常驻文本块；build_memory_tools(ctx) 给出两个工具`

**写入（显式）**
`模型调用 memory_write → MemoryService.write → 校验（长度、类型、SensitiveContentGuard、相对时间检查）→ 详情对象 PUT（如有）→ 事务：条目 INSERT + 被取代条目条件 UPDATE + rev 加一 + 本轮记录一行 → 同步建索引（失败置 pending）→ 审计 → 返回 → 接入点下发 memory 信号`

**一轮结束**
`接入点对工具事件脱敏后落消息 → MemoryService.bind_turn(turn_id, message_id) → MemoryActivity.end_turn(chat_id, last_message_id, enabled)`

**写入（自动整理）**
`Beat 扫描登记表 → 按用户投任务 → 取用户锁 → 对每个到期会话：重新判定启用 → 读水位之后、终点之前的消息 → 模型给出候选 → 代码校验 → 与现有有效条目比对（重复/矛盾）→ 事务：落条目 + 调整常驻 + 推进水位 + rev 加一 → 建索引`

**读取（检索）**
`memory_search 或记忆检索节点 → MemoryService.search(ctx, query, limit) → 关键词与向量两路（同一过滤函数）→ 倒数排名融合 → pending 条目追加 → 回表校验 → 计数 → 返回`。模型工具另把取回的 id 记入本轮记录；检索节点不记。

**相对时间（AC-14）。** 换算由模型完成，校验由代码完成：工具说明里给出用户时区下的今天日期，要求内容与 `event_time` 都用具体日期；`MemoryService` 落库前用一组确定的模式检查内容里是否残留相对时间词（今天、明天、下周几、本月、tomorrow、next week 等），命中即拒绝并返回原因码，模型据此改写后重试。自动整理与手动新增走同一检查。

### 4.2 关键数据结构

新表六张。全部带 `tenant_id` 并登记进 `tenant_filter` 的模型模块列表；JSON 用 `dialect_helpers.JsonType`，长文本用 `LargeText`；全部走 Alembic，`assistant` 表加列同样走 Alembic 并带 `server_default`。

| 表 | 一行是什么 | 关键列 |
|---|---|---|
| `memory_item` | 一条记忆条目 | `id`（应用侧生成的 UUID）、`tenant_id`、`user_id`、`scope`（本期恒为 `personal`）、`type`（fact/preference/experience）、`content`、`status`（active/superseded/deleted）、`superseded_by`、`pinned`、`pin_order`、`event_time`、`valid_from`、`valid_to`、`recorded_at`、`origin`（explicit/auto/manual）、`source_scene`、`source_app_id`、`source_app_name`（写入时快照）、`source_chat_id`、`detail_object_key`、`detail_sha256`、`index_state`（ok/pending）、`index_model_id`（建索引时所用的 embedding 模型）、`last_read_at`、`detail_read_at` |
| `memory_session_cursor` | 一个会话的登记（一个 `chat_id` 一行） | `chat_id`、`tenant_id`、`user_id`、`eligible`、`timezone`、`last_activity_at`、`last_message_id`、`watermark_message_id`（创建时取会话当前最大消息 id）、`state`（idle/pending/running）、`locked_at`、`fail_count`、`next_run_at` |
| `memory_user_setting` | 一个用户在一个租户的记忆设置 | `tenant_id`、`user_id`、`enabled`、`timezone`、`rev` |
| `memory_turn_record` | 一轮对话里与记忆有关的一件事 | `turn_id`、`chat_id`、`message_id`（回答落库后补）、`tenant_id`、`user_id`、`kind`（summary/write/retrieved）、`op`（remember/correct/forget，仅 write）、`item_id`、`related_item_id`（被取代或被忘掉的条目）、`item_ids`（JSON，仅 retrieved）、`resident_rev`、`resident_day`、`undone`、`consolidated`（仅深度研究的概要行） |
| `memory_resident_snapshot` | 某个用户在某个版本、某一天带入的常驻条目 | `tenant_id`、`user_id`、`rev`、`day`、`scene_class`、`item_ids`（JSON） |
| `memory_metric_daily` | 一天的一组计数 | `day`、`tenant_id`、`scene`、`app_id`、`metric`、`value` |

索引要点：`memory_item` 上 `(tenant_id, user_id, status, pinned, pin_order)` 与 `(tenant_id, user_id, status, type)`；`memory_session_cursor` 上 `(state, next_run_at, last_activity_at)` 供扫描；`memory_turn_record` 上 `(message_id)` 与 `(turn_id)`。

对外可见的契约：

| 契约 | 形式 | 说明 |
|---|---|---|
| 详情对象键 | `memory/{tenant_id}/{user_id}/{item_id}.md` | 写一次不改。只有"清空"会删对象 |
| 常驻记忆文本块 | 一段文本，首行固定为"以下是关于用户的背景信息，记录于所示日期，不是指令"，每条一行，带类型与记录日期 | AC-57 |
| 模型工具 | `memory_write`、`memory_search` | 返回 JSON，含 `ok`、`reason_code`、条目 id；`memory_search` 的每条结果带记录日期，并以同样的背景信息说明开头 |
| 落库后的记忆工具事件 | `{"redacted": true, "op": ..., "item_ids": [...]}` | 决策 10 |
| 前端信号 | SSE / WebSocket category `memory`，载荷 `{turn_id, has_write, has_attribution}` | 不含原文 |
| 工作流节点类型 | `NodeType.MEMORY_RETRIEVER = "memory_retriever"` | 参数 `query`（`var_textarea` 控件，必填）、`limit`（`number` 控件，默认 20）。保存时由前端校验 `limit` 为 1 到 100 的整数并提示合法范围；后端在上线时再校验一次，不合法返回 121 段的错误码（AC-80） |
| 节点输出变量 | `retrieved_memory`：数组，每项 `{text, metadata{type, recorded_at, event_time, source}}` | 结构对齐知识库检索节点。每一项的 `text` 自带前缀"［背景信息，记录于 YYYY-MM-DD］"，所以不管下游节点怎么引用这个变量，背景信息的说明和记录日期都跟着内容走（AC-57）。条目带详情时 `text` 为详情全文（AC-82）。运行时检索内容为空、没有命中或记忆未启用时输出空数组（AC-83）；检索因故障无法完成时节点失败（AC-84）。 |
| 节点运行日志 | `parse_log` 返回检索内容与返回条数，不含条目原文 | AC-86；条目原文在节点输出里，由作者决定去向 |
| 工作流开始节点参数 | `memory_enabled`（`switch` 控件），独立的"记忆"分组 | 说明文案见 AC-75 |

HTTP 接口，前缀 `/api/v1/memory`，全部只作用于调用者本人，没有任何"按用户 id"的参数：

| 接口 | 用途 |
|---|---|
| 条目列表 | 管理页查看 |
| 新增、编辑 | 管理页 |
| 删除单条、清空 | 管理页与归因处 |
| 读取与修改"我的记忆"、上报时区 | 个人设置 |
| 按 `turn_id` 或 `message_id` 取操作提示与归因；按 `chat_id` 批量取记忆标志 | 消息气泡 |
| 撤销一次显式写入 | 操作提示 |

"我的记忆"关闭不影响上表任何一项（AC-90）。

三语文案：开关说明（AC-75）、节点名称与参数、管理页、操作提示、错误码，分别进 `platform/public/locales/*/{bs,flow}.json`、`client/src/locales/*/translation.json`、`packages/locales/src/api_errors/*`。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `memory/domain/services/memory_service.py` | 唯一业务入口：write、search、resident、experience、list、edit、delete、clear、undo、bind_turn | 不直接写 ORM；不知道场景细节 |
| `memory/domain/services/gate.py` | `MemoryGate.open` / `resolve`：资格登记与启用判定 | 不读写条目 |
| `memory/domain/services/guard.py` | `SensitiveContentGuard`、长度与类型校验、工具事件脱敏 | 不调用模型 |
| `memory/domain/services/consolidator.py` | 整理一个用户的到期会话 | 不决定何时运行 |
| `memory/domain/services/activity.py` | `MemoryActivity.end_turn` | 不触发整理 |
| `memory/domain/services/tools.py` | 模型工具工厂 | 不做启用判定（调用方先过 gate） |
| `memory/domain/services/index.py` | ES / Milvus 的写入、删除、检索、融合、重建；唯一的过滤条件生成函数 | 不作为事实源 |
| `memory/domain/repositories/*` | 六张表的数据访问；按决策 9 显式带租户与用户条件 | 不含业务规则 |
| `memory/api/endpoints/*` | 本人的管理接口 | 不暴露按用户 id 查询 |
| `memory/domain/ports.py` | 三个接口：`MemoryIndex`、`DetailStore`、`MemoryLLM` | 不含实现 |
| `worker/memory/*` | 五个任务：扫描、整理、对账（补建待建索引、换模型后重建、清理孤儿详情对象）、指标落库、遗留本轮记录清理 | 不含业务规则 |
| `workflow/nodes/memory_retriever/` | 记忆检索节点 | 不做启用判定以外的权限判断 |

**分层（C1）。** 四个场景的 Service 层调用 `memory` 的 domain service，属于 Service 调 Service，合规。`common/` 不得引用领域模块，所以 `common/chat/client.py` 里不出现任何对 `memory` 的引用：助手的每轮处理和落库后的回调都通过 `AssistantAgent` 的方法完成（决策 11、决策 15）。`api/v1/callback.py` 属于 API 层，可以调用 `memory` 的脱敏函数。`scripts/arch-guard.sh` 的领域模块名单是固定列表，目前不含 `memory`，所以 `common/` 引用 `memory` 不会被自动拦住；落码时把 `memory` 加进这个名单。

### 4.4 已取证的接入点（基线 `feat/3.0.0@741662475b`）

路径省略前缀 `src/backend/bisheng/`。行号由 design 审查核对过，前端行号区间未逐一核对。

| 接入点 | 位置 | 要做的事 |
|---|---|---|
| 日常模式：对话入口 | `workstation/api/endpoints/chat.py:97` → `chat_service.py:2634` | 在 endpoint 里调 `MemoryGate.open`。**不在** `stream_chat_completion` 里调：开放 API 的入口 `open_endpoints/api/endpoints/workstation.py:66-97` 也进这个函数 |
| 日常模式：系统提示词 | `chat_service.py:2099-2111` | 追加常驻记忆文本块 |
| 日常模式：无工具直连分支 | `chat_service.py:2407-2411` | 同样带上常驻记忆。记忆已启用时工具列表恒非空，此分支实际不会走到，但两条分支都要测 |
| 日常模式：工具组装 | `_prepare_tools`（`:1268`，调用处 `:2013`） | 追加记忆工具 |
| 日常模式：工具事件 | `chat_service.py:2311-2319`（入参）、`:2343-2344`（返回） | 记忆工具的事件在写入 `events` 前脱敏 |
| 日常模式：流式事件 | `workstation/domain/services/chat_helpers.py:153` `_sse_resp` | 新增 category `memory`。事件类别是字符串字面量，没有集中枚举 |
| 日常模式：一轮结束 | `chat_service.py:2558-2575`；中断路径 `:1955-1980` | 两处都调 `bind_turn` 与 `end_turn` |
| 助手：建连与会话切换 | 登录态 WebSocket endpoint → `chat_manager.dispatch_client` → `common/chat/client.py:230`、`:361-372` | 登录态 endpoint 注入登记回调；`ChatClient` 在 `chat_id` 确定或切换时调用（**V2**）。免登录 `public_endpoints/api/endpoints/assistant.py:45` 与开放面 `open_endpoints/api/endpoints/assistant.py:160` 不注入 |
| 助手：每轮调用 | `api/services/assistant_agent.py:576` `run`、`:605` `astream`；裁剪 `:548-572` | 每轮：重读开关、启用判定、必要时重建 agent、裁剪后插入常驻记忆系统消息；`run()` 返回前对工具消息脱敏 |
| 助手：工具 | `assistant_agent.py:285` `init_tools` | 启用时追加记忆工具；两种执行器（ReAct、function call，`:445-458`）都要验证 |
| 助手：工具消息落库（路径一） | `common/chat/client.py:391-405` | 行由 `run()` 返回值构造，已脱敏 |
| 助手：工具消息落库（路径二） | `api/v1/callback.py:472-495`、`:523-545`、`:572-585`；挂载 `client.py:308-322` | 回调处理器内脱敏（V1） |
| 助手：回答落库 | `client.py:427-428`；中断 `:337-354`、`:461-465` | 落库后调 `AssistantAgent.after_answer_persisted` |
| 工作流：入口 | 登录态 WebSocket endpoint → `common/chat/clients/workflow_client.py:97-98`、`:171-179`；任务体 `worker/workflow/tasks.py:62` | 同助手：endpoint 注入登记回调，`WorkflowClient` 在拿到消息体里的 `chat_id` 时调用（**V8**）。评测与调试运行 `chat_id` 为空，不登记 |
| 工作流：节点注册 | `workflow/common/node.py:8-24`、`workflow/nodes/node_manage.py` | 新增类型与节点类 |
| 工作流：实例化 | `workflow/graph/graph_engine.py:207-231` | 按 `flow_id` 查上线版本的开关，与本次运行的 `chat_id` 一起放进 `graph_state`（V4、V8） |
| 工作流：节点拿身份 | `workflow/nodes/base.py:39,49` | 节点不用 `self.user_id` 判定资格，按 `chat_id` 查登记行 |
| 工作流：上线校验 | `api/services/workflow.py:1219`，ONLINE 分支 `:1237-1244` | 加"含记忆检索节点而开关为关则拒绝"与 `limit` 校验；前端 `useNodeEvent.ts` 同步提示 |
| 工作流：一轮结束 | `worker/workflow/tasks.py:40-55` | 任务函数每次让出控制时调一次 `end_turn`：停在等待输入（INPUT）返回时，以及成功或失败结束时。不在 `redis_callback.save_chat_message` 里调，它每条消息都会触发 |
| 深度研究：入口 | `linsight/api/endpoints/linsight.py:174`、`:327`、`:390` | 与日常模式同一个 `chat_id`，三个 endpoint 都调 `MemoryGate.open`。开放面 `open_api/domain/services/task_mode_service.py:292-307` 与无人值守运行不登记 |
| 深度研究：常驻与经验带入 | `linsight/domain/services/agent_factory.py:1400` `create_linsight_agent`，中间件 `:222-259`、`:1559-1564` | 新增一个中间件，排在两个尾部中间件之前；文本任务开始时取一次 |
| 深度研究：步骤落库 | `linsight/domain/services/stream_event_mapper.py:631`、`:662`、`:700-712` → `linsight_execute_task.history`；读取 `linsight/api/endpoints/linsight.py:579-615` | 落库前脱敏（V3） |
| 深度研究：工具 | `_generate_tools` 定义在 `task_exec.py:1097`，调用点 `:537`、`:668`、`:749` | 三个调用点之后都追加记忆工具；按 `linsight/AGENTS.md`，提示词与工具同步出现 |
| 深度研究：每一轮的开始与结束 | 首次提交与追问 `linsight/api/endpoints/linsight.py:174`、`:327`；任务行原地更新 `linsight/domain/utils.py:973-1019`；结束 `task_exec.py:2440`、`:2369`、`:1990`、`:2075` | 每一轮开始时建本轮概要行并生成 `turn_id`；结束时调 `end_turn`（V7） |
| 会话与消息 | `database/models/session.py:20/81`（含 `is_delete`）、`database/models/message.py:35/90` | 整理按 `chat_id` 读 `chatmessage`；深度研究轮次是同一会话里 `category='task'` 的行 |
| 用户停用 | 入口至少六处，没有统一回调 | 不挂钩子；`MemoryGate.resolve` 每轮读用户状态（AC-99） |
| 租户归属变化 | `tenant/domain/services/user_tenant_sync_service.py:76` | 不挂钩子；靠决策 9 的显式过滤满足 AC-06、AC-07 |
| 应用删除 | 助手软删 `api/services/assistant.py:419`；工作流硬删 `database/models/flow.py:211` | 不挂钩子；来源名称已快照 |
| 审计 | `database/models/audit_log.py:531` `AuditLogDao.ainsert_v2` | 动作名 `memory.item.*`，`metadata` 不放内容 |
| 工作台配置 | `workstation/domain/services/workstation_service.py:57/247`；`api/v1/schemas.py` `WorkstationConfig` | 加 `memory_model_id` 字段 |
| 额度 | `dsh/domain/services/chat_credits.py:20-23,57-60`；`llm/domain/services/llm.py:1407-1412,1457-1464` | 记忆的调用不扣个人额度，按租户记用量（决策 18） |
| 前端：工作流节点 | `platform/src/controllers/API/workflow.ts:185`、`pages/BuildPage/flow/FlowNode/Parameter.tsx`、`FlowNode/NodeLogo.tsx`、`public/locales/*/flow.json` | 新增节点四处都要改 |
| 前端：助手设置 | `platform/src/pages/BuildPage/assistant/editAssistant/Setting.tsx`（`knowledge_auth` 开关是样板） | 新增开关与说明 |
| 前端：工作台配置 | `platform/src/pages/BuildPage/bench/index.tsx`、`DailyChatConfig.tsx` | 新增一项"记忆整理使用的模型"下拉，没有开关 |
| 前端：日常模式气泡 | `client/src/components/Chat/AiMessageBubble.tsx`；SSE 解析 `client/src/hooks/useAiChatSSE.ts`；工具卡片 `Messages/ToolCallDisplay.tsx` | 操作提示与归因入口；记忆工具的卡片按脱敏后的格式渲染 |
| 前端：应用聊天 | `client/src/pages/appChat/ChatMessages.tsx`、`components/ClientMessageFooter.tsx` | 同上，第二套 |
| 前端：深度研究结果 | `client/src/components/Linsight/Execution/ResultPanel.tsx`、`TaskTurnPanel.tsx` | 操作提示（含撤销）与归因入口，按该轮的 `turn_id` 取数。这是第三处接入 |
| 前端：个人设置 | `client/src/pages/settings/settingsSections.ts`、`SettingsPage.tsx`；样板 `sections/AiAccessPane.tsx` | 新增"记忆" section |
| 前端：管理端查看会话 | `platform/src/pages/LogPage/useAppLog/appChatDetail.tsx`、`dailyChatDetail.tsx`、`LabelPage/taskAppChats.tsx` | 不接记忆接口。它们渲染到脱敏后的记忆工具事件时显示为"记忆操作"，不显示内容 |

### 4.5 实现后的现状（2026-11-13）

路径省略前缀 `src/backend/bisheng/`。行号会漂移，这里只列文件与函数。

| 部分 | 实际位置 | 说明 |
|---|---|---|
| 接口与上下文 | `memory/domain/ports.py` | `MemoryContext`、`build_scope_filter`、三个 Protocol |
| 资格与启用 | `memory/domain/services/gate.py`、`repositories/cursor_repository.py` | `open` 核对会话归属；`resolve` / `resolve_sync` 按登记行构造上下文 |
| 条目写入与管理 | `memory/domain/services/memory_service.py` | `write`、`add_manual`、`edit`、`delete`、`clear`、`undo`、`apply_operations`（整理）|
| 常驻与经验 | `memory/domain/services/resident.py` | Redis 缓存键含 `rev` 与用户时区日期 |
| 检索 | `memory/domain/services/search.py`、`index.py` | 倒数排名融合、待建索引追加、回表校验；ES `bisheng_memory_item`、Milvus `bisheng_memory_item_{model}` |
| 模型工具与脱敏 | `memory/domain/services/tools.py`、`redaction.py` | `memory_write` / `memory_search`；`redact_tool_event`、`is_memory_tool_output` |
| 本轮记录 | `memory/domain/services/turn_record.py`、`views.py` | `/api/v1/memory/turn` 与 `/flags` 的数据 |
| 自动整理 | `memory/domain/services/consolidator.py`、`consolidation_content.py`、`consolidation_prompt.py`、`consolidation_linsight.py`、`app_switch.py` | 附加步骤：深度研究轮次整理、过期事件改写（P1）|
| 装配 | `memory/domain/services/factory.py` | 全部接入点从这里取服务实例 |
| 定时任务 | `worker/memory/tasks.py`、`memory/domain/services/reconcile.py`；调度项在 `core/config/settings.py` | 扫描每分钟触发、按部署配置的扫描周期自行节流 |
| 管理接口 | `memory/api/endpoints/memory.py` | `/api/v1/memory/*`，只作用于本人 |
| 日常模式 | `workstation/domain/services/daily_memory.py`；`workstation/api/endpoints/chat.py` 注入 `memory_register`；`chat_service.py` 调用 | 日常入口的任务模式经 `task_submit_service.submit_task_turn(on_session_created=...)` 登记 |
| 助手 | `api/services/assistant_memory.py`、`assistant_agent.py`、`api/v1/callback.py`（按 `run_id` 脱敏，含 `intermediate_steps`）、`common/chat/client.py`（`memory_register` 与 `after_answer_persisted` 回调，不导入 memory）、`api/v1/assistant.py` | 每轮重读开关；R6 的注入方式 |
| 工作流 | `workflow/nodes/memory_retriever/`、`memory/domain/services/workflow_retrieval.py`、`workflow/graph/graph_state.py`（冻结字段）、`worker/workflow/tasks.py`（上线版本开关、`end_turn`）、`api/services/workflow.py`（上线校验）、`common/chat/clients/workflow_client.py`、`api/v1/workflow.py` | |
| 深度研究 | `linsight/domain/services/memory_turns.py`、`task_exec.py`（轮开始、三个入口的 finally、`_handle_exec_step` 脱敏、`_generate_tools`）、`agent_factory.py`（记忆中间件、子 agent 禁用）、`context_budget.py`、`workspace_backend.py`、`state_message_manager.py`（`MEMORY` 事件） | P-01、P-03 按保守做法 |
| 共用接线 | `common/chat/manager.py` `dispatch_client(memory_register=...)` | 只有登录态 endpoint 传值 |
| 前端 platform | `controllers/API/workflow.ts`、`util/workflowMemory.ts`、`assistant/editAssistant/Setting.tsx`、`bench/DailyChatConfig.tsx`、`PlatformConversationMessages.tsx`、`dailyChatDetail.tsx` | |
| 前端 client | `api/memory.ts`、`hooks/useMemoryTimezone.ts`、`pages/settings/sections/MemoryPane.tsx`、`components/Chat/MemoryNotice.tsx`、`pages/appChat/appMemory.ts`、`components/Linsight/Execution/ResultPanel.tsx` | |

各 Wave 的实现细节与偏差记录在 `wave-notes/`。真实模型端点上多条系统消息的兼容性（V5 的后半）仍待 T094。

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 租户自动过滤给普通用户的是可见租户 IN 列表，给全局超管的是不过滤，并且只拦 SELECT | 调岗用户仍读到原租户的记忆；超管读到别的租户里同 id 的行；批量写跨租户生效 | 决策 9：repository 每个方法显式带租户与用户条件 |
| 2 | 各场景会把工具入参与返回原样落进消息，管理端接口原样返回 | 管理员翻会话就看到记忆原文 | 决策 10：落点清单里的每一处都调同一个脱敏函数 |
| 3 | 下游只有整型 `user_id`，分不出自然人、服务账号、访客配置 | 给不该有记忆的调用开了记忆 | 决策 6：入口登记，下游只查登记行 |
| 4 | 助手 agent 在连接内只建一次 | 常驻记忆不更新、开关改了不生效 | 决策 11：调用时注入，开关状态变化时重建 |
| 5 | 深度研究的首条消息有两处拼装，写进消息的文本会留在检查点线程里 | 续轮没有常驻记忆；已删除的记忆仍对模型可见 | 决策 11：中间件注入 |
| 6 | 深度研究的工具拼装有三个调用点（`task_exec.py:537`、`:668`、`:749`） | 只改一处，续跑的任务没有记忆工具 | 三处都改 |
| 7 | 深度研究轮次与日常模式共用 `chat_id`；任务行先插空占位、完成时原地更新 | 一个会话两个水位；水位越过占位行后，任务结果永远不被整理 | 决策 7：登记按 `chat_id` 一行；水位不越过未完成的任务行 |
| 8 | 写入工具被调用时，回答的消息行还没有插入 | 用 `message_id` 关联会拿到空值 | 决策 15：按 `turn_id` 记录，落库时补 `message_id`，中断路径也要补 |
| 9 | Beat 任务触发时没有租户上下文；直接调用任务函数体会跳过 `task_prerun` | 扫描查询报缺租户上下文；本地直调得出"调度坏了"的错误结论 | 枚举查询包 `bypass_tenant_filter()`，逐租户设置上下文；投任务时 `headers={"tenant_id": tid}` |
| 10 | 条目在关系库、详情在对象存储，没有事务 | 先插行后写对象，中途失败会留下指向不存在对象的条目 | 先写对象再插行；读取详情失败按 AC-62 降级并计数；孤儿对象由对账任务清理 |
| 11 | 助手用 `prompt` 字段，不是 `system_prompt` | 以为改 `system_prompt` 能影响助手 | 本设计不动这两个字段 |
| 12 | 助手没有版本表；工作流硬删 `flow` 行 | 以为助手开关随版本发布；删除工作流后来源名称查不到 | 决策 17；来源名称写入时快照 |
| 13 | 工作流节点模板写死在前端常量里 | 只加后端节点类，编辑器里看不到节点 | 前端四处同步改 |
| 14 | `core/vectorstore/multi_retriever.py` 不做关键词与向量的融合，且一路失败整体抛错 | 复用它会得到不可比的分数排序和脆弱的降级 | 决策 12：自己实现融合 |
| 15 | `settings.aget_from_db` 缺键时返回空字典 | 存量部署读不到新参数，行为未定义 | 决策 19：代码自带默认值 |
| 16 | Milvus 的向量维度随 embedding 模型而定 | 租户换 embedding 后检索报错或全不命中 | 按模型分 collection，提供重建任务 |
| 17 | 错误码要写成 `Code: int = NNNNN` 并同批进三语文案 | `check-i18n` 不识别，CI 失败 | 落码时按 C5 |
| 18 | client 跑 jest 前执行 `pnpm install` 会让全部测试起不来 | 前端测试整体失败 | 见 `src/frontend/client/AGENTS.md` |
| 19 | 登录用户与开放 API 的调用共用 `stream_chat_completion` 等 Service 函数 | 在 Service 里登记资格，会给服务账号开记忆 | 决策 6：登记只做在登录态的 endpoint |
| 20 | 助手的工具调用有两条落库路径，其中一条由 LangChain 回调直接插库 | 只在 `run()` 返回值上脱敏，回调那条路径照样把记忆原文存进消息 | 决策 10 的落点清单 |
| 21 | 深度研究的步骤入参与输出会落进 `linsight_execute_task.history`，持分享链接的人可读 | 分享一个任务就把记忆原文分享出去了 | 决策 10 |
| 22 | 助手连接持有的助手对象在连接期内不重读 | 作者关掉助手记忆后，已建立的连接仍按开启处理 | 决策 11：每轮重读开关 |
| 23 | 助手的 `trim_messages` 从消息列表头部开始丢 | 常驻记忆先插后裁会最先被丢掉 | 决策 11：裁剪之后再插入 |
| 24 | 日常模式的中断落库路径是同步函数，里面 `await` 会被取消 | 用异步方法补本轮记录，中断时静默丢失 | 决策 15：提供同步实现 |
| 26 | 深度研究的追问轮不插新消息行，问题也不落消息表 | 用消息 id 当水位，追问轮永远不会被整理；多轮的操作提示挂在同一个消息上混在一起 | 决策 7：以任务轮为整理单位；决策 15：按 `turn_id` 取 |
| 27 | 助手与工作流的 `chat_id` 由连接内的消息送达，处理它的客户端类同时服务免登录与开放 API | 在客户端类里直接登记，会给免登录和开放 API 的连接开记忆 | 决策 6：登录态 endpoint 注入回调 |
| 28 | 登录态路径上工作流执行的图来自客户端消息 | 读正在执行的图上的开关，使用者可以自带一个开着的图绕过作者的设置 | 决策 17：读数据库里的上线版本 |
| 25 | 对话型工作流停在等待输入时任务函数已返回，但工作流没有结束 | 只在成功或失败时登记活跃，这类会话永远不会被整理 | §4.4"工作流：一轮结束" |
| 29 | 日常模式新会话的 `chat_id` 在 endpoint 层还不存在，要到服务里插入问题行时才确定 | 在 endpoint 里直接调 `MemoryGate.open` 登记不到新会话，首轮没有记忆 | endpoint 只构造 `memory_register` 回调，服务在插入本轮问题行之前调用（`daily_memory.register_session`）|
| 30 | 助手 WebSocket 的 `ChatResponse` 对 `type` 有校验，不接受 `memory` | 用 `ChatResponse` 发记忆信号会抛校验错误、这一轮中断 | `callback.send_memory_signal` 直接发 `{category: "memory", type: "memory", message: {...}}` 帧，前端 `appMemory.isMemoryFrame` 按此识别 |
| 31 | 深度研究的任务 WebSocket 在 `FINAL_RESULT` 后关闭 | 只在一轮结束时下发记忆事件，前端收不到 | 写入成功、记忆工具结束、一轮结束三处下发，去重 |
| 32 | 流式模型的工具调用第一个分片只有名字和 id，参数后到；深度研究落库的普通工具 `params` 是 `{}` | 脱敏函数假定入参里一定有 `action`/`query` 会出错 | `redact_tool_event` 对空入参返回只含 `op` 的结构 |
| 33 | 测试进程里别的套件会留下租户 ContextVar；`MemoryGate.open` 按当前租户登记 | 合跑时测试的会话登记到别的租户，记忆读不到（单跑通过） | 记忆相关测试夹具显式固定租户（`test/workstation/memory_support.py`、`test/memory/conftest.py` 的会话接缝绕过租户自动过滤）|

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `/api/v1/memory/**` | HTTP API，只作用于调用者本人 | client 个人设置、client 两套消息气泡 |
| `MemoryGate.open` / `resolve`、`MemoryService.resident` / `experience` / `bind_turn`、`build_memory_tools`、`MemoryActivity.end_turn`、工具事件脱敏函数 | 内部 Python API | 工作台、助手、深度研究、工作流的接入点 |
| `memory_retriever` 节点类型与输出结构 | 工作流节点契约 | 工作流作者的下游节点 |
| `memory` SSE / WebSocket 信号；脱敏后的记忆工具事件格式 | 流式事件与落库格式 | client 两套渲染、platform 管理端回放 |
| `ChatManager.dispatch_client(memory_register=...)`、`ChatClient` / `BaseClient.memory_register` | 内部 Python API（可调用对象注入） | 登录态助手与工作流 WebSocket endpoint；免登录与开放面不传 |
| `submit_task_turn(..., on_session_created=...)` | 内部 Python API（`workstation/domain/services/task_submit_service.py`） | 日常入口的任务模式登记；开放 API 不传 |
| `create_linsight_agent(..., memory_prompt=...)` | 内部 Python API（`linsight/domain/services/agent_factory.py`） | 深度研究的记忆中间件 |
| 助手 WebSocket 记忆帧 `{category: "memory", type: "memory", message: {turn_id, has_write, has_attribution}}`；深度研究 `MessageEventType.MEMORY` | 流式事件 | client 应用聊天与深度研究结果面板 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `chatmessage` 按 `chat_id` 可读，`category` 能区分用户输入、系统输出、深度研究任务行及其终态 | 隐式数据契约 | 任一场景改消息格式，整理会读不懂或水位判断出错；每个场景要有一条整理的集成测试 |
| 各场景的工具事件落库点 | 代码位置 | 新增一种落库路径而没有调脱敏函数，就是一处泄漏；要有覆盖三个场景的断言 |
| `WorkstationConfig` 与工作台配置接口 | 结构与接口 | 该结构改形态时 `memory_model_id` 字段要同步 |
| 知识库默认 embedding、`MilvusFactory`、`ElasticsearchFactory` | 内部 API | 属于知识库模块，记忆不得改变它们的行为 |
| `AuditLogDao.ainsert_v2` | 内部 API | 动作名需登记 |
| 租户上下文（`get_current_tenant_id`、`bypass_tenant_filter`） | 内部 API | "当前租户"的语义变化会直接影响隔离 |
| 模型调用的额度机制 | `dsh/domain/services/chat_credits.py` | 记忆的调用要绕开个人额度扣减；该机制改形态时要复核 |
| 引用呈现组件（F075） | 前端组件 | 归因沿用其样式，不沿用其数据通道 |

**在其他 Owner 的对象上新增的写入点**（`release-contract.md` 的 F132 段同步）：审计记录；`WorkstationConfig` 的 `memory_model_id` 字段；`assistant.memory_enabled` 列；工作流开始节点参数、实例化时的 `graph_state` 字段与上线校验；三个场景的工具事件落库处；client 个人设置的新 section。管理端查看会话的页面只多一种"记忆操作"的占位渲染。

---

## 7. 测试与可观测

| 层 | 覆盖 | 位置 |
|---|---|---|
| 单元 | guard 规则、时间换算、常驻截取与缓存键、启用判定的全部组合、条目状态机（含三种撤销及其边界）、倒数排名融合、工具事件脱敏 | `src/backend/test/memory/` |
| 服务级（需数据库） | 隔离（两用户、两租户、可见多租户、全局超管）、并发写入不丢、整理的水位与幂等与崩溃恢复、开关关闭期间的消息不被整理、生命周期各事件、审计 | 同上 |
| 接入点 | 四个场景各一组：启用时有带入和工具，未启用或无登记时都没有；落库后的消息里没有记忆原文；工作流节点的参数校验、输出、空结果、故障、上线校验 | 各模块现有测试目录 |
| 前端 | 节点参数面板、助手与工作台开关、个人设置记忆页、两套气泡的提示与归因入口、管理端页面不请求记忆接口 | platform 用 Vitest，client 用 Jest |
| 评测集 | 全部〔评〕条目，以及"带记忆/不带记忆"对比 | `tools/memory_eval/`，做法沿用 `tools/taskmode_eval/` |

spec 中标〔测〕的验收标准，每一条都要有至少一个标注其编号的测试，供 tasks.md 追溯。〔测〕类测试里模型一律用桩。

**DM8。** 按 C2，由方言辅助与评审保证，集中回归验证，不在本功能的门禁里。

**可观测。** 整理失败、带入失败、检索失败、检索降级、详情读取失败、索引待重试各有结构化日志与计数，进 `memory_metric_daily`。

**手动验证。** 环境地址与账号见 `.claude/docs/dev-environments.md` 的 test 环境一节。用两个非管理员账号加一个租户管理员账号走以下各步：
1. 账号甲在日常模式说"记一下我下周二有个会"，确认出现操作提示并能展开；新开会话问本周安排能答出日期。
2. 在操作提示上撤销，新会话里不再知道这件事。
3. 账号甲进入一个开启了记忆的助手，问到同一类信息能答出；账号乙在同一个助手里问不到。
4. 建一个含记忆检索节点的工作流，开关关闭时上线被拒；开启后运行，节点输出里有账号甲的记忆，换账号乙运行输出为空。
5. 账号甲发起一个深度研究任务，确认任务里带入了常驻记忆。
6. 租户管理员在管理端打开账号甲的上述会话，确认看不到记忆条目原文，只看到"记忆操作"占位。

---

## 8. 后续改进 / 不打算做的事

- 密钥类内容的规则会漏报，不用模型审查补（决策 14）。
- 归因不区分常驻记忆中哪条起了作用（决策 16）。
- 没有重排（决策 12）。
- 整理延迟的下限是安静期加一个扫描周期（决策 19）。
- 删除是软删除，被删除条目的行与详情对象保留到用户"清空"为止（决策 4）。
- 没有任何由系统发起的清除：停用用户、调走用户的记忆一直保留（决策 22）。
- 模型在回答正文里复述的记忆内容，对能查看该会话的人可见。
- 深度研究里已经检索过的记忆，被删除后在同一个任务线程里仍可能对模型可见（决策 11）。
- 助手下一轮看不到上一轮检索到的非常驻条目，需要时会重新检索（决策 10）。
- 进程崩溃时，当轮的操作提示在刷新后丢失，条目本身不受影响（决策 15）。
- 停在"等待用户补充"超过 24 小时的深度研究任务，其内容不会被整理（决策 7）。
- 开放 API、免登录链接、评测与调试运行都不使用记忆（决策 6）。
- 深度研究上下文压缩生成的摘要可能复述记忆内容，与回答正文复述同级（R4）。
- 日常模式在记忆开启时一定带两个记忆工具，所以原本不选任何工具的对话也会走工具调用分支：不支持函数调用的模型（例如未开启 tool choice 的本地 vLLM）在记忆开启时会报错；每轮多一次 agent 循环的时延。这是 AC-28（日常模式提供显式写入能力）的直接后果，处理方式是对这类模型关闭"我的记忆"或换支持函数调用的模型（代码审查 MEDIUM，未改代码）。
- 回调与 ReAct 的 debug 级日志在脱敏之前打印工具入参与输出，开启 DEBUG 时记忆原文会进入日志（与决策 10 已列的调试开关同级）。
- 助手同一连接上并发的两条消息共用一个 `AssistantAgent`，记忆上下文可能串到另一轮（原有的共用 agent 问题，F132 加大了影响）。
- 深度研究经 `/workbench/continue` 追问的轮次本期不自动整理（P-01，按保守做法）。
- `BISHENG_AGENT_DUMP`、`BISHENG_RECORD_HISTORY` 与 debug 日志会带出提示词和工具内容，默认关闭，本期不处理（决策 10）。
- 遗忘、信念、实体关系、组织级记忆：见 spec 排除项。

---

## 9. 设计阶段的偏差与裁定

**已裁定（2026-11-13）。**

| # | 偏差 | 原口径 | 裁定 | 落点 |
|---|---|---|---|---|
| 1 | 详情不复用深度研究的工作区后端，改为不可变对象 | PRD 附录 A.3、调研结构版 §7.3 | 采纳 | 决策 3 |
| 2 | 归因改为检索条目逐条列出、常驻记忆整份可查看 | spec AC-87 原文 | 采纳，AC-87 已改写 | 决策 16 |
| 3 | 实体关系表本期不建 | PRD D2 | 采纳 | 决策 21 |
| 4 | 账号删除在平台中没有触发点 | spec AC-100 | 本期不做，AC-100 移出 | 决策 22 |

**第 2 稿新增（第 5、6 项已于 2026-11-13 裁定，其余为知悉项）。**

| # | 事项 | 性质 | 落点 |
|---|---|---|---|
| 5 | 整理与 embedding 的模型调用是否计入用户个人额度 | 已裁定：不计个人额度，按租户记用量 | 决策 18 |
| 6 | 记忆的读写显式按"当前租户 + 本人"过滤，是对 C3"不手写租户条件"的一处显式例外 | 已同意 | 决策 9 |
| 7 | 删除是软删除，行与详情对象保留到用户清空；撤销在三种情况下会失败 | 请知悉。spec §3 需补这三种边界 | 决策 4 |
| 8 | 助手没有版本，助手记忆开关保存即生效 | 事实订正，spec AC-71 需改写 | 决策 17 |
| 9 | 管理端回放会话时，记忆工具的调用显示为"记忆操作"占位，不显示内容 | 请知悉。这是 AC-09 的实现方式 | 决策 10 |
| 10 | 工作台配置里增加"记忆整理使用的模型"；client 加载后向记忆接口上报浏览器时区 | 实现所需的新增项 | 决策 18、决策 13 |

**第 3 稿新增的裁定（2026-11-13）。**

| # | 事项 | 裁定 | 落点 |
|---|---|---|---|
| 11 | 开放 API 的调用是否支持记忆 | 本期都不支持，spec AC-11 移出 | 决策 6 |
| 12 | 助手回调落库、连接内切换会话、深度研究分享链接等不确定点 | 先做小实验再定，见 §10 | §10 |
| 13 | 是否保留租户级的记忆开关 | 去掉，只保留个人、助手、工作流三处；工作台配置里保留整理模型 | 决策 17 |

**Wave 0 验证后的实现修订（2026-11-13，结论与证据见 [verification.md](./verification.md)）。** 下列修订不改变任何验收标准的含义，方向都是更严或等价，按 goal-runbook §4 自行决定；唯一推翻原前提、需要用户确认的是 V7 的 `/continue` 路径（`pending-confirmation.md` P-01，目前按保守做法 C 实现）。

| # | 修订 | 影响的决策 | 来源 |
|---|---|---|---|
| R1 | 助手回调脱敏按 `run_id` 识别记忆工具（`on_tool_error` 拿不到工具名）；`intermediate_steps` 列同样脱敏；ReAct 执行器下回调是工具调用唯一的落库路径 | 决策 10 | V1、V6 |
| R2 | 登记回调经 `ChatManager.dispatch_client` 的新参数 `memory_register`（默认 `None`）传入，只有登录态的助手与工作流 WebSocket endpoint 传值；助手在 `ChatClient.init_gpts_agent` 开头调用（同时覆盖每轮与切换会话），工作流在 `WorkflowClient` 拿到 `chat_id` 后调用；助手的异常分支（不落回答）同样结束本轮 | 决策 6、15 | V2、V8 |
| R3 | 深度研究的步骤脱敏收敛到 `task_exec._handle_exec_step` 入口一处（同时覆盖数据库、Redis 任务键、WS 列表、乱序与子 agent 帧）；压缩写 `conversation_history/` 的实际位置是 deepagents 的 `_offload_to_backend`，在 `BishengSummarizationMiddleware` 上覆盖并先脱敏；大结果卸载三条路径都会把记忆工具结果写成工作区文件：BiSheng 预算中间件对 `memory_` 工具改为截断，`WorkspaceBackend.write/awrite` 拒绝写入以固定前缀开头的记忆工具输出；记忆工具加入子 agent 禁用名单（`_SUBAGENT_TOOL_DENY`），子 agent 不读写记忆 | 决策 10、11 | V3 |
| R4 | 压缩生成的摘要可能复述记忆内容，与"回答正文复述"同级，记入 §8 已知限制，不另做处理 | §8 | V3 |
| R5 | 工作流的开关不在 `GraphEngine.init_nodes` 里查（发布校验也会构造引擎，此时 `is_current` 仍是旧版本）；改在 `worker/workflow/tasks.py` 执行入口查询，经 `Workflow`、`GraphEngine` 传入 `GraphState` 的两个冻结字段 `chat_id`、`memory_enabled`；"上线版本"判定为 `flow_version.is_current=1` 且 `flow.status=2`；同一次运行停在等待输入后续跑，沿用首次取得的值 | 决策 17 | V4 |
| R6 | 助手注入常驻记忆：在 `run()` 里把裁剪结果先复制一份再插入系统消息，返回前按消息 id 剔除。原写法会因为三处原地修改同一个列表而只在裁剪发生时错位。插入位置是输入的最前面，紧接助手自己的系统提示词（代码审查后修订：插在中间会出现不相邻的多条系统消息，Anthropic 端点直接拒绝）；最后一条仍是问题，ReAct 不受影响 | 决策 11 | V5、代码审查 |
| R7 | 管理端：助手页与工作流页经 `/api/v1/session/chat/history` 渲染 `category=tool` 行，占位替换放在 `PlatformConversationMessages`（不改共享包），卡片标题也要替换；日常页只在 `msg` 为空时回落渲染原始 JSON（`dailyChatDetail.tsx`），占位放在那里 | 决策 10 | V6 |
| R8 | 深度研究的"轮"：主路径一轮 = 一个 svid = 一条任务消息行，任务消息行在轮开始前已插入；本轮概要行在 worker 里建（首轮在 `_execute_workflow` 写占位行之后，追问轮在 `_continue_workflow` 置为进行中之后，ask_user 恢复复用原 `turn_id`），按 svid 关联；一轮结束在 `async_run`、`async_resume`、`async_continue` 三个入口的 `finally` 一处调用（停在等待补充时跳过），覆盖原清单漏掉的失败与续轮终止；整理时经深度研究模块的 Service 按 svid 读 `question` 与 `output_result`；前端按 svid 取该轮的操作提示与归因。`/continue` 轮见 P-01 | 决策 7、15 | V7 |
| R9 | 深度研究的记忆工具在 `_generate_tools` 内部追加一次（覆盖三个调用点）；记忆中间件插在技能块之后、引用尾部之前 | 决策 11 | V7 |
| R10 | 代码审查后的资格修订：`MemoryGate.resolve` 增加 `actor_user_id`，登记行属于别人时返回空（防止知道他人 chat_id 的登录用户读写对方记忆）；登记行按主键读取、不经租户自动过滤（身份取自行本身）。助手只在登录态连接（`memory_register` 存在）上启用记忆；工作流只在 `source == "platform"` 的运行里启用记忆，开放 API 运行即使复用已登记的 chat_id 也不读写 | 决策 6 | 代码审查 |
| R11 | 代码审查后的整理修订：续期锁失败即停止并把未处理行交还；一次整理期间用户清空记忆则丢弃本次结果；超长积压只把水位推进到实际读入的最后一条；提示词里的已有条目最多 200 条；模型调用 300 秒超时；对账删除孤儿详情对象前有 1 小时宽限；过期事件改写保留来源、每条只尝试一次；被内容安全拦截的一轮推进水位、永不整理；脱敏只匹配两个内置记忆工具的确切名称 | 决策 4、5、7、10 | 代码审查 |

---

## 10. 待验证项（编码最前面做，结论写回本文）

每一项都用最小代码在本地跑通，判据是可观测的结果。验证不通过的，对应决策要改，并按 SDD-Guide §3 判断是否需要用户重新确认。

| # | 要验证什么 | 判据 | 不通过时影响 | 结论（2026-11-13） |
|---|---|---|---|---|
| V1 | 助手的工具回调（`api/v1/callback.py`）里能否在落库和下发之前识别记忆工具并脱敏 | 调用一次记忆工具后，`chatmessage` 里 `category=tool` 的行和 WebSocket 下发的消息都不含条目原文 | 决策 10 | 通过，见 R1 |
| V2 | 助手的登记回调：登录态连接在 `chat_id` 确定或切换时登记；免登录与开放 API 的连接不登记 | 登录态连接切换会话后首轮记忆能工作；免登录链接与开放 API 的助手连接无论如何切换，登记表里都不出现它们的 `chat_id` | 决策 6 | 通过，见 R2 |
| V3 | 深度研究的步骤事件在写入 `linsight_execute_task.history` 前能否脱敏；大工具结果卸载到工作区 `large_tool_results/` 时，`memory_search` 的结果会不会被写成工作区文件 | 调用一次记忆工具后，`history` 与工作区里都没有条目原文；用分享链接读取任务详情看不到条目原文；实际触发一次上下文压缩后，工作区 `conversation_history/` 下的文件里也没有条目原文 | 决策 10 | 通过，落点修订见 R3、R4 |
| V4 | 工作流节点能否从 `graph_state` 拿到 `chat_id` 与开始节点的 `memory_enabled` | 记忆检索节点在 Celery worker 里执行时两者都取得到；评测与调试运行取到空 | 决策 17 | 通过，位置修订见 R5 |
| V5 | 输入里带多条系统消息时，助手的两种执行器在平台已接入的主要模型端点上是否正常 | ReAct 与 function call 各跑通一轮，模型能用上常驻记忆里的信息 | 决策 11 | 本地通过（消息送达），实现修订见 R6；真实端点兼容性留 T094 |
| V7 | 深度研究追问轮的问题与结果存在哪里，能否按轮取出；前端每一轮的结果面板能否拿到该轮的 `turn_id` | 一个任务追问两次后，三轮各有一条本轮概要、各自被整理一次，三轮的操作提示互不混淆 | 决策 7、决策 15 | 前提部分推翻，见 R8 与 P-01 |
| V8 | 工作流的登记回调与开关取值：`chat_id` 来自消息体；开关读数据库的上线版本 | 登录态运行被登记而免登录与开放 API 不被登记；客户端自带一个开关为开的图时，数据库里开关为关则检索节点输出空数组 | 决策 6、决策 17 | 通过，见 R2、R5 |
| V6 | 管理端查看会话的三个页面实际调用哪些接口，是否读取 `category=tool` 的行与深度研究步骤 | 列出接口清单；用管理员账号打开一个含记忆操作的会话，页面上没有条目原文 | 决策 10 | 通过，见 R7 |

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-13 | 初版（设计草稿，未编码） | spec 第 2 稿确认后进入设计 |
| 2026-11-13 | `/sdd-code-review` 修复：R10（资格：本人校验、助手仅登录态、工作流仅平台来源）、R11（整理安全、脱敏范围、内容安全拦截），R6 注入位置修订，§8 补三条已知限制 | 代码审查 |
| 2026-11-13 | 实现完成：新增 §4.5 实现后的现状；Wave 8–13 由 6 个并行 worktree 实现后合并（各 Wave 记录见 wave-notes/） | 无人值守开发 T095 |
| 2026-11-13 | Wave 0 验证后的实现修订 R1–R9（§9 末），§10 写入结论；V7 的 `/continue` 路径待用户确认（P-01） | 无人值守开发 Wave 0 |
| 2026-11-13 | 第 5 稿：去掉租户级记忆开关，启用判定少一层；工作台配置只留整理模型一个字段 | 用户裁定 |
| 2026-11-13 | 拆任务时的三处细化：时区改为客户端一处上报；条目记录建索引所用的模型以支持换模型后重建；引入三个接口解开服务与索引的循环依赖 | `/sdd-review tasks` 第一轮 |
| 2026-11-13 | 第 4 稿：深度研究改为以任务轮为整理单位；助手与工作流改为由登录态 endpoint 注入登记回调；工作流开关读数据库上线版本；水位只增不减；检索节点的每条输出自带背景信息前缀；指标改为事件计数；新增 V7、V8 | 三轮 design 审查：原 6 个高严重度问题已解决或由待验证项覆盖，新发现 1 个高严重度问题 |
| 2026-11-13 | 第 3 稿：登记只做在登录态 endpoint 且开放 API 不支持记忆；脱敏落点补全助手回调与深度研究步骤；助手每轮重读开关、裁剪后注入；本轮记录的各场景落点；登记行的初值、并发写与清空；新增常驻快照表与待验证项 | 二轮 design 审查发现 6 个高严重度问题；用户裁定收窄范围并先做实验 |
| 2026-11-13 | 第 2 稿：新增入口登记（决策 6）、显式租户过滤（决策 9）、工具事件脱敏（决策 10）、调用时注入（决策 11）、软删除（决策 4）；整理的运行语义、缓存正确性、按轮记录、开关存储、检索融合全部重写 | design 审查发现 6 个高严重度问题 |
