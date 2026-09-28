# Design: F073 中粮 E+ 智能机器人接入毕昇助手

> **状态：设计已于 2026-09-28 确认，进入实现。** 本文区分「现有代码」与「拟新增」，实现完成前不能把拟议接口或表当作已上线能力。
>
> 技术评审用大白话流程图见 [technical-review-flowcharts.md](./technical-review-flowcharts.md)。

**需求**：[spec.md](./spec.md) · **版本**：v3.0.0-beta1 / 中粮 923 客户线（发布归属待排期确认） · **更新**：2026-09-23
**客户资料**：`/Users/shanghang/Downloads/中粮E+开发者文档_离线全站.html` 的「智能机器人」10 篇；已核对该章的示例报文、表格、流程图与配置截图。本文 §6.2 列出实际使用的对方协议。
**客户接入示例**：[wwlbotdemo](https://gitee.com/hanphycai/wwlbotdemo)（长连接模式封装企业微信官方 `wecom-aibot-python-sdk` 1.0.2，包名 `aibot`）。E+ 文档写明私有化与 SaaS 共用同一 SDK，因此协议细节以该 SDK 源码为准，文档没写清的地方已按 SDK 补齐（见 §2、决策 6）。

## 1. 目标与非目标

目标是让一个 E+ 机器人以一个指定毕昇助手应用为对话核心，接受单聊/群聊的文字和图片，同时把**毕昇知识空间**严格限制在该机器人绑定的空间集合内；发送者必须是已同步、可用的本租户用户。助手应用与 E+ 机器人在租户内一对一，机器人可绑定多个知识空间。内部助手入口的权限与会话行为保持原样。

不改造 E+ 的员工「可见范围」，不接语音/文件/视频/卡片，不让机器人用提问者或助手创建者的空间权限扩围，不承诺非视觉模型能理解一般场景/图表图片。本期仅回复文字（可含 Markdown），不向 E+ 上传或主动推送媒体。

## 2. 关键约束

- 遵循 [constitution](../../../docs/constitution.md) C1–C8；尤其是 C4 的唯一权限执行面、C2 的 MySQL/DM8 双库、C3 的租户隔离与 C8 的跨进程状态不得依赖本地文件。引用现有 [release-contract](../release-contract.md)，不另建一套通用权限体系。
- E+ 长连接每机器人同一时间仅允许一个有效订阅，新连接会踢掉旧连接；订阅请求有频率保护，订阅成功后不得反复订阅。地址由客户管理端给出，格式为 `协议://<私有化地址>/im_openws?bizid=1`，**协议可能是 `wss` 也可能是 `ws`**，不是固定的 `euat.cofco.com`；`wss` 私有化环境可能需客户 CA 证书。
- E+ 后台的 API 模式只能二选一：切到「设置接收消息回调地址」会使现有长连接立即失效，反之亦然。
- 图片下载 URL 仅 5 分钟有效；长连接消息的每个图片 URL 带自己的 `aeskey`，下载内容仍加密。解密口径按官方 SDK `crypto_utils.decrypt_file`：`aeskey` 是 **base64 字符串**（可能缺 `=`，需补齐后解码）→ 32 字节 AES-256 密钥；IV 取密钥前 16 字节；密文长度不是 16 倍数时先补 `\x00` 对齐再做 CBC 解密（不自动去填充）；最后手动去 PKCS#7 填充，填充值允许 1–32 并逐字节校验。E+ 私有化实例是否完全一致，仍需一组真实样例确认。
- 每条发出的帧（`aibot_subscribe`、`ping`、`aibot_respond_msg`）都会收到一条**不带 `cmd`** 的回执 `{headers.req_id, errcode, errmsg}`，回执只能靠 `req_id` 对应。因此同一 `req_id` 的回复必须**串行**：发一帧、等回执（SDK 超时 5 秒）再发下一帧；`errcode≠0` 表示该帧被拒（含限流）。我方自己生成的 `req_id` 按 SDK 约定为 `{cmd}_{毫秒时间戳}_{随机串}`，订阅与心跳回执靠前缀识别。
- 心跳：认证成功后每 30 秒发一次 `ping`；**连续 2 次没收到回执即视为连接已死**，主动关闭并重连。重连按指数退避 1s、2s、4s…上限 30s。
- 对同一回调流式回复必须沿用 `headers.req_id` 与同一 `stream.id`；每次刷新发送的是**截至当前的完整内容**（覆盖显示，不是增量追加），因此 20,480 UTF-8 字节是整条答案的上限；从首次发送起 6 分钟内必须 `finish=true`，否则 E+ 自动结束；长连接回复暂不支持 `msg_item`。每会话合计发送不超过 30 条/分钟、1,000 条/小时（流式刷新是否计入文档未明，按计入设计）。
- 同一用户与同一机器人**最多同时 3 条消息交互中**（E+ 侧限制）。
- 客户文档（接收消息章与长连接章）**明确纯图片 `image` 仅单聊投递**；群聊只有 `text`、`mixed`（含 @机器人 的图文混排）。毕昇解析逻辑不区分单群聊，但不承诺群聊纯图片。
- 群聊 `text.content` 与 `mixed` 文本段带 `@机器人` 前缀（文档示例 `"@RobotA hello robot"`）。
- 组织同步身份链路已确认：客户网关从 IAM 拉取人员，将 IAM `userid` 原样写入推送报文的 `external_user_id`；既有企微组织同步使用常量 `WECOM_SOURCE = 'wecom'`，最终落到 `user.source='wecom'`、`user.external_id=<IAM userid>`。E+ 消息的 `body.from.userid` 用同一原始值，因此机器人准入固定按 `(source='wecom', external_id=from.userid)` 精确匹配，不再将同步来源作为待确认项。
- 助手应用与 E+ 机器人在同一租户内一对一：一个助手最多配置一个机器人，一个机器人只能绑定一个助手；未配置 E+ 的助手仍可正常从毕昇内部使用。每个机器人可绑定零到多个知识空间，无绑定时机器人知识空间范围为空。

## 3. 方案对比与选定

### 决策 1：共用助手核心，E+ 另设接入与会话线路

- **备选 A**：把 E+ 消息模拟成现有助手 WebSocket 客户端，直接走 `ChatManager → ChatClient`。好处是少写会话代码；问题是这条链路绑定浏览器 WebSocket、纯文本 `inputs.input`、个人会话所有者和原有知识权限，群聊、图片及机器人范围都会被强行塞进错误的语义。
- **备选 B**：为 E+ 复制一套独立 Agent。接入隔离简单，但提示词、模型、工具、引用逻辑与内部助手会长期分叉。
- **选定**：E+ 新建接入适配器、会话持久化和回复编排；抽取/扩展 `AssistantAgent` 的可复用执行核心，使其接受显式的输入内容和执行范围。内部 `ChatClient` 仍调用默认路径，E+ 调用带机器人范围的路径，不伪造浏览器 WebSocket。
- **原因**：现有 `assistant_agent.py:533-572` 的 `query: str` 与 `HumanMessage(content=query)` 不接图片，`trim_messages` 还把 `HumanMessage.content` 当字符串编码；`common/chat/client.py` 把会话所有者固定为 `user_id`。仅增加 E+ 外壳无法满足 AC-07、AC-12、AC-17。
- **何时重议**：若平台已有统一的多通道、多人会话 Agent 执行接口且覆盖这些边界，可将 E+ 适配器迁入统一通道层；不能因此改变机器人知识上限。

### 决策 2：首选长连接而非 Webhook

- **备选 A**：Webhook 回调 URL。后端可无状态横向扩展，但客户必须让 E+ 访问回调入口；URL 验证、回调/回复签名与加解密，以及流式刷新轮询均需实现。
- **备选 B**：客户侧 WSS 长连接。无需公网回调，消息体本身不走 Webhook 加密，但要负责单活、心跳、断线重连与媒体资源解密。
- **选定**：首期采用 B，由独立连接 worker 出站连接 E+，复用客户提供的 BotID、Secret、WSS 地址和 CA。部署前先做网络及订阅探测；若客户环境只允许 Webhook，应另行确认协议变更，不在本期悄悄双实现。
- **原因**：客户给的是私有化环境，文档专章与截图给出长连接凭据；该方式消除入站公网依赖及回调 JSON 的额外加解密。一个机器人一条有效连接通过 Redis 租约选主，SQL 保存配置/消息真相；租约失效或旧连接被踢后停止发送并重连。
- **何时重议**：客户无法提供可连通 WSS/CA，或运维明确只批准入站 Webhook；届时沿用下游身份、会话和知识范围，仅替换 E+ 协议适配器。

### 决策 3：机器人知识范围 = 管理员配置的绑定，运行时不看个人或文件级权限

- **备选 A**：用发送者或助手创建者的文件级 `visible` 检索，再按绑定空间过滤。会先检索越界数据；绑定空间内设了自定义权限（CUSTOM，不继承空间授权）的文件夹/文件会被错误排除，违反 AC-13；提示词约束同样不可靠。
- **备选 B**：机器人关联专用 F053 `ServiceAccount`，F048 新增知识空间具体动作 `robot_retrieve` 并授予该服务账号，运行时取「绑定 ∩ 动作授权」。权限语义最完整，但新增动作须改 `authorization_model_f048.py` 的动作集与 `MODEL_VERSION`、在每个环境重新发布模型与 Catalog（未对齐时整个权限运行时失败关闭），且依赖尚未上线的 F048；服务账号上的 CUSTOM 子资源仍不继承空间授权，还得额外绕开文件级过滤。首期代价与风险远大于收益。
- **选定**：**管理员配置、运行时只认绑定**。保存/修改 `EPlusBotSpace` 时，只校验操作者具备该助手的 E+ 接入管理权限（首期复用助手 `edit`，租户管理员按 C4 身份短路），**不再逐个校验操作者对空间的 `manage_permission`**；但后端必须校验空间真实存在、未删除且属于同一租户，不能跨租户绑定。运行时机器人可检索范围 = 当前启用的绑定中、空间仍存在/未删除/属于本租户的那部分；检索按空间 ID 召回，**不调用 `KnowledgeFileVisibilityService`，不看发送者、助手创建者、配置管理员或任何人的文件/文件夹权限**；结果层仅剔除已删除、非解析成功状态或已不属于该空间的文件。不新增 PermissionAction、不改 OpenFGA 模型、不使用服务账号。
- **原因**：机器人空间配置本身就是管理员对该机器人作出的业务授权；管理员选择哪个同租户空间，就代表所有获准使用该机器人的用户都可通过机器人问答该空间内容，配置责任由管理员承担。运行时再叠加管理员个人空间权限会把“机器人授权”错误变成“配置人的个人授权”，也会导致管理员权限变化后机器人范围无意变化。
- **已接受的代价**：具备该助手 E+ 接入管理权限的管理员可以绑定本租户内任意有效空间，因此管理页需明确提示“绑定后，所有可使用该机器人的用户均可问答该空间内容”，并记录操作者及绑定变更审计；撤销时由管理员在机器人配置页移除。
- **何时重议**：客户要求绑定随绑定人权限自动失效、或要求文件级限制时，再评估备选 B（届时仍以**机器人主体**表达限制，不退回发送者个人权限）；F048 若已提供可复用的空间级检索动作也可迁移过去。

### 决策 4：图片统一成一轮内容，理解路径由已声明能力决定

- **备选 A**：无论模型能力都把图片直接塞进助手模型；非视觉端点会报错，旧助手令牌裁剪/历史序列化也会损坏。
- **备选 B**：所有图片只 OCR 成文字；截图文字可用，但图表、物体、场景信息必然丢失。
- **选定**：E+ 先把 `text` / `image` / `mixed.msg_item[]` 规范化为有序文字与图片块；下载解密后沿用日常对话的能力分流：已确认支持视觉的模型接收图片块，非视觉模型只走已配置的文本提取/OCR 能力；没有可用能力时明确告知无法理解图片。助手执行核心补多模态输入及历史裁剪，不改内部文字调用契约。
- **原因**：日常对话现有 `_process_agent_files` 根据 `model_info.visual` 决定图片直送或提取文本，且用 `HumanMessage(content=[text,image_url...])`；助手模型配置目前没有同等视觉声明，不能凭模型名称猜。视觉标记需从可核验的模型配置取得，缺省按非视觉处理。
- **何时重议**：客户要求非视觉模型理解复杂图像且提供独立视觉解析服务时，再增加预处理模型；不能把 OCR 宣称为完整多模态。

### 决策 5：其他工具保留，毕昇知识入口统一受限

- **备选 A**：E+ 机器人禁用全部工具，易守边界但直接违背需求。
- **备选 B**：原样装载所有工具，只对助手自带知识工具加提示词上限；被包装的工作流、API、MCP 若再查毕昇知识空间就能旁路。
- **选定**：普通工具仍按真实发送者身份与现有工具权限装载；助手原本关联的知识库/知识空间工具在 E+ 入口不装载，改为只装载机器人范围检索工具。任何能访问**毕昇知识空间**的内置工具、工作流节点或内网 API/MCP 必须接收同一不可放宽的机器人范围并在真正检索点校验；无法证明可传递范围的此类工具在 E+ 入口失败关闭并提示管理员，不能作为“其他工具”例外。纯外部数据源沿用其独立授权，不假称机器人范围能约束第三方内容。
- **原因**：当前 `AssistantAgent.init_tools` 会从 `AssistantLink` 装载工具与知识源，后者由 `knowledge_auth` 选择发送者或创建者；工具类型还可为任意 API/MCP。只改直接空间工具不能证明 AC-15，须在装载和执行两层拦截。
- **何时重议**：工具框架提供强制的知识范围类型和跨工作流传播能力后，可移除逐类审查；仍须保留实际检索点的失败关闭。

### 决策 6：自研轻量长连接客户端，协议对齐官方 SDK，不直接依赖 SDK

- **备选 A**：直接依赖客户 demo 用的 `wecom-aibot-python-sdk` 1.0.2。协议实现现成，但读源码发现它在私有化环境下有硬伤：
  - SSL 上下文写死为 `certifi` 默认证书（`ws.py`、`api.py` 模块级 `_SSL_CONTEXT`），**不能加载客户的自签 CA**，图片下载同样受影响；
  - 无论 `ws://` 还是 `wss://` 都给 `websockets.connect` 传 `ssl=`，而 `websockets` 对 `ws://` 传 `ssl` 会直接报错，**明文地址连不上**；
  - 订阅返回 `errcode≠0` 时只发 error 事件，不关连接也不重试，连接会挂着但永远收不到消息；
  - 收到 `disconnected_event` 后服务端关闭旧连接，SDK 会自动重连，**重连又会把新连接踢掉**，两边互踢；
  - 默认最多重连 10 次后放弃；回复队列、回执、流状态全在进程内存；还需新增依赖 `pyee`。
- **备选 B**：照 demo 在 SDK 外面包一层并 monkeypatch 私有属性。能跑但依赖 SDK 内部实现，升级即坏，且互踢与订阅失败问题仍要自己补。
- **选定**：在毕昇内自研约 300–400 行的长连接客户端，**帧格式、`req_id` 规则、回执串行、心跳判死、退避参数、解密算法逐项对齐 SDK 源码**；只用已有依赖（`websockets`、`aiohttp`、`cryptography`，均在 `pyproject.toml`）。连接地址支持 `ws`/`wss`，`wss` 与图片下载共用按机器人配置的 CA；订阅失败即关连接并按退避重试，超过阈值告警；收到 `disconnected_event` 不自动重连，标记为「被其他连接接管」并告警。SDK 仅作为测试参照：用 SDK 的 `decrypt_file` 做解密对拍测试。
- **原因**：私有化自签 CA 和 `ws://` 是 E+ 文档明确提到的场景，SDK 在这两处都走不通；互踢和订阅失败挂起会让机器人整体静默失效。协议本身很薄，自研成本与包一层 + 打补丁相当，但行为完全可控。
- **何时重议**：官方 SDK 支持自定义 SSL 上下文与 `ws://`，并正确处理 `disconnected_event` 与订阅失败后，可改为直接依赖 SDK。

### 决策 7：助手应用与机器人一对一，机器人绑定多个知识空间

- **选定**：E+ 接入配置挂在助手应用设置下，但作为独立配置对象保存。租户内同时约束 `(tenant_id, assistant_id)` 唯一和 `(tenant_id, bot_id)` 唯一，即一个助手应用最多绑定一个 E+ 机器人，一个 E+ 机器人也只能绑定一个助手应用。每个机器人通过规范化关联表绑定零到多个知识空间。
- **配置项**：机器人 ID、连接地址、Secret、可选 CA 根证书、知识空间多选、启用状态和连接状态。Secret 只可填写或轮换，不回显；只有私有 CA/自签证书场景才上传 CA，系统可信证书使用默认信任链。机器人配置允许在助手未上线时先保存，但此时不建立连接。
- **原因**：一对一符合本期产品关系，避免同一助手被多个机器人复用后难以解释配置、连接状态和空间范围；知识空间直接支持多个，与单空间相比只增加跨空间召回、去重和测试成本，避免后续再迁移表结构和接口。
- **边界**：删除/停用机器人配置不删除助手；停用助手时机器人连接停止。变更绑定空间仍递增配置版本用于审计和标识本轮快照，但不取消在途回答，也不隔离既有会话历史；下一轮开始时读取最新绑定。

## 4. 系统现状与拟议数据流

### 4.1 现有代码事实

内部助手入口 `api/v1/assistant.py → common/chat/manager.py → common/chat/client.py → api/services/assistant_agent.py`；助手模型、提示词和链接由 `Assistant` / `AssistantLink` 提供。`assistant_agent.py:264-352` 装载工具和知识源；F041 `knowledge/domain/services/space_flow_retrieval.py` 使用 `KnowledgeFileVisibilityService` 按发送者或创建者的文件权限检索。`workstation/domain/services/chat_service.py:1361-1402,1791-1844` 是现有日常对话图片分流与内容块组装的参考，不应直接调用整条日常对话业务链。

105 的 `user` 表有 `source`、`external_id`，代码已有 `WECOM_SOURCE = 'wecom'` 和 `UserDao.aget_by_source_external_id`。网关推送的 `external_user_id` 最终写入 `user.external_id`，可用 `(WECOM_SOURCE, body.from.userid)` 精确找人；机器人入口还要补充删除/停用、自然人身份及租户校验，该查询现状本身**不会**完成上述全部准入校验。

现有代码没有独立的“助手 worker”服务；`AssistantAgent` 是由调用进程直接装载和执行的助手核心。F073 首期同样由 E+ 长连接 worker 在进程内调用共享的 `AssistantAgent` 能力，不新增一次网络调用或 Redis 任务转发。长连接收发、心跳和 Agent 执行必须放在不同异步任务中，并以有界并发隔离，避免一次模型调用阻塞其他机器人或心跳。

### 4.2 拟新增主线

`E+ 长连接回调 → 按订阅机器人确定租户/核对 aibotid → (tenant_id,bot_id,msgid) 落库去重 → 用 (WECOM_SOURCE,from.userid) 精确映射用户 → 建立/读取机器人会话 → 规范化内容（去掉 @机器人 前缀）并下载解密图片 → 按日常对话能力完成图片预处理 → 固定本轮机器人范围 → 进程内调用助手核心（模型/其他工具 + 受限知识工具） → 合并模型流式片段 → 同 req_id、同 stream.id 流式回复 E+ → 持久化结果/审计`。

不存在或不可用的用户在映射步骤即结束，仅回复「无权限使用」。单聊会话键为 `(tenant_id, bot_id, single, from.userid)`；群聊会话键为 `(tenant_id, bot_id, group, chatid)`，但**每一条**群消息仍以 `from.userid` 独立验人。不同机器人即使在同一个群也不共享历史。

连接生命周期按“目标状态”驱动，而不只依赖某一次保存或上线事件：只有**助手已上线 + E+ 配置已启用 + 配置完整有效**三项同时满足，worker 才抢租约并建立长连接；助手下线、E+ 配置关闭或配置删除时释放租约并断开。保存离线助手的机器人配置只落库；助手上线时触发 worker 对账并连接。若助手已经在线，此时新开启 E+ 配置或轮换连接凭据，也会触发对账并连接/重连，不要求管理员先下线再上线。上线/下线与配置接口向 worker 发送变更通知，worker 启动时及运行中还会周期性按数据库状态对账，避免通知丢失后连接状态永久错误。

同一个机器人的所有用户消息都由当前持有该机器人 Redis 租约的 worker 实例从同一条长连接接收；不是每个用户单独启动 worker。这里的“机器人单活租约”就是 Redis 中一把带自动过期时间、需要 worker 持续续期的分布式锁：同一时刻只有抢到锁的一个 worker 可以连接该机器人，避免多个实例互相踢线和重复收发；持有者宕机且租约过期后，其他实例才能接管。worker 内按会话键隔离队列：同一会话的消息按 E+ 到达顺序串行进入 Agent，避免历史乱序；不同单聊/群聊会话可在有界并发内同时执行。

业务去重以 SQL 为最终真相，不依赖进程内集合：完成机器人身份校验后，先原子插入唯一键 `(tenant_id, bot_id, msgid)` 的 `EPlusInboundMessage`；只有插入成功的调用获得执行权。唯一键冲突表示重投，复用原记录的稳定 `stream_id` 和处理结果，不再次启动 Agent，也不再次生成业务回答。Redis 可保存短期热键减少重复查库，但不能作为唯一去重依据。消息记录按 `RECEIVED → QUEUED → PROCESSING → SUCCEEDED/FAILED` 条件更新；超过在途上限的消息记为 `REJECTED_BUSY`，使其重投时也不重复回复。worker 崩溃后通过持久状态识别未完成消息，不能把它当成一条新提问重新执行。

E+ 允许同一用户对同一机器人同时有 3 条消息在途。“在途”是并发控制状态，不是“历史轮次”的同义词：消息已被接收、但尚未得到最终成功或失败回复时都算一条，包含 `QUEUED` 和 `PROCESSING`；完成后即不再计数。前一轮若还没完成，它就是一条在途消息；已经完成的前一轮只是历史，不算在途。`QUEUED` 不是现有内部助手的原逻辑，而是 E+ 接入为“用户连续发消息”新增的排队状态：同一会话正在执行时，后续消息完成验人、落库和图片保存后进入队列，不与前一轮并发。每个会话由当前 E+ worker 内的一个串行消费协程负责；前一轮进入成功/失败/取消终态后，该协程立即取出下一条，重新加载包含前一轮完整问答的最新历史，再发送「处理中」并启动 Agent，不需要用户再次发消息，也不由 Celery 或另一个“助手 worker”触发。worker 崩溃接管后，新持有者根据数据库中的 `QUEUED` 状态恢复未开始任务。排队阶段不提前发送占位；同一用户与机器人已有 3 条在途时，第 4 条立即以 `finish=true` 回复「消息处理中，请稍后再试」，不进入队列。

“6 分钟窗口”是 E+ 对**一条消息的流式回复通道**规定的有效期，不是会话历史有效期，也不是排队超时：从我方向这条消息第一次发送 `aibot_respond_msg`（本设计为「处理中」）开始计时，必须在 6 分钟内用同一 `req_id`、同一 `stream.id` 发送 `finish=true`，否则 E+ 自动结束该回复流。排队时尚未发送首帧，所以该消息自己的 6 分钟还没开始；轮到执行后才开始。我方执行硬上限取约 5 分钟（与客户 demo 的 300 秒一致，给结束帧留余量），到点以明确超时终态结束。**占位帧的回执失败（发送异常、超时或 `errcode≠0`）就不再启动 Agent**，直接把该消息记为失败：占位都发不出去，后面的答案也发不出去，白跑只会浪费模型调用。该设计依赖“6 分钟从首次回复起算”的文档口径；真实环境若要求回调到达后必须在更短时间内首次响应，则改为直接拒绝同会话后续消息，不能让排队消息悄悄超时。

模型流式输出通常是 token/文本片段，不是稳定的“一个字”。worker 不按每个片段立即向 E+ 发帧，而是累计答案并按约 1–2 秒或达到缓冲阈值合并刷新；每次向 E+ 发送的是截至当前的**完整累计内容**，且必须等上一帧回执后再发下一帧，并为 `finish=true` 预留额度。`scope_version` 不是知识空间自身的版本，而是**这个机器人“绑定空间清单”的递增版本号**：每次新增、移除或替换绑定时加一。本轮开始时把版本号和空间 ID 集合一起写入 Turn，作为审计快照；本轮始终使用该空间集合，不在检索或流式发送中途重新比较版本。管理员修改绑定不会打断已开始的回答，下一轮启动时才读取最新版本和空间集合。会话历史跨版本完整保留并继续提供给模型，不按 `scope_version` 过滤。超过回复窗口前结束本轮并回明确超时。

#### 4.2.1 助手详细执行流程

1. **协议与媒体预处理**：E+ 适配层解析 `text/image/mixed`，剥离群聊 `@机器人`；对图片校验下载域名、时效、大小与文件头，使用配置的 TLS CA 下载，再按消息自带 `aeskey` 解密并存入 MinIO。该步骤属于 E+ 接入层，不让通用 `AssistantAgent` 感知企微协议。
2. **图片能力分流**：复用日常对话的图片处理能力。助手模型明确支持视觉时，生成有序的文字/图片内容块；非视觉模型使用已配置的文字提取/OCR，将结果作为本轮文字上下文；两种能力都不可用时明确告知无法理解图片。这里不是固定把所有图片都 OCR 成文字。
3. **建立执行上下文**：读取一对一绑定的助手配置、模型、系统提示词和完整会话历史，注入真实发送者、机器人 ID、空间绑定版本和不可扩大的空间 ID 快照；本轮启动后不再因配置变化替换该快照。
4. **装载工具**：保留普通工具及其原授权。仅在 E+ 本次执行路径中，不加载助手原来关联的知识入口，改为注入只允许检索机器人绑定空间的 `RobotSpaceRetrievalPolicy`；这不是修改助手配置，也不影响助手在毕昇内部的原有行为。任何间接访问毕昇知识空间的工具必须携带同一范围，否则不装载或执行失败关闭。
5. **Agent 循环**：把系统提示词、历史和本轮内容交给模型；模型可以直接生成回答，也可以提出工具调用。执行工具后把结果追加回模型上下文，继续推理，直到形成最终回答或达到步数/时间/取消边界。每次知识检索都只使用本轮启动时固定的机器人空间快照。
6. **流式回传**：助手核心将模型产生的文本片段交给回复组包器；组包器合并、累计、截断和限流后，由长连接发送协程串行发送给 E+。连接协程负责 `req_id/stream.id`、回执和 `finish`，助手核心不直接操作 WebSocket。
7. **完成与审计**：持久化本轮输入引用、实际发送者、空间版本、工具/检索摘要、最终安全文本和发送状态；日志不记录消息原文、Secret、AES key、完整临时 URL 或图片字节。

### 4.3 拟新增数据与模块职责

| 对象/模块 | 内容与职责 | 不做什么 |
|---|---|---|
| `EPlusBotConfig` | `(tenant_id, bot_id)` 与 `(tenant_id, assistant_id)` 分别唯一，落实助手应用↔机器人一对一；保存连接地址、加密 Secret、可选 CA 对象引用、启用状态、连接状态与配置版本 | 不存员工个人空间权限；不把 Secret 写明文配置或日志；不把 CA 当客户端私钥 |
| `EPlusBotSpace` | `(tenant_id, bot_id, space_id)` 唯一、规范化绑定，是机器人知识范围的唯一真相；记录绑定人与时间，配置更改入审计 | 不把 ID 列表塞入大 JSON；不写 PermissionGrant/OpenFGA |
| `EPlusInboundMessage` | `(tenant_id, bot_id, msgid)` 唯一；原子插入决定执行权，记录 `RECEIVED/QUEUED/PROCESSING/SUCCEEDED/FAILED/REJECTED_BUSY`、回调 `req_id`、稳定 `stream_id` 与最终回复状态 | 不用进程内 Set 或 Redis 短期键充当最终消息真相；重投不再次执行 Agent |
| `EPlusConversation` / `EPlusTurn` | 机器人+单聊用户或群聊 ID 的独立上下文；逐轮记录实际发送者、文本、图片对象引用、回答和当时的范围版本 | 不把群聊塞进某个人的内部助手历史，也不让普通会话 API 读到群记录 |
| `EPlusConnectionWorker` | 独立常驻进程；每机器人 Redis 租约单活，同一机器人的所有会话由租约持有实例接收；连接协程负责订阅/心跳/重连/收发，独立有界执行任务在进程内调用 `AssistantAgent` | 不是 Linsight/Celery 式一次性任务消费者；不新增“助手 worker”网络服务；不依赖 `aibot` SDK；收到 `disconnected_event` 不自动重连 |
| `EPlusRobotService` | 校验配置/用户/会话、固定执行范围、编排 Agent、审计 | 不直接操作 OpenFGA tuple 或跨层写 ORM |
| `RobotSpaceRetrievalPolicy` | 使用本轮启动时固化的空间 ID 快照召回；结果层剔除已删除、非解析成功或已移出这些空间的文件 | 不在执行中重读绑定或因改绑撤销本轮；不调用 `KnowledgeFileVisibilityService`，不看任何人的文件/文件夹权限，不只靠提示词 |
| `AssistantAgent` 的显式执行上下文 | 默认内部入口保持原行为；E+ 入口接收有序内容块、真实发送者和不可扩大的机器人知识范围 | 不感知 E+ 的 WS 命令、Secret 或群 ID |

#### 4.3.1 五张新增表

关系如下；`EPlusInboundMessage` 管协议幂等与收发状态，`EPlusTurn` 管助手上下文，二者不能合并，否则协议重投、未授权/忙碌拒绝和正常会话历史会混在一起。

```text
Assistant 1 ── 0..1 EPlusBotConfig 1 ── N EPlusBotSpace
                              ├────── N EPlusInboundMessage 0..1 ── 1 EPlusTurn
                              └────── N EPlusConversation 1 ────── N EPlusTurn
```

**1. `eplus_bot_config` — 助手应用与机器人一对一配置**

| 字段 | 类型 / 约束 | 语义 |
|---|---|---|
| `id` | BIGINT，PK | 稳定配置主键；历史表引用它，机器人 ID 轮换时历史仍可追溯 |
| `tenant_id` | INT，NOT NULL | 租户边界，所有唯一键和查询必须带上 |
| `assistant_id` | VARCHAR(64)，NOT NULL | 逻辑关联 `assistant.id`；保存时校验同租户且未删除，允许助手未上线时预先保存配置 |
| `bot_id` | VARCHAR(128)，NOT NULL | 客户 E+ 机器人 ID；订阅与回调核对使用 |
| `connection_url` | VARCHAR(1024)，NOT NULL | 客户提供的 `ws://` / `wss://` 长连接地址 |
| `secret_ciphertext` | TEXT，NOT NULL | Secret 经平台密钥加密后的密文；接口永不回显明文 |
| `credential_version` | BIGINT，NOT NULL，默认 1 | Secret/CA/地址轮换时递增，worker 据此重建连接 |
| `ca_object_key` | VARCHAR(512)，NULL | 私有 CA/自签根证书在 MinIO 的对象引用；公网可信证书为空 |
| `ca_sha256` | CHAR(64)，NULL | 上传证书完整性及变更识别；上传内容必须是 CA 证书，拒绝私钥 |
| `media_host_allowlist` | `JsonType`，NOT NULL | 允许下载临时图片的主机白名单；不从消息 URL 动态放宽 |
| `enabled` | BOOL，NOT NULL | 是否启用 E+ 接入；关闭后释放租约并断开连接 |
| `is_deleted` | BOOL，NOT NULL，默认 false | 解除接入时逻辑删除并断开；重新配置同一助手时复用该稳定配置行，历史引用不失效 |
| `connection_status` | VARCHAR(32)，NOT NULL | `DISABLED/CONNECTING/AUTHENTICATED/RETRYING/TAKEN_OVER/ERROR`；用于管理页展示，不以它代替 Redis 租约 |
| `last_connected_at` / `last_error_at` | DATETIME，NULL | 最近成功建连和最近错误时间 |
| `last_error_code` | VARCHAR(64)，NULL | 脱敏的稳定错误分类，不存 Secret、URL 或报文原文 |
| `scope_version` | BIGINT，NOT NULL，默认 1 | 空间绑定变化时递增；用于配置通知、本轮快照标识与审计，不取消在途执行、不切断历史 |
| `created_by` / `updated_by` | BIGINT，NOT NULL | 配置与轮换操作者 |
| `create_time` / `update_time` | DATETIME，NOT NULL | 使用项目统一时间默认值 |

约束与索引：`UNIQUE(tenant_id, assistant_id)`、`UNIQUE(tenant_id, bot_id)`；索引 `(tenant_id, enabled, connection_status)`。机器人配置不物理级联删除，停用助手或解除接入时保留配置/历史并关闭连接。

**2. `eplus_bot_space` — 机器人多知识空间绑定**

| 字段 | 类型 / 约束 | 语义 |
|---|---|---|
| `id` | BIGINT，PK | 绑定行主键 |
| `tenant_id` | INT，NOT NULL | 租户边界 |
| `bot_config_id` | BIGINT，NOT NULL | 关联 `eplus_bot_config.id` |
| `space_id` | BIGINT，NOT NULL | 逻辑关联知识空间 `knowledge.id`；保存时校验同租户、存在且未删除 |
| `bound_by` | BIGINT，NOT NULL | 执行绑定的管理员用户 ID |
| `create_time` | DATETIME，NOT NULL | 绑定时间 |

约束与索引：`UNIQUE(tenant_id, bot_config_id, space_id)`；索引 `(tenant_id, space_id)`。一次保存用事务替换绑定集合并递增 `eplus_bot_config.scope_version`；解绑物理删除关联行，但审计日志保留操作者和变更前后集合。

**3. `eplus_inbound_message` — 回调去重与协议状态**

| 字段 | 类型 / 约束 | 语义 |
|---|---|---|
| `id` | BIGINT，PK | 消息内部 ID |
| `tenant_id` | INT，NOT NULL | 租户边界 |
| `bot_config_id` | BIGINT，NOT NULL | 收到消息时对应的机器人配置 |
| `bot_id` | VARCHAR(128)，NOT NULL | 收到消息时的机器人 ID 快照，参与幂等键 |
| `msgid` | VARCHAR(255)，NOT NULL | E+ 业务消息 ID；缺失即丢弃并告警，不造随机值 |
| `req_id` | VARCHAR(255)，NOT NULL | 本次回调回复关联 ID，不用于业务去重 |
| `stream_id` | VARCHAR(255)，NOT NULL | 由 `(bot_id, msgid)` 稳定派生，同一消息的所有回复刷新保持一致且跨机器人不冲突 |
| `conversation_id` / `turn_id` | VARCHAR(64)，NULL | 通过准入后关联内部会话与轮次；无权限和忙碌拒绝不创建 Turn |
| `sender_external_id` | VARCHAR(255)，NOT NULL | E+ `from.userid` 原值 |
| `sender_user_id` | BIGINT，NULL | 匹配到的毕昇自然人；未匹配时为空 |
| `chat_type` | VARCHAR(16)，NOT NULL | `SINGLE/GROUP` |
| `chat_id` | VARCHAR(255)，NULL | 群聊使用 E+ `chatid`；单聊为空 |
| `msg_type` | VARCHAR(16)，NOT NULL | `TEXT/IMAGE/MIXED` |
| `payload_sha256` | CHAR(64)，NOT NULL | 原始回调规范化摘要，用于异常重投对账；不在本表保存完整原文 |
| `status` | VARCHAR(32)，NOT NULL | `RECEIVED/QUEUED/PROCESSING/SUCCEEDED/FAILED/REJECTED_BUSY` |
| `reply_status` | VARCHAR(32)，NOT NULL | `NOT_STARTED/STREAMING/FINISHED/SEND_FAILED` |
| `error_code` | VARCHAR(64)，NULL | 如用户无权限、图片失败、助手超时、E+ 回执失败等稳定分类 |
| `received_at` / `started_at` / `finished_at` | DATETIME，按阶段可空 | 排队、执行和时延统计 |
| `create_time` / `update_time` | DATETIME，NOT NULL | 通用审计时间 |

约束与索引：`UNIQUE(tenant_id, bot_id, msgid)`、`UNIQUE(tenant_id, stream_id)`；索引 `(tenant_id, bot_config_id, status, received_at)`、`(tenant_id, sender_external_id, status)`。先插入本表再做用户准入与排队判断，因此无权限和第 4 条忙碌拒绝同样具备幂等性。

**4. `eplus_conversation` — 独立单聊/群聊上下文**

| 字段 | 类型 / 约束 | 语义 |
|---|---|---|
| `id` | VARCHAR(64)，PK | 内部会话 ID，不暴露给 E+ |
| `tenant_id` | INT，NOT NULL | 租户边界 |
| `bot_config_id` | BIGINT，NOT NULL | 所属机器人配置 |
| `assistant_id` | VARCHAR(64)，NOT NULL | 创建会话时绑定的助手 ID 快照 |
| `chat_type` | VARCHAR(16)，NOT NULL | `SINGLE/GROUP` |
| `conversation_key` | VARCHAR(255)，NOT NULL | 单聊为 `from.userid`，群聊为 E+ `chatid` |
| `scope_version` | BIGINT，NOT NULL | 最近一次创建 Turn 时的空间绑定版本，仅作会话范围状态与审计标识；不用于过滤历史 |
| `next_turn_seq` | BIGINT，NOT NULL，默认 1 | 事务内递增，为同会话排队和历史顺序分配序号 |
| `status` | VARCHAR(16)，NOT NULL | `ACTIVE/CLOSED` |
| `create_time` / `update_time` | DATETIME，NOT NULL | 会话建立与最近活动时间 |

约束与索引：`UNIQUE(tenant_id, bot_config_id, chat_type, conversation_key)`；索引 `(tenant_id, bot_config_id, update_time)`。群聊会话由全群共享历史，但每个 Turn 仍保存实际发送者并逐条验人。

**5. `eplus_turn` — 助手轮次与内部历史**

| 字段 | 类型 / 约束 | 语义 |
|---|---|---|
| `id` | VARCHAR(64)，PK | 轮次 ID |
| `tenant_id` | INT，NOT NULL | 租户边界 |
| `conversation_id` | VARCHAR(64)，NOT NULL | 所属 `eplus_conversation.id` |
| `inbound_message_id` | BIGINT，NOT NULL | 一条有效回调最多产生一个 Turn |
| `turn_seq` | BIGINT，NOT NULL | 同会话严格递增；排队和读取历史按此排序 |
| `sender_user_id` | BIGINT，NOT NULL | 本轮真实毕昇用户 |
| `sender_external_id` | VARCHAR(255)，NOT NULL | 本轮 E+ 原始用户 ID 快照 |
| `user_text` | TEXT，NULL | 去掉 @ 前缀后的文字内容 |
| `content_manifest` | `JsonType`，NOT NULL | 有序文字/图片块及 MinIO 对象引用、媒体类型和大小；不存图片字节 |
| `extracted_text` | TEXT，NULL | 非视觉路径得到的 OCR/文字提取结果 |
| `scope_version` | BIGINT，NOT NULL | 本轮使用的机器人空间绑定版本 |
| `scope_space_ids` | `JsonType`，NOT NULL | 本轮实际空间 ID 快照，是本轮检索授权边界并用于审计；配置变更不撤销本轮，下一轮重新生成快照 |
| `assistant_run_id` | VARCHAR(64)，NULL | 关联助手执行/运行日志，便于定位工具和模型失败 |
| `answer_text` | TEXT，NULL | 实际向 E+ 完成发送的安全文字；最长遵守协议 20,480 UTF-8 字节 |
| `status` | VARCHAR(16)，NOT NULL | `QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED` |
| `error_code` | VARCHAR(64)，NULL | 稳定失败分类，不保存内部异常堆栈 |
| `queued_at` / `started_at` / `finished_at` | DATETIME，按阶段可空 | 排队和执行耗时 |
| `create_time` / `update_time` | DATETIME，NOT NULL | 通用审计时间 |

约束与索引：`UNIQUE(tenant_id, inbound_message_id)`、`UNIQUE(tenant_id, conversation_id, turn_seq)`；索引 `(tenant_id, conversation_id, scope_version, turn_seq)`、`(tenant_id, status, queued_at)`。把该会话此前已成功完成的 Turn 跨 `scope_version` 组装为完整助手历史；这些记录不向 E+ 提供历史查询或同步接口。

五表内引用使用明确外键或等价的仓储校验，禁止级联删除会话与轮次；对既有 `assistant`、`knowledge`、`user` 使用逻辑关联并在业务 Service 校验存在性、租户和状态。MySQL/DM8 均使用 `dialect_helpers` 的 JSON/更新时间兼容类型，状态字段使用字符串常量而非数据库原生 Enum。第 3 条在途准入用 Redis 原子计数（按 `tenant_id + bot_id + sender_external_id`，带 TTL）加 SQL 非终态记录对账，不能用单进程内计数。

新表使用关系列与 `dialect_helpers`，租户字段按 C3 自动注入；跨进程图片字节放 MinIO、DB 只存对象指针与元数据，Redis 仅作租约、短期去重加速和节流。助手应用设置中增加可选的“E+ 机器人接入”（机器人 ID、连接地址、Secret、可选 CA 根证书、知识空间多选、启用状态、连接状态/密钥轮换）；Secret 只写不回显，公网可信证书无需上传 CA。空间选择器向具备该助手 E+ 接入管理权限的管理员展示本租户全部有效空间，保存时后端校验空间存在、未删除且同租户；界面明确提示绑定后的机器人使用者均可问答所选空间。UI 仅使用已有已落地组件与三语 i18n，不修改设计规范或发明新组件。

### 4.4 关键外部字段

| E+ 字段 | 用途 | 校验/边界 |
|---|---|---|
| `headers.req_id` | 一次回调的回复关联 | 同轮所有 `aibot_respond_msg` 原样透传；不用于业务去重 |
| `body.msgid` | E+ 回调去重键 | 与当前订阅 BotID、租户组成唯一键；网络重投不得二次执行；缺失时记告警并丢弃，**不能**像 demo 那样用随机 UUID 兜底（会让去重失效） |
| `body.aibotid` | 机器人 ID | 必须等于当前已认证订阅的 BotID，不能仅凭消息体选择租户 |
| `body.from.userid` | 中粮员工原始 ID | 与 IAM `userid`、网关同步报文 `external_user_id`、毕昇 `user.external_id` 是同一原始值；固定用 `(WECOM_SOURCE='wecom', from.userid)` 查本租户自然人，无记录返回固定文案 |
| `body.chattype` / `body.chatid` | 单聊/群聊会话键 | 群聊必须有 `chatid`；单聊以发送者 ID 为键，不能把昵称当键 |
| `body.msgtype`、`text.content`、`mixed.msg_item[]`、`image.url/aeskey` | 本轮有序文字/图片内容 | 只接受本期三类（纯图片仅单聊会出现）；`msg_item` 各项优先看 `msgtype`，缺失时按是否含 `text`/`image` 键判断（demo 测试用例里的 `msg_item` 就没有 `msgtype`）；文本去掉 `@机器人` 前缀；图片类型按文件头魔数判断，不信下载响应里的文件名；图片 URL 只从该机器人配置的 E+ 下载域名下载（私有化域名各异，按机器人配置，不写死文档示例域名）并解密 |
| `stream.id`、`stream.finish/content` | 同一回答的创建、刷新和结束 | 同 `msgid` 稳定生成；每次刷新发送完整累计内容；超 20,480 字节截断并附提示；超时/失败也发送明确终态 |
| `aibot_event_callback` 的 `body.msgid`、`event.eventtype` | 事件去重与分派 | 仅处理 `disconnected_event`；`enter_chat`、`template_card_event`、`feedback_event` 按 `msgid` 去重后忽略 |

## 5. 已知坑与安全边界

| # | 事实 / 后果 | 处理位置 |
|---|---|---|
| 1 | 长连接**消息明文**不代表图片明文；把下载结果直接交模型会得到乱码，5 分钟后再下载会失效。解密也不是标准做法：`aeskey` 要补 `=` 后 base64 解码，密文要补零对齐，填充值最大到 32，直接用常规 PKCS#7(16) 去填充会报错。 | E+ 图片适配：收到后尽快下载，按 §2 所列 SDK 口径解密（与 SDK `decrypt_file` 对拍），校验魔数/尺寸后存 MinIO。 |
| 2 | E+ 同一个机器人新订阅会踢旧连接；多 API 副本同时启动会反复互踢，可能漏消息。 | 独立连接 worker + Redis 单活租约/心跳；SQL 去重并支持重连后恢复，旧 worker 失去租约即停止发送。 |
| 3 | `req_id` 关联回复，`msgid` 才是业务去重；混用会生成重复答案。 | 回调协议层/`EPlusInboundMessage`；重投沿用稳定 `stream_id`，对发送结果做幂等记录。 |
| 4 | 当前助手 `knowledge_auth` 仅在人/创建者之间切换，**没有机器人范围**；直接复用会越权或漏检索。 | `AssistantAgent` 装载机器人专属知识工具；实际 RAG 层再做空间与文件归属过滤。 |
| 5 | 直觉上会想复用现有空间检索（`space_flow_retrieval` → `KnowledgeFileVisibilityService`）并换个身份；但它按文件级 `visible` 过滤，设了自定义权限（CUSTOM，不继承空间授权）的文件夹/文件会被排除，违反 AC-13。 | `RobotSpaceRetrievalPolicy` 另走按空间 ID 召回的路径，只做文件存在/状态/归属过滤；内部入口仍走原路径。 |
| 6 | E+ 群答复对**整个群**可见，回调只给发送者 ID，没有全体收件人的权限快照；即使未同步成员不能提问，仍可能读到群答复。 | 上线门禁：客户确认绑定空间内容允许在该机器人的可加入群传播；否则只开单聊或由 E+ 限制群使用。毕昇不能伪称逐成员保密。 |
| 7 | 引用消息可能在 `quote` 中带图片/文字；本期只要求当前消息的三类输入，引用内容不可悄悄扩大知识/图片范围。 | 规范化层将 `quote` 单列为上下文并按相同下载、校验策略处理；无法安全处理则忽略引用并提示，不当作新的授权来源。 |
| 8 | 助手可挂任意 API/MCP 工具，某些工具可能再调用毕昇知识 API；只过滤助手知识链接不够。 | 配置与运行时工具能力审查；内部知识调用必须传机器人范围；无法验证者在 E+ 入口拒用并告知管理员。 |
| 9 | 旧会话可能含已撤绑空间的检索摘要。 | 经客户确认，本期接受该边界：历史不按绑定版本过滤；解绑只影响下一轮新检索，不追溯清除或屏蔽旧历史。 |
| 10 | 文档主动推送段表格列 `markdown/template_card`，后文又列媒体类型；该处不一致。 | 本期仅用 `aibot_respond_msg` 回复文字流，不实现 `aibot_send_msg` 或媒体主动推送；若扩围先联调核实。 |
| 11 | 流式 `content` 是**覆盖**语义：第一次发 "1"、第二次发 "123"，最终显示 "123"。按增量发送会只显示最后一个片段；20,480 字节限制的是整条答案而非单个片段。 | 回复组包：每次刷新发送累计全文；接近上限时截断并附「内容过长已截断」提示后 `finish=true`。 |
| 12 | 30 条/分钟是**每会话**所有回复与推送的总额，按 token 频率刷新几秒即耗尽；群聊多轮回答共享同一额度，超限后连结束消息都发不出去。 | 回复组包：刷新合并（最小间隔约 1–2 秒，另受回执串行天然限速），每会话在 Redis 维护发送额度并为 `finish=true` 预留配额。参考：客户 demo 每 0.3 秒检查一次、内容有变化就推，说明刷新帧大概率不按 30 条/分钟计，但文档未写明，仍按计入设计。 |
| 13 | 群聊文本带 `@机器人` 前缀；原样交给模型会干扰理解，也会污染会话历史。 | 规范化层：按文档格式剥离开头的 @ 提及后再入会话与模型。 |
| 14 | 订阅有频率保护；Redis 租约在多个 worker 间来回切换会导致反复订阅，可能被 E+ 限制，表现为机器人整体收不到消息。 | 连接 worker：租约续期留足余量、重连指数退避并设订阅次数上限，订阅被拒时告警而不是紧密重试。 |
| 15 | E+ 后台一旦把机器人切到「设置接收消息回调地址」模式，长连接立即失效，毕昇侧只看到断线。 | 上线说明写明客户侧须保持「长连接」模式；连接 worker 连续订阅失败时在后台连接状态中提示检查 E+ 模式。 |
| 16 | 连接地址可能是 `ws://`（明文）；此时 Secret 与消息内容在网络上明文传输。 | 连接 worker 同时支持 `ws`/`wss`；配置为 `ws` 时后台显示风险提示，上线门禁要求客户书面知悉。 |
| 17 | 回执没有 `cmd`，只能按 `req_id` 对应；同一 `req_id` 并发发多帧，回执会对不上，刷新可能被静默丢弃或乱序。 | 连接客户端：每个 `req_id` 一个发送队列，发一帧等回执（5 秒超时）再发下一帧；超时或 `errcode≠0` 记入 `EPlusInboundMessage` 并停止该轮刷新。 |
| 18 | 客户 demo 能跑通，不代表官方 SDK 能在毕昇私有化环境里用：SDK 写死 `certifi` 证书、对 `ws://` 也传 `ssl` 参数（毕昇装的 `websockets` 会抛 `ssl argument is incompatible with a ws:// URI`）。 | 决策 6：自研客户端；CA 按机器人配置，同时用于建连和图片下载。 |
| 19 | 客户 demo 在长连接模式下**只处理文字消息**（只注册了 `message.text`），图片、图文混排从未在客户环境跑过，没有可参照的实现。 | 联调把单聊图片、图文混排排在最前面验证；解密先用 SDK `decrypt_file` 做对拍测试。 |
| 20 | 官方 SDK 在服务端关闭旧连接后会自动重连，而这次关闭正是 `disconnected_event` 触发的，重连会把新连接踢掉，形成两边互踢、谁都收不全消息。 | 连接客户端：收到 `disconnected_event` 后停止发送、不重连、释放或冻结租约并告警；由管理员确认是否有其他程序在用同一机器人。 |
| 21 | 订阅失败（`errcode≠0`）时连接本身还是通的，若不主动关闭，心跳可能照常成功，后台看起来「已连接」却永远收不到消息。 | 连接客户端：订阅失败即关闭连接，按退避重试并计数；后台连接状态区分「已连接未认证」与「已认证」。 |

## 6. 对外契约与依赖

### 6.1 毕昇侧拟提供的接口

| 契约 | 消费者 | 要点 |
|---|---|---|
| 助手 E+ 接入管理 API（路由在实现时定稿） | 助手应用设置页 | 同租户内强制助手↔机器人一对一；保存时校验操作者具备助手 E+ 接入管理权限，并校验所选空间均真实存在、未删除且属于同一租户，不校验操作者对每个空间的个人权限；保存机器人 ID、连接地址、Secret、可选 CA 根证书、多个空间和启用状态；Secret 只可写/轮换不可回显。 |
| `EPlusRobotService.handle_message(bot_context, callback)` | 长连接 worker | 只接已订阅身份与校验过的消息；返回安全的回复任务，不接受任意客户端自报 `bot_id` 取得权限。 |
| `AssistantAgent` 执行上下文扩展 | E+ 编排与既有 `ChatClient` | 内部入口默认文本与原权限；E+ 入口显式多模态块、工具调用人、机器人范围；范围不得被工具或提示词扩大。 |
| `RobotSpaceRetrievalPolicy` | 助手知识工具与嵌套的毕昇知识读取 | 查询只使用本轮启动时固化的空间快照；所有 Milvus/ES 结果均核验空间归属与文件状态。 |

### 6.2 实际使用的中粮 E+ 接口/命令（长连接方案）

| 方向 | 对方接口/WS `cmd` | 本期用途与关键字段 |
|---|---|---|
| 毕昇 → E+ | `ws(s)://…/im_openws?bizid=1` | 出站建连；准确 URL、协议（`wss` 或 `ws`）和 CA 从客户机器人详情页取得，不能将文档示例地址写死。 |
| 毕昇 → E+ | `aibot_subscribe` | `body.bot_id` + `body.secret` 订阅并鉴权；`headers.req_id` 形如 `aibot_subscribe_{ts}_{rand}`，回执靠前缀识别，只有 `errcode=0` 才收消息；失败即关连接并退避重试。 |
| E+ → 毕昇 | `aibot_msg_callback` | 收文字、图片（仅单聊）、图文混排；读 `headers.req_id`、`body.msgid/aibotid/chattype/chatid/from.userid/msgtype` 及内容。 |
| 毕昇 → E+ | `GET image.url` | 5 分钟内下载加密图片；用同个图片结构中的 `image.aeskey` 解密。图文混排中的每张图片独立处理。URL 为回调给出的临时地址，并非固定 REST 路由。 |
| 毕昇 → E+ | `aibot_respond_msg` | `body.msgtype=stream`，同 `req_id`、同 `stream.id` 先发处理中/答案更新，最后 `finish=true`；每次发送累计全文，不带 `msg_item`；无权限也用此命令回复固定文案。 |
| 双向 | `ping` | 认证成功后每 30 秒发一次，`req_id` 形如 `ping_{ts}_{rand}`；连续 2 次无回执判定连接已死，关闭后按 1s 起、上限 30s 的指数退避重连。 |
| E+ → 毕昇 | 回执帧（无 `cmd`） | 对我方每一帧的应答 `{headers.req_id, errcode, errmsg}`；按 `req_id` 匹配，同一 `req_id` 串行等待，超时 5 秒。 |
| E+ → 毕昇 | `aibot_event_callback` | 仅 `disconnected_event` 有动作：旧连接被新连接替换时停止发送、不抢回连接；`enter_chat`、`template_card_event`、`feedback_event` 去重后忽略，不生成欢迎语/卡片。 |

**明确不用的对方接口**：Webhook 的 GET URL 验证、加密 POST 回调和加密被动回复；`response_url` HTTP 主动回复；`aibot_send_msg` 无触发主动推送；`aibot_respond_welcome_msg`、模板卡片更新、媒体上传三段命令。它们都在客户文档中，但不属于本期会话主线。若改为 Webhook，需单独纳入 URL 验证、签名、解密和回包协议，不能把本表的 WS 命令当 HTTP API。

### 6.3 对内依赖与变更影响

| 依赖 | 关系与风险 |
|---|---|
| F048 统一权限入口 | 仅在后台保存绑定时校验操作者具备助手 `edit`（作为首期 E+ 接入管理权限）；不校验空间 `manage_permission`，不新增动作、不改 OpenFGA 模型、不写 Grant。空间只做同租户、存在和有效性校验。权限服务不可用时保存失败，已生效绑定不受影响。 |
| 组织同步 User | 复用既有 `WECOM_SOURCE = 'wecom'`；网关把 IAM `userid` 原样放入 `external_user_id` 并落为 `user.external_id`，机器人入口以 `(WECOM_SOURCE, body.from.userid)` 精确映射真实自然人，不自动创建缺失员工。 |
| F041 空间检索、F029/F054 引用 | 内部入口原路径不变；E+ 独立检索范围和空间内文件口径。E+ 只回安全文字，不公开内部 citation token/直链；若后续开放来源详情，需新增按机器人范围的解析校验，不能套 `shared` 档。 |
| 助手与工具框架 | 共用模型、提示词、非知识工具；助手关联的普通知识库和知识空间不能在 E+ 入口旁路机器人范围，任意 API/MCP 工具若触及毕昇知识须可传入范围，否则拒用。 |
| E+ 私有化网络/证书/Secret | 连接地址、CA、Secret、图片下载域名由客户提供；不拿文档的 `euat.cofco.com` 当生产地址。Secret 与临时图片 URL、AES key 不入普通日志。客户侧须保持机器人为「长连接」模式。待客户确认项见 [customer-checklist.md](./customer-checklist.md)。 |

### 6.4 错误与文案

本草案不占用新 `MMMEE` 模块：后台的未授权、资源不存在、助手未上线沿用现有错误；E+ 用户不存在/不可用对外固定回复「无权限使用」，图片不可用、模型失败、超时以明确文字终态回复并在审计中区分原因。若实现阶段确需新增可分支处理的后台业务错误，先按 C5 核对模块编码、更新版本契约及本文，再落代码，不能把内部异常原样回给 E+ 用户。

## 7. 测试、上线门禁与可观测

- **单元**：`text/image/mixed` 归一化（含 `@机器人` 前缀剥离）、模型小片段按约 1–2 秒/阈值合并、流式累计全文与 20,480 字节截断、每会话额度、群/单会话键、`(WECOM_SOURCE='wecom', from.userid)` 身份匹配、用户缺失固定回复、消息去重、图片解密（与 SDK `decrypt_file` 对拍，覆盖缺 `=` 的 key、非 16 倍数密文、填充值 17–32）、超时/大小限制、本轮空间快照固定且下一轮读取新绑定、历史跨版本保留、工具嵌套不能放宽范围。
- **连接客户端**：用本地模拟 E+ 服务（按 SDK 帧格式）覆盖：`ws://` 与带自签 CA 的 `wss://` 都能连；订阅失败即断开并退避；连续 2 次无心跳回执重连；同一 `req_id` 串行等回执、回执超时与 `errcode≠0`；收到 `disconnected_event` 后不重连；占位帧失败不启动 Agent。
- **集成**：MySQL 与 105 DM8 验证新表及唯一键，包括同租户助手 ID/机器人 ID 一对一和 `(tenant_id, bot_id, msgid)` 并发插入只有一个执行者；验证一个机器人绑定多个空间；具备助手 E+ 接入管理权限的管理员即使没有空间个人权限也可绑定同租户空间，跨租户、已删除或不存在空间必须拒绝；绑定空间内含 CUSTOM 文件夹时仍可检索；Milvus/ES 检索前后过滤；MinIO 图片对象跨进程读取；Redis 租约切主。内部助手原有测试必须原样通过。
- **E+ 真实联调**：客户创建机器人并给出 WSS/CA/BotID/Secret、真实同步用户；单聊发送文字、纯图片、图文混排，群聊 @机器人 发送文字、图文混排；群聊纯图片按文档不投递，只确认 E+ 行为与文档一致；同一用户连发 3 条验证排队与 6 分钟窗口；长回答验证刷新频率不触发 30 条/分钟限制；用两个机器人绑定互斥空间、一个拥有额外个人权限的员工、一个库中不存在的 ID 测越权与「无权限使用」；断线、重复 `msgid`、图片 URL 超时，以及执行中改绑后本轮继续、下一轮使用新绑定再测一遍。105 当前没有真实同步用户样本，此项不能用 `local/loadtest` 冒充通过。
- **已完成协议探针基线（2026-09-28，客户测试环境）**：系统 CA 直接通过 TLS；订阅鉴权、单聊文本、单聊图片、图文混排、群聊 @机器人、图片下载解密、30 秒心跳与逐帧回执全部通过；未发生连接接管，手动 SIGTERM 退出。该结果只证明 E+ 协议链路，不替代毕昇身份、知识范围、排队与助手执行的集成验收。
- **图片发布门禁**：客户部署必须至少验证一种可用的图片处理路径（视觉模型或已配置的文字提取/OCR）；若验收包含图表、场景等非文字内容，则必须验证视觉模型路径，不能以 OCR 用例替代。
- **连接发布门禁**：客户 E+ 后台机器人保持「长连接」模式；若连接地址为 `ws://`，客户书面知悉明文传输风险。联调开始前完成 [customer-checklist.md](./customer-checklist.md) 中的阻断项。
- **群聊发布门禁**：客户书面确认所绑空间可以对机器人所在群全部成员展示；若不能确认，群聊知识问答不启用。机器人 E+「可见范围」不能替代此确认。
- **观测**：按租户/机器人聚合连接状态、重连、订阅失败、消息去重、用户不匹配、图片下载/解密、范围拒绝、模型/工具失败、回复延迟/超时、E+ `errcode` 与限流；日志保留可追踪 `msgid`/`req_id` 的脱敏摘要，不记录消息原文、Secret、AES key、完整临时 URL 或图片字节。

## 8. 暂不做与重议条件

不提供 E+ 模板卡片、欢迎语、语音/文件/视频、主动推送或媒体上传；需要时另起范围并用客户环境验证文档不一致处。图片复杂视觉理解以客户部署的视觉模型为前提，OCR 不能替代。任意第三方工具私有数据不由机器人知识空间绑定自动管控；若客户要求所有外部信息也只来自绑定空间，须收缩工具清单并重议产品范围。

客户 demo 里有两项本期不做、但可作为后续候选：用户说「清除历史 / 重新开始」时重置会话上下文（demo 用关键词 + 模型返回 `/clear` 两道判断）；首条流式回复带 `stream.feedback.id`，接收 `feedback_event` 做点赞点踩统计。demo 的 Skill 脚本执行（按模型输出拼命令行在服务器上执行子进程）**不采用**：毕昇已有工具体系，且让模型直接决定服务器命令有命令注入风险。

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-23 | 初版设计草案；选定助手核心复用 + E+ 独立线路、WSS、机器人专属空间授权、图片能力分流，并列出实际使用的 E+ 命令 | 用户确认需求稿并要求设计及对方接口清单 |
| 2026-09-23 | 决策 3 改为「配置时鉴权、运行时只认绑定」：去掉服务账号与 F048 `robot_retrieve` 动作（不升级 OpenFGA 模型），运行时不看文件级权限；原方案降为备选 B | 设计评审：新增动作需升级权限模型且依赖未上线的 F048，用户要求首期按简单方式做 |
| 2026-09-23 | 按客户文档逐条对齐：纯图片仅单聊投递、连接协议可能为 `ws`、流式覆盖语义与整条上限、每用户 3 条在途、@ 前缀剥离、订阅频率保护、API 模式互斥、事件去重忽略；新增坑 11–16 与客户确认清单 | 与《中粮 E+ 开发者文档》智能机器人章复核 |
| 2026-09-24 | 按客户 demo 及其依赖的官方 SDK 源码补齐：解密口径、回执串行、心跳判死与退避参数、`req_id` 规则、占位失败即终止、5 分钟硬上限；新增决策 6（自研客户端，不依赖 SDK）与坑 17–21 | 客户提供 wwlbotdemo 接入示例 |
| 2026-09-24 | 固化助手应用↔机器人一对一、机器人多知识空间；配置项增加连接地址/Secret/可选 CA；确认 IAM `userid` → 网关 `external_user_id` → `user.external_id` 且 `WECOM_SOURCE='wecom'`；补充常驻 worker、SQL 去重、进程内助手执行和流式合并流程 | 用户进一步确认配置关系、同步身份链路并追问运行机制 |
| 2026-09-24 | 同会话后续消息改为串行排队：排队时先保存图片但不发送占位，开始执行时加载最新历史并开启回复窗口；同用户同机器人第 4 条在途消息直接返回忙碌提示 | 用户确认未完成回复期间继续发消息的处理策略 |
| 2026-09-24 | 展开 5 张新增表的字段、状态、唯一键、索引和关系；补充 `REJECTED_BUSY` 幂等状态、会话顺序号、空间版本历史隔离及三条在途的跨进程计数 | 用户指出原设计只列领域对象、缺少可落库的表结构 |
| 2026-09-24 | 空间绑定改为管理员业务授权：只校验助手 E+ 接入管理权限及空间同租户/有效，不再校验配置者的空间个人权限；补充 `scope_version`、单活租约和在途消息的大白话定义 | 用户确认管理员对机器人可用空间负责，并要求澄清运行术语 |
| 2026-09-24 | 明确连接按目标状态驱动：离线可保存，上线且启用才连接，下线或关闭即断开，并由通知加周期对账保证执行；明确 `QUEUED` 为 E+ 新增状态、由 worker 会话消费协程续跑，解释 6 分钟回复流窗口，并将“替换”改写为仅 E+ 路径注入机器人知识范围 | 用户追问保存/上线触发、排队执行者、回复窗口与行为替换含义 |
| 2026-09-28 | Design 确认进入实现；客户测试环境探针完成 TLS、订阅、四类消息、图片解密、心跳与回执验证；配置表补 `is_deleted` 以落实解除接入后历史保留 | 用户确认对接方案并要求开始集成开发 |
| 2026-09-28 | 简化空间变更语义：历史跨版本完整保留；执行中改绑不撤销本轮，本轮继续使用启动快照，下一轮读取新绑定；机器人主动返回图片暂不实现 | 用户与客户确认范围 |
