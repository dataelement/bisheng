# DSH 模型转发敏感词控制与审计回传方案

- 日期：2026-10-22
- 状态：待评审；本轮仅新增方案文档
- BiSheng 分支：feat/bisheng-work-dsh-guardrails
- BiSheng 基线：2e6b5ae0fb1dcd2e32d480545e1d1ea57e77cd24
- Gateway 核查基线：feat/remove-dsh-seat，f6160db4ec40bfb815bdcde22f41fd9804008d0a
- Desktop 核查基线：codex/dsh-without-gateway，025fa9198218e989ebec51ff25b48622a1926291

本期由 Gateway 按租户执行 DSH 输入与输出敏感词检查，并可靠地将检查结果回传到 BiSheng 审计。backend 的模型鉴权、执行、额度和计量链路继续独立运行，审计模块新增外部内容安全事件接收、投影和查询能力。

内容安全事件单独保存事实明细；审计列表的命中标记及筛选直接读取现有审计主表上的摘要字段。默认列表不关联全量事件表，不临时聚合事件历史。会话和树形目录同步维护命中汇总。

## 1 目标与职责边界

| 系统 | 本期职责 |
|---|---|
| Gateway | 可信租户定位、profile 缓存、租户策略、词库及匹配器、协议检查、阻断、投递 Outbox、补报与监控 |
| backend 模型链路 | 保持既有 Token 和会话鉴权、模型权限、额度准入、供应商调用、取消及计量行为 |
| backend 审计模块 | 接收外部检查事件、校验绑定、幂等落库、生成或补齐审计条目、维护筛选摘要和会话汇总 |
| 平台前端 | 租户策略管理、审计命中标记、筛选、详情和汇总展示 |
| Desktop | 正确识别内容阻断、停止当前轮次和工具交付、显示提示 |
| 部署 | 模型流量统一经过 Gateway，backend 模型端口不对客户端直接暴露 |

backend 不新增 Gateway URL、敏感词检查 RPC、词库或阻断判断。审计接收端允许可信外部检查器上报事实；采用通用的内容安全事件契约，不把 Gateway 的内部实现写入模型执行流程。

本期按租户统一配置，覆盖该租户通过 DSH 使用的所有模型。暂不引入按人、部门、模型分别覆盖的策略优先级。图片识别、OCR、加密 reasoning、同音词、语义审核不在本期范围。原有 Python 工作台、频道和文件策略独立运行。

## 2 当前实现与可复用能力

DSH 的 Chat Completions 和 Responses 共用 DshModelService.complete。Chat 通过 BishengLLM.ainvoke/astream 执行；原生 Responses 使用所配置 SDK Client 的 responses 接口，因此只包装 LangChain 的调用不能覆盖两条路径。

Gateway 的 HTTP 敏感词过滤目前仅覆盖助手对话和旧 process 路由。HTTP 响应检查逐个 SSE 事件匹配，缺少跨事件词语匹配。已有 testWords 接口返回命中话术，并沿用旧过滤器的原文日志及 BlockRecord 写入，不作为新的执行接口直接调用。

本期复用 Gateway 的内置词库加载、词表解析和 ACPlus。DSH 使用单独的协议适配与策略读取服务，避免把新行为混进旧应用过滤器。旧应用路由和响应语义保持兼容。

现有 backend 审计具有三个需要纳入设计的条件：

1. 审计主行和正文异步写入，外部回传可能先到。
2. 请求列表以 started_at 和 request_id 进行游标分页，主表本身是元数据表。
3. 会话和树形目录已有独立投影，命中状态变化必须触发投影，不能只在详情页添加标记。

## 3 请求链路与身份定位

    Desktop
      → Gateway DSH 路由
      → 身份缓存命中，或调用 backend profile
      → 读取租户策略快照
      → 输入检查
      → backend 原有模型鉴权、执行和计量
      → Gateway 输出检查
      → Desktop

    Gateway 检查结果
      → Gateway 事务 Outbox
      → backend 内容安全事件接收
      → 事件明细与审计摘要
      → 审计列表、详情、会话与树形目录

仅拦截下列模型入口：

| 方法 | 路径 |
|---|---|
| POST | /api/v1/dsh/chat/completions |
| POST | /api/v1/dsh/responses |

同一入口下所有 request_kind 均检查，不根据客户端审计字段跳过。登录、刷新、profile、模型目录、用量等接口继续透传。部署存在其他模型入口时，必须先列出实际可达路由，再决定接入或封闭，不能根据前缀猜测覆盖范围。

Gateway 使用原始 Bearer Token 直接访问 backend 的 GET /api/v1/dsh/profile。目标地址来自部署配置，不接受请求传入的目标 URL，不经过 Gateway 自身路由。user.id 与 tenant.id 以成功响应为准，不使用客户端自报的租户选择策略。

profile 用于 DSH 运行时身份定位。它不证明调用人具有租户管理权限，不能用于策略管理授权。实际模型请求仍原样携带 Token，由 backend 重新验证身份、会话及模型权限。

## 4 profile 开销与缓存

### 4.1 当前调用成本

当前正常成功路径按源码静态计数，主体包含约 8 次 SELECT：

| 路径 | 次数 |
|---|---:|
| DSH 管理设置读取 | 1 |
| access.authenticate 中的用户、租户归属、租户读取 | 3 |
| 设备会话查询 | 1 |
| profile 中再次读取用户、归属和租户 | 3 |

此计数不包含冷启动和配置基础设施额外访问。缓存未命中会增加一次内部 HTTP 和上述读取；没有实测毫秒延迟。profile 每次查询的去重优化不纳入本期 backend 改动。

### 4.2 缓存结构

查找顺序为本机 L1、Redis L2、backend profile。复用 Gateway 已有的 Guava 依赖实现有限容量缓存，不因本功能引入新的缓存库。

| 项目 | 建议初值 |
|---|---|
| 键 | backend 实例命名空间 + SHA-256 完整原始 Token |
| 值 | tenant_id、user_id、验证时间、绝对失效时间；必要的会话标识可空 |
| L1 正缓存 | 最多 2 秒，容量有限 |
| Redis 正缓存 | 最多 30 秒，可仅向下抖动失效时间 |
| Token 到期上界 | min(30 秒，exp 减当前时间减 5 秒) |
| 凭证错误负缓存 | 本机最多 1 秒，仅限明确凭证或会话失效，容量有限 |
| profile 总预算 | 建议 1 秒，等待合并和 HTTP 共用预算，不自动重试 |

命中不续期，L1 不延长 L2 的绝对失效时间。只有 profile 成功后才写正缓存。读取同一已验证 Token 的 exp 仅用于限制缓存寿命，身份归属仍取 profile 返回值。Token 解码异常时不缓存该成功结果。

缓存不保存原始 Token，不以用户 ID 或租户 ID 单独作为键。新的 Token 需重新验证。现有通用 WebClient 会在 DEBUG 下输出请求头，新 ProfileClient 不沿用该头部日志，不记录 Authorization 或 Cookie。

### 4.3 并发、故障与失效

同一实例对同一 Token 的并发未命中合并成一次查询；多个 Gateway 副本通过 Redis 短锁协调并读取共享结果。共享查询不因一个等待请求取消而被取消。锁有有限租约，等待有截止时间；超时不触发无上限重复查询。

profile 设置连接池、独立并发上限和有限等待队列。建议初始每实例最多 32 个在途 profile 查询，结合实际负载调整。容量耗尽返回明确不可用，不延长旧缓存有效期。

Redis 不可用时，允许使用仍在有效期内的本机结果；未命中则在并发预算内直接查询 profile。profile 超时、5xx、响应格式异常时拒绝本次模型请求，不写成身份无效或策略关闭。

backend 返回明确凭证、会话、用户或租户失效时删除该 Token 缓存，并原样返回错误；模型权限不足和额度不足不当作身份缓存失效。模型请求不因清缓存而自动重试。

身份缓存最多保留 30 秒旧定位信息，不承诺缓存期内会话持续有效。实际模型准入仍由 backend 检查最新会话和归属。输入被提前阻断时，可能优先显示内容提示；若要求所有阻断前都实时报告注销，需要额外实时验证，此项不作为默认行为。

### 4.4 成本估算与验收

估算公式为 profile QPS 约等于模型请求 QPS 乘身份缓存未命中率。计量单位是模型 HTTP 请求，不能按 SSE 片段计算。

例如，同一 Token 在缓存有效的 30 秒内连续请求 20 次，首次调用 profile，其余请求使用缓存。不同 Token 的首次访问仍要查询，低频访问的命中率可能较低。

上线前分别测量冷缓存、热缓存、Token 刷新、多副本和 Redis 故障下的 profile QPS、缓存命中率、p50/p95/p99、连接池等待及 backend 查询量。建议超时值不代表已达到的响应时间。

## 5 租户策略与词库

Gateway 新增 gt_dsh_sensitive_policy，以 tenant_id 唯一定位策略，保存 enabled、input_enabled、output_enabled、word_types、custom_words、auto_reply、version、内置词库摘要、操作者及更新时间。使用版本号防止并发编辑覆盖。

策略按租户隔离，不把租户 ID 塞入旧应用 resource_id 来复用主键。无策略记录表示默认关闭，查询失败表示不可用。启用时验证词表来源、实际有效词数、词数和字节预算、单词长度及提示话术；空词表不能成为已启用但无检查的状态。

| 缓存 | 规则 |
|---|---|
| 租户当前策略 | Redis 最多 5 秒，本机最多 1 秒 |
| 策略保存 | DB 事务提交后更新共享缓存，广播失效 |
| 广播丢失 | 由绝对有效期保证新请求最多 5 秒后刷新 |
| 匹配器 | 按 tenant_id、策略版本、词库摘要编译缓存，限制总内存 |
| 在途请求 | 固定使用进入时的策略快照 |

旧查询不能覆盖新版本；缓存有效期从读取开始计算并在写入前检查，防止慢查询延长旧版本寿命。保存接口说明“新请求最多 5 秒生效”。普通策略更新不打断在途流。

内置词库随 Gateway 发布，发布时核对副本词库摘要。相同策略版本不能在不同实例上静默使用不同内置文件。匹配器加载和编译不阻塞 Reactor 事件循环。

部署级围栏能力开关默认关闭。关闭时保持原有透传。启用后需要取得可信租户才能判断租户策略；无法取得身份或策略时返回不可用。Gateway 商业能力不可用时，已启用的围栏不能自动降为透传。

## 6 输入和输出检查

### 6.1 检查范围

结构化提取完整上下文中的消息文本、可读 reasoning、工具描述、工具参数和工具结果。JSON 先解码，工具参数进一步还原 JSON 中的字符串内容，不扫描整个原始请求 JSON。

同一消息的连续文本块保持连续；不同消息、不同工具调用分别处理，避免误拼接。图片 base64、加密 reasoning、鉴权材料、协议标识和审计元数据不进入匹配缓冲。

首版沿用 Gateway 字面子串匹配和大小写语义，不附加同音、拼音或语义判断。遇到无法安全解析的协议正文，返回明确错误，不跳过检查透传。

### 6.2 放行时机

| 类型 | 行为 |
|---|---|
| 输入命中 | 不转发 backend，立即阻断并记录安全事件 |
| 非流式输出 | 完整聚合、解析和检查后交付 |
| 流式文本 | 本地批次检查，保留最大词长 L 减 1 的尾部，结束时检查剩余部分 |
| 工具调用 | 完整组装参数并解析检查后交付，检查前不暴露可执行参数 |
| backend 原有错误 | 保持鉴权、额度等错误，不伪装成敏感词命中 |

检查以 Unicode 码点统一计长，正确处理 UTF-8 跨字节分片及 SSE 多行。仓库内置词表样本的最大词长为 16 个码点，实际尾部长度按生效词库计算。

Chat 与 Responses 都覆盖正文、可读推理及工具参数。Responses 的 delta、done、最终 response 不能分别走不同检查口径，完整快照出现新正文时需先检查。原始事件保持顺序及 sequence_number，不因延迟交付重新排序。

验收目标是命中词在约定可读文本范围内不被下发。已放行的安全前缀保留。若要求命中后整条回复均不可见，需要整轮缓冲，属于另一种产品口径。

### 6.3 限制与终止

DSH 路由使用独立有限缓冲，不能直接继承 Gateway 当前 200 MB 的全局缓存预算。对齐现有 DSH 的 32 MiB 请求上限，以及原生 Responses 的 8 MiB 单事件、32 MiB 累计响应上限；额外限制总在途缓冲、解析复杂度、词表编译内存和检查任务并发。

检查器异常、协议解析失败、缓存超限均停止交付并报告错误。禁止打印原文后透传。文本检查不复制图片 base64 到匹配缓冲，压测同时测量编码字节预算与 Java 堆内存放大。

输出命中后建议停止客户端交付，由 Gateway 管理有界后端流读取，争取让 backend 获得 usage 并完成结算。建议初始剩余读取时间最多 30 秒，另设字节和并发预算。此期间仍可能生成 Token 并计费。超时、断连或预算耗尽时关闭上游，backend 沿用现有取消和 USAGE_UNKNOWN 行为。

| 场景 | 客户端结果 |
|---|---|
| 输入或非流式输出命中 | HTTP 403，content_blocked |
| Chat 流式命中 | content_filter 终止，不再发送正常成功尾帧 |
| Responses 流式命中 | 明确的内容阻断错误事件，停止正常完成事件 |
| 检查基础设施失败 | 响应开始前 HTTP 503；开始后发送错误事件并终止 |

Gateway 对模型入口使用现有 DSH 错误包结构。错误回传保持最小元数据，不包含匹配原文。

## 7 审计回传契约与可靠性

### 7.1 事件

backend 新增通用接收端 POST /api/v1/internal/dsh/content-safety-events。Gateway 使用服务间凭据及 HMAC-SHA256 签名，复用现有签名计算机制；接收认证不依赖用户 Token 当前仍有效。

仅对新增事件端点建立服务鉴权入口，签名通过后按事件绑定建立租户上下文，不豁免整个 DSH 路由前缀。浏览器 JWT 不能直接写入检查结果。

采用内容安全专用凭据、请求体大小限制和签名时间窗口。签名覆盖方法、路径、完整原始请求体，事件编号和发送时间位于签名保护范围内。重试保留原事件编号和发生时间，每次发送更新签名时间。接收端保留幂等结果，重复投递返回已提交确认。

| 字段 | 含义 |
|---|---|
| source_id、event_id、schema_version | 来源、幂等标识和契约版本 |
| gateway_request_id | Gateway 在模型请求开始时生成的编号 |
| backend_request_id | 本次模型响应 X-Request-ID；未转发时为空 |
| tenant_id、user_id、model_id | 检查发生时的归属 |
| session_id | 可空；缺失时不能编造 |
| request_started_at、occurred_at | 请求发生时间和事件发生时间 |
| protocol、event_kind、stage、decision | 协议、DECISION/FINAL/DRAIN 事件种类、适用阶段与决定 |
| stage_results、event_version | 输入输出各阶段结果与来源内单调事件版本 |
| policy_version、builtin_digest | 采用的策略和词库快照 |
| hit_count、rule_refs | 有限命中摘要，不保存原文 |
| conversation、request_kind | 按现有约束校验的可选会话提示 |
| forwarded、drain_status | 是否向 backend 转发及后续读取情况 |

每次请求上报检查终态，正常请求通常一条最终汇总；命中时立即生成事件，后续读取结束需要更新状态时另发事件。事件量随请求数增长，不随 Token 或 SSE 片段数增长。上报 input/output 两阶段状态，禁止只上报“输出通过”就把未检查的输入显示为通过。

阶段结果区分 PASSED、BLOCKED、ERROR、DISABLED、NOT_APPLICABLE 和 UNREPORTED。例如，输入阻断后输出为 NOT_APPLICABLE；backend 返回鉴权或额度错误时，没有模型输出可检查，不能编造输出通过。

没有事件时汇总为 UNREPORTED；全部阶段明确关闭才为 DISABLED；任一阶段命中优先汇总为 BLOCKED；其余可检查阶段失败为 ERROR；全部适用阶段完成且通过才为 PASSED。DISABLED 需要收到明确事实，部署未接入 Gateway 或开关关闭且未上报时仍是 UNREPORTED。后到 PASSED、ERROR 或旧版本事件均不能清除命中。

### 7.2 Gateway Outbox

Gateway 在同一事务内提交检查决定和待投递事件；也可以直接以不可变 Outbox 事件作为本地事实，避免再保存重复正文日志。后台通过有限租约领取任务、指数退避投递，支持重启恢复、失败告警及补报。

backend 在事件与审计摘要事务提交后才确认成功。不能仅放入现有内存审计队列就返回成功。ACK 丢失后 Gateway 重试，由 backend 唯一约束去重。

Outbox 写入失败仍阻断内容，产生明确告警，不能把缺口描述为已可靠回传。待投递数量、最老事件年龄、失败数及最后成功时间可观测。

### 7.3 关联与竞态

输出事件使用模型响应中的 backend_request_id，不使用 profile 请求的 X-Request-ID。接收端按事件的 tenant_id、user_id、model_id 校验与已有审计行的绑定。历史事件不因用户现在已退出或调换租户而丢弃。

输出事件可能先于模型审计到达。接收端先保存事件，并创建仅有外部安全元数据的审计条目；模型审计后到时补齐同一条目，不产生第二条记录。双方创建竞争通过唯一约束和短事务重读解决。

输入命中时没有 backend 模型请求，使用 gateway_request_id 创建外部安全审计条目，明确显示“输入命中，未调用模型”。不写 dsh_model_call，不产生额度或 Token 用量事实。

转发后未取得 backend 请求编号的事件保留为未关联，不猜测匹配某条模型记录。重试投递不能重新创建已超过保留期且已清理的审计条目。

## 8 数据模型与大数据量筛选

### 8.1 事实表与摘要分离

backend 新增 dsh_content_safety_event，保存不可变事件事实；投递处理状态可单独维护。事件表承担幂等、详情、排障、回放与修复，不承担默认列表的临时聚合。

现有 dsh_model_audit_request 新增查询摘要：

| 字段 | 用途 |
|---|---|
| has_sensitive_hit | 是否已经收到命中事实，单调 false 到 true |
| input_sensitive_hit、output_sensitive_hit | 输入与输出命中方向 |
| content_safety_state | UNREPORTED、PASSED、BLOCKED、ERROR、DISABLED；处理中可按明确事件扩展 |
| content_safety_updated_at | 最近事实更新时间 |
| content_safety_policy_version | 可显示的策略版本；多版本以事件详情为准 |
| safety_projection_version | 摘要并发控制和重建水位 |
| record_origin | MODEL 或 EXTERNAL_SAFETY |
| model_entered | 可空；外部输入阻断为 false，仅 backend 事实可确认 true |
| model_started_at | 可空；保存 backend 原生审计提供的实际模型执行起点 |

has_sensitive_hit=false 仅表示没有已知命中事实，必须与 content_safety_state 一起展示，不能翻译为“安全”。历史记录初值 UNREPORTED，不回填为 PASSED。

### 8.2 外部安全条目的状态兼容

当前审计 DTO 要求所有条目具备模型审计模式，主表也仅接受 METADATA/CONTENT；不能直接插入安全条目并把状态凑成 RUNNING。

本期需要明确扩展审计契约：

- EXTERNAL_SAFETY 的 effective_mode、model_result、response_result、usage_settlement 允许不适用；不伪造模型运行、ASGI 交付和结算结果。
- 此类条目的原文状态是 NOT_CAPTURED，audit_status 增加 NOT_APPLICABLE，界面显示“不适用”；输入阻断另显示 model_entered=false。其计数不归入原模型审计的 NORMAL 或 ABNORMAL。
- 后到 backend 原生审计补齐真实字段，来源升级为 MODEL，恢复既有状态派生规则，并保留全部安全摘要。当前 upsert_request 对身份字段要求完全相等，需要增加受控合并：允许补齐未知字段，拒绝覆盖已知且冲突的租户、用户、模型及会话绑定。
- UNKNOWN 与“不适用”分别表达；仅外部事件到达不证明模型已执行。
- 停滞扫描、完整性校验、readiness、会话索引和正文访问均识别条目类型。未知模型名称不阻塞全租户索引发布。
- 外部安全条目不生成正文查看链接；真实原文仍遵循既有权限和保留规则。

主表 started_at 首次建立后固定：原生模型条目沿用既有 started_at，外部条目使用经验证的 request_started_at；后到的原生审计填写 model_started_at，不移动排序键。旧 MODEL 行可将 model_started_at 回填为 started_at。事件仍保留自己的 occurred_at，界面区分请求开始和模型执行开始，不把回调到达时间当作发生时间。

### 8.3 默认列表直接使用主表索引

默认列表读取主表摘要，不 JOIN 全量事件表，不对事件表逐条查询，不从事件 JSON 搜索命中词。仅详情按 tenant_id 和 request_id 游标读取对应事件。

建议必备索引：

| 表 | 索引顺序 | 查询 |
|---|---|---|
| 审计主表 | tenant_id、has_sensitive_hit、started_at、request_id | 租户内命中记录和时间分页 |
| 事件表 | source_id、event_id，唯一 | 幂等接收 |
| 事件表 | tenant_id、request_id、occurred_at、event_id | 单请求事件详情 |
| 事件表 | tenant_id、received_at、event_id | 保留期处理和排障 |

按实际高频组合，经执行计划验证再增加主表的 tenant_id、user_id、has_sensitive_hit、started_at、request_id，或 tenant_id、model_id、has_sensitive_hit、started_at、request_id。不为所有筛选组合堆索引，也不单独给布尔值建索引。

命中列表的逻辑条件如下，由 SQLAlchemy 生成 MySQL/DM8 对应分页语法：

    SELECT request_id, started_at, has_sensitive_hit, content_safety_state, ...
    FROM dsh_model_audit_request
    WHERE tenant_id = :tenant
      AND has_sensitive_hit = :hit
      AND started_at >= :start_at AND started_at < :end_at
      AND (started_at > :cursor_time
           OR (started_at = :cursor_time AND request_id > :cursor_id))
    ORDER BY started_at, request_id

每页取 page_size 加 1，避免 OFFSET 深分页。游标绑定租户和全部过滤条件，新增命中条件也计入指纹。活动查询中后到的事件可能让旧记录新满足条件，界面提供刷新，不宣称跨页构成不可变快照。

默认时间窗口建议最近 7 天，单次在线查询最多 31 天。更长时间分段查询或后续专项导出。不在每次翻页执行全历史 COUNT DISTINCT 或对事件做 GROUP BY。现有 usage 补数的查询成本单独作为基线，本功能不能额外引入每行一次事件查询。

### 8.4 投影与汇总一致性

事件接收事务内完成去重、行锁或 CAS、摘要更新及持久 dirty 标记；ACK 表示这部分已经提交。安全字段由安全投影器唯一维护，原模型审计 writer 补齐其他字段时不得把命中标记重置。

相同 source_id 和 event_id 对应不同载荷摘要时返回冲突，不能按重复成功掩盖冲突。事件重复不增加命中次数，乱序不清除 BLOCKED。输入和输出的命中标记累积，检查结果按请求阶段及事件版本归并。冲突身份事件拒绝关联并保留诊断，不覆盖原行。

会话和树形目录新增 sensitive_hit_count、has_sensitive_hit 及 own/branch 命中汇总，独立于原模型审计异常数。即使原 audit_status 没变，命中变化仍要触发 group 和 tree summary 更新。

计数按“该请求是否已计入命中”计算差量，持久保存每请求已投影的安全命中状态，不能按收到的命中事件数累加。审计条目数包含外部安全条目；模型调用次数和用量继续取 dsh_model_call，不由新增条目推算。worker 有有限批次、租约、重试和可恢复的进度。汇总构建复用现有代际发布机制，合并短时间内重复变更，不为每个 SSE 片段或事件重建整棵树。

只按是否命中筛选会话或树节点时，直接读取汇总标记并使用包含租户、父节点或代际、命中标记、排序键的索引。组合模型、用户、时间等请求条件时，沿用有界候选查询，超过扫描预算必须标记 scan_limited，不能把未扫描部分展示成没有命中。

### 8.5 数据增长与保留

独立事件表确实有存储和写入成本。若假设每天 100 万个请求、平均 2 条事件、每条编码后 1 KiB，则原始事件约 1.91 GiB/天、57.2 GiB/30天，尚未计入行、索引、Outbox、副本及备份。这是容量示例，不是当前环境实测。

主表摘要每请求一行，不随事件条数增加；普通命中列表的查询不随事件总量做线性聚合。主表规模、租户倾斜、筛选选择率和索引写放大仍需压测。

建议在线事件明细先按 30 天评估，最终与现有审计保留期一起确认。摘要保留到对应主审计删除，不因明细清理变回 UNREPORTED。需要完整重建的窗口必须保留事件或可回放归档，不能一边删除事实一边承诺任意重建。

清理使用按租户和时间游标的有限批次，先验证关联保留条件；不执行单次大事务删除。分区、额外搜索服务或归档存储作为达到容量门槛后的专项评估，首期不承诺跨 MySQL/DM8 通用的分区 DDL。

## 9 平台前端与 Desktop

平台 DSH 管理增加租户敏感词配置，沿用现有词表交互和已落地组件。管理接口由 Gateway 持有，建议使用 /api/sensitive/dsh/settings 和 /api/sensitive/dsh/records 等明确路径。

Gateway 使用浏览器登录凭据查询已有 backend 用户和租户接口，验证租户管理权限。普通租户管理员仅能管理本租户；超管选定的目标租户也须验证存在与可管理范围。配置写操作实时校验权限，不使用 DSH profile 身份缓存授权。

backend 审计 API 返回安全摘要，增加是否命中、方向和检查结果筛选。列表显示“输入命中”“输出命中”；详情显示策略版本、时间、有限命中摘要和投递来源。会话、轮次及树形目录显示命中汇总和汇总更新时间。

界面允许同时显示“模型执行成功”和“输出命中，已拦截”。输入安全条目显示“未调用模型”，不显示零 Token 来冒充已完成计量。未知结果显示“尚未收到检查结果”，不当作已通过。

Desktop 的 Chat 已识别 content_filter；Responses 当前会把错误事件归类为上游错误，需要保留内容阻断和检查不可用的明确错误码。阻断后停止当前轮次，不自动重试，不执行尚未检查通过的工具参数。后台读取可能仍在结算，客户端用量展示以 backend 后续结果为准。

界面沿用当前设计规范和组件，新增文案补齐 zh-Hans/en/ja，不自行改变组件视觉样式。

## 10 各仓库改动范围

| 范围 | 计划改动 | 边界 |
|---|---|---|
| Gateway 路由及过滤器 | DSH 精确路由、有限 body/SSE 缓冲、输入输出适配、阻断与有界读取 | 不重新引入席位和旧 DSH 登录认证 |
| Gateway 身份 | 独立 ProfileClient、L1/L2 缓存、请求合并、并发限制、失效监控 | 不持有 backend Token 签名密钥 |
| Gateway 策略与投递 | DSH 租户策略、匹配器快照、Outbox、签名发送和重试 | 不调用旧 filterNormal 的原文持久化副作用 |
| backend 事件接口 | 独立接收认证、契约校验、幂等事务、补报状态 | 不主动连接 Gateway |
| backend 数据与审计 writer | 新事件事实表、主表摘要、外部安全条目与后到模型审计合并 | 不修改模型调用和 quota 结算语义 |
| backend 查询和投影 | 主表索引、DTO、过滤、会话和树汇总、保留期与修复 | 不把正文或事件 JSON 放进主列表热查询 |
| 平台前端 | 租户配置、命中筛选、标签、事件详情、汇总与三语文案 | 配置走 Gateway，审计查询走 backend |
| Desktop | Chat/Responses 错误展示和终止语义 | 不新增客户端词库判定 |
| 部署和迁移 | 网关入口、专用回传凭据、SQLModel/迁移适配、索引回填、监控 | 独立核对 MySQL 和 DM8 |

backend 重点涉及 dsh/api/endpoints、domain/models/model_audit_request、domain/schemas/model_audit、domain/repositories/model_audit_write 与 model_audit_queries、domain/services/model_audit_writer、会话和树投影以及安全事件专用模块。runtime.py、model.complete 的执行与计量逻辑不增加 Gateway 检查依赖。

外部安全条目的状态扩展是审计合同变更，需要在后续 Spec/Design 评审中明确，不能仅增加几个前端字段后视为完成。

## 11 发布与迁移

1. 先发布 backend 接收、事件表、摘要字段及兼容读取能力；旧记录按有限批次回填 UNREPORTED 和无已知命中。新增列与索引的锁表和耗时需在目标库预演。
2. 批次构建会话和树命中汇总，维护 readiness。完成前界面显示索引准备中，不返回貌似完整的空结果。
3. 发布平台与 Desktop 兼容展示，再发布 Gateway 检查和投递能力。保持部署开关关闭验证透传。
4. 检查 Gateway 与 backend 时钟、签名配置、profile 内网连通、Outbox 补报、词库摘要与模型流量入口。
5. 按租户启用，观察正常流量、命中率、profile 开销、回传滞后和查询性能，再扩大范围。

接收端支持事件先到和重试；Gateway 不依赖 backend 已升级的模型接口。关闭租户策略影响新请求，在途请求按固定快照结束。停用检查后，已经产生的 Outbox 继续补报；回滚不删除事实表、摘要或待投递事件。

backend 接收与查询增量迁移接在当前 work-110 实际迁移 head 后，不复制其他版本线的 revision。跨仓库分别提交、测试和核对发布顺序。本轮只交付评审文档。

## 12 验收与性能验证

| 编号 | 必须验证的结果 |
|---|---|
| AC-S01 | 两个模型入口的流式与非流式均覆盖；未命中透传保持协议、Token、错误和用量兼容 |
| AC-S02 | profile 键按完整 Token 和 backend 区分；30秒上界、Token到期、并发合并、多副本、撤销、负缓存和Redis故障符合约定 |
| AC-S03 | 普通用户不能管理策略；管理员不能越租户读写策略、事件或审计；回传不依赖用户Token当前有效 |
| AC-S04 | 策略保存对新请求最多5秒生效，在途快照固定；词库为空或加载失败不会默许放行 |
| AC-S05 | 跨SSE、UTF-8字节、连续文本块、转义JSON和工具参数命中均在交付前阻断；Responses最终快照不能绕过 |
| AC-S06 | 输入命中后backend模型调用次数为0，有独立安全审计条目，没有额度和Token调用事实 |
| AC-S07 | 输出命中关联准确，模型审计先到、后到、关闭、缺失及Gateway未拿到编号分别显示真实状态 |
| AC-S08 | 重试、ACK丢失、乱序、并发、重启和多实例消费不重复记账、不清除命中、不丢已确认事件 |
| AC-S09 | 原模型writer后写不重置安全字段；外部条目不导致readiness永久失败、正文入口失效或停滞任务误报 |
| AC-S10 | 列表直接筛选主表摘要；会话及树命中计数按请求去重且独立于模型异常；索引未完成有明确提示 |
| AC-S11 | 内容审计关闭仍能保存最小安全事实；新字段不把历史UNREPORTED显示为检查通过 |
| AC-S12 | 有界读取在30秒及字节/并发预算内停止，保留实际计量或未知状态，不伪造零消耗 |
| AC-S13 | MySQL/DM8升级、索引、回填、幂等、保留期、权限及既有Gateway应用回归通过 |

性能数据集至少覆盖百万与千万请求主行，事件量按平均每请求1至3条生成；分别覆盖低命中率、高命中率、单租户集中、跨租户、晚到事件和长会话。逐类验证“仅命中”“命中加用户”“命中加模型”“命中加时间”“会话和树汇总”。

MySQL 与 DM8 分别查看执行计划、扫描行数、排序、p95/p99、索引大小、写入与锁等待，特别验证深游标页和回填期间。与相同数据和选择条件下的当前审计查询比较，不能用空库或 SQLite 证明生产性能。

正常列表不触发事件表全扫、全历史聚合或逐行事件查询是结构验收条件；目标延迟与容量门槛在真实中间件压测后确定。新增安全功能不能用“有索引”替代实测结论。

## 13 需要评审确认的取舍

| 项目 | 本方案建议 |
|---|---|
| 身份缓存 | 最多30秒，只定位租户，模型准入仍由backend验证 |
| 策略生效 | 新请求最多5秒，在途请求固定快照 |
| 流式展示 | 保留安全前缀，命中词不下发；工具参数整调用检查 |
| 输出命中计量 | 有界读取后端流，最多30秒，接受继续产生Token的可能 |
| 审计存储 | 独立事件事实表加现有主表摘要，列表不聚合事件历史 |
| 外部安全条目 | 输入阻断和原审计缺失也可展示，明确不适用或未观测状态 |
| 在线时间范围 | 默认7天、单次最多31天；更久分段 |
| 明细保留 | 先按30天评估，与原审计保留和归档能力一起确认 |

当前为方案评审。通过后按项目 SDD 流程形成 Spec、Design 和任务拆分，再进入实现与真实环境验收。

## 附录 源码核查入口

以下路径相对对应仓库根目录。当前结论来自所列基线源码；缓存参数、索引和容量数据集属于待实现和待压测设计。

| 仓库 | 路径 | 核查内容 |
|---|---|---|
| BiSheng | src/backend/bisheng/dsh/api/endpoints/models.py | 两个模型入口、profile和SSE资源关闭 |
| BiSheng | src/backend/bisheng/dsh/domain/services/model.py | 准入、供应商执行、结算与SSE出口 |
| BiSheng | src/backend/bisheng/dsh/infrastructure/chat_adapter.py | Chat调用、工具片段、推理和usage |
| BiSheng | src/backend/bisheng/dsh/infrastructure/responses_adapter.py | 原生SDK、事件、终态及大小限制 |
| BiSheng | src/backend/bisheng/dsh/access_runtime.py | profile依赖与DSH设置读取 |
| BiSheng | src/backend/bisheng/dsh/domain/services/access.py | Token、身份和会话验证 |
| BiSheng | src/backend/bisheng/dsh/domain/services/identity.py | profile重复身份读取 |
| BiSheng | src/backend/bisheng/dsh/domain/repositories/identities.py | 用户、归属和租户的三次读取 |
| BiSheng | src/backend/bisheng/dsh/api/responses.py | X-Request-ID和ASGI审计观察边界 |
| BiSheng | src/backend/bisheng/dsh/domain/models/model_audit_request.py | 主表、证据和现有索引 |
| BiSheng | src/backend/bisheng/dsh/domain/schemas/model_audit.py | 当前状态类型和元数据DTO约束 |
| BiSheng | src/backend/bisheng/dsh/domain/repositories/model_audit_queries.py | 主表过滤、游标和页面补数 |
| BiSheng | src/backend/bisheng/dsh/domain/repositories/model_audit_write.py | 严格身份绑定和异步主行创建 |
| BiSheng | src/backend/bisheng/dsh/domain/services/model_audit_writer.py | 元数据、正文写入及字段更新 |
| BiSheng | src/backend/bisheng/dsh/domain/repositories/model_audit_conversations.py | 会话计数、dirty标记及有界候选查询 |
| BiSheng | src/backend/bisheng/dsh/domain/repositories/model_audit_tree_build.py | 会话树代际构建与汇总发布 |
| BiSheng | src/backend/bisheng/sso_sync/domain/services/hmac_auth.py | 可提取复用的签名计算模式 |
| BiSheng | src/backend/bisheng/user/api/user.py | 浏览器用户信息和管理标识 |
| BiSheng | src/backend/bisheng/tenant/api/endpoints/tenant_crud.py | 已有租户读取和管理鉴权 |
| Gateway | src/main/java/com/dataelem/gateway/filter/SensitiveWordsFilter.java | 旧路由、缓存、匹配及日志副作用 |
| Gateway | src/main/java/com/dataelem/gateway/filter/CustomResponseFilter.java | HTTP响应过滤及逐SSE事件检查 |
| Gateway | src/main/java/com/dataelem/gateway/entity/SensitiveWords.java | 旧应用策略没有tenant_id |
| Gateway | src/main/java/com/dataelem/gateway/utils/ac/ACPlus.java | 可复用匹配引擎 |
| Gateway | src/main/java/com/dataelem/gateway/config/SpringCustomConfig.java | WebClient、Redis与请求头日志 |
| Gateway | src/main/java/com/dataelem/gateway/client/BishengSsoPushClient.java | 已有HMAC发送模式 |
| Gateway | src/main/java/com/dataelem/gateway/filter/LicenseExpiredGlobalFilter.java | 商业端点和透传端点的现有边界 |
| Desktop | packages/dsh-desktop-enterprise/openai.js | content_filter及错误码处理 |
| Desktop | packages/dsh-desktop-enterprise/responses.js | 错误事件归类、事件顺序验证 |
