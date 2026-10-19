# 客户端模型调用审计技术设计

版本：0.13　日期：2026-10-19　对应规格0.23；用户已确认，父子会话嵌套已实现并完成本机定向验证；尚未部署109，验证边界见audit-hierarchy-e2e.md

> 本轮增量：§4.6的层级目录、独立分页、历史准备及Platform嵌套已实现，替代顶层平铺展示。§4.5的客户端采集与单次父会话定位继续保留；原始请求归属、正文去重和用量账本不合并。开发基线为f0b54cdcb（该提交本身只有文档）；本次不改桌面客户端，不操作109，已实现不等于已上线。

> 本分支两端已实现[契约 0.4](./client-api-audit-extension.md)的五字段扩展，根协议保持 0.5.0。真实桌面适配器/主进程校验器→HTTP→异步审计→管理解密读取在独立 SQLite/内存对象存储通过；本轮 MinIO 镜像下载失败，不能沿用早期三存储联调结论证明新增标注可用。当前实现与验证边界见[验证结果](./validation-results.md)最新增量章节；不代表已提交、部署或正式环境验收。

## 1 目标与非目标

对实际经过毕昇 DSH 专用 Chat Completions 入口的每次统一模型调用，保存独立的请求事实及实际输入输出，管理员按客户端声明的会话浏览请求时间线。本轮补充请求用途、会话来源/直接父会话，以及最终输入消息的来源种类/形态，能分别识别子 Agent 的普通和压缩调用。审计或来源标注失败不能改变模型调用、原件或用量结算结果。

不重建客户端精确气泡、源消息身份、完整任务树、父请求/父轮次、重试归组、压缩摘要来源或普通 Fork 父子关系；只增加子 Agent 声明的直接父会话。客户端直连第三方、其他毕昇入口和未进入统一模型接口的本地工具结果不纳入。本设计不追踪供应商 SDK/网络报文，不保证供应商或客户端实际收到了哪些字节。

## 2 今日系统与特有约束

| 今日事实 | 代码锚点 | 本功能的落点与风险 |
|---|---|---|
| DSH 专用路由先用 DSH 凭证认证；流式响应在客户端未开始读取时也会关闭 | `dsh/api/endpoints/models.py:complete`、`DshStreamingResponse` | 仅该路由启用审计；流式迭代前关闭不能记成已进入统一模型接口 |
| DshRoute 生成一次 request_id，经 runtime 传给模型服务；usage.check_and_start 仍在 invoke/stream 前 | `dsh/domain/services/model.py`、`dsh/runtime.py` | 业务明细仍可能早于实际调用，不能单独证明接口已进入；审计、用量与响应已复用编号 |
| 非流式业务异常与正常 JSON/SSE 已复用模型请求编号 | `dsh/api/responses.py:DshRoute.error`、`model.py:DshModelService.complete` | 首批验证了上游/结算失败及前置拒绝；不得回退为错误响应重新生成编号 |
| `DshChatAdapter.prepare` 转换消息、绑定工具并形成参数；`ChatExecution` 调用 `llm.ainvoke/astream`，输出统一结果或增量 | `dsh/infrastructure/chat_adapter.py` | 记录统一 API 接受的有效参数、工具及逐条消息；不记录底层 SDK 私有报文；非流式结果和流式 delta/finish_reason 分别保序 |
| 本分支启用的 config 已公布五字段能力；路由解析一次 JSON、剥离扩展后严格校验业务 DTO；协议仍 0.5.0 | `dsh/domain/schemas/model_audit_context.py`、`api/endpoints/identity.py:config`、`api/endpoints/models.py:complete` | 只证明字段可接收，不保证留存；旧部署仍可能无能力或仅两字段，不得通过错误重放探测 |
| 既有调用与用量按 `request_id` 关联，但不保存模型输入输出正文 | `dsh/domain/schemas/usage.py`、`domain/models/model_call.py` | 审计另建索引和原件，不建立第二套额度账本 |

原8张审计原件/管理表、会话目录及本轮3张可重建树目录表已接入模型发现与租户过滤。模型入口装配audit_runtime.ModelAuditRuntime，独立队列异步写SQL/MinIO；历史状态由Celery收敛。管理接口与Platform审计页已实现，旧operations仍隐藏。桌面客户端在独立工作树实现协商、sessionId/purpose及主进程净化，本次未修改客户端。既有CONTENT真实存储验证见历史记录，本轮树目录的实际验证与未完成环境门禁见audit-hierarchy-e2e.md。

本轮服务端代码基线为 `997447482`；其后的 `f0b54cdcb` 只有规格等文档改动，未增加层级查询。桌面客户端五字段增量的既有验证基线为 `0367d8e674`，不是本次重新核验的客户端远端状态。公开 sessions 服务提供存活会话 header，企业序列化器在最终 push 处保留来源对应关系；两端规范化器已允许五字段并独立限制标注预算。内置 purpose 区分聊天/压缩/标题，会话来源及父会话由客户端公开 header 提供，不升级依赖、不合并其他分支、不修改 Harness 核心。

本功能特有约束：租户模式读取失败按 OFF 降级；CONTENT 不截断审计正文；审计内存与排队资源有界，远程 SQL/MinIO 不在模型首字路径上；完全失写可能留下不可逐条发现的缺口；正文不进入可检索 SQL 列、普通日志或未授权列表。全局架构遵循 [constitution](../../../../docs/constitution.md) C1–C8；F062 客户端契约变更遵循 [release contract](../../release-contract.md) B2-INV-7。

## 3 关键决策、被否方案与重评条件

| 决策 | 选定及原因 | 不采用 / 何时重评 |
|---|---|---|
| 采集位置 | 在 `ChatExecution.invoke/stream` 真正进入统一接口时观察；输入由适配后的有序消息、有效参数、工具定义/选择及多模态载荷组成，输出取统一返回和增量。这样可与 spec D-03 逐字段对照 | 不直接留入口原始 JSON、SSE 帧或供应商 SDK 私有报文。若统一层遗漏业务字段，先补齐规范化载荷并重跑契约测试；若产品改为供应商网络报文审计，重开范围 |
| 写入路径 | 调用协程只做有界编码与投递；后台写 SQL 索引和共享 MinIO 原件，失败不阻断调用。D-05 已接受完全失写可能不可逐条发现 | 不同步等待数据库/MinIO，也不以无限内存任务掩盖写入失败。若将来要求零缺口，需重评可靠队列、同步持久化、延迟与失败语义 |
| 会话归组 | 用认证租户、认证用户、客户端声明且通过基本类型与长度校验的 `conversation_id` 三元组归组；没有有效 ID 就未关联。服务端没有客户端会话真相，不做语义验真 | 不按文本、登录会话或时间猜测，也不要求 UUID/固定前缀。客户端误复用 ID 会误合并、换 ID 会拆分；若未来要求真实气泡或防伪关系，需新建可验证会话契约 |
| 正文与索引 | SQL 只放查询字段、状态、顺序和对象引用；MinIO 存版本化加密原件。完整请求原件不随列表返回，正文单独授权与留痕 | 不将正文写 SQL 文本列或浏览器直连预签名 URL。若容量实测不可承受，重评架构，不静默截断或生成替代摘要 |
| 物理复用 | 相同原件仅在相同认证租户、用户、有效客户端会话 ID 内候选复用；无有效 ID 仅单请求内复用。调用、出现和用量事实仍各自独立 | 不做全局哈希去重。若收益低，可关闭物理复用但保持隔离与独立事实；若需跨会话复用须重新确认 D-08 |
| 权限与保留 | 超管按所选租户、租户管理员按本租户查看原文，正文每次读取先持久留痕；一期不做自动删除 | 不以菜单可见代替业务授权，不做逐人授权或旧草案 TTL。角色或期限政策改变须重新确认 D-04、D-06 |
| 增量：客户端扩展层 | 企业插件经公开 sessions.get 读取已加载 header；企业适配器读取 purpose/source，并在最终消息 push 时生成索引标注；Electron 用可信能力再次校验。公开 API 已具备所需数据 | 不改 Harness 核心、不维护全量事件镜像、不按原消息 ID 数组直接 zip。若未来公开 API 不再提供来源或需要精确消息身份，再评估最小上游接缝 |
| 增量：三个维度独立 | request_kind 不变；新增 session_origin/parent_conversation_id 与 message_sources。子 Agent 压缩可同时表达，父子不合并 | 不把 compaction 当独立会话，不凭 parentSession 判断子 Agent，不从正文分类。若要精确因果链/任务图需重开需求 |
| 增量：浏览层级与原件分离 | 在独立、可重建的 SQL 目录快照上组织父子层级；顶层、直接子节点和节点请求各自分页。筛选通过目录祖先路径定位命中分支 | 不把当前前端页拼树，也不改写子请求的 conversation_id；109样本的父子会话已分别有62/38个请求，平铺代码只能提供父导航。若目录构建实测成本不可承受，重评读侧结构，不退回审计大表实时扫描 |
| 增量：发布完整目录代次 | 后台分批构建、校验后发布一个完整代次；游标绑定代次，旧代次不可读时明确要求刷新 | 不分批直接改在线根节点，否则同一子会话可能先顶层出现、后又出现在另一页父节点内。若高频新建会话导致构建持续被结构变更打断，须以实测重评增量版本化，不假称已实时收敛 |
| 增量：独立受限标注 | 12KiB 消息标注预算独立于 4KiB 请求级字段；CONTENT 中以请求专属加密对象保存，只有 body-access 可读取。标注状态与正文完整性分开 | 不复制 source 全对象、不将数组明文放 SQL、不让标注超限清空会话 ID；不把附加信息作为模型输入。若受控长历史确有大量标注不足，再以实测重评上限而非改正文 |

## 4 目标数据流与状态

### 4.1 模型主流程旁路

1. DSH 请求处理入口生成一次 `request_id` 并放入 `request.state`；完成 DSH 认证后传给 `DshModelService.complete`、既有用量事件和审计采集器。非流式成功/错误响应及 SSE 复用该编号，错误封装不得重新生成；调用前拒绝也返回该次请求编号，但不产生模型已调用审计。以有界等待从权威配置读取并固定本请求的 OFF/METADATA/CONTENT；无配置即 OFF。以该次配置读取作为“请求开始/模式生效”的判定点：变更事务在读取前提交则取新模式，读取后提交则在途请求保持旧模式。读取失败或超时本次按 OFF，模型照常调用；降级诊断尽力写入独立通道，不能用旧缓存值采集。
2. 身份、模型、参数和额度校验沿用现状。只有本次模式为 METADATA/CONTENT，才创建活动采集器；在 `ChatExecution.invoke` 调用或流式 `astream` 真正开始时发布 `MODEL_ENTERED` 并登记请求活动。显式 OFF 不投递该事件，不建立审计活动标记，不产生请求行或正文。读取失败降级 OFF 仅尽力投递系统故障诊断 `MODE_READ_FAILED`，不启动模型审计。准入失败和流式开始迭代前关闭不产生“模型已调用”审计。进入事件只证明毕昇进入统一接口，不证明供应商接收。
3. METADATA/CONTENT 在调用边界将请求身份、模式、模型、时间、客户端声明的关联字段及观察到的模型事实送入有界缓冲。CONTENT 另将规范化统一输入编码成有序块；原件包含角色、顺序、工具定义/调用/结果、有效参数及实际输入中的多模态字节或引用。HTTP Token、Cookie、供应商密钥和 `audit_context` 不属于模型输入。统一接口仅收到引用时不主动下载引用目标。
4. 非流式捕获统一结果；流式在 `ChatExecution.stream` 统一增量产出处仅将已编码片段及通道/序号/单元索引追加到本请求内存缓冲，不投递逐片段 I/O 事件，也不持久化任何输入/输出正文。统一模型调用正常结束、失败或取消时，以不复制片段的方式将整个正文缓冲移交后台，一次调用最多一个正文任务。移交为同步本地操作，不等待 SQL/MinIO、消费者或重试；后台写入可以晚于 HTTP/SSE 完成。DSH 响应发送结果在 API/ASGI 边界单独观察，用量状态引用既有链路；不得用一次结果推断另一结果。审计观察器故障不得吞掉或重放模型增量。
5. 采集器为 CONTENT 维护固定数量通道的计数、增量校验值和采集失败标志，统一接口终止时向独立控制队列尽力投递完整性清单；entered、response、usage 仍使用控制队列，不必等正文写完。后台写入器按 `request_id + stage + channel + sequence` 幂等写正文块和引用；相同键仅接受相同规范化字节摘要，冲突须留痕并将内容标 PARTIAL，不能覆盖原件。不在调用或首字前同步插入 SQL 行。只有清单声明输入采集完成且无采集失败，各通道预期片段、对象校验、SQL 引用与模型终止事实全部核对成功，才标 COMPLETE；控制与正文乱序到达时均按事实重新核验。资源预算耗尽则停止该次正文捕获，已缓存前缀仍在终止后尽力写入，保留失败标志并尽力投递清单，继续模型调用，不把前缀伪装成完整原件。
6. 审计活动刷新器在后台尽力更新开启模式下的请求活动租约，覆盖等待首字及暂时无输出的阶段；模型调用不等待 Redis 确认。审计状态检查任务结合终止事实、活动租约和观察窗口处理失联及写入停滞，具体规则见 §4.4；不改变现有用量巡检和结算语义。

调用协程不得复制一份无界完整正文；采用有界增量编码、固定上限分块及单请求/全局预算。队列满或进程退出时缓冲可丢失，尤其在模型终止移交前，整个请求正文尚未持久化，可能全部丢失；进入事实可有而正文无，不伪装可恢复。选择结束后持久化是为避免大量短增量耗尽事件条数；不选择逐片段排队或同步写对象。若要求进程崩溃也零缺口，须重新确认可靠持久队列及业务延迟/失败语义，不暗中改为同步存储。多节点共用 SQL、Redis 和 MinIO；本地磁盘及进程内缓冲不是跨节点事实来源（constitution C8）。

模块责任边界如下；具体实现锚点以本节末尾的模块表为准：

| 模块/接口 | 负责 | 不负责 |
|---|---|---|
| DSH 路由 `parse_audit_context(raw_body, advertised_fields)` | 从解析一次的 JSON 请求中对附加字段做有界软解析，剥离后交给既有 `DshChatRequest` 严格校验；维持模型业务错误语义 | 不因为关联字段无效重放请求，不把关联字段发给模型；不为审计另设模型正文上限 |
| `DshRoute` 与模型路由 | 建立请求级编号，传给模型服务；成功、非流式错误和 SSE 复用同一编号 | 不为错误响应另生成关联编号，不让调用前拒绝产生模型已调用审计 |
| `DshModelService.complete` 的 `AuditCapture` | 固定请求生效模式，关联 `request_id`/认证身份，提供 `entered/input/output/terminal` 有界非阻断投递 | 不等待远程审计持久化，不改用量账本 |
| `DshChatAdapter.prepare` 与 `ChatExecution` | 明确有效消息、参数、绑定工具及统一增量的规范化观察值；在实际调用点发布进入事实 | 不采集供应商 SDK 私有报文，不以 SSE 帧替代统一出参 |
| 审计写入器与证据写入器 | 分离消费、幂等落库、存原件、推进状态和水位，记录失败指标 | 不触发模型调用重试，不把系统指标冒充逐条证据 |
| 审计活动刷新器、审计状态检查任务 | 有界刷新开启模式下的活动租约；按终止/活动事实处理停滞并核验迟到事件 | 不以租约失效证明模型失败，不修改用量账本或现有用量巡检 |
| 审计查询/授权 Service | 按认证租户与角色查元数据、归组、核验原件并先留痕后返回 | 不验证客户端真实会话，不绕过权限服务直查 OpenFGA |

实际模块：`audit_runtime.py` 装配模型旁路，`audit_admin_runtime.py` 装配管理服务；`model_audit_body_buffer.py` 统一登记活跃、排队、写入中的正文预算及任务所有权；`model_audit_queue.py` 保留独立控制消费者。`model_audit_write.py` 统一请求、清单、出现及证据写入，`model_audit_queries.py` 仓储统一元数据查询和查看日志事务。`model_audit_writer.py` 控制事件逐次有限重试；正文在后台每组最多32个块，每次最多4个并发对象操作，全部先加密写入并回读验证，只将成功对象的引用在一个有界 SQL 事务内提交，批次事务有限重试且幂等。保留原编码、序号、单元索引与解密协议，不将流式片段合并成无法还原的正文。重放不得重复计数，任一失败不得用终止清单冒充完整。`ModelRuntime.close` 在关闭共享额度 Redis 前有限关闭审计。Worker 复用已有 `operations_worker_runtime`，不另建权限/Gateway 客户端。

审计阻塞 SQL/MinIO I/O 使用独立 4 线程、最多 12 个在途/排队工作的 `model_audit_blocking.py`，通过 copy_context 传递租户上下文。取消等待不提前释放仍执行的线程容量；达到上限则旁路降级，避免占满主业务默认线程池。单请求默认正文预算16MiB、块16KiB；进程正文预算默认64MiB，覆盖活跃、排队及写入中的全部正文，另为每请求计4096字节加字符串元数据成本、每块计512字节保守对象开销，而非仅在结束时才检查容量。`audit_queue_max_events` 默认4096，分别限制控制事件条数和全部已预留正文请求数，流式片段不再逐个占事件名额。正文、控制、独立证据及来源标注各自有界；控制队列仍有自己的条数/字节上限，不能宣称绝对不丢失。正文请求只在后台消费完成/失败或有限关闭放弃时退账，移交不提前释放容量；关闭超时取消消费者并释放活跃/排队/在途缓冲，之后投递软失败，不影响仍执行的模型。超预算标不完整而非改业务参数，均不是 SLA，也不以逻辑预算冒充进程RSS测量。

每个已确认出现事务增量更新字节计数；不为每个正文块全量扫描历史片段。终止清单存在且预期字节匹配后才核对全部事实，避免长正文落库 O(n²)。片段使用绑定作用域及密钥版本的 HMAC，而非可离线猜测短文本的裸 SHA；清单对长度和 HMAC 的有序序列做校验。每个请求固定活动密钥版本；UTF-8 分块不截断码点，部分原件遇缺序号输出 gap，不把跨缺口片段无提示拼起来。

### 4.2 数据对象

| 对象 | 关键字段或唯一性 | 职责 |
|---|---|---|
| `dsh_model_audit_setting` | `tenant_id` 唯一、mode、version、updated_by/at | 租户模式；未建行视为 OFF，超管变更用版本保护 |
| `dsh_model_audit_setting_change` | tenant、actor、before/after、time、operation_id | 模式切换与变更日志同事务提交；日志失败则切换失败 |
| `dsh_model_audit_request` | `request_id` 唯一；认证 tenant/user、登录 session、model、客户端 `conversation_id` 及精确匹配的派生键、`request_kind`、有效模式、时间、四个状态轴、关联状态、状态版本 | 请求索引、分页、模式与缺口证据；会话 ID 是客户端声明，不是服务端会话实体 |
| `dsh_model_audit_occurrence` | `(request_id,stage,channel,sequence)` 唯一、unit_index、长度、带密钥校验、content_id | 保留有序出现事实；角色/多模态类型保留在加密单元内，不建立源消息边 |
| `dsh_model_audit_content` | tenant/user、`scope_type`、`scope_id` 及作用域派生键、编码版本、带密钥摘要、长度、object_key、密钥版本、写入状态 | 加密对象和作用域内候选复用；有会话 ID 为 `CONVERSATION + conversation_id`，否则为 `REQUEST + request_id` |
| `dsh_model_audit_manifest` | `request_id` 唯一、编码版本、input_complete、capture_failed、各通道预期数量/末序号/校验值、统一接口终止事实与观察时间 | CONTENT 的完整性核验依据，仅存计数和校验等非正文信息；没有清单不能标 COMPLETE |
| `dsh_model_audit_body_access` | tenant、actor、request_id、attempt/result、time、trace_id | 每次原文读取的持久留痕；成功提交前不传正文 |
| `dsh_model_audit_evidence` | `(request_id,event_type)` 唯一、认证 tenant、发生时间、模式/原因；仅 MODEL_ENTERED 包含认证 user | 与正文写入器分离的尽力持久化进入证据或系统降级诊断；显式 OFF 不建进入证据，MODE_READ_FAILED 不保存用户、登录会话、模型、会话 ID 或正文 |
| Redis 审计活动租约 | 随机 request_id 的私有 key、随机活动代次及 TTL | 开启模式下后台刷新；认证范围与模式以已授权 SQL 事实为准，不把租约当权限或正文；代次保护避免迟到结束删除新租约 |

不创建旧设计的 `context_event`/`edge`、源消息映射、任务父子、修订、Fork 或压缩来源表。索引包含 `(tenant_id,user_id,conversation_key,started_at,request_id)`，以及 `(tenant_id,started_at,request_id)`、`(tenant_id,model_id,started_at,request_id)`、`(tenant_id,model_name_digest,started_at,request_id)` 联合索引；选型使用 MySQL/DM8 兼容类型。model_name 保留完整历史快照，model_name_digest 为原始 UTF-8 名称的 SHA-256 十六进制摘要，名称过滤同时使用摘要等值与原名等值校验；摘要强制大小写和空白敏感，不执行名称 LIKE。新增 DDL-only 迁移 dsh_audit_model_lookup，已有记录摘要为 NULL，须部署所有新写入进程后按租户运行独立有界、可恢复的 backfill_dsh_audit_model_names.py；回填完成前不承诺历史名称检索完整，禁止以大表 LIKE 或动态计算摘要兜底。conversation_key 从认证租户、用户及 ID 的原始 UTF-8 值以无歧义编码生成稳定的 SHA-256 摘要，精确定位额外使用 conversation_id_digest=SHA256(原始 ID UTF-8) 并在读出后精确核对原值，避免两库默认排序规则把大小写或其他不同值视为同一 ID；不转换大小写或归一化 ID。查询会话时先设置已授权租户的 ContextVar，让租户过滤按 constitution C3 自动注入，再显式限定目标用户；不能把客户端 ID 当全局唯一主键或对象路径。用户模糊检索仅在授权租户内 join 现有 User 名称，转义 LIKE 元字符，不对正文建立全文索引。`dsh_model_call` 仅按 `request_id` 提供已有用量事实，不改变额度投影。

版本化原件编码保持实际接口值、多模态载荷或引用、消息和增量顺序；对重复历史按规范化消息/内容部分切成稳定复用单元，流式增量仍按实际出现顺序记录，不能把整次请求做唯一去重单元。不同编码版本不直接视为相同正文。去重键和加密关联数据均包含 `(tenant,user,scope_type,scope_id,encoding_version)`，采用无歧义编码；会话 ID 与请求 ID 即使字符串相同也属于不同作用域。去重用作用域密钥摘要筛候选，再核对长度和实际等价，避免全局内容存在性探测。共享 MinIO 对象用成熟 AEAD 加密；密钥独立于 License/HMAC，轮换、恢复、备份在 CONTENT 启用前落实。加密/密钥不可用不退回明文；不能给浏览器绕开授权与查看日志的预签名直链。元数据按请求保存模型提供方/名称、开始与终止时间、耗时、四轴各自的来源及观察时间；用量值只引用既有用量事实，缺失时展示未知而不填零。

完整性清单由实际观察/编码边界生成，不能从成功写入的行反推。每个审计块在尝试入队前分配连续序号并更新预期数量、末序号和增量校验值；仅统计成功入队会掩盖丢片，禁止采用。输入的全部有效业务字段完成编码才置 input_complete；编码失败、预算耗尽、入队丢失或观察器异常均置 capture_failed。统一接口正常、失败或可核验取消时记录终止事实，合法空输出的预期数量为零。清单自身丢失或终止边界无法核验时不能标 COMPLETE。

后台按清单核对每个通道的连续序号、预期数量、顺序校验、对象完整性与引用；末片缺失而终止事件到达仍须等待或标不完整。计数/摘要按固定通道维护，不额外保留完整正文；清单以双库兼容的非正文结构保存。上述模型内容核验与 response_result、usage_settlement 独立，不等待客户端送达或用量结算成功才确认模型内容完整。

### 4.3 四个独立状态轴

| 轴 | 值与证据 | 不可推断的事项 |
|---|---|---|
| `model_result` | RUNNING、SUCCEEDED、FAILED、CANCELLED、UNKNOWN；统一接口及可核验取消事实 | 不证明 HTTP/SSE 响应成功 |
| `response_result` | RUNNING、COMPLETED、ERROR、INTERRUPTED、UNKNOWN；DSH API/ASGI 发送边界 | 完成发送不证明客户端确实收到 |
| `usage_settlement` | PENDING、SETTLED、USAGE_UNKNOWN、UNCERTAIN；既有用量链路 | 未知不等于零，也不等于模型失败 |
| `content_status` | PENDING、COMPLETE、PARTIAL、NOT_CAPTURED；后台确认的正文、引用与终止事实 | 模型成功或失败均不能替它定性 |

CONTENT 的 PENDING 只在 SQL 审计行已经提交、但正文或终止事实尚待核验时可见；流式开始前不要求有此行，尚未落库不伪造 PENDING。METADATA 的正文固定 NOT_CAPTURED 且不算缺口，OFF 无本功能请求行。失败/取消的完整已观察输入输出与终止事实都留存时，`content_status` 仍可 COMPLETE；有正文但片段或终止边界缺失则 PARTIAL，完全没有可确认正文则 NOT_CAPTURED。进程退出导致某结果轴无法核验时，该轴保持 UNKNOWN，不借其他轴补造。

各轴通过已确认事实和状态版本推进，不按事件到达顺序直接覆盖；迟到 RUNNING 或过期检查结果不得覆盖已确认终态。因暂时缺片/缺清单而标 PARTIAL/NOT_CAPTURED 的记录，只有后续事实补齐并通过完整性核验才可更新为 COMPLETE；清单已声明 capture_failed 或存在原件冲突时仍不完整。UNKNOWN 也仅可由后续可核验事实更新，不因恢复活动标记推断调用成功。

### 4.4 缺口证据

仅对本次生效模式为 METADATA/CONTENT 的调用投递独立 `MODEL_ENTERED` 小事件，包含 request_id、认证租户/用户、模式与进入时间。模式读取失败另投递 `MODE_READ_FAILED` 系统诊断，仅包含 request_id、认证租户、时间和降级原因，不记录会话信息或模型正文；显式 OFF 不投递进入证据或活动租约。两类事件进入与正文/元数据不同的有界队列，由独立写入器写 `dsh_model_audit_evidence`；模型路径不等待远程确认，进程退出或共因故障仍可能与审计行一起丢失。

在实际进入统一接口时，将开启模式的 request_id 注册到 API 进程的有界活动集合。后台活动刷新器批量更新 Redis 请求租约，刷新与模型是否产出文本无关，等待首字及无输出阶段同样刷新；结束时停止刷新并尽力登记结束。活动集合容量或刷新失败只影响可观测性，尽力告警，不能阻断模型调用。Redis 写入使用活动代次保护，迟到刷新不得重新激活已登记结束的同一请求。刷新间隔、租约期限和观察窗口为可调整运维参数，D-09 开发后实测校准，不作为开发前 SLA。

`dsh.scan_model_audit` 按有历史在途记录的租户 ID 分批（最多 100）分派 `dsh.inspect_model_audit`；子任务严格核对整型 tenant_id 与可信 header，再按请求 ID 分批（最多 100）及状态版本收敛。默认 Beat 周期 60 秒，`audit_state_scan_interval_seconds` 可配置；不因当前模式 OFF 跳过旧请求。有效活动租约保护长流；超过观察窗口仍无可确认事实的模型/响应轴转 UNKNOWN、结算观察转 UNCERTAIN，正文按存在片段标 PARTIAL 或 NOT_CAPTURED，不改真实业务用量账本。已确认终态/COMPLETE 不被检查覆盖，迟到事实可恢复。

精确编号查询没有审计行时，独立进入证据仍在窗口内或活动可确认，返回 AWAITING；超窗且活动无法确认才返回 CONFIRMED。读取失败证据返回 DEGRADED_OFF，不算缺口。只有业务明细而没有请求模式证据，返回 MODE_UNKNOWN，不能凭当前配置制造“已知缺口”；完全没有证据返回 UNKNOWN。页面使用这些状态，不把异步尚未可见当作未调用。各进程未持久缓冲及完全失写没有跨节点可靠总量，因此 progress.pending_events=null，明确展示积压未知；本页 last_write_at 也不是全局覆盖率。

按 request_id 查询合并审计行、独立证据、活动信息和既有业务明细。既有 `dsh_model_call` 可能在接口前创建，只提供候选，不证明已进入。显式 OFF 或可证实的降级 OFF 无审计记录、METADATA 无正文均不报缺口；模式未知则标适用性待核实。已知开启且有同一请求进入证据，终态后的写入窗口已过，或无活动且停滞窗口已过，才将缺失的应留存事实标已知缺口；仅有业务明细且模式可证实为开启，在无活动且超过窗口后标待核实候选，无终态时注明调用状态未知。没有 SQL 行时不伪造 PENDING。系统指标和水位只报告整体异常；记录和独立证据同失时不承诺逐条发现。

### 4.5 增量实现：来源采集、独立留存与父会话定位

#### 客户端与服务端对应流程

1. 企业插件将 `resolveAuditSession(sessionId)` 同步回调注入 EnterpriseLlmAdapter；回调只调用可选公开 `ctx.get('sessions')?.get(id)`，核对 header.id 后返回受限 origin/parentSession，不返回 Session 实例。服务缺失、异常或会话不在存活集合则省略来源，不加载磁盘、不增加事件订阅或请求。只有 header.origin=subagent 才识别子 Agent；已知 header 未设置 origin 时为 main，普通 Fork 也属 main；未来未知 origin 不默认 main。
2. 在企业模型序列化的统一 `appendMessage(wireMessage, sourceDescriptors)` 边界同时 push 最终消息与来源；公开 `serializeEnterpriseRequest` 的业务请求返回值保持原形，可内部增加返回映射的 helper。文本模型投影须保留 source 直到序列化；视觉与文本路径均不把 source/id 插入 wire message。
3. 内部消息拆成工具结果和普通文本时，每个最终消息沿用该消息来源；合并工具图片时累积所有贡献消息已知来源，去重并标混合/部分。无来源的 options.system、临时指令不制造标签。message_index 为最终 messages 的 0 基索引，服务端输入 unit_index=message_index+1，不能使用 UI 分页序号或原始消息数组索引。
4. contract 共享规范化器与 Electron 边界均按可信五字段交集、最终消息数量、固定限额处理；请求级四字段 4096 字节与 message_sources 12288 字节分别校验。源 kind/form 仅受限 ASCII 标识，最多 128 项、每项 4 个来源，不复制来源载荷；具体字段、裁剪顺序、重复索引及异常规则以契约 0.4 §3 为唯一线协议来源。
5. 毕昇路由在业务 DTO 前剥离扩展，先校验请求级字段；严格校验模型请求后，才按合法 messages 数量校验来源索引。内部 AuditContext 增加三字段，来源数据 `repr=False`，不经模型业务参数传递。normalized sources 只向审计捕获工厂提供，不能进入 ChatExecution 的有效输入、供应商参数或普通日志。

#### 数据结构与模式

本来源标注增量不新增审计原件表或来源边；本轮浏览目录新增投影表另见§4.6。对dsh_model_audit_request增加以下可空/安全默认字段，需DDL-only迁移；旧行不扫描正文或回填猜测：

| 新字段 | SQL/内部类型 | 用途与暴露范围 |
|---|---|---|
| session_origin | String(16)，可空 | main/subagent；缺失表示未知。正常请求列表/详情可返回 |
| parent_conversation_id | String(1024)，可空 | 最多 256 码点的客户端声明，只在自身 ID 有效且来源为 subagent 时保存。列表/详情可返回，不当作授权或正文复用键 |
| message_sources_status | String(16)，默认 NOT_PROVIDED | 标注单独状态，见下表；默认列表/详情不扩展逐消息信息，仅 body-access 按需返回此状态 |
| message_sources_ref | dialect_helpers.JsonType，可空 | 受限 StoredAuditBlock 引用（对象键、密钥版本、HMAC、长度、scope_key、encoding_version），不含标注正文，不通过普通 DTO 返回 |

单次父导航仅按现有租户/历史用户/目标 conversation_key 查询父会话，复用现有联合索引，不在请求大表新增 parent_id 反向检索或 DISTINCT/GROUP BY；新浏览层级的反向索引放在 §4.6 的目录投影，不扫描请求大表找所有子会话。标注 PENDING 巡检单独增加 `(tenant_id,message_sources_status,started_at,request_id)` 联合索引，以等值状态和时间范围、游标有界扫描，不能为新巡检全表扫描审计大表。新列和 JsonType 使用当前双库约定；迁移基于实施时的唯一 Alembic head，不在设计阶段假设主线未变化。旧 CONTENT 行无来源显示 NOT_PROVIDED；METADATA 的读取状态按生效模式固定为 NOT_CAPTURED，不回填旧来源、不改变原会话及正文。

| message_sources_status | 含义 |
|---|---|
| NOT_CAPTURED | METADATA 不留逐消息标注；OFF 根本不建请求行 |
| NOT_PROVIDED | CONTENT 请求没有有效来源 section，包括旧记录；不是正文缺口 |
| PENDING | 有来源待异步写入，尚未核验对象引用 |
| AVAILABLE | 已核验全部接收的合法标注；不保证客户端所有输入都有来源、不代表来源真实 |
| PARTIAL | 客户端 truncated=true、服务端忽略了一部分标注，且其余标注对象已核验 |
| INVALID | section 被拒绝且没有可用标注；不返回无效字段值 |
| UNAVAILABLE | 标注曾待写入但存储/核验失败、超观察窗口无引用，或读取对象损坏；不改变正文 content_status |

OFF 不产生事件。METADATA 在采集工厂丢弃逐消息数组，仅保留请求级来源/父编号。CONTENT 在进入模型时准备一次有界规范化标注字节快照，添加专用 annotation 事件；payload 不放进 AuditCapture.metadata，避免被每个正文/用量事件重复复制。进入/终止等事件只带标注期望状态，写入器须使来源字段与请求身份一样保持请求内不可变；迟到基础事件不能覆盖 AVAILABLE/PARTIAL，冲突标注不覆盖首次已核验对象，只把标注状态置 INVALID。

annotation 使用独立有界旁路队列（最多 64 个事件、总 payload 768KiB，metadata 也计入有界成本）；复用审计消费者/线程池约束，但不得挤占原输入输出队列容量。无独立持久化 ACK，投递/存储失败只推进标注状态或尽力指标，不设置原正文 capture_failed。队列满时不重试模型；后续状态收敛将超窗口且没有可核验引用的 PENDING 置 UNAVAILABLE。状态检查沿用已有审计扫描，也处理正文已经 COMPLETE 但标注仍 PENDING 的行，不能只扫描正文非终态。注释消费者和队列纳入各 API 进程 runtime 的启动/有限关闭；不会把进程缓冲当跨节点真相。

单个来源对象最大 12288 字节，使用现有 AES-GCM/HMAC 密钥环和 put_verified_block/open_verified_block。作用域固定 `AuditScope(tenant,user,'REQUEST',request_id,encoding_version=2)`，版本 2 专用于来源 JSON 对象；既有模型正文仍为编码版本 1，版本/请求 ID 纳入 AAD，不能互换或跨请求复用。来源存储实例使用固定 16KiB 写上限，不随正文分块调小而拒绝合法标注；读取仍受声明长度、路径、scope、HMAC/AEAD 的独立核验。先写入回读核验，后在请求行同事务保存 ref 与状态；若 SQL 失败可留下私有孤立加密对象，有限重试沿用相同内容地址，不覆盖已有请求引用。沿用本期不删除的边界，不暗加清理任务。

annotation 不加入原件 input/output occurrence 或 manifest 计数，不改变 input_units、正文大小、编码、去重或 COMPLETE 计算；空标注、标注失败和原件失败可分别组合。正文 CONTENT 采集本身仍完全遵循 AC-10、AC-12、AC-13、AC-38。

#### 父会话定位与展示

新增管理 Service 的 `parent_conversation(actor,tenant,request_id)`：先以现有 authorize_admin/目标租户范围读取子请求，再取其历史 user_id、有效父编号；在同一 profile_scope 内按该 user_id + conversation_key + 原值核验精确查最多 1 条父请求。不能使用调用方自填的 user_id/parent_id 扩展范围，也不能按管理员当前个人租户或被审计用户今日组织归属改写历史范围。

没有有效自身 ID、来源非 subagent、缺父编号或自指时无导航；有合法声明但当前范围无记录只返回 UNAVAILABLE，不泄露其他范围是否存在同名编号。A→B→A 等循环不会自动展开或加载树，单次人工导航只走一跳；不同请求的声明保持各自事实，不维护权威会话父节点。普通列表只展示子 Agent / 压缩等独立标签；用户点击父会话才查询目标，没有每张卡片的 N+1 查父请求，更不预取父正文。

### 4.6 已实现：父子会话嵌套目录

本节覆盖AC-H01至AC-H09，新增model_audit_hierarchy/tree_build/tree_queries仓储及独立DshAuditTreeProjectionService，接入Platform ModelAuditTree。桌面客户端已存的session_origin、parent_conversation_id足够使用，不改线协议、不要求重新发模型请求。原group_page保留为旧客户端/未准备目录的兼容入口；parent_conversation继续一跳定位，不充当递归树接口。

#### 4.6.1 关系事实与目录结构

保留 `dsh_model_audit_request` 的原始身份、编号、状态、用量及正文作用域。对同一个 `(tenant_id,user_id,conversation_key)`，后台独立折叠已存请求的合法声明：未知来源/缺失字段不充当反证；已知 main 与 subagent 同时出现、两个不同有效父编号均视为冲突，不选第一条。仅有 subagent 但无有效父编号标缺父信息；相同父声明重复出现不增加关系数。普通 main/Fork 不建立父子边。

现有会话目录增加受限关系摘要：`origin_state`、`declared_parent_key`、`parent_declaration_missing`、`relation_conflict`。父 key 仍按同一认证租户和历史用户计算，且读后核对原值。请求增加独立 `hierarchy_indexed` 标记及 `(tenant_id,hierarchy_indexed,request_id)` 待处理索引；关系折叠与标记在同一事务完成，避免正文/状态反复更新时重复处理声明。`group_index_pending` 继续负责原计数，不能混用两者的进度。

新增可重建的读侧对象，均为普通关系列、现有双库兼容类型，不存正文/来源数组：

| 对象 | 关键内容 | 索引与职责 |
|---|---|---|
| `dsh_audit_tree_state` | tenant、active/building generation、结构修订号、阶段与游标、租约及摘要进度 | 每租户唯一；后台持久任务进度和发布指针，不用进程内锁代表跨节点完成 |
| `dsh_audit_tree_node` | tenant、generation、conversation_key、user、原会话编号、直接 parent_key、root_key、relation_state、固定 listed_at、自身和分支计数快照 | 唯一 `(tenant,generation,key)`；索引 `(tenant,generation,parent_key,listed_at,key)` 和 `(tenant,generation,user_id,parent_key,listed_at,key)`，查根节点/直接子节点；根节点统一使用空 parent_key 哨兵，不将其用于外部 ID |
| `dsh_audit_tree_path` | tenant、generation、user、ancestor_key、descendant_key、depth | 唯一 `(tenant,generation,ancestor,descendant)`；同时建 descendant 方向索引。包含 depth=0 的自己，用于筛选命中分支和定位祖先路径 |

独立整表由模型发现创建；现有请求/会话列及索引用 DDL-only Alembic 迁移，基于实施时唯一 head。历史数据处理不放进迁移脚本。索引长度、约束及实际查询须经过 MySQL/DM8 编译检查；DM8 真库仍由 Linux 中央回归验证。

#### 4.6.2 独立构建、发布与故障处理

1. 所有当前写入进程升级后，独立维护命令按租户、request_id 游标每批最多100条折叠未处理历史声明；输出进度并支持 dry-run/继续。只读请求元数据，不读 MinIO、解密正文或写用量；无会话编号的请求只推进独立处理标记，不制造目录节点。普通后台任务持续处理新记录，不在模型入口增加查询或等待。租户扫描须同时覆盖存在未处理关系标记或脏目录的租户，不能只依赖旧“在途请求”枚举；全部终态或当前OFF也应能推进。
2. 每次新建目录节点或关系摘要改变，在独立投影事务中递增租户结构修订号；同声明重复和仅请求状态变化不递增结构修订。迟到父节点也会触发重建。失败保留待处理标记，正常请求状态不受影响。
3. 持租约的后台任务以修订号 R 建立影子代次，按目录稳定 key 游标分页复制元数据，不一次加载整个租户。通过持久阶段/节点游标计算直接关系、祖先路径及快照汇总，每次工作单元最多100节点，任务间交还执行权；重试使用同一 generation 幂等写入。数据库租约支持续租、过期接管及旧持有者 fencing，不能只用 Celery task id 防并发。
4. 只在同历史用户范围解析父节点。缺父节点、自指、循环、冲突分别为 `PARENT_UNAVAILABLE`、`SELF_REFERENCE`、`CYCLE`、`CONFLICT`，这些节点独立作为根入口；不能挂到一个不可解析的祖先下面。祖先解析最多32跳，超限标 `DEPTH_LIMIT` 并保留精确定位继续查看入口，不静默截断、无限递归或伪称真实执行树。
5. 发布前再次核对结构修订仍为 R、输入准备完成、全部目录节点恰有一个可访问归属、路径无跨用户边/循环、计数非负且无重复归集，最后在租户状态行事务中 CAS 切换 active generation。结构变更则放弃本代发布并重新排队，不能发布读了一半的新旧关系。构建失败保留上一完整代次和明确“关系更新中/失败”状态；没有完整代次则继续提供旧平铺目录和请求明细入口，而非空列表。
6. 数量快照在复制时记录 `summary_as_of`。任何目录计数变化都递增单独的摘要修订号并标脏，调度合并后的下一轮快照构建，不能只在父关系变化时刷新数量。关系准备与状态/计数准备分离：发布时摘要修订若与开始时不同、状态仍待投影或汇总不完整，summary.ready=false且未知计数为null，显示“汇总更新中”；已有明确异常仍标异常，不把未知显示0/正常。结构发布只要求结构修订一致，不依赖模型调用停止；高频更新下可先提供完整层级、摘要继续等待，不能承诺实时正常统计。
7. 新请求及关系变化在下一代次反映；刷新拿当前完整代次并提示准备进度。已打开的旧代次游标可在保留期内继续读；代次已不可用时明确返回刷新要求，不悄悄切代混页。仅保留 active、building 和一个 retired 代次；再发布导致更老游标失效。后台有界清理退休的可重建目录行，不删除任何原始审计、正文或查看日志，不把旧代次永远堆积在库里。

首次准备失败时仍可查看旧平铺和请求明细；准备成功后正常子节点仅在父节点内出现。请求无 conversation_id 的既有“未关联请求”视图不变；有 ID 但父关系不可用的会话仍在会话目录中独立展示及注明原因，不能混为未关联请求。

#### 4.6.3 分页、筛选与精确定位

新增 `/model-audit/conversation-tree` 及 `/{key}/children` 管理查询，旧 `conversation-groups` 和节点 requests 接口保持兼容。三个分页相互独立：顶层根节点按固定 `(listed_at,key)` 倒序，子节点同序，节点自身请求继续按 `(started_at,request_id)` 升序，不将子请求插入父请求分页中。前端在父会话展开区分别展示“本会话请求”和折叠的“子 Agent 会话”，子节点可继续展开；不是把所有正文拼成一条时间线。

查询继续采用既有严格用户/模型名称/时间/状态/请求编号/会话编号条件。检查某分支命中时，分批取得 path 的 descendant_key，再对这些 key 的请求使用同一个 EXISTS，所有条件必须由同一请求满足；不能在根节点会话 ID 上先应用子会话编号筛选。请求表无 GROUP BY/DISTINCT/LIKE，不把整棵树的所有 key 一次塞入 IN。

每次最多探测1000个目录节点、每批100个，时间预算1秒；到界限返回 `scan_limited`、可继续的游标，即使当页为空也不能伪称无匹配。游标须包含租户、代次、查询指纹、当前根/子候选位置及该候选内尚未扫描完的后代位置；没有判定完的候选不能直接跳过。有匹配即返回一次该根/子节点并推进到下一候选，避免同一根重复出页。空候选页和重试必须覆盖测试。SQL/驱动超时与独立执行池沿用既有约束，async timeout 不释放仍执行线程的容量。

`GET /model-audit/conversation-tree/{key}/location` 在已授权租户、历史用户及本代次中返回最多32段祖先路径，供精确子会话定位及当前“查看父会话”导航使用；键不是访问凭证，不可覆盖节点 owner。只命中子分支时返回路径父节点 `match_scope=DESCENDANT`，标注“仅用于展示路径”，其非命中自身请求不显示。子节点继续保留过滤后的自身 requests 分页，不能取消条件后混入无关请求。

节点DTO保留身份和用户真名，新增generation、parent_key、root_key、relation_state、has_children、match_scope、own_summary、branch_summary、summary_as_of。两个summary包含ready、request_count、abnormal_count、known_abnormal；未齐时数量及summary_as_of为null，不将未知显示正常。自身统计是本节点，分支统计是本节点及本代次全部后代，每请求只计一次，界面不相加。summary_as_of取目录快照写入时间而非父会话最后请求时间；摘要修订变化时整份统计只作待更新。SELF表示自身已确定命中，不代表穷尽排除了子命中；DESCENDANT表示自身不命中，仅作父路径。BOTH为兼容预留，本版不为确定它额外扫描整棵分支。

新树接口响应含 `items/next_cursor/scan_limited/progress`；progress包括 `hierarchy_ready`、`phase:PREPARING|READY|UPDATING|FAILED`、`generation` 和 `refresh_required`。代次已退休不可读时返回空items、无next_cursor且refresh_required=true，前端显示刷新按钮，不自动当成空结果或回退到另一代。非法/跨租户游标继续使用现有 DshAuditQueryInvalidError，节点不可访问使用既有 unavailable 错误；不回显其他范围对象是否存在。旧后端不提供树能力时仍走原平铺，不拿空响应猜测支持与否；query-readiness显式增加可选 `hierarchy_available` 能力字段。

#### 4.6.4 接线与页面边界

| 位置 | 本轮职责 | 保持不变 |
|---|---|---|
| Repository 新 hierarchy 模块 | 声明折叠、影子目录/路径、代次发布、树查询与游标 | 不直接调用模型、MinIO或权限引擎 |
| DSH Query Service / 管理 Endpoint | 复用 authorize_admin、profile_scope，校验节点与 generation 后查询 | 不自行查询角色关系，不以父声明扩展管理员范围 |
| `worker/dsh/model_audit.py` | 注册独立有界关系准备/续跑阶段，OFF租户仍能整理历史 | 不把关系失败并入模型结果/正文缺口，不阻塞原收敛与正文队列 |
| `ModelAuditPanel/ModelAuditGroup`及独立层级 hook | 按需根/子分页、路径展开、准备/重试提示、三语文案 | 复用现有 Button/折叠和卡片风格，不新增UI库、不改变组件视觉规范 |

节点折叠按钮提供 aria-expanded/aria-controls；窄屏不依赖无限横向缩进，32层渲染边界提供继续查看。展开根或子节点只查元数据，不发 body-access，不预取下一层或所有后代。正文仍逐请求点击授权和留痕。租户/条件/刷新/定位变化须取消旧查询并重建游标、展开状态和正文缓存；旧响应不能覆盖新范围。

已知陷阱：只在当前页组装会丢跨页父节点；先按根应用请求筛选会丢只命中子的分支；只看父异常数会把异常子会话标正常；分批原地改 root 会跨页重复。这四项分别由持久目录/祖先路径、同请求 EXISTS、分支快照汇总、完整代次与游标绑定处理，不能以 UI 标签代替。

#### 4.6.5 验证、操作与回滚

单元/Repository覆盖声明未知与冲突、缺父/父迟到、跨租户/历史用户同编号、自指/环、多层和深度边界、重复投影及状态回写。隔离HTTP测试贯穿根/子/请求分页、子单独命中、精确定位、目录半途失败/抢租约/新代次发布、旧游标失效和正文零预取；分页断言须比较完整期望集合，不只检查没有重复。Platform覆盖折叠、子独立翻页、路径提示、异常汇总、空但可继续的页、重试及旧响应隔离。

操作验收：在隔离测试租户产生主→子→孙三级合成请求，再按正常/异常、时间及精确子编号筛选；只展开关系时 body-access 次数为0，点击单条原文后才增加1，且内容仍属于该原始子请求。后台命令先 dry-run、再按指定租户执行并核对进度；不能把109历史回填视为本次开发授权。正式账号和环境现场指定，不写入文档。

指标只记录准备批数/节点数、失败类型、代次年龄、结构重试、查询 scan_limited、刷新要求；不将会话编号、父编号、generation或来源内容作为指标标签。部署故障可切回旧平铺查询或旧镜像；新增可空/安全默认列保留，停止关系任务即可，不逆向合并/删除请求和用量。容量、高频新建会话造成构建饥饿、DM8真库及实际浏览器验收为明确待验证门禁，不能以文档检查冒充通过。

## 5 已知坑与防护位置

| 反直觉事实 | 不知道会怎样 | 防护位置 |
|---|---|---|
| sr-only隐藏标签使用absolute，但请求卡片未建立定位上下文 | 标签以页面为包含块，从内部滚动列表溢出并撑大document，出现能滚到的整页空白；简单隐藏滚动条不能修复 | `ModelAuditCard.tsx`根article使用relative并保留sr-only语义；真实浏览器检查document高度不随会话展开增长 |
| 流式请求在响应迭代前已建立用量事件，客户端可能先断开 | 把未进入模型接口的请求误记为实际调用 | `PreparedStream.aclose` 与 `DshStreamingResponse.__call__`；进入事件只在 `ChatExecution.stream` 真正迭代时发 |
| 工具定义和默认参数不只在 messages 里 | 只留消息会漏审实际统一接口的工具定义/选择/参数 | `ChatExecution.input_units` 对参数/工具和逐条消息分别版本化编码 |
| 完整 model_dump 会深复制嵌套载荷，工具消息的 content:null 仍是有效统一接口字段 | 超出旁路内存边界或丢失实际入参形态 | 输入持有已校验模型，编码器逐字段惰性展开；保留必需 null，省略可选 None，不深复制整棵树 |
| `dsh_model_call` 是用量明细，可能早于真正的模型调用 | 业务终态被错当为供应商接收或已知审计缺口 | `model.py:DshModelService.complete` 与独立 `MODEL_ENTERED` 证据分开 |
| `conversation_id` 是客户端生成的字符串，服务端没有真实聊天会话注册表 | 误称“服务端核实的会话”，甚至按它改变租户归属 | `audit_context` 软解析；请求行记录声明值，归组键加认证 tenant/user |
| 旧服务端 DTO 为 `extra="forbid"`，新字段会直接失败 | 客户端为探测能力重试时重复调用模型、重复计费 | `GET /dsh/config` 能力声明；客户端缺声明则不发送，失败不自动重放 |
| 长流或审计异步积压时可能暂时没有 SQL 行，PENDING 只表示已建行 | 错把“无行”断言成“无调用”，或把长流判成缺口 | 管理查询与观察窗口；结合活动证据，不用当前租户模式倒推 |
| 原非流式错误封装会重新生成 request_id；日志 trace 上下文在异常离开模型服务时已复位 | 客户端按错误编号查询不到该次用量或审计 | `DshRoute.get_route_handler/error` 与模型路由使用 request.state 中的同一编号 |
| 存储末片丢失后，正常终止事件仍可能成功到达 | 只看到终止就把不完整正文标 COMPLETE | CONTENT 完整性清单与后台核验；预期计数在入队前更新 |
| 模型等待首字或暂时无输出时仍可能正常运行；租约失效也可能只是刷新故障 | 将活跃请求误判失败或补造取消终态 | 审计活动刷新器、`dsh.inspect_model_audit`；失联标 UNKNOWN 而非失败 |
| MySQL 普通 DATETIME 会抹去子秒；SQL 字符串 collation 可能忽略大小写或尾空格 | 顺序倒置，不同 ID 被归同组 | `PreciseDateTime` 的 MySQL fsp=6、UTC DTO，以及 ID 原始 UTF-8 摘要+读后精确核对 |
| 裸内容 SHA 可离线猜测短提示词；超时底层线程并不消失 | 无原文 SQL 仍可能泄露短文本，慢存储挤占模型业务线程池 | scope HMAC 清单/出现摘要、独立有界审计 executor，真实完成才释放容量 |
| 每个片段重扫全部引用、React 每片复制/渲染全量数组会随正文变慢 | 长原文写入/浏览 O(n²)，卡住管理页面 | 增量字节计数+终止核验；组件 ref 增量组装，最多100条消息分段渲染，长文本每段16000字符，完整查看不重复读取 |
| 新写入块调小不代表历史加密块也变小 | 已留存历史忽然无法读取 | 编码-v1 的读取上限固定64KiB，独立于新写块设置；NDJSON 帧预算256KiB |
| end 帧生成不等于发送完成，流可在 yield 处关闭 | 将中途关闭的查看记录误记为完成 | body-access 仅在 end 被下游消费后更新 COMPLETED，关闭时记 INTERRUPTED；不声称客户端已阅读 |
| 查看会话时可能仍携带单请求过滤；配置读取失败有证据也不是模式未知 | 只看见一张卡、错误报告已知审计缺口 | 清空不相关过滤；AWAITING/DEGRADED_OFF/MODE_UNKNOWN 按可核验事实分别显示 |
| 普通 Fork 也有 parentSession；子 Agent 内也可能压缩 | 按父编号把 Fork 误判子 Agent，或把子 Agent 压缩并入父聊天 | 企业插件只按公开 header.origin 分类，保留独立 request_kind 和子会话 ID |
| 源消息与最终请求消息不是一对一，输入单元 0 又是参数 | 插入系统消息或工具图片合并后全体标签错位 | 企业适配器统一追加消息时同步映射；auditMessages.ts 保留真实 unit_index，不按显示索引贴标签 |
| 现有 _within_budget/normalizeAuditContext 序列化整个扩展，且现有采集 metadata 会复制到每个事件 | 新标注超限会抹掉会话 ID，或造成正文事件重复携带大数组 | 规范化按 section 独立有界检查；来源 payload 独立 annotation 事件，不放共享 metadata |
| 原有巡检可能只取正文非终态请求 | 正文 COMPLETE 后来源永久 PENDING | 审计仓储增加有界标注 PENDING 扫描分支，与正文状态独立收敛 |
| 标注第一页可能全是仍活动的请求，反复从头扫会饿死后续页 | 后续标注无法转为可核验状态或 UNAVAILABLE | `model_audit_states.inspect` 增加 annotations 游标阶段；按 started_at/request_id 继续，不重复停在前100条 |
| JavaScript 的正则 `$` 可匹配末尾换行之前，Python `\Z` 不会 | 两端对 kind/form 合法性的判断不同 | 客户端和平台校验同时要求首字符合法且全串无非法字符；回归覆盖 CR/LF/Unicode 行分隔符 |
| Platform 尚不能直接解析共享包 @bisheng/ui | 引入 Tag 会造成构建/测试导入失败 | 复用 Platform 已有 bs-ui/Badge 和 Button，不新增依赖或修改组件样式；实际页面人工验收仍待执行 |

## 6 对外契约、管理入口与依赖

### 6.1 客户端契约：两字段现状与五字段增量目标

本分支代码在 GET /api/v1/dsh/config 的 enabled 响应声明 conversation_id、request_kind、session_origin、parent_conversation_id、message_sources；对应接收、传递、独立存储及读取链路已实现并通过定向契约测试，不代表镜像或部署已更新。只更新 fields 白名单，不公开租户模式，不增加 audit_context.version，contract_version 仍 0.5.0；后续不能仅将未实现字段写入能力响应。

新客户端在 POST /api/v1/dsh/chat/completions 只发送文档定义与服务端公布字段的交集。请求级字段与消息来源分别预算，字段无效软降级，不为探测能力重放模型；旧服务端仅支持两字段时仍遵守原 4096 字节上限。字段类型、上限、来源与裁剪顺序以[接口契约 0.4 候选](./client-api-audit-extension.md) §2、§3 为线协议唯一来源。示例为子 Agent 的压缩请求，messages 中至少有一条输入：

```json
{
  "model": "bisheng:123",
  "messages": [{"role": "user", "content": "你好"}],
  "audit_context": {
    "conversation_id": "child-123", "request_kind": "compaction",
    "session_origin": "subagent", "parent_conversation_id": "parent-1",
    "message_sources": {
      "items": [{"message_index": 0, "sources": [{"kind": "user"}]}],
      "truncated": false
    }
  }
}
```

模型路由仍解析一次 JSON并剥离扩展，再严格 DshChatRequest.model_validate；标注的索引校验需要该合法业务请求的 messages 数量。请求级校验、标注校验分别有界，不能先 JSON 序列化整个扩展导致标注超限连带清空会话；不读取未知字段的深层载荷。按认证租户/历史用户归组，五字段始终不进入统一模型输入；不增加源消息 ID、补报、任务图或压缩摘要来源边。

### 6.2 管理 API 与正文访问

2026-10-19展示修复：新树目录及旧平铺会话均删除底部“查看全部已存请求”按钮；节点本身展开和分页、请求卡片的会话导航与返回入口保留，不变更任何查询API、筛选、授权或正文读取规则。滚动修复只给请求卡片建立定位上下文，不锁死页面滚动、不删除读屏标签、不改全局布局及设计系统。验证见[audit-scroll-ui-fix.md](./audit-scroll-ui-fix.md)。标题上报本轮不实施。

常用筛选仅用户和时间，模型完整名称、统一正常/异常状态及精确请求/会话编号位于高级筛选。聚焦模型框加载当前租户开放候选，250ms 输入防抖只搜索目录，选择和手填均提交 model_name 完整原值精确查询，不提交 model_id，不 trim 或忽略大小写，同名候选去重。正常表示当前未发现异常，未完成有辅助提示；失败/取消/中断/结果未知/用量不确定/应存正文缺失归异常，METADATA 不保存正文不算异常，四轴保留排障。默认会话目录按首次收录倒序，组内按开始时间和请求编号升序分页；未关联请求独立展示。筛选须在同一请求同时满足，汇总范围为全会话已索引记录；展开会话不读取原文，逐请求显式查看才读取和留痕。草稿、显式查询、半开时间、租户切换和访问权限保持既有边界。

请求卡片底部以二态状态和原因替代四轴，四轴移入请求详情；正文固定 24rem 原生滚动，仅显式展开加载，来源为本地化标签，Esc 收起归焦。沿用既有组件、语义色及触屏热区。

在既有 `/api/v1/dsh/admin` 下新增 `model-audit` 子路由，路径不用 `config`。Platform 客户端管理页消费以下接口，桌面客户端不调用它们；普通响应 envelope 沿用管理 API 规范：

| API | 输出与限制 |
|---|---|
| `GET /model-audit/users` | 复用审计管理员鉴权和目标租户校验；按当前租户现有用户目录查询，支持 `tenant_id`、`keyword`（最多 128 字符）、`page`、`page_size`（1–100）；仅返回 `{data:[{user_id,user_name}],total}`，响应禁止缓存，不放宽原租户用户管理接口权限 |
| `GET /model-audit/models` | 复用审计鉴权和当前租户开放模型目录，不读取审计明细；keyword最多2048字符、page/page_size（1–100）；按完整name去重排序，保留兼容结构`{data:[{id,name}],total}`，新前端只提交name |
| `GET /model-audit/requests` | 新页面使用用户、时间、完整model_name、audit_status和精确请求/会话编号；未关联视图固定association_status=UNASSOCIATED。旧model_id/提供方/四轴仅兼容保留，不在新UI使用；id/name冲突返回26131。相关历史回填未完成拒绝名称/状态筛选而非假空；仅返元数据 |
| `GET /model-audit/query-readiness` | 授权租户内索引LIMIT 1探测status_ready/name_ready/indexing_pending，不计数 |
| `GET /model-audit/conversation-groups` | 按不可变listed_at/key倒序，批100、最多1000候选/循环1秒；同一请求EXISTS内匹配全部条件；稀疏匹配返回scan_limited及续查游标，不假称结束 |
| `GET /model-audit/conversation-groups/{key}/requests` | 先鉴权核对绑定，再固定历史用户/会话；拒绝覆盖；按started_at/request_id升序分页，沿用相同筛选，不默认读取正文 |
| `GET /model-audit/requests/{request_id}` | 单请求元数据、客户端声明的会话 ID、状态及用量引用；不带原文 |
| `GET /model-audit/requests/{request_id}/parent-conversation`（既有） | 先授权并读取子请求，按其历史用户及同一授权租户精确定位声明的父会话；返回 `{status:AVAILABLE,user_id,conversation_id}` 或 `{status:NOT_PROVIDED/UNAVAILABLE}`，后两者无目标身份字段。不能由请求参数覆盖 user/parent，不能跨范围搜索或预取正文 |
| `GET /model-audit/conversation-tree`、`/{key}/children`、`/{key}/location`（已实现） | 分别查询根目录、直接子目录和精确祖先路径；字段、三层分页、同请求筛选、代次/刷新要求以 §4.6.3 为准。query-readiness增加可选hierarchy_available，旧接口继续兼容；节点展开仅元数据，正文接口不变 |
| `GET /model-audit/conversations?user_id=...&conversation_id=...` | 在授权租户及目标用户范围按开始时间、request_id 分页给请求卡片；不把 ID 当全局唯一，默认不返回原文 |
| `POST /model-audit/requests/{request_id}/body-access` | 校验授权并先提交查看日志，再以有界流按原始顺序返回该请求正文；一次展开不预取其他请求，不提供批量导出或对象直链 |
| `GET /model-audit/settings`、`PUT /model-audit/settings/{tenant_id}` | 两类管理员可查看本范围模式；返回 `{mode,version,content_available}`，其中可用性为本实例密钥实时校验结果、不持久化、不返回密钥。只有全局超管可切换所选租户并原子留痕；新 CONTENT 变更须提交前校验合法活动密钥，缺失/无效返回 `26135` 且不写模式/版本/历史；OFF/METADATA 不要求密钥。幂等重放保持原操作结果，附当前可用性 |

密钥预检仅在管理配置链路执行，沿用外部密钥环的解析及活动版本 32-byte 校验；不要求 MinIO 探针或集群一致性探针通过。浏览器根据 `content_available` 禁用 CONTENT 并显示具体原因，缺字段的旧接口响应视为就绪状态未知，不能据此开启正文。已配置 CONTENT 但密钥不可用时保持真实配置展示，打开/刷新后提示新原文无法保存；不自动改成 OFF 或 METADATA。业务请求沿用既有非阻断捕获路径，缺密钥时不提交明文正文、尽力保存元数据并标不完整，不修改用量或模型结果。多实例部署仍须按运维清单核验所有采集/读取实例及旧密钥；单实例预检通过不等于集群就绪或原文一定完整。

普通响应使用 resp_200；游标列表 data 为 items、next_cursor、progress，请求 progress 包含模式/最近成功写入时间/积压及证据局限，会话目录 progress 包含回填与投影就绪信息，不含原文。游标绑定查询过滤和目标租户，以 (started_at,request_id) 稳定定位，不为 keyset 页伪造精确总数。模式写命令包含 operation_id、expected_version、mode，冲突沿现有管理错误返回。

正文 POST 成功响应使用 application/x-ndjson，Cache-Control: no-store。先返回 meta（request_id、encoding_version、content_state），再返回 part（全局递增 seq、channel=input/output、unit_index、fragment），最后 end（last_seq、content_state、transfer_status）。part.fragment 是同一有序原件单元的连续序列化文本片段，按序拼接是编码原件，而非模型生成摘要；管理页只暂存当前单元的连续片段，单元边界或 end 时解析并释放原始片段，不等整份原文到齐才展示。已解析消息和当前待解析单元合计受20Mi字符展示预算约束，刷新节流40ms；不执行内容。未采集可返回 meta+end，部分按实际留存范围返回。传输开始前失败沿标准管理错误；开始后返回不含正文的 error 事件并结束。缺少 end 仅表示本次浏览传输不完整，不把服务器已留存原件改判缺失。传输日志追加结果不替代传正文前已持久的授权查看日志。

消息呈现：`input/unit_index=0` 且具有 parameters、无 role 的设置单元不进入消息区；其他输入按 role/content 解包，保留顺序和 tool_call_id。同次请求的 `{delta:...}` 增量以片段数组追加 content 和 reasoning_content，合成一个助手消息，思考区默认折叠；tool_calls 按 index 合并 function.name/arguments，保留 id；非流式 role 消息直接解包，finish_reason 不单独绘制成消息。不跨请求合并或推断新增消息。gap 打断合并并显示缺口，受损单元不冒充完整 JSON；未知/解析失败内容标明并折叠保留片段。图片载荷/引用和其他结构化内容在原位置折叠展示，浏览器不自动请求外部资源、不执行 HTML/脚本。每页最多100条消息，单条文本每16000字符分页，切段只读已授权的内存数据，不再次 POST；切请求/租户或收起取消传输并清空原文。传输中断只标本次读取及消息显示不完整，存储不完整只根据服务端 PARTIAL/gap 事实提示，NOT_CAPTURED 不误算缺口。

增量正文协议：新增可选 query `include_message_sources=true`（缺省 false），不改变请求体或已有帧字段。缺省时帧序列与旧版一致；新 Platform 展开时显式请求该开关，新前端连接旧后端未收到新帧时降级为来源未提供。开关只影响是否返回标注，不绕过既有正文授权/访问留痕。授权日志持久化成功后才可读取来源对象；按 opt-in 返回 meta 后、第一条 part 前最多一条 annotations 帧：

```json
{"type":"annotations","message_sources_status":"AVAILABLE","items":[{"message_index":0,"sources":[{"kind":"user"}]}]}
```

annotations 帧不参与 part 的 seq、last_seq、input/output 单元或内容 manifest 计数，最大 16KiB，客户端读取及 DTO 支持新帧；它也不修改原件 encoding_version。NOT_CAPTURED/NOT_PROVIDED/PENDING/INVALID/UNAVAILABLE 返回空 items。来源对象读取/解密错误或 1 秒标注读取期限到达，返回 UNAVAILABLE 的空帧并继续已有正文读取，不回显对象引用、密钥或异常载荷，不把完整正文改为 PARTIAL；底层未结束 I/O 仍受独立线程池容量约束。客户端不得无限等 annotations；缺帧按未提供，原有 end 缺失只判断读取未完成。未 opt-in 的旧前端不接收陌生帧。

AuditMessageAssembler 增加真实输入 unit_index，按 `message_index=unit_index-1` 应用已验证标注；隐藏参数单元、分页、gap 不改变对应关系。未知角色、解析失败或不满足输入消息结构的单元不强贴来源；output 不套用输入标注。保留真实 role 并额外显示来源，已知 kind=user/system-prompt/model/tool/skill-catalog/runtime-context 使用三语可读标签；未知合法 kind/form 安全纯文本展示。多个来源显示混合及明细，PARTIAL 提示部分提供，缺来源明确未提供，不凭 role=user 宣称用户手输。所有新增文案同步 zh-Hans/en/ja，复用既有标签/折叠组件，不改设计规范或控件视觉。

现有 Platform Axios 浏览器封装没有 ReadableStream 能力，需要先在共享请求层扩展流式包装，复用 BASE、认证及集中错误策略，并回归会话失效/踢出和权限拒绝；业务组件不直接 import axios、不自行处理 403。普通接口仍走原 request；正文增量走共享 requestStream，支持 AbortSignal，不输出原文到 console。

默认会话目录与独立未关联视图，索引未齐保留请求明细。§4.6使合法子Agent折叠在父会话内，根/直接子/节点自身请求分别分页；只合并浏览入口，不合并原始审计或重建跨请求气泡。目录未准备可回旧平铺且有提示；后台完成期间如果分页方式改变，前端要求刷新，不把平铺游标传给树接口。

管理接口沿用现有 `UserPayload.get_tenant_admin_user` 作为入口身份筛选，并在 DSH 管理 Service 中按现有 `authorize_admin` 路径核对所选租户和记录归属；只有全局超管可切换模式，租户管理员仅能读本租户元数据与原文。此处是固定管理员角色与租户范围规则，不做逐人资源授权，也不新增 F048 审计资源、动作或 Catalog 项；新接口复用既有管理员判定与租户范围校验，不自行新增角色关系表查询，也不以菜单权限放行。目标记录先加载并核验归属，普通用户、其他管理员、越界租户与受限管理范围均拒绝。正文读取先验证对象可读和授权，再持久提交本次读取尝试；日志提交失败拒绝传正文。可追加传输结果，但成功授权日志不表示浏览器已收到全部内容。响应禁缓存、禁原文入普通日志和错误；浏览器只安全渲染文本/媒体，不执行 HTML 或脚本。

常用筛选仅用户和时间，模型完整名称、统一正常/异常状态及精确请求/会话编号位于高级筛选。聚焦模型框加载当前租户开放候选，250ms 输入防抖只搜索目录，选择和手填均提交 model_name 完整原值精确查询，不提交 model_id，不 trim 或忽略大小写，同名候选去重。正常表示当前未发现异常，未完成有辅助提示；失败/取消/中断/结果未知/用量不确定/应存正文缺失归异常，METADATA 不保存正文不算异常，四轴保留排障。默认会话目录按首次收录倒序，组内按开始时间和请求编号升序分页；未关联请求独立展示。筛选须在同一请求同时满足，汇总范围为全会话已索引记录；展开会话不读取原文，逐请求显式查看才读取和留痕。草稿、显式查询、半开时间、租户切换和访问权限保持既有边界。

租户初始范围：全局超管使用系统默认租户编号 1 作为首选，经现有租户目录确认后自动加载，不采用用户个人归属或返回列表的首项；用户主动切换后保留所选租户。租户管理员直接从当前身份的 `tenant_id` 派生查询范围，不加载全局租户目录；身份延迟加载或范围变化时随当前身份更新，不把最初的空值固化在组件 state。未确认租户时不渲染模式和审计查询子视图。沿用现有选择器及切换时的子视图重建，无新增授权规则或控件样式。

新增状态列及索引、待投影标记、会话表；纯状态计算位于 schemas，查询和投影位于 Repository，Service 负责授权。独立幂等投影不阻塞模型或回滚已有审计；有界批量候选 + EXISTS、严格查询 DTO、双库 DDL 和独立回填按[已确认方案](./audit-query-conversation-proposal.md)实施。新增 query-readiness、conversation-groups 及组内 requests API，旧接口仅兼容旧调用方。

### 6.3 依赖与变更风险

| 依赖 | 变化会破坏什么 |
|---|---|
| `DshChatAdapter.prepare`、`ChatExecution.invoke/stream` 的统一形态 | 消息、工具或多模态字段变化时，审计编码可能漏字段，需同步契约测试 |
| DSH 凭证与 `dsh_model_call.request_id` | 不能用客户端声明改变 tenant/user，也不能用另一套 ID 造成用量和审计错配 |
| `GET /dsh/config` 和正式客户端 0.5.0 后续版本 | 新旧客户端/服务端必须能力协商，不能用错误重放探测 |
| Harness SessionStore.get / SessionHeader.origin、parentSession | 只能查询存活会话，升级可能改变分类语义；不得从 parentSession 单独推断 subagent；无法取得则省略，不扫描历史 |
| GenerateOptions.sessionId/purpose、Message.source.kind/form | 临时消息可能没有 source；purpose 新值不能默认 chat；内部 source 携带敏感/大载荷，只取受限标识 |
| 企业消息投影与序列化、输入 unit_index 约定 | 插入/拆分/合并会改变 wire 索引；须在最终 push 处建映射，平台保留原 unit_index，不按显示条数匹配 |
| annotations opt-in NDJSON / AuditScope 编码版本 2 | 修改帧或 scope 会破坏新管理页和来源解密；旧调用必须维持原帧，不能将来源版本误用于模型原件解码 |
| MySQL/DM8、Redis、MinIO、密钥服务 | 写入、缺口证据或正文读取可分别降级；加密不可用不写明文；多节点不能靠本地盘 |

## 7 验证与可观测

本轮 AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48 的覆盖目标如下，不沿用历史测试通过结果：客户端验证公开 sessions 有/无、普通 Fork、子 Agent、主/子压缩、消息变换的最终索引与多来源；contract/Electron/服务端验证能力子集、无效索引、12KiB/128项/4来源边界及有效基础字段不丢失。服务端还须核对实际统一模型输入不含扩展，标注状态与正文状态独立、重复/迟到事件不改来源，标注队列满不占正文队列，正文 COMPLETE 后标注 PENDING 仍会收敛。实际已执行与正式操作待验收项分开记录，不把覆盖目标当作已通过。

以上为覆盖目标，不是所有环境均已完成：已执行结果以 validation-results.md 最新增量记录为准，正式 Electron 和真实三存储仍未完成。新测试分布在 test_model_audit_sources.py、test_model_audit_sources_flow.py、test_model_audit_sources_local_e2e.py；最后一个必须显式选择 memory 或真实 Docker 模式，不能把两者结果混记。

真实链路用当前客户端企业插件及 Electron 请求校验模块，调用隔离毕昇 HTTP + 独立 MySQL/Redis/MinIO + 可记录入参的受控模型；核对一次请求只调用一次模型，主会话/子会话普通与压缩的字段、MinIO 标注加密回读、原件字节一致、授权后 annotations 帧与正文映射一致。管理页交互测试覆盖旧后端无新帧、旧前端不开 opt-in、标签混合/缺失、父编号跨用户/租户碰撞、无父记录、自指/环状声明不递归，以及父导航不预取正文。数据库迁移与 SQL 编译覆盖 MySQL/DM8；DM8 运行证据仍须 Linux 环境，不能用编译替代。

手动增量验收：测试环境用超管给测试租户开启 CONTENT，使用测试账号在已协商客户端创建会话、触发一次内置压缩、委派一个子 Agent 并在子会话压缩；客户端管理的模型审计按用户/时间找到请求，核对子会话卡片的“子 Agent / 压缩”，点击直接父会话入口只定位时间线，展开单请求核对 user 角色的技能目录/运行时上下文标签及普通用户来源。测试租户与账号现场指定，不在文档保存凭证；缺内置压缩触发条件时可用合成会话通过真实适配器验证，但须单列正式 Electron 操作未执行。相关 API 路径见 §6.2，桌面定向命令见契约 §7。

标注指标新增 received/rejected/truncated/enqueue_failed/write_failed/read_failed/pending_timeout，按固定 reason 及租户计数，不使用 kind/form、会话 ID 或父 ID 作为指标标签，不记录标注数组。它们不能并入模型失败率或正文缺口率；父导航只记录管理员操作结果，不额外采集模型原文。

- 单元测试：字段软解析/剥离、三元组归组与无效 ID、同用户误复用/换 ID、会话/请求作用域同值碰撞及大小写精确匹配、单请求事实、编码顺序/分块、清单计数、状态轴与迟到事件和幂等冲突；对应 [spec](./spec.md) AC-01 至 AC-38。
- 基本成功路径：使用受控统一接口、正常存储、成功模式读取及足够预算，确定性处理完异步队列后验收 AC-35：METADATA 留单次元数据且无正文，CONTENT 留完整输入输出、清单核验为 COMPLETE；不先以持久化成功作为测试前提，也不为此新增生产覆盖率/时效阈值。
- 密钥模式配置回归（AC-39）：没有有效活动密钥时新 CONTENT 变更失败且版本/历史不变，OFF/METADATA 仍可保存；幂等重放、已配置 CONTENT 后密钥失效及当前实例可用性提示维持既有边界，不把标注加密要求扩大成 METADATA 的配置前置。
- 受控统一模型接口测试：分别比较非流式与流式的有效入参、工具、多模态、返回增量和终止边界；覆盖调用前拒绝、半包/合包、失败、取消、长流、用量结算失败、响应中断。只与统一接口观察值对照，不假称 SDK/供应商网络报文相同。
- 故障与关联测试：显式 OFF 不产生进入证据/活动租约，读取失败只产生最小系统诊断；验证非流式上游失败和结算失败的响应编号可定位对应审计，调用前拒绝保持同编号但无模型已调用审计；注入末片丢失但终止清单到达、清单丢失、等待首字、进程退出、活动刷新丢失及迟到终态，验证 AC-36、AC-37、AC-38，不伪造完整、失败或取消状态。
- 双库与端到端：MySQL 和 DM8 分别验证索引、权限、模式切换、MinIO 故障、队列满、进程退出、模式读取失败、正文日志失败和新旧客户端联调；前端验证长会话分页、单卡片展开、无默认原文、租户管理员本范围读取及越权拒绝。新后端测试放 `src/backend/test/dsh/`。
- 手动验收（实现后）：从 `src/backend/` 执行 `uv run pytest test/dsh/ -m "not e2e"`；在测试租户由超管开启 METADATA、CONTENT，分别用旧客户端和已协商的新客户端调用 `POST /api/v1/dsh/chat/completions`，到客户端管理页按 request_id 与 user_id/conversation_id 查询、展开单次正文并查访问日志。禁止用真实用户提示词或凭证作样本。
- 观测：按租户统计模式读取降级、缓冲满/丢事件、编码失败、SQL/MinIO/加密错误、PENDING 滞留、可证实与候选缺口、正文读取拒绝与日志失败。指标不带正文或高基数字符串 ID；告警不承诺逐条完整。开发后按 spec D-09 在测试环境测首字/总耗时 P95/P99、内存峰值、元数据/正文可见时效与受控覆盖率；固定现有 DSH Token 用量展示的对照来源，不能用 Redis 实时额度冒充同类基线。

## 8 交付门禁、短板与后续

增量发布次序：设计确认后拆解任务并实施；先验证唯一 Alembic head 并执行可空列迁移，再部署支持五字段及 annotation 消费/读取/巡检的全部 API/Worker，完成隔离链路测试后开启五字段能力声明；随后交付新客户端，刷新 config 后才发送新字段。新 Platform 对旧后端保持无 annotations 的兼容；新后端对旧前端缺省不发新帧。无停机迁移仅增加可空列，不读取历史正文；回退时保留新增列及加密对象，先撤销新字段能力、刷新客户端连接再回退应用，不删除历史数据。能力快照未刷新的在途新请求不得自动重放；旧后端仅软忽略未知字段，在允许的通用请求体大小内保留原调用。迁移及全实例就绪需实际验证，不把文档发布次序当作已执行。

1. 服务端链路、管理 API/页面及客户端代码到本机真实共享存储的联调已通过；正式 Electron UI、Linux DM8、真实供应商/Gateway/平台登录和持续容量压力尚未验收。任务清单保留这些环境门禁，不以本机合成身份或 mock 上游替代发布验收。协议仍为 0.5.0，不限定会话 ID 格式。
2. 管理接口须验证“超管按所选租户读/改、租户管理员仅本租户读、其余角色拒绝”的矩阵；不新增 F048 资源/动作，也不能只复用 DSH 菜单可见性满足 D-06。
3. CONTENT 启用前由数据/安全责任方确认持续留存原文的容量、密钥轮换、备份与运维责任；一期不声称具备自动删除或“过期”状态。
4. D-09 的时效、覆盖率与性能数值开发后在测试环境测量并调参，当前不宣称实时、零丢失或零额外开销。完全失写且独立证据也丢失时仍有不可逐条识别的审计盲区，这是 D-05 的已确认取舍。
5. 若后续要求精确客户端气泡、源消息身份、真实会话验真、跨会话去重、全量回补、零缺口、全文检索或到期删除，应重新开需求与设计，不从本期请求时间线反推或默默扩展。

## 修订记录

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-19 | 用户确认0.13后实现 §4.6；迁移f062_dsh_audit_tree、独立任务/维护命令、代次绑定分页、父子嵌套及三语、单元/HTTP/MySQL/浏览器验证 | 用户要求功能完成后再提交推送；109部署及DM8真库/容量门禁仍未执行 |
| 2026-10-16 | 请求元数据收敛为上下紧凑信息行、长编号按需展开，正文固定 24rem 可滚；消息来源和正文分栏分层，增加触屏热区、翻段回顶和三语文案 | 用户根据 109 截图提出展示优化；不变更采集、权限或接口，合成页面浏览器验证不替代线上验收 |
| 2026-10-16 | 用户确认后实现两端五字段、独立加密标注与队列、父会话定位、opt-in 帧和三语展示；修正巡检翻页饥饿与 JS 正则末尾换行差异 | 实施与代码审查；本机 HTTP 实际客户端链路通过，真实三存储因镜像不可取未通过 |
| 2026-10-16 | 规格 0.20 确认后拟定五字段契约、最终消息来源映射、独立加密标注/预算/状态及直接父会话导航；补齐新旧 body-access 与发布兼容 | 用户确认消息类型、压缩请求、子 Agent 关系增量；设计待确认，新代码未实施 |
| 2026-10-14 | 以规格 0.17 重写一期设计：按客户端声明 ID 归组，删除高级关联图，加入简洁时间线与单请求正文读取 | 用户确认请求级审计展示及服务端不验真会话关系 |
| 2026-10-14 | 取消额外协议版本/特定会话 ID 格式与 F048 审计资源要求，改为能力字段协商和现有 DSH 管理员授权路径 | 用户澄清接口与权限边界 |
| 2026-10-14 | 补齐 OFF 采集边界、带类型去重作用域、完整性清单、请求编号贯通、活动租约/失联收敛和 AC-35 至 AC-38 验证 | 用户要求落实本轮七项评审建议 |
| 2026-10-14 | 对齐客户端接口 0.3、两字段保护限制及并行任务，补明确管理页增量正文线格式与共享流式请求层 | 用户要求生成任务文档并交付客户端同步开发 |
| 2026-10-14 | 回写首批入口/仓储/编码/加密模块现状和独立客户端开发，明确尚未接线留存链路 | 用户要求双端分支并行开发 |
| 2026-10-14 | 接通异步留存、活动/状态收敛、管理员查询和原文日志、Platform 页面；回写有界线程池/HMAC/微秒 UTC/精确 ID/缺口状态与隔离联调证据 | 用户要求完成服务端剩余开发并与客户端联调 |


### 2026-10-19 实施与上线约束

新增请求 audit_status、group_index_pending、group_indexed_status 及对应联合索引；新建可重建的 dsh_model_audit_conversation 目录表，不储存正文。请求事实和派生状态同事务，组投影在独立事务锁请求及目录，以已投影状态差值幂等维护计数，失败不撤销审计。复用租户巡检任务；详情超时5秒仅结束等待，底层线程槽保留到实际工作结束，循环预算不承诺单条数据库语句能被终止。

先部署DDL迁移 dsh_audit_groups（前序 dsh_audit_sources）及模型发现建表，再部署所有采集和消费进程；逐租户运行 scripts/backfill_dsh_audit_presentation.py，默认dry-run，显式--apply才写，按输出游标恢复，最后从头检查遗漏。已有status但缺名称摘要的异常历史仍需原 backfill_dsh_audit_model_names.py 修复。目录首次收录时间不代表真实会话创建时间；持续新请求不调整目录位置。状态未完成属于当前未发现异常，不代表请求已成功；元数据模式不存正文不算异常。投影尚待处理必须显示延迟提示。
