# Design: 长期记忆

> **本文档定位 — 现状快照（Why this How）**。`spec.md` 回答做什么，本文回答为什么这么实现，`tasks.md` 是流水账。实现变化时覆盖更新本文，只留今天的状态。

**关联**: [spec.md](./spec.md) · [discovery.md](./discovery.md) · [tasks.md](./tasks.md)（待写）
**版本**: v3.0.0（开发基线）
**最后更新**: 2026-11-13（第 2 稿）
**状态**: 设计草稿第 2 稿，已按 2026-11-13 的 design 审查重写，待用户确认。本功能尚未编码：§4.1–§4.3 是**目标形态**，§4.4 是**已取证的接入点现状**（基线 `feat/3.0.0@741662475b`）。实现后按实际覆盖更新。

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
| K6 | 主体类型只在 API 入口可知。工作流节点、消息落库回调、深度研究 worker、Beat 任务手里只有一个整型 `user_id`；用户表没有主体类型列；免登录链接的配置里也带一个 `user_id` | `open_api/domain/services/identity_service.py:67-81`；`workflow/nodes/base.py:39`；`public_endpoints/domain/services/guest_link.py:35,72` | 不能在下游凭 `user_id` 判定"是不是一个确定的自然人"。资格必须在入口判定并持久化，下游只查结果，查不到即不工作 |
| K7 | 各场景会把工具调用的入参和返回落进消息：日常模式写进 `chatmessage.message` 的 `events`；助手把 tool_call、tool_result 各存一行。管理端的会话接口原样返回这些数据 | `workstation/domain/services/chat_service.py:2311-2319`、`:2343-2344`、`:2557-2560`；`common/chat/client.py:403-405`；`chat_session/api/endpoints/session.py:33-41` | 记忆工具的入参与返回如果照常落库，管理员翻会话就能看到记忆原文，违反 AC-09。记忆工具的事件必须在落库前脱敏 |
| K8 | 助手的 agent 在一个 WebSocket 连接内只构建一次，提示词和工具列表在连接期内固定 | `common/chat/client.py:235-256` | 常驻记忆和开关状态不能在构建时确定，必须每轮在调用时处理 |
| K9 | 深度研究的轮次落在日常会话的同一个 `chat_id` 里；任务行在开始时插入空占位、完成时原地更新 | `linsight/domain/services/workbench_impl.py:345-355`；`linsight/domain/utils.py:975-992` | 整理登记按 `chat_id` 一行，不按场景分；水位不能越过未完成的任务行 |
| K10 | 助手和工作流的会话不刷新 `message_session.update_time` | 只有工作台与深度研究调 `touch_session` | 安静期用记忆自己的登记判定 |
| K11 | 平台没有硬删除账号的路径；工作流删除是硬删 `flow` 行；助手没有版本表 | 全仓无删除用户实现；`database/models/flow.py:211`；全仓无 `assistant_version` | 账号删除时的清除本期不做（spec AC-100 已移出）；来源名称写入时快照；助手开关就地保存 |
| K12 | 用户表没有时区字段，现有提示词里的日期用服务器时间 | `chat_service.py:2105`；`linsight/domain/task_exec.py:1595` | AC-14 需要新的时区来源 |
| K13 | 消息渲染有三套：client 日常模式（SSE，自有气泡）、client 应用聊天（WebSocket，`@bisheng/chat` 共享组件）、platform 管理端查看会话 | 取证 §4.4 | 操作提示与归因在前两套各接一次；第三套不接 |

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
- **索引**：行提交后同步写 ES 与 Milvus。任一失败不回滚行，把条目的 `index_state` 置为 `pending`，由对账任务重试。检索时把该用户 `index_state='pending'` 的有效条目用关系库做一次子串匹配并入候选（数量很小），所以刚写入的条目一定搜得到。
- **代价**：两个会话同时"记下"同一件事会产生两条内容相同的条目，由下一次整理合并（AC-47）。
- **何时该重新考虑**：embedding 调用的延迟让显式写入明显变慢时，把向量索引改为异步，关键词索引保持同步。

### 决策 6：资格在入口判定并持久化，下游只查登记

- **备选**：
  - A. 每个接入点自己从手头的 `user_id` 判断能否使用记忆。
  - B. 在知道主体类型的入口调用 `MemoryGate.open(chat_id, principal, scene, app, timezone)`，把"这个会话属于哪个自然人、是否有资格"写进 `memory_session_cursor`。下游（节点、回调、worker、Beat）按 `chat_id` 查这一行，查不到或无资格即不工作。
- **选定**：B
- **原因**：K6。下游拿不到主体类型，A 方案会把服务账号、访客配置里的 `user_id` 当成自然人，违反 AC-10 与候选 INV-44 的"不得回落"。B 的失败方向是关闭：任何没有经过入口登记的路径，记忆都不工作。
- **入口清单**：日常模式与深度研究的对话入口（同一个 `chat_id`）；助手与工作流的 WebSocket 建连和 HTTP 调用入口；开放 API 的助手与工作流入口。免登录链接入口不调用 `open`。
- **资格规则**：登录用户有资格；开放 API 代表调用取被代表人；个人访问令牌取持有人；服务账号自身身份、只带外部用户标识的调用无资格。
- **这一行同时承载**：会话的时区（决策 13）、整理水位与状态（决策 7）。
- **何时该重新考虑**：平台给运行时统一下传主体对象时，可以去掉这层持久化。

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
- **只整理启用之后的对话（AC-40）与关闭后不再整理（AC-41）**：
  - 每轮结束时接入点都调 `MemoryActivity.end_turn(chat_id, last_message_id, enabled)`。`enabled=true` 置 `pending`；`enabled=false` 直接把水位推进到 `last_message_id`，即这轮被跳过，永不整理。
  - 任务开始时对每个会话重新过一次启用判定。判定为关，或会话已软删除（`message_session.is_delete`），就把水位推进到当前终点并置 `idle`，不整理。
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
- **与 C3 的关系**：C3 写"不要手写 `WHERE tenant_id`"，其目的是防止遗漏隔离。本功能的隔离比自动过滤更严，手写是加强而不是绕过。新表仍登记进 `tenant_filter`，自动过滤作为第二道。**这是一处显式例外，需要用户与评审知悉**（§9）。
- **强制方式**：repository 的每个方法签名都必须接收 `MemoryContext`，没有不带上下文的重载；有一条测试用全局超管身份和"可见多租户"身份各跑一遍隔离用例。
- **何时该重新考虑**：`tenant_filter` 提供"严格等于当前租户"的模式时，改用它。

### 决策 10：一个工具工厂，三个场景复用；记忆工具的事件落库前脱敏

- **选定**：`memory/domain/services/tools.py` 的 `build_memory_tools(ctx) -> list[BaseTool]` 返回两个 `StructuredTool`：
  - `memory_write(action, content, target_id?, type?, event_time?)`，`action ∈ {remember, correct, forget}`
  - `memory_search(query, limit?, detail_ids?)`
- **被否方案**：做成平台"工具"由作者勾选。否决原因是 AC-77 要求助手记忆开启后无须另配，并且它会把记忆带进 `ToolExecutor` 的权限与配置体系。
- **脱敏（K7）**：三个场景在把工具调用写入消息之前，对名称以 `memory_` 开头的工具做统一处理：入参与返回替换为 `{"redacted": true, "item_ids": [...], "op": ...}`。流式下发给前端的工具事件同样只带这些。本人需要看原文时，前端拿 `item_ids` 向记忆接口取。这样管理端接口原样返回消息时，里面没有记忆原文（AC-09）。
  - 这只保护工具事件。模型在**回答正文**里复述的记忆内容不做遮盖（spec §3 已声明）。
  - 脱敏函数只有一个，放在 `memory` 模块，三处调用；有一条测试对三个场景的落库结果做断言。
- **同名工具**：`memory_` 是保留前缀。助手作者配置的工具若与记忆工具同名，以记忆工具为准并记录一条告警日志（spec §3 指向此处）。
- **何时该重新考虑**：平台统一了工具调用事件的落库格式时，把脱敏挪到那一层。

### 决策 11：常驻记忆和工具在"调用时"注入，不在 agent 构建时

- **备选**：A. 拼进系统提示词、构建 agent 时加工具。B. 每轮调用模型时注入。
- **选定**：按场景不同：
  - **日常模式**：每轮都重新拼提示词和工具（`chat_service.py:2010-2021`、`:2099-2111`），直接在这两处加，属于 A 但天然每轮。无工具时走直连 `astream` 的分支（`:2407-2411`）也要带上常驻记忆。
  - **助手**：agent 在连接内只建一次（K8）。常驻记忆不进 `prompt`，而是在 `AssistantAgent.run` / `astream`（`assistant_agent.py:576`、`:605`）拼输入消息时，作为一条系统消息插在历史之前。工具列表与启用状态挂钩：每轮开始取一次启用判定的结果指纹，与构建时不同就重建 agent。
  - **深度研究**：用一个新的中间件在 `wrap_model_call` 里追加常驻记忆与经验类条目（`linsight/AGENTS.md` 约定的尾部追加方式）。不写进首条用户消息。
- **原因**：
  - 助手：AC-51 每轮带入、AC-74 下一轮按新状态，构建时注入都做不到。
  - 深度研究：首条消息有两处拼装（`task_exec.py:1600` 与续轮的 `:701-703`），并且写进消息的文本会留在检查点的线程历史里，条目被删除后仍对模型可见，违反 AC-91。中间件注入不进线程历史，两处拼装也都覆盖。
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
- **embedding**：取租户的知识库默认 embedding（`llm/domain/services/llm.py:1248`）。租户更换 embedding 模型后，旧 collection 不再使用，由重建任务按新模型重新写入。
- **被否方案**：每个用户一个 collection。collection 数量随用户数增长，不可行。
- **何时该重新考虑**：评测显示检索质量不足时，加重排一路。

### 决策 13：时区随会话登记保存，取不到用部署默认值

- **备选**：A. 给用户表加时区设置。B. 客户端在发起对话时带上浏览器的 IANA 时区，入口调 `MemoryGate.open` 时写到登记行，并同步到 `memory_user_setting.timezone`。
- **选定**：B
- **原因**：K12。A 需要一个新的用户设置项，超出本功能范围。B 借助决策 6 已有的入口登记，一处解决了传递问题：工作流节点、深度研究 worker、整理任务都从登记行读时区，不需要让时区穿过 WebSocket 或任务队列。
- **回落顺序**：本会话登记的时区 → `memory_user_setting.timezone`（最近一次已知）→ 部署默认时区。开放 API 的调用没有浏览器，走后两级。
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
- **原因**：A 下这些数据随消息被三套渲染读到，要在每一套里分别过滤。B 下管理端的会话接口不含这些数据，隔离做在数据访问层。引用角标也是独立成表（`message_citation`）。
- **按轮而不是按消息**：写入工具在回答生成的中途被调用，那时回答的消息行还没有插入（日常模式在 `chat_service.py:2560`、中断路径 `:1971` 才落库）。所以每轮开始生成一个 `turn_id`，写进 `MemoryContext`；表里的行先挂在 `turn_id` 上，回答落库时接入点调 `MemoryService.bind_turn(turn_id, message_id)` 补上 `message_id`。正常结束和中断两条落库路径都要调。
- **表里一轮最多三类行**：每次显式写入一行（含操作类型、新条目 id、被取代或被忘掉的条目 id）；检索取回的条目一行（条目 id 列表）；本轮带入的常驻记忆一行（条目 id 列表）。后两类各是**一行一个 id 列表**，不是每个条目一行，所以每轮最多多写两行。
- **流式信号**：日常模式新增 SSE category `memory`；助手与工作流走同名的 WebSocket 消息；深度研究在 `MessageEventType` 里加一个事件。信号只带 `turn_id` 和"有操作提示/有归因"的标志，不带原文。
- **何时该重新考虑**：平台统一了"消息附属数据"的存储时。

### 决策 16：归因只列检索取回的条目；常驻记忆整份可查看

- **备选**：A. 让模型用句柄标注它用了哪几条常驻记忆。B. 检索取回的逐条列出；常驻记忆给一个入口整份查看。
- **选定**：B（用户已于 2026-11-13 确认，spec AC-87 已按此改写）
- **原因**：A 要在三套互不通用的引用机制上各做一遍句柄转换，并且标注是否准确无法保证。B 完全由系统确定，可自动化测试。
- **何时该重新考虑**：用户反馈"分不清哪条常驻记忆起了作用"成为主要问题时。

### 决策 17：开关存储在各自对象的现有配置里

| 开关 | 存储 | 说明 |
|---|---|---|
| 租户记忆 | `WorkstationConfig` 的新字段 `memory: {enabled, model_id}`，存在现有的工作台配置键里 | 沿用 `POST/GET /api/v1/workstation/config/daily` 与 `_aresolve_tenant_config` / `_aupsert_tenant_config`，不新开配置键，所以不涉及 `_TENANT_KEYS` 白名单。字段缺失时按 `enabled=true` 处理（AC-76）。未开多租户时它落在全局配置里，由系统管理员修改（AC-67）；子租户没有自己的配置时继承根租户，这是工作台配置的既有行为 |
| 我的记忆 | 新表 `memory_user_setting`，一人一租户一行 | 同一行还有 `rev` 与 `timezone`。没有行时按 `enabled=true` |
| 助手记忆 | `assistant` 表新列 `memory_enabled`，`server_default` 为关 | 助手没有版本表，保存即生效（spec AC-71 已据此订正） |
| 工作流记忆 | 开始节点的参数 `memory_enabled`，存在 `flow_version.data` 里 | 随版本走；参数缺失视为关 |

- **备选**：给租户记忆单开一个配置键。否决原因是要改白名单、要新开接口，而且新接口路径受"不得含 config"的约束。
- **工作流开关在运行时怎么读**：工作流实例化时（`GraphEngine.init_nodes`）从开始节点参数取出 `memory_enabled`，放进 `graph_state` 的一个只读字段。记忆检索节点和消息落库回调都从 `graph_state` 读。整理任务判定"现在是否仍开启"时读该工作流当前上线版本的开始节点参数。
- **启用判定**：`MemoryGate.resolve(chat_id, scene, app) -> MemoryContext | None`。顺序：登记行存在且有资格（决策 6）→ 用户未停用 → 租户记忆 → 我的记忆 → 应用开关。一轮开始时取一次，沿用到该轮结束（AC-74）。
- **每轮的查询代价**：登记行一次、用户状态与 `memory_user_setting` 各一次、租户配置走既有的 Redis 缓存、应用开关来自已加载的应用对象。不另加缓存。
- **何时该重新考虑**：每轮三次小查询成为可测的延迟时，把登记行与用户设置合并缓存。

### 决策 18：整理用的模型由租户指定，调用按租户计量

- **选定**：
  - 租户记忆配置里有"整理使用的模型"（决策 17 的 `model_id`）。未指定时用工作台模型列表的第一个。两者都没有时整理任务按失败处理并计数，不静默跳过。
  - 整理的模型调用与记忆的 embedding 调用，以记忆主人的 `user_id` 发起，标记一个新的应用类型"记忆"，记入现有的 token 用量记录。
- **⚠ 待用户裁定：额度**。现有模型调用会经过额度检查（DSH 积分等，`dsh/domain/services/chat_credits.py:20-23`）。整理是系统发起的后台调用，用户没有主动触发。本稿建议**不计入用户个人额度、只做租户维度的用量记录**；被额度机制拒绝时按失败处理。这是成本归属问题，不是技术问题。
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
  - 显式写入、自动整理、手动新增的新增条数，被取代与被删除的条数：从条目表按 `origin`、`status` 聚合。
  - 被带入、被检索返回的条目数；带入失败、检索失败、详情读取失败、整理失败、检索降级的次数：Redis 计数。
  - 从未被带入也未被检索返回的条目数：条目上的 `last_read_at` 为空。Redis 里维护"今日被读条目集合"，定时任务批量更新这一列。
  - 详情被取回过的比例：条目上的 `detail_read_at`，同样由定时任务从 Redis 集合批量更新。
  - 用户撤销次数：从决策 15 的表聚合。
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
`对话入口（知道主体类型）→ MemoryGate.open(chat_id, principal, scene, app, timezone) → 写或更新 memory_session_cursor`

**一轮开始**
`MemoryGate.resolve(chat_id, scene, app) → 得到 MemoryContext（含 tenant_id、user_id、时区、turn_id）或 None → 非 None 时：MemoryService.resident(ctx) 给出常驻文本块；build_memory_tools(ctx) 给出两个工具`

**写入（显式）**
`模型调用 memory_write → MemoryService.write → 校验（长度、类型、SensitiveContentGuard）→ 时间换算 → 详情对象 PUT（如有）→ 事务：条目 INSERT + 被取代条目条件 UPDATE + rev 加一 + 本轮记录一行 → 同步建索引（失败置 pending）→ 审计 → 返回 → 接入点下发 memory 信号`

**一轮结束**
`接入点对工具事件脱敏后落消息 → MemoryService.bind_turn(turn_id, message_id) → MemoryActivity.end_turn(chat_id, last_message_id, enabled)`

**写入（自动整理）**
`Beat 扫描登记表 → 按用户投任务 → 取用户锁 → 对每个到期会话：重新判定启用 → 读水位之后、终点之前的消息 → 模型给出候选 → 代码校验 → 与现有有效条目比对（重复/矛盾）→ 事务：落条目 + 调整常驻 + 推进水位 + rev 加一 → 建索引`

**读取（检索）**
`memory_search 或记忆检索节点 → MemoryService.search(ctx, query, limit) → 关键词与向量两路（同一过滤函数）+ pending 条目并入 → 倒数排名融合 → 回表校验 → 记本轮检索到的 id → 计数 → 返回`

### 4.2 关键数据结构

新表五张。全部带 `tenant_id` 并登记进 `tenant_filter` 的模型模块列表；JSON 用 `dialect_helpers.JsonType`，长文本用 `LargeText`；全部走 Alembic，`assistant` 表加列同样走 Alembic 并带 `server_default`。

| 表 | 一行是什么 | 关键列 |
|---|---|---|
| `memory_item` | 一条记忆条目 | `id`（应用侧生成的 UUID）、`tenant_id`、`user_id`、`scope`（本期恒为 `personal`）、`type`（fact/preference/experience）、`content`、`status`（active/superseded/deleted）、`superseded_by`、`pinned`、`pin_order`、`event_time`、`valid_from`、`valid_to`、`recorded_at`、`origin`（explicit/auto/manual）、`source_scene`、`source_app_id`、`source_app_name`（写入时快照）、`source_chat_id`、`detail_object_key`、`detail_sha256`、`index_state`（ok/pending）、`last_read_at`、`detail_read_at` |
| `memory_session_cursor` | 一个会话的登记（一个 `chat_id` 一行） | `chat_id`、`tenant_id`、`user_id`、`eligible`、`timezone`、`last_activity_at`、`last_message_id`、`watermark_message_id`、`state`（idle/pending/running）、`locked_at`、`fail_count`、`next_run_at` |
| `memory_user_setting` | 一个用户在一个租户的记忆设置 | `tenant_id`、`user_id`、`enabled`、`timezone`、`rev` |
| `memory_turn_record` | 一轮对话里与记忆有关的一件事 | `turn_id`、`chat_id`、`message_id`（回答落库后补）、`tenant_id`、`user_id`、`kind`（write/retrieved/resident）、`op`（remember/correct/forget，仅 write）、`item_id`、`related_item_id`（被取代或被忘掉的条目）、`item_ids`（JSON，仅 retrieved/resident）、`undone` |
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
| 工作流节点类型 | `NodeType.MEMORY_RETRIEVER = "memory_retriever"` | 参数 `query`（`var_textarea` 控件，必填）、`limit`（`number` 控件，默认 20）。后端在保存与上线时校验 `limit` 为 1 到 100 的整数，否则返回 121 段的错误码（AC-80）；前端同步校验 |
| 节点输出变量 | `retrieved_memory`：数组，每项 `{text, metadata{type, recorded_at, event_time, source}}` | 结构对齐知识库检索节点。被大模型节点作为变量引用时，序列化结果以背景信息说明开头，每条带记录日期（AC-57） |
| 节点运行日志 | `parse_log` 返回检索内容与返回条数，不含条目原文 | AC-86；条目原文在节点输出里，由作者决定去向 |
| 工作流开始节点参数 | `memory_enabled`（`switch` 控件），独立的"记忆"分组 | 说明文案见 AC-75 |

HTTP 接口，前缀 `/api/v1/memory`，全部只作用于调用者本人，没有任何"按用户 id"的参数：

| 接口 | 用途 | 租户记忆为关时 |
|---|---|---|
| 条目列表 | 管理页查看 | 可用 |
| 新增、编辑 | 管理页 | 拒绝（AC-90） |
| 删除单条、清空 | 管理页与归因处 | 可用 |
| 读取与修改"我的记忆" | 个人设置 | 读取返回"不可用"，前端据此隐藏开关 |
| 按 `turn_id` 或 `message_id` 取操作提示与归因 | 消息气泡 | 可用（历史消息仍可查看） |
| 撤销一次显式写入 | 操作提示 | 可用 |

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
| `memory/domain/repositories/*` | 五张表的数据访问；每个方法都接收 `MemoryContext` 并显式带租户与用户条件 | 不含业务规则 |
| `memory/api/endpoints/*` | 本人的管理接口 | 不暴露按用户 id 查询 |
| `worker/memory/*` | Beat 扫描、整理任务、索引对账、指标落库 | 不含业务规则 |
| `workflow/nodes/memory_retriever/` | 记忆检索节点 | 不做启用判定以外的权限判断 |

**分层（C1）。** 四个场景的 Service 层调用 `memory` 的 domain service，属于 Service 调 Service，合规。助手的一轮结束处理放在 `api/services/assistant_agent.py` 的 `run` / `astream`，**不放在** `common/chat/client.py`：`common/` 不得引用领域模块。`client.py` 里需要的只有一件事（落库前对工具事件脱敏），做法是 `AssistantAgent` 在把工具消息交给 `client.py` 之前就完成脱敏。

### 4.4 已取证的接入点（基线 `feat/3.0.0@741662475b`）

路径省略前缀 `src/backend/bisheng/`。行号由 design 审查核对过，前端行号区间未逐一核对。

| 接入点 | 位置 | 要做的事 |
|---|---|---|
| 日常模式：对话入口 | `workstation/api/endpoints/chat.py:97` → `chat_service.py:2634` | 调 `MemoryGate.open`；请求体带时区 |
| 日常模式：系统提示词 | `chat_service.py:2099-2111` | 追加常驻记忆文本块 |
| 日常模式：无工具直连分支 | `chat_service.py:2407-2411` | 同样带上常驻记忆。记忆已启用时工具列表恒非空，此分支实际不会走到，但两条分支都要测 |
| 日常模式：工具组装 | `_prepare_tools`（`:1268`，调用处 `:2013`） | 追加记忆工具 |
| 日常模式：工具事件 | `chat_service.py:2311-2319`（入参）、`:2343-2344`（返回） | 记忆工具的事件在写入 `events` 前脱敏 |
| 日常模式：流式事件 | `workstation/domain/services/chat_helpers.py:153` `_sse_resp` | 新增 category `memory`。事件类别是字符串字面量，没有集中枚举 |
| 日常模式：一轮结束 | `chat_service.py:2558-2575`；中断路径 `:1955-1980` | 两处都调 `bind_turn` 与 `end_turn` |
| 助手：建连 | `common/chat/client.py:230` `init_gpts_agent`；开放面 `assistant/domain/services/published_assistant_service.py:86` | 由其上层的 Service 调 `MemoryGate.open`。开放面入口的消息落库位置**未取证**，写任务前要补 |
| 助手：每轮调用 | `api/services/assistant_agent.py:576` `run`、`:605` `astream` | 每轮：启用判定、插入常驻记忆系统消息、必要时重建 agent、结束时 `bind_turn` 与 `end_turn` |
| 助手：工具 | `assistant_agent.py:285` `init_tools` | 启用时追加记忆工具；两种执行器（ReAct、function call，`:445-458`）都要验证 |
| 助手：工具消息落库 | `common/chat/client.py:403-405` | 落库前已由 `AssistantAgent` 脱敏 |
| 工作流：入口 | WebSocket 建连与 HTTP 调用入口；任务体 `worker/workflow/tasks.py:62` | 入口调 `MemoryGate.open` |
| 工作流：节点注册 | `workflow/common/node.py:8-24`、`workflow/nodes/node_manage.py` | 新增类型与节点类 |
| 工作流：实例化 | `workflow/graph/graph_engine.py:207-231` | 把开始节点的 `memory_enabled` 放进 `graph_state` |
| 工作流：节点拿身份 | `workflow/nodes/base.py:39,49` | 节点不用 `self.user_id` 判定资格，按 `chat_id` 查登记行 |
| 工作流：上线校验 | `api/services/workflow.py:1219`，ONLINE 分支 `:1237-1244` | 加"含记忆检索节点而开关为关则拒绝"与 `limit` 校验；前端 `useNodeEvent.ts` 同步提示 |
| 工作流：消息落库 | `worker/workflow/redis_callback.py:532/583/623` | `save_chat_message` 每条消息都调用且是同步上下文，**不在这里**调 `end_turn`；在工作流一次运行结束处调一次。结束点位置写任务前要补取证 |
| 深度研究：入口 | `linsight/api/endpoints/linsight.py`（提交任务） | 与日常模式同一个 `chat_id`，调 `MemoryGate.open` |
| 深度研究：常驻与经验带入 | `linsight/domain/services/agent_factory.py:1400` `create_linsight_agent`，中间件 `:222/:289` 一带 | 新增一个中间件在 `wrap_model_call` 追加 |
| 深度研究：工具 | `_generate_tools` 定义在 `task_exec.py:1097`，调用点 `:537`、`:668`、`:749` | 三个调用点之后都追加记忆工具；按 `linsight/AGENTS.md`，提示词与工具同步出现 |
| 深度研究：任务结束 | `task_exec.py:2440` `_handle_task_success`、`:2369`、`:1990`、`:2075` | 调 `end_turn` |
| 深度研究：管理端可见性 | — | 管理端能否查看深度研究的执行步骤及其工具入参**未取证**。若能，步骤里的记忆工具事件同样要脱敏 |
| 会话与消息 | `database/models/session.py:20/81`（含 `is_delete`）、`database/models/message.py:35/90` | 整理按 `chat_id` 读 `chatmessage`；深度研究轮次是同一会话里 `category='task'` 的行 |
| 用户停用 | 入口至少六处，没有统一回调 | 不挂钩子；`MemoryGate.resolve` 每轮读用户状态（AC-99） |
| 租户归属变化 | `tenant/domain/services/user_tenant_sync_service.py:76` | 不挂钩子；靠决策 9 的显式过滤满足 AC-06、AC-07 |
| 应用删除 | 助手软删 `api/services/assistant.py:419`；工作流硬删 `database/models/flow.py:211` | 不挂钩子；来源名称已快照 |
| 审计 | `database/models/audit_log.py:531` `AuditLogDao.ainsert_v2` | 动作名 `memory.item.*`，`metadata` 不放内容 |
| 租户配置 | `workstation/domain/services/workstation_service.py:57/247`；`api/v1/schemas.py` `WorkstationConfig` | 加 `memory` 字段 |
| 额度 | `dsh/domain/services/chat_credits.py:20-23,57-60`；`llm/domain/services/llm.py:1407-1412,1457-1464` | 决策 18 待裁定 |
| 前端：工作流节点 | `platform/src/controllers/API/workflow.ts:185`、`pages/BuildPage/flow/FlowNode/Parameter.tsx`、`FlowNode/NodeLogo.tsx`、`public/locales/*/flow.json` | 新增节点四处都要改 |
| 前端：助手设置 | `platform/src/pages/BuildPage/assistant/editAssistant/Setting.tsx`（`knowledge_auth` 开关是样板） | 新增开关与说明 |
| 前端：工作台配置 | `platform/src/pages/BuildPage/bench/index.tsx`、`ToggleSection.tsx`、`DailyChatConfig.tsx` | 新增"记忆"区：开关加整理模型下拉 |
| 前端：日常模式气泡 | `client/src/components/Chat/AiMessageBubble.tsx`；SSE 解析 `client/src/hooks/useAiChatSSE.ts`；工具卡片 `Messages/ToolCallDisplay.tsx` | 操作提示与归因入口；记忆工具的卡片按脱敏后的格式渲染 |
| 前端：应用聊天 | `client/src/pages/appChat/ChatMessages.tsx`、`components/ClientMessageFooter.tsx` | 同上，第二套 |
| 前端：深度研究结果 | `client/src/components/Linsight/Execution/ResultPanel.tsx` | 归因入口 |
| 前端：个人设置 | `client/src/pages/settings/settingsSections.ts`、`SettingsPage.tsx`；样板 `sections/AiAccessPane.tsx` | 新增"记忆" section |
| 前端：管理端查看会话 | `platform/src/pages/LogPage/useAppLog/appChatDetail.tsx`、`dailyChatDetail.tsx`、`LabelPage/taskAppChats.tsx` | 不接记忆接口。它们渲染到脱敏后的记忆工具事件时显示为"记忆操作"，不显示内容 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 租户自动过滤给普通用户的是可见租户 IN 列表，给全局超管的是不过滤，并且只拦 SELECT | 调岗用户仍读到原租户的记忆；超管读到别的租户里同 id 的行；批量写跨租户生效 | 决策 9：repository 每个方法显式带租户与用户条件 |
| 2 | 各场景会把工具入参与返回原样落进消息，管理端接口原样返回 | 管理员翻会话就看到记忆原文 | 决策 10：落库前脱敏，三处共用一个函数 |
| 3 | 下游只有整型 `user_id`，分不出自然人、服务账号、访客配置 | 给不该有记忆的调用开了记忆 | 决策 6：入口登记，下游只查登记行 |
| 4 | 助手 agent 在连接内只建一次 | 常驻记忆不更新、开关改了不生效 | 决策 11：调用时注入，指纹变化时重建 |
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

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `/api/v1/memory/**` | HTTP API，只作用于调用者本人 | client 个人设置、client 两套消息气泡 |
| `MemoryGate.open` / `resolve`、`MemoryService.resident` / `experience` / `bind_turn`、`build_memory_tools`、`MemoryActivity.end_turn`、工具事件脱敏函数 | 内部 Python API | 工作台、助手、深度研究、工作流的接入点 |
| `memory_retriever` 节点类型与输出结构 | 工作流节点契约 | 工作流作者的下游节点 |
| `memory` SSE / WebSocket 信号；脱敏后的记忆工具事件格式 | 流式事件与落库格式 | client 两套渲染、platform 管理端回放 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `chatmessage` 按 `chat_id` 可读，`category` 能区分用户输入、系统输出、深度研究任务行及其终态 | 隐式数据契约 | 任一场景改消息格式，整理会读不懂或水位判断出错；每个场景要有一条整理的集成测试 |
| 各场景的工具事件落库点 | 代码位置 | 新增一种落库路径而没有调脱敏函数，就是一处泄漏；要有覆盖三个场景的断言 |
| `WorkstationConfig` 与工作台配置接口 | 结构与接口 | 该结构改形态时 `memory` 字段要同步 |
| 知识库默认 embedding、`MilvusFactory`、`ElasticsearchFactory` | 内部 API | 属于知识库模块，记忆不得改变它们的行为 |
| `AuditLogDao.ainsert_v2` | 内部 API | 动作名需登记 |
| 租户上下文（`get_current_tenant_id`、`bypass_tenant_filter`） | 内部 API | "当前租户"的语义变化会直接影响隔离 |
| 开放 API 的身份解析 | `open_api/domain/services/identity_service.py` | `MemoryGate.open` 依赖它给出的主体类型 |
| 模型调用的额度机制 | `dsh/domain/services/chat_credits.py` | 决策 18 |
| 引用呈现组件（F075） | 前端组件 | 归因沿用其样式，不沿用其数据通道 |

**在其他 Owner 的对象上新增的写入点**（`release-contract.md` 的 F132 段同步）：审计记录；`WorkstationConfig` 的 `memory` 字段；`assistant.memory_enabled` 列；工作流开始节点参数、实例化时的 `graph_state` 字段与上线校验；三个场景的工具事件落库处；client 个人设置的新 section。管理端查看会话的页面只多一种"记忆操作"的占位渲染。

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

**第 2 稿新增，待用户裁定或知悉。**

| # | 事项 | 性质 | 落点 |
|---|---|---|---|
| 5 | 整理与 embedding 的模型调用是否计入用户个人额度 | 待裁定（成本归属） | 决策 18 |
| 6 | 记忆的读写显式按"当前租户 + 本人"过滤，是对 C3"不手写租户条件"的一处显式例外 | 待确认（架构法则的例外） | 决策 9 |
| 7 | 删除是软删除，行与详情对象保留到用户清空；撤销在三种情况下会失败 | 请知悉。spec §3 需补这三种边界 | 决策 4 |
| 8 | 助手没有版本，助手记忆开关保存即生效 | 事实订正，spec AC-71 需改写 | 决策 17 |
| 9 | 管理端回放会话时，记忆工具的调用显示为"记忆操作"占位，不显示内容 | 请知悉。这是 AC-09 的实现方式 | 决策 10 |
| 10 | 租户记忆配置里增加"整理使用的模型"；client 对话请求带上浏览器时区 | 实现所需的新增项 | 决策 18、决策 13 |

**写任务前还要补的取证**：助手开放面入口的消息落库位置；工作流一次运行的结束点；管理端能否查看深度研究的执行步骤。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-13 | 初版（设计草稿，未编码） | spec 第 2 稿确认后进入设计 |
| 2026-11-13 | 第 2 稿：新增入口登记（决策 6）、显式租户过滤（决策 9）、工具事件脱敏（决策 10）、调用时注入（决策 11）、软删除（决策 4）；整理的运行语义、缓存正确性、按轮记录、开关存储、检索融合全部重写 | design 审查发现 6 个高严重度问题 |
