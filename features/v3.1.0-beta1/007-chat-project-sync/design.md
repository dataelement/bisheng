# Design: Web 与 Desktop 项目数据实时同步

**关联**：[已确认规格](./spec.md) · [阶段状态](./tasks.md) · [版本契约](../release-contract.md)。
**版本**：v3.1.0-beta1 / F007。
**最后更新**：2026-11-11（简化修订，见 §0；§0 与下文冲突时以 §0 为准）。
**状态**：三端源码已实现，相关回归、构建及隔离 Electron 验收通过；3006 已由并行发布流程载入同步实现，真实 Web 新建在开发版 Desktop 自动出现，Desktop 改名也在后台 Web 自动更新。用户追加的自动迁移修订已发布到 3006，界面不再需要迁移操作。目标环境、安装包和平台限制见 [验证记录](./verification.md)。

## 0. 2026-11-11 简化修订（优先于下文）

**结论**：保留账号私有的项目与归属数据，删除实时推送层和幂等回执层；旧数据迁移改为按对话归属判定项目主人。修订原因见 2026-11-11 设计复审：同步层的复杂度超出需求（普通对话列表本身也不实时推送），而且每个浏览器标签页常驻一条 SSE，会在 HTTP/1.1 部署下占满浏览器对同一 host 的 6 条连接上限，并给服务端带来与用户数成正比的 Redis 连接和加锁查询。项目的未来定位是类似 ChatGPT / Claude Projects 的上下文容器，本期数据模型只承担“项目 + 归属”，为后续增加项目级指令和文件保留扩展空间。

**删除的内容**：
- 表 `chat_project_revision`、`chat_project_receipt`。已建库中残留的空表不影响运行，本次不写删表迁移。
- 接口 `GET /chat/projects/events`（SSE）、Redis 发布订阅、版本号高水位、nginx 的 events 专用 location。
- 快照分页游标与版本绑定；项目会话分页游标与版本绑定。
- 首条消息的 `project_request_id` 与“已创建会话”重放（原 13018）。
- 错误码 13013、13014、13016、13017、13018（13017 原本就没有调用方）。

**保留的内容**：表 `chat_project`、`chat_project_membership`；接口 `snapshot`、`actions`、`conversations`；首条消息在同一事务内创建会话并写入归属；删除会话在同一事务内解绑归属；对外改名校验会话所有者。

**同步方式**：客户端在本端操作成功后使 React Query 缓存失效并重新读取；窗口重新获得焦点、网络恢复时重新读取（React Query 默认行为）。Desktop 宿主若通过 `onProjectsChanged` 发出失效提示，Web 同样重新读取。

**幂等方式**：
- 新建项目：客户端生成项目 UUID 并随 `create` 提交。同一账号重复提交同一 UUID 时，服务端返回已有项目，不产生副本；该 UUID 已被删除或属于他人时返回 13011。
- 重命名、删除、归属：操作本身幂等，重复提交结果相同。
- 并发写入：归属表主键（tenant_id, user_id, chat_id）保证同一对话至多属于一个项目；插入冲突时整笔事务重试一次。

**旧数据迁移（AC-11/12）**：前端一次提交整份旧数据（上限 100 个项目、2000 条归属）。服务端在一个事务内逐个处理旧项目：
1. 用 `uuid5(租户, 账号, legacy_id)` 计算确定性项目 ID。该 ID 已存在（包括已删除）时，返回 `already_imported`，不再处理它的归属，因此重复导入不会覆盖云端的改名、删除或移出。
2. 统计该项目的旧归属中，属于当前账号、未删除、自然人会话、且当前没有云端归属的对话。数量为 0 时返回 `not_owned`，不创建项目。
3. 数量大于 0 时创建项目，只写入这些对话的归属，返回 `imported`；其余归属按原因返回 `conversation_unavailable` 或 `cloud_membership_kept`。

前端去掉“来源绑定首个账号”（`bs_project_import_owner_v1`）；完成标记按账号记录（`bs_project_import_done_v2:<身份>`），同一浏览器的每个账号各自导入一次。

**对外契约（取代 §6.1 中的同名条目）**：

| 接口 | 输入与输出 |
| --- | --- |
| `GET /chat/projects/snapshot` | `{identity:{user_id,tenant_id}, projects:[{id,name,created_at,updated_at}], memberships:[{chat_id,project_id}]}`，一次返回全部 |
| `POST /chat/projects/actions` | create=`project_id,name,chat_id?`；rename=`project_id,name`；delete=`project_id`；assign=`chat_id,project_id|null`；import=`projects:[{legacy_id,name,created_at?}],memberships:[{chat_id,legacy_project_id}]`。返回 `{outcome}` |
| `GET /chat/projects/conversations` | `project_id?`、`query`、`cursor`（不透明偏移量）、`limit`；返回 `{data,total,next_cursor}` |

**Desktop 影响**：Desktop 主进程控制器（BishengWork 仓库）依赖已删除的 events 接口、`request_id` 和 `revision` 字段，需要同步改为“获得焦点时读取快照”。本仓库无法验证 Desktop 侧改动。

## 1. 目标与非目标

将项目和对话归属变为账号私有的服务端数据，Web 与 Desktop 对同一身份实时显示一致结果。项目中的首条消息由服务端持久化归属，重连及迁移保持幂等。

边界遵循 spec：组织现有对话，保留既有聊天与任务执行链路；团队共享项目、Work 上云、模型流式协议重构另行设计。

## 2. 关键约束

- 遵循 [constitution C1–C8](../../../docs/constitution.md) 及版本契约。项目属于自然人的会话组织数据，沿用会话所属身份约束，不增加可向其他用户授予权限的资源类型。
- 同步覆盖 API 多进程、多节点，以及 Web、Desktop 和多个浏览器窗口。进程内内存、浏览器 localStorage、共享磁盘均不能作为三端权威数据源。
- 正常网络及 Redis 正常时，以变更提交后另一个已打开前台客户端 **2 秒内**完成自动更新为联合验收目标；失去同步连接必须显示状态。隔离 Electron 双客户端测得 25 ms；该结果不代表实际 Gateway 环境时延达标。
- Desktop 使用当前企业账号拥有的短期 Cookie 会话。凭据、续期和服务端流读取归 main；不新增 renderer 通用代理、任意 URL 或令牌参数。
- 元数据按页读取，单页最多 500 条项目/归属、响应最多 4 MiB；项目会话每页默认 40、最多 100。总数据不按普通历史首屏的 40 条截断。
- 初版复用数据库、Redis、现有前端请求和状态库、Electron 会话能力，不增加基础设施或运行时依赖。MySQL/DM8 实机兼容性需分别验收，SQLite 测试只验证可运行的事务与查询行为。

## 3. 方案对比与选定

### 决策 1：同一后端权威数据源，关系表保存项目与归属

- **备选**：互相复制两端 localStorage；在 Redis 或用户设置中覆盖整份项目 JSON；独立项目服务；在 chat_session 内建立项目元数据。
- **选定**：chat_session 领域服务及 Repository，使用关系表、账号版本和幂等回执。对话正文仍由原 Owner 管理。
- **原因**：已核实两端是不同浏览器会话；Desktop 的嵌入会话退出会清理存储。整份 JSON 覆盖会丢失并发修改，且不能独立分页、验证每条会话归属。项目只组织现有 MessageSession，独立服务无必要。
- **重新考虑条件**：将来支持团队共享项目、项目成员或跨租户共享时，须重新定义授权资源和生命周期；不能沿用本次个人归属语义。

### 决策 2：Redis 变更通知 + SSE，数据库版本负责恢复（2026-11-11 已被 §0 取代）

- **备选**：客户端定时刷新全量列表；只依赖 Redis Pub/Sub；新建 WebSocket 控制协议；SSE 通知失效并读取数据库快照。
- **选定**：SSE 发送轻量版本通知，Redis 用于跨 API 节点广播；数据库账号版本是事实。连接建立先完成订阅确认再读版本，断线后拉取一致快照；15 秒心跳同时核对数据库版本，修复提交后通知丢失。
- **原因**：项目是低频的服务端到客户端通知，不需要双向 socket；现有 Redis 已有 async Pub/Sub 使用范例。Pub/Sub 无重放，单独依赖会永久漏掉断线期间变更。通知不承载权限或正文。
- **重新考虑条件**：测量显示每连接的心跳版本读取造成数据库瓶颈，或需高频逐条增量重放时，另行设计持久事件日志；本次不引入后台 outbox/新 worker。

### 决策 3：按账号串行提交单个操作，保留幂等回执（2026-11-11 已被 §0 取代）

- **备选**：两端整份列表最后写入覆盖；让客户端合并；对单项操作在数据库事务内串行化。
- **选定**：锁定账号版本行，再锁项目和相关会话，完成单项操作、版本递增及回执后一起提交。独立对象的操作依次保留，同一字段或归属以服务端提交顺序为准。
- **原因**：无需另建 CRDT 或分布式锁即可捕获并发与重试；当前本地 map 已规定会话最多属于一个项目。回执允许“提交成功但响应丢失”后安全重试。
- **重新考虑条件**：单账号写并发实测超过短事务可承受范围时，再拆对象版本；不能先用全量覆盖简化。

### 决策 4：项目意图随首条消息提交，服务端原子绑定

- **备选**：沿用 Web 的 created 回调或 Desktop 的路由变化后再发归属请求；先造一个空会话；首条消息附带项目意图。
- **选定**：仅工作台自然人新会话提交接受 `project_id`、`project_request_id`。在现有实际创建会话的阶段，将 MessageSession、项目归属、账号版本和创建回执同事务保存，再发送 created / task handoff 事件。
- **原因**：现有 Web 的 `captureProjectChatCreation` 在客户端处理 created 后写本机 map；客户端关闭、换账号或请求丢失会使会话已经存在但归属未保存。普通 Agent、旧聊天分支和 task-mode 各有创建点，必须接到同一 Owner 服务。
- **重新考虑条件**：上游统一会话创建事务时迁入其正式扩展点。重试已有创建请求只恢复已有会话，不再次运行首轮模型或创建第二份会话。

### 决策 5：登录后自动合并旧记录，来源绑定账号，不覆盖云端（2026-11-11 已被 §0 取代）

- **备选**：静默上传当前浏览器全部数据；按项目名称合并；保留旧数据并执行可重试的逐项导入。
- **选定**：依用户最新指示，认证及项目快照就绪后自动迁移，不提供手动入口或确认弹窗。Web 无账号的旧来源在首次尝试前绑定当前完整账号身份，避免切换账号后再次采用同一来源；Desktop 使用原 projectScope。稳定来源/条目回执保持幂等，云端归属优先，原键保留。
- **原因**：用户明确要求历史记录自动迁移。Web 的两个旧键没有账号信息，因此首次迁移冻结目标，之后的账号不能接管该来源；Desktop 旧键已有账号摘要。同名项目可共存，旧快照不能覆盖云端新修改。
- **重新考虑条件**：旧数据全部迁移且产品正式结束旧版本支持后，再单独评审清理策略，不在本次成功导入后自动删除。

## 4. 已实现的数据流

### 4.1 实施前基线与替换入口

核查基准：Bisheng `feat/3.1.0-beta1` / `aa5fe342ad201317a429948d9bed4f8e1cde1bf6`，另有现存工作树修改；Desktop `V1.3.0` / `7c883d71cf5e52d8d7cd0df4e2db09409d910a70`，含上一轮未提交的本机项目实现。实施前重新核对当前文件，不重置其他工作。

| 现有入口 | 实际行为 | 对设计的影响 |
| --- | --- | --- |
| Web `WorkbenchSidebar/projectsStore.ts` | `bs_mock_projects`、`bs_mock_project_chats` 保存在 localStorage | 仅作为旧数据导入来源，替换 mock 导出和调用方 |
| Web `projectChatCreation.ts`、`useAiChatSSE.ts:openChatStream` | 捕获 URL 项目意图，created 或 task handoff 后在浏览器写归属 | 改为发送前捕获不可变意图，删除 created 后客户端补写归属 |
| Web `SidebarProjects.tsx` | 消费普通会话查询已加载的 `conversations` | 项目展开后增加独立分页查询，不能只过滤普通首屏 |
| Web `useDesktopNavigation.ts:isDesktopNavigationPath` | 当前白名单不接受 `/c/new?projectId=...` | 增加精确项目草稿路由，避免依赖整页加载回退 |
| Desktop `createChatProjects`、`createChatNavigation` | 本机账号摘要键持久化，路由变化后补归属 | 保留 UI；数据改为主进程服务端投影，移除本机写入与路由后补写 |
| Desktop `EnterpriseChatView` | 私有 Session、短期 Cookie、history/open 窄接口、generation 清理 | 新控制器复用会话身份和续期，独立承担流生命周期 |
| 后端 `chat_service.initialize_chat`、`_agent_initialize_chat` | 实际插入 MessageSession 的普通创建点 | 项目参数存在时调用统一的项目会话创建事务 |
| 后端 `task_submit_service.submit_task_turn`、`LinsightWorkbenchImpl.submit_user_question` | task-mode 有独立创建路径，且 Open API 复用该核心 | 显式传递已验证的可选项目意图；Open API/public_v3 不取得项目写入能力 |
| `ChatSessionService.delete_session`、`WorkflowFileRepository.soft_delete_owned_session` | 校验会话所属身份，事务标记删除；之后清附件 | 归属解绑和账号版本进入标记删除事务，通知先于可能失败的附件清理 |
| SQLModel `model_discovery.py`、Alembic `env.py` | 按目录发现 `table=True`，在线升级先创建缺失表 | 新独立表使用现有创建流程；不改旧表、不编写夹带数据迁移的 revision |

### 4.2 数据结构

四张表均在 `chat_session/domain/models/` 声明，由 Repository 写入；依赖自动租户边界，身份从认证结果生成，客户端不能指定 owner。项目不是新 OpenFGA 共享资源，不能借管理员管理范围读取个人分组。

| 表 | 关键内容与约束 |
| --- | --- |
| `chat_project` | UUID `id`、`tenant_id`、`user_id`、1–30 字符 `name`、创建/更新时间、`deleted_at`。逻辑删除保留项目身份，导入或旧请求不得复活已删除项目 |
| `chat_project_membership` | `tenant_id`、`user_id`、`chat_id`、`project_id`。账号与 chat_id 唯一；写入前及事务内验证自然人会话存在、未删除、同属当前身份 |
| `chat_project_revision` | `(tenant_id,user_id)` 唯一、单调 `revision`。初次创建竞争用唯一约束与有界事务重试解决；版本以十进制字符串传输 |
| `chat_project_receipt` | `(tenant_id,user_id,key)` 唯一、操作种类、规范化请求摘要、有限结果、提交版本。普通操作使用 `mutation:<UUID>`；迁移内部键按来源、条目类型和旧 ID 稳定派生，记录项目映射及归属导入结果 |

所有事务统一按“账号版本 → 项目 ID 顺序 → 会话 ID 顺序”取锁；不在持锁期间访问 Redis、模型或网络。项目删除同时解绑成员。会话软删除与归属解绑共享提交边界。项目内会话查询始终联合真实会话状态；不从回执恢复已删除会话。

`ChatSessionService.create_owned_project_session(...)` 是会话创建 Owner 入口。保留现有用户组归属、组织快照、自然人 subject、遥测以及 task 版本语义；Repository 只负责事务写入。项目已删除/不属于当前身份时，在正式会话插入前拒绝。创建回执保存正式 chat_id；同一请求重放通过明确的已有会话结果结束初始化，不再次调度模型。未带项目意图的路径保留原契约。

会话改名和删除仍由 ChatSessionService Owner 对外提供。新增可组合的会话 Repository 事务方法，与项目 Repository 共用事务 Session；改名在会话仍属于项目时递增账号版本，软删除同时解绑归属并递增版本，均遵守账号版本先取锁的顺序。对外改名必须传入 login_user 并校验自然人所属；内部自动标题从真实会话解析 owner，保留 `only_if_default` 条件更新语义，不把后台任务执行者当 owner。`chat_helpers.py`、`LinsightWorkbenchImpl` 的异步标题与同步兜底标题入口接到 Owner 方法，提交后统一发布通知。现有 `database/models/session.py` 不反向导入 domain 服务或项目模型，附件 Repository 也不调用服务来发布事件。

快照每页在版本锁保护的短事务内读取，cursor 绑定 actor、版本、阶段及最后一项 ID。后续页遇到新版本时返回快照变化，客户端重新组装；只有所有页完整且版本相同才发布新快照。SQL 关系字段用于过滤和排序，回执结果使用 `dialect_helpers.JsonType`，不使用数据库专有 JSON 查询。

### 4.3 更新与订阅流程（2026-11-11 已被 §0 取代）

1. **读取**：认证身份 → 项目服务 → 一致分页快照 → Web React Query 或 Desktop main 的当前身份缓存 → 侧栏。后续项目会话按页独立读取并复用原会话行与导航。
2. **修改**：UI 保留草稿并显示提交中 → 固定 actions 接口 → 身份与业务状态校验 → 项目事务、版本及回执提交 → 返回结果 → 重新读取当前快照。客户端不整份上传列表，不凭旧回执直接覆盖当前视图。
3. **广播**：提交后通过 Redis 发布 actor 专属版本 → 每个已订阅的 API SSE 连接发送 `changed` → 客户端合并失效通知并刷新。事件只提示读取，不能直接赋予会话可见权。
4. **握手**：订阅 Redis 并等待确认 → 读取当前数据库版本 → 发送 `ready`。握手过程中排队的通知按版本去重，避免“先读快照再订阅”之间漏变更。
5. **恢复**：连接断开或 45 秒无有效帧 → 标记连接未同步并释放 reader → 2/5/10/30 秒有抖动重试；重连先读最新快照，旧 epoch/旧版本响应丢弃。恢复到前台另触发一次校验，不依赖切换焦点才能更新。
6. **通知失败**：数据库提交成功后 Redis 发布失败，记录阶段并返回“已保存、同步延迟”的传输状态；保留服务端提交结果。SSE 的 15 秒数据库版本校验负责补齐；Redis 不可用时流标记 degraded 并重试，不能把未同步显示为实时正常。
7. **身份**：SSE 每 15 秒复核账号、租户、token_version 和到期时间；失效发送 `auth_required` 后关闭。客户端立即清空旧身份可见数据。Desktop 沿现有身份所有的 web-session 续期合并请求，再重建该身份的订阅；不把流的存活当作永久授权。

每个身份维护已观察版本的高水位。快照组装期间若收到更高版本通知，不能发布旧版本组装结果，必须重新读取；同一 epoch 中的旧请求不能覆盖较新版本。项目/归属通知同时失效项目会话页和受影响的普通历史查询，conversation 通知也覆盖标题、删除等会话行变化，不能只刷新项目名称。失效合并后保留尚未覆盖的最高版本，避免读请求正在进行时吞掉后到通知。

Web 的同步控制组件位于已认证 shell，而不依赖侧栏或项目是否展开。浏览器模式持有一条 SSE；原生嵌入模式接收 host 的无数据失效通知并刷新同源查询，不再为同一 Desktop 窗口另开 SSE。现有 `DesktopShellBridge` 和 presentation preload 增加只读的 `onProjectsChanged` 监听接缝；没有通用消息或本机执行接口。

Desktop 的新 `enterprise/chat-projects.ts` 控制器由 `EnterpriseChatView` 组装。身份 Cookie 安装后创建，在侧栏首次请求 projectsState 时启动，`clear()/dispose()` 或身份变化时 abort 全部请求、释放订阅和重试 timer。stream 与请求使用当前 Session，包含内容类型、大小、超时、重定向和版本校验。连接重试、SSE 读取和投影逻辑不继续堆入 `main/index.ts` 或 `client.js`。

### 4.4 Web 状态与迁移（2026-11-11 已被 §0 取代）

服务器数据使用既有 React Query v4，query key 包含已验证的平台/账号/租户身份。`api/chatProjects.ts` 集中 REST、流解析和取消；hooks 负责 query/mutation 生命周期，UI 通过 props 与回调交互，不另建服务器数据的 Recoil/Zustand 镜像。

项目命名弹窗等待提交成功才关闭；失败保留输入和同一 request_id。移动时新建项目使用一次 `create` 操作携带可选 chat_id，保证新项目与移动一起提交。删除、移动、重连、unsupported 和迁移均有中英文/日文文案；Desktop 维护中英文。

自动迁移在已认证 shell 挂载，待项目快照成功后读取、提交；不依赖侧栏展开，不显示手动入口。Web 首次尝试先保存来源到账号的绑定，身份变化即停止；失败按 2/5/10/30 秒退避重试。Web 使用原两个键，Desktop 使用当前 `projectScope` 对应旧键；为每一来源保留稳定 UUID。每批最多 100 项目、500 归属、请求不超过 1 MiB；服务端回报逐项结果和未导入原因。项目映射及每条归属的迁移回执随成功事务保存，重试不会覆盖用户后来在云端改名、删除或移出的状态；已有云端归属优先。新批次不能绕过同一来源条目的已处理回执。

导入中发生账号切换立即停止后续批次，当前批次仍按其原认证身份执行，其迟到响应不能影响新账号。损坏、超限或外来会话只显示可定位的条目结果，原本机数据保持。完成标记按账号、来源记录，迁移模块不删除旧键。

## 5. 已知坑与处理位置

| 事实 | 不知道的后果 | 处理位置 |
| --- | --- | --- |
| Desktop 嵌入 Session 是随机内存 partition，退出会 clearStorageData | 把 Web localStorage 复制进嵌入页仍不能跨端持久化 | Desktop 项目主进程控制器及服务端表 |
| Web 旧项目键不区分账号，Desktop 旧键只带不可逆身份摘要 | 必须明确首次迁移目标并防止后续账号重复接管；用户已指定自动采用首次当前账号 | Web 来源账号绑定、Desktop projectScope、自动迁移生命周期 |
| 页面内导航当前拒绝带 projectId 的路径 | 看似能打开，但只能通过整页回退并丢失页面内状态 | `useDesktopNavigation.ts` 的精确 URL 白名单和对应测试 |
| task-mode 绕过普通 Agent 的创建点，且共用 Open API 核心 | 只改普通聊天会漏归属，或误向 service account 开放私有项目 | workstation submit → 可选已验证意图 → ChatSessionService Owner |
| 普通会话只加载若干历史页，项目 UI 当前过滤同一数组 | 较早的项目会话刷新后消失 | 项目独立分页及项目成员搜索查询 |
| 后端存在 leaf/root 可见租户和管理员管理范围 | 普通可见范围不能作为个人分组数据边界 | 认证 actor + `tenant_execution_scope` + 自然人所属校验，不手写租户 WHERE |
| Pub/Sub 不重放，subscribe() 返回不代表订阅确认已消费 | 连接启动或断线恢复漏事件 | 订阅确认屏障、数据库版本、心跳修复 |
| 会话删除后附件清理仍可能失败 | 把项目清理放在附件之后会残留项目行 | 同事务解绑，提交后先发失效通知，再按原生命周期清附件 |
| 当前会话改名入口没有把 login_user 传给 rename_session | 新增通知若按当前操作者广播可能越界或误通知 | 对外改名先按原自然人会话 Owner 验证；内部标题生成按真实会话 owner 产生失效通知 |
| 成功回执可能比当前项目状态旧 | 重放创建响应会复活被另一端删除的项目 | 只按当前快照呈现，回执仅用于确认操作和取得 ID |
| 常规 API 代理有 300 秒超时且未保证 SSE 不缓冲 | SSE 返回 200 但浏览器迟迟看不到变化 | 精确 events 路由、响应头及部署代理验证 |

## 6. 对外契约与依赖

### 6.1 服务端 HTTP 与事件协议（2026-11-11 已被 §0 取代）

所有接口走现有 `/api/v1` Cookie/认证与统一成功/错误 envelope。路径和 body 不接受 user_id、tenant_id、topic 或任意远端 URL；extra 字段拒绝。Web 继续使用现有请求包装和错误机制。

| 接口 | 输入与输出 | 消费方 |
| --- | --- | --- |
| `GET /chat/projects/snapshot?cursor=...` | 首次 cursor 省略。data 为 `{protocol_version:1, identity:{user_id,tenant_id}, revision:"42", projects:[], memberships:[], next_cursor:null}`；分页期间版本变化拒绝旧 cursor | Web、Desktop main |
| `POST /chat/projects/actions` | `{request_id:UUID, operation:"create"/"rename"/"delete"/"assign"/"import", ...}`，见下表；结果带 `applied_revision`、当前 `revision`、`replayed`、`outcome`、`notification:"live"/"degraded"`，不把旧结果当当前快照 | 两端 mutation |
| `GET /chat/projects/conversations?project_id=...&query=...&cursor=...&limit=40` | 指定项目时分页读取其全部有效会话；项目 ID 省略仅用于有 query 的项目成员搜索。返回 `{data:[原会话行字段],total,revision,next_cursor}`，每页重新校验 actor 和归属版本 | 项目展开、搜索；Desktop 仅将本次有效结果加入可打开路由集合 |
| `GET /chat/projects/events` | SSE：`ready`、`changed`、`heartbeat`、`auth_required`。data 限 `{protocol_version:1, revision, notification, reason?}`，id 为 revision；reason 枚举 project/membership/conversation。不传正文、项目名称或凭据 | 浏览器控制器、Desktop main |

actions 逐类校验：create=`name,chat_id?`；rename=`project_id,name`；delete=`project_id`；assign=`chat_id,project_id|null`；import=`source_client_id,projects:[{legacy_id,name,created_at?}],memberships:[{chat_id,legacy_project_id}]`。名称 trim 后 1–30 字符，项目 ID 为 UUID，会话 ID 沿用已有长度和字符约束。普通同一 request_id 改用另一操作或 body 摘要返回冲突；来源迁移逐项回执有独立命名空间。

接口成功仅表示服务端已提交。重放只返回已执行操作的结果与当前版本，删除目标不可复活。客户端请求不确定时必须复用原 request_id，不能自动生成新建请求。首条消息的重放结果携带已有 chat_id，两端按普通打开已有会话的流程加载；任务模式读取已有任务状态，不自动重发用户消息或重新调度生成。若该会话后来已删除，返回不可恢复状态，不从回执重建。

首条消息在已有工作台提交 DTO 中增加可选 `{project_id,project_request_id}`，两字段必须同时出现且只能用于新会话。URL `projectId` 只是发送前意图来源，不是授权凭证；发出请求后由该不可变提交上下文持有。已有会话、service-account、public_v3 和其他非工作台入口不调用此项目创建能力。

SSE 使用 `text/event-stream`、`Cache-Control:no-store`、`X-Accel-Buffering:no`，15 秒心跳；单帧最大 16 KiB。400/401/403/404 或 JSON/HTML 响应必须先分类，不能当空项目或流成功；断流释放 reader。精确代理规则同时覆盖 `/api/v1/...` 与现有 `/workspace/api/v1/...` 的映射，关闭该路由缓冲，保持原认证、方法、路径、来源和 Cookie。

**错误码**：13011 项目不可用；13012 操作参数无效；13013 快照/cursor 版本变化；13014 请求幂等冲突；13015 会话不可归入当前账号项目；13016 同步传输不可用；13017 导入批次无效；13018 首条项目请求已创建会话（附已拥有 chat_id，供恢复而不重复生成）。实现前复核占用，在现有 chat 130 段继续登记；Web zh-Hans/en/ja 文案同批生成，Desktop 映射到既有语言机制。通用认证错误继续用现有协议。

### 6.2 Desktop 窄桥与模块职责

内部 Python 契约由 ChatSessionService Owner 提供：`create_owned_project_session(actor, session, project_id, request_id)` 返回已创建或重放的 chat_id 及提交版本；外部改名入口接受 actor，后台标题入口从会话解析自然人 owner，并分别提供 async/sync 适配以保留现有调用生命周期；删除入口返回提交后通知信息，再执行原附件清理。项目参数只从已认证的工作台入口传递，不允许 service-account/public_v3 借用。服务负责业务编排，Repository 接受事务 Session 完成 SQL，不能让模型层、Repository 或前端自行调用另一套创建流程。

| 模块/接缝 | 职责与限制 |
| --- | --- |
| `chat_session/api/endpoints/projects.py`（新） | 固定 HTTP 参数及认证；不直接查询 ORM，不跨模块 import API |
| `chat_session/domain/services/project_service.py`（新） | 所属身份、动作和导入编排，发布提交后的通知；不写 ORM 查询 |
| `chat_session/domain/repositories/project_repository.py`（新）及会话 Repository 事务方法 | 项目/归属/版本/回执及分页事务；会话写入由 ChatSessionService Owner 协调，共享提交边界，不能另建会话 runtime |
| `chat_session/domain/services/project_events.py`（新） | SSE 订阅屏障、心跳、重新认证、关闭；Redis 客户端从现有 Context 获取，不新建配置入口 |
| Web `api/chatProjects.ts`、项目 query/mutation hooks、同步控制组件（新） | API 封装、服务端 cache 与生命周期；不把服务器真相再放进本地 store |
| Desktop `src/shared/chat-projects.ts`（新） | 可序列化 DTO、固定动作、unknown 校验、协议版本；不依赖 Node/Electron |
| Desktop main `enterprise/chat-projects.ts`（新） | 认证 Session 的传输、分页快照、重连、身份代际、命令；组装入口不承担这套状态机 |
| `dshEnterpriseChat.projectsState()` / `projectAction(action,expectedEpoch)` / `projectConversations(page,expectedEpoch)` / `onProjectsChanged(listener)`（新） | 返回投影与可定位错误；main 校验可信窗口/主 frame、epoch、动作和参数。禁止任意路径或服务器地址 |
| 嵌入 presentation 的 `onProjectsChanged(listener)`（新） | 只接收无数据失效提示并返回 disposer；不把 main 的账号或权限 API 开给远程页面 |
| Desktop 现有 `createChatProjects` 和项目 UI | 替换为异步桥接及临时 UI 状态，保留现有槽位和组件；旧 localStorage 只用于导入，不继续写作权威数据 |

### 6.3 上游依赖与风险

| 依赖 | 风险与约束 |
| --- | --- |
| MessageSession、SessionSubject、原创建/改名/软删除 Owner | 三个实际创建点、自动标题、删除清理顺序改变时，必须复验项目绑定与失效通知；普通聊天行为仍由原模块决定 |
| SQLModel 发现、在线 Alembic bootstrap、tenant_execution_scope | 新表必须实际被发现并在目标库创建；只 import 模型、只通过 SQLite 或只添加 tenant_id 不算部署验收 |
| Redis async Pub/Sub（含单机、sentinel、cluster） | 使用当前 Context 的连接和 actor 隔离 topic；不能假定开发机单实例语义覆盖 cluster。异常时可见降级并靠数据库版本恢复 |
| Web 认证 shell、React Query v4、现有 API 错误协议 | mount 在隐藏侧栏外；身份变化清缓存和请求，不能使用不稳定 localize 回调作为订阅身份 |
| 原生 Cookie 会话、web-session 续期、Electron session.fetch | Cookie 最长短周期，流须续接；Chat 重试和账号切换会释放 Session，必须一起释放项目控制器 |
| nginx/商业 Gateway | 必须验证 SSE 不缓冲、不断路径、不回 HTML 或登录重定向；Gateway 的实际转发规则为目标部署验收项 |
| 系统二进制与发布资源 | 本功能不新增二进制；Desktop 仍须按现有原生打包脚本构建，不能用 macOS 构建结果代替 Windows 安装验收 |

## 7. 测试、可观测与部署验收

**分层策略**：后端用真实 SQL 事务覆盖并发、回滚、唯一归属和回执，测试两 API worker 的通知、订阅屏障、通知丢失恢复、认证失效和三个创建点。Web 组件测试覆盖等待保存、失败保稿、身份切换、独立历史页、导入与 stream 生命周期；Desktop 测试 main 固定接口和来源校验、Cookie 续期、epoch、流解析/取消、分页一致性及真实 Electron UI。

**联合验收步骤**：部署测试后端并升级数据库，检查 events 实际响应头；打开测试 Web `/workspace/c/new`，并以同一测试账号登录临时 Profile 的 Desktop。双向执行新建/改名/移动/移出/删除、项目首条消息、较早对话和搜索；保持另一端前台，记录提交与可见时间验证 2 秒目标。用两账号和两租户复验拒绝与清理；断开一端网络、在另一端修改后恢复，检查完整恢复；重复导入相同来源，确认没有副本、覆写或丢失原数据。账号使用测试环境分配的普通账号，不记录密码或生产数据。

实现后运行的现有命令：后端 `uv run pytest test/chat_session/`、受影响 workstation/linsight 回归、ruff 与 `scripts/arch-guard.sh`；Web 在 frontend workspace 运行 `pnpm --filter bishengchat test:ci --runInBand <受影响用例>`、lint、typecheck、build 与 locale 检查；Desktop 执行相关 `npm test -- test/...`、`npm run typecheck`、`npm run build`、完整回归及原生验证。`scripts/verify-chat-project-sync.mjs` 已提供并运行双客户端隔离 Electron 验证；真实 3006 及安装包验收分别记录。

日志以 project-sync 阶段、版本、操作/订阅结果、通知失败和重连原因定位，保留底层异常类型；不记录 Cookie、token、正文、完整导入 payload 或姓名。统计提交到另一端可见延迟、快照重启次数、活跃订阅和通知失败。发布顺序为数据库/后端 → Web → Desktop；分别记录源码、构建、实际加载、部署、双端实测和 Windows 状态。回退旧代码保留新增表和原本机数据，不能清库实现回退。

## 8. 后续改进及明确限制

- 幂等与迁移回执初版不按时间自动删除，避免离线旧请求产生重复；达到容量阈值后再设计保持去重语义的归档策略。
- 目前没有团队项目授权、成员协作和 Work 同步；新增这些能力须重审身份与资源边界。
- SQLite/ASGI、Web/桌面行为测试和 macOS Electron 隔离联调已验证。真实 MySQL/Redis 的初步 Web→Desktop 同步已观察到；多节点、DM8、Windows 和正式安装包尚未完成，不能由本地测试替代。

## 修订历史

| 日期 | 内容 | 状态 |
| --- | --- | --- |
| 2026-11-11 | 简化修订：删除 SSE/Redis 推送、版本表与回执表；迁移改为按对话归属判定项目主人（§0） | 用户已确认 |
| 2026-11-06 | 根据已确认的 13 项规格、两仓库实际代码和订阅/会话生命周期核查形成初版；补齐标题/删除的 Owner 事务边界与版本高水位后通过 24 项设计审查 | 已评审，待用户确认，尚未实现 |

2026-11-06 实现修订：同步控制器、四端点、会话 Owner 事务、标题/删除通知及独立分页落地；Snapshot 分页整合和高水位后再发布，失败页在同版本恢复时重读；Desktop 项目/删除弹窗显式让出 native view。用户取消迁移确认，改为 shell 自动迁移、来源身份绑定和退避重试。项目表采用已确认的 created_at/updated_at 对外字段；版本和回执按提交版本追踪，未引入另一套 wall-clock 审计语义。


2026-11-06：实现、自动迁移用户修订、本地/原生回归、3006 前端发布及真实双向读回完成；当前实现及限制见 verification.md。


### 项目草稿生命周期补正（用户反馈，2026-11-06）

宿主打开 new 是动作，不能由 URL 相等判定无需处理。main 在 open(new) 的 dsh:navigate detail 中显式携带 resetDraft=true；其它导航（特别是设置返回）为 false。Web 只对显式重置执行普通 useStartNewChat 生命周期，不把导航等同新建；项目 query 保留给首条提交。正式会话仍消费同一 MessageSession/历史 API，无第二份对话正文。

项目草稿意图在异步租约前固定；逻辑草稿身份用于消息桶、回放导航和幂等请求，第二次 reset 不换身份，下一次明确新建才换。旧流和异步发送完成不能清除另一草稿的输入/附件或采用另一草稿的消息快照。只清理结束且不再活跃的临时草稿，不停止后台正式会话生成。

环境边界：同 origin/tenant/account 才共享项目和对话。localhost 开发页使用哪个数据库由其 API 代理决定；不能把 173 和 119 两个环境当作同账号同步，不自动跨服务复制用户数据。用户截图所示会话经两端 SQL 身份对照已证明分属两服务。
