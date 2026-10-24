# Design: DSH 模型转发敏感词控制

- **特性**：F111 / v3.0.0
- **关联规格**：[spec.md](./spec.md)，用户于 2026-10-23 确认
- **需求输入**：[已确认方案](../../../docs/architecture/proposals/2026-10-22-dsh-gateway-content-safety.md)
- **状态**：已用户确认；核心实现及真实109单实例子集已完成，完整验收PARTIAL，详见tasks与交付记录
- **最后更新**：2026-10-24
- **工作分支**：feat/bisheng-work-dsh-guardrails
- **执行流水**：[tasks.md](./tasks.md) 已按确认设计拆解并评审，用户已授权按依赖持续实施；验证证据见 [implementation-verification.md](./implementation-verification.md)

本文区分已核实的代码现状与拟新增行为。下述新增类型、表、字段、接口和参数均为设计，不能据此认定功能已交付。后续实现变化应覆盖更新本文，同时保留决策原因；推翻已确认需求时按 [SDD 流程](../../../docs/SDD-Guide.md) 重新确认。

## 1. 目标与非目标

Gateway 根据可信租户身份，对 DSH Chat Completions、Responses 的输入和输出执行敏感词检查，并将检查事实可靠回传到 backend 审计。backend 的模型鉴权、执行、额度和计量继续独立；平台和 Desktop 展示策略、阻断及审计结果。

本期不恢复席位、License 准入或旧 Gateway DSH 登录，不让 backend 主动连接 Gateway，不迁移其他敏感词业务，不增加按人、部门、模型覆盖策略。语义审核、图片识别、整轮撤回、全历史检索及导出均按 spec 排除。

## 2. 关键约束

遵循 [constitution.md](../../../docs/constitution.md) C1–C8、[版本契约](../release-contract.md) 及各子项目 AGENTS.md；本文只记录本功能的落点，不复写全局架构规则。

### 2.1 已确认的行为边界

| 约束 | 设计落点 |
|---|---|
| backend 无 Gateway 运行时依赖 | 仅审计增加通用外部事实接收；模型路径无检查 RPC、网关地址或词库 |
| 身份定位最多保留 30 秒，不能超过 Token 寿命 | 绝对截止时间、Redis 剩余寿命及本机单调时钟共同限制；命中不续期 |
| 新策略最多 5 秒生效，在途固定快照 | 版本化策略、绝对缓存寿命；普通更新不追杀在途流 |
| 完整命中词不能交付，安全前缀可保留 | 按逻辑文本域检查，整事件有序交付；工具参数完整检查 |
| 输出阻断后续读最多 30 秒 | 从判定命中计时，不能从后台任务开始或最后一个片段重新计时 |
| 未确认事实重启可恢复，确认后的事实和摘要可查询 | Gateway SQL Outbox；backend 提交事件和摘要后 ACK |
| 历史和未知不等于通过 | 六种阶段状态与六种请求汇总；NOT_APPLICABLE 纳入本次已确认的修订 |
| 在线默认 7 天，单次跨度最多 31 天 | 沿用既有分页，不新增默认窗口冻结；显式条件及租户仍需校验 |

### 2.2 资源和故障预算

以下为设计初值，未做真实负载验证。业务硬上限不得通过调优放宽；其余参数在实现压测后可下调或评审调整。

| 项目 | 初值 / 上界 |
|---|---|
| profile L1 / Redis 正缓存 | 2 秒 / 30 秒；Token 到期另预留 5 秒，负值不缓存 |
| 明确凭据错误负缓存 | 仅本机 1 秒；超时、5xx、格式错误不负缓存 |
| profile 总预算 / 并发 / 等待队列 | 1 秒，包含请求合并等待；每副本 32 在途、64 等待，不自动重试 |
| 策略 L1 / Redis / 读取预算 | 1 秒 / 5 秒 / 500 毫秒；词库缺失或过期后不可读时拒绝检查 |
| 请求 / 原生 Responses 单事件 / 累计响应 | 32 MiB / 8 MiB / 32 MiB，与现有 DSH 协议边界一致 |
| DSH 检查中的保留编码字节总额 | 每副本 64 MiB；同一缓冲不能在请求、响应两边漏计或重复抵扣 |
| 检查任务并发 / 后台续读并发 | 每副本 16 / 8；无续读额度时立即关闭上游，不排长队 |
| 后台续读 | 命中后最多 30 秒，剩余累计响应预算最多 32 MiB 减已读字节 |
| 自定义词 / 生效词表 / 单词长度 | 自定义 UTF-8 1 MiB；合并后最多 30,000 词、1 MiB；每词 256 Unicode 码点 |
| 匹配器编译 | 单副本最多 2 个编译任务；节点最多 200,000，缓存估算权重最多 128 MiB |
| 外部事件 / JSON 深度 / 命中摘要 | 每事件 64 KiB，深度 16；至多 20 个 rule_ref、hit_count 超限截断并标记 |
| Outbox 领取 / 租约 / 单次回传超时 | 每批 100，租约 30 秒，回传 3 秒；重试退避 1 秒至 5 分钟，带抖动 |
| SQL 接收与摘要事务 / 汇总批次 | 接收目标预算 2 秒；每次最多 200 个 dirty 请求，使用持久租约 |

64 MiB 是编码缓冲额度，不是 Java 堆占用承诺。解析树、字符串和匹配器有放大；压测须记录实际堆峰值、GC 和基线余量，部署启用前据目标 JVM 堆设置调低额度。不得用扩大 Netty 全局缓存或无限 Reactor 队列规避限制。

### 2.3 证据边界

仓库内置词表静态样本为 3,592 个去重词、44,592 字节，最长 16 码点，符合上述词表初值；部署自定义词库仍须独立校验。历史设计评审时仅完成基础设施编译、单元/组件与结构检查，尚无模型请求/真实迁移/压测或浏览器E2E；当前已执行真实MySQL迁移、109模型协议/审计、Platform与Desktop子集，详见implementation-verification与deployment-execution。LinuxDM8、真实容量/多副本与完整故障验收仍未执行。profile 成功路径约 8 次 SELECT 是静态路径计数，不含冷配置开销，也不是实测时延。

### 2.4 本轮用户评审取舍

用户于 2026-10-23 明确：审计分页沿用既有方式，不纳入固定默认筛选窗口；身份以毕昇成功验证结果为准，接受其可信变化，不新增跨事件身份冻结、独立请求绑定表或针对该变化的冲突拒绝。两项复审意见撤回，不再作为本期设计或验收门槛。

该取舍已同步 spec AC-38、AC-42、AC-49。服务来源认证、来源允许租户范围、查询权限、同事件异载荷冲突及已持久化事件的幂等重试继续按既有契约执行；不依据用户当前状态重写历史事件或模型执行、用量事实。

## 3. 方案对比与选定

### 3.1 检查执行位置

- **备选**：backend 调 Gateway 检查 RPC；只包 LangChain；Gateway 覆盖两个 HTTP 模型入口。
- **选定**：Gateway 执行；backend 审计接收通用 ContentSafety 事实。
- **原因**：F110 已解除网关依赖；原生 Responses 不经过 Chat 的 LangChain adapter，只包模型封装会漏检。现有 Gateway 具有词库、解析与 ACPlus，复用它们可保持既有匹配语义。
- **重新考虑条件**：出现可绕过 Gateway 的新公开模型入口，或需要在非 HTTP 模型消费路径执行同一策略；先补入口和需求，不能偷偷在 backend 恢复远程检查。

### 3.2 租户定位和管理授权

- **备选**：信任客户端租户；Gateway 解码 Token 后自行认定身份；每次实时 profile；短期复用成功 profile。
- **选定**：短期复用 profile，实际模型准入仍交给 backend；管理策略单独使用浏览器身份实时校验。
- **原因**：客户端租户不可信；profile 不表达租户管理权。静态约 8 次读取使逐模型请求新增调用有可观成本，短期复用减少的是额外 profile 开销，不减少 backend 原有模型鉴权。
- **重新考虑条件**：要求输入提前阻断前也必须实时识别注销，或负载测量显示 30 秒内低复用使缓存收益很小。

### 3.3 事实保存和查询

- **备选**：只给主表写布尔值；每次列表 JOIN 全量事件；独立事件事实加主表摘要。
- **选定**：不可变事件独立保存，主表和会话、目录持有查询投影。
- **原因**：布尔值不能证明方向、策略和乱序处理；原审计已经按 started_at、request_id 游标翻页，主表可直接承接筛选。每请求重复事件不应放大列表读成本或计数。
- **重新考虑条件**：需要按任意命中词跨年检索或复杂统计；根据真实数据再评估归档和搜索索引，不先引入新检索服务。

### 3.4 回传可靠性

- **备选**：用户 Token 回调；内存异步发送；网关 SQL Outbox 加服务签名。
- **选定**：复用 Gateway 与 backend 现有共享 HMAC 密钥配置和签名规则，配合持久 Outbox、幂等接收和提交后 ACK。
- **原因**：审计回传由既有 Gateway 服务互信承担，不依赖用户仍在线；复用已有配置可避免重复维护一套密钥。旧内存审计队列的成功入队不代表持久化，spec 明确区分发送端未确认恢复与接收端确认后恢复。
- **重新考虑条件**：Outbox 写入压测成为瓶颈且有可复用的可靠消息平台；仍须保持相同幂等、保留和租户绑定合同。

### 3.5 流式交付方式

- **备选**：逐 SSE 片段匹配；整轮缓冲所有输出；按文本域扫描并有序保留原事件。
- **选定**：保持原事件顺序的延迟交付，文本域保留最长词长减一的尾部，工具参数完整检查。
- **原因**：逐事件会漏跨片段命中；整轮缓冲会把所有回复变成非流式。Responses 的 sequence_number 不允许为切分文本任意重编号。
- **重新考虑条件**：产品改为命中后整轮不可见，或多文本域交错造成的队头阻塞在实测中不可接受；不能为了延迟指标提前放出未确认文本。

### 3.6 外部条目与保留

- **备选**：伪造 RUNNING/零用量条目；只保存事件而不让输入阻断进入审计；明确外部条目和不适用状态。
- **选定**：外部条目有独立来源，模型相关未知字段可空；事实明细与主审计分别保留，默认不自动删除明细。
- **原因**：当前 DTO 仅支持 METADATA/CONTENT 和 NORMAL/ABNORMAL，必须显式扩展；spec 未批准独立强制 30 天删除期，不能把容量评估值直接变成清理规则。
- **重新考虑条件**：统一审计保留期和归档策略另获确认；归档可回放能力成立后再缩短在线明细窗口。

### 3.7 上游代理所有权

- **备选**：在默认 Netty 响应装饰器闭流后启动游离订阅；专用 DSH 路由拥有一次上游请求及完整读取生命周期。
- **选定**：前置检查加专用 DSH 路由，保持公共前序过滤和限流，受控持有上游。
- **原因**：默认代理的连接释放与响应链完成相关，不能把“客户端已结束”误当“上游可释放”；重新订阅还可能重复发起有费用的模型调用。
- **重新考虑条件**：现有代理提供经过验证的连接所有权和独立续读接口；必须以取消、断连和零重复调用测试证明再简化。

## 4. 系统现状与拟接入结构

### 4.1 已核实基线

| 仓库 | 核查基线 | 已有行为 |
|---|---|---|
| BiSheng 本工作树 | 2e6b5ae0fb1dcd2e32d480545e1d1ea57e77cd24 | F110 本地接入、两个 DSH 模型协议、异步审计及会话树 |
| bisheng-gateway | feat/bisheng-work-dsh-guardrails / main 基线 2995df6fdf9c51b70617a86a803aec9c6633b69e | DSH 认证与席位逻辑已移除；应用敏感词仍为旧资源策略 |
| bisheng-work Desktop | feat/bisheng-work-dsh-guardrails / main 基线 01e09d027ba729f6021ec37c33937f5745cee992 | Chat 识别 content_filter；Responses 把错误事件统一归为 UPSTREAM_ERROR |

当前 backend 入口在 models.py：desktop_principal → read_model_request → DshModelService.complete → Chat 或原生 Responses adapter。DshRoute 创建模型请求编号，并在响应头返回 X-Request-ID；AuditObservedResponse 只观察 backend 到直接下游的 ASGI 发送事实。

审计主行由 DshModelAuditWriter 异步创建；upsert_request 对身份字段要求完全相等，mode 仅支持 METADATA/CONTENT。refresh_audit_status 主要依赖模型审计状态变化触发 group dirty，安全标志变化尚无入口。新增能力均未接线。

### 4.2 拟新增数据流

~~~mermaid
sequenceDiagram
    participant C as Desktop
    participant G as Gateway
    participant B as Backend 模型
    participant O as Gateway Outbox
    participant A as Backend 审计
    C->>G: 原始 DSH 凭据和模型请求
    G->>B: 缓存未命中时查询 profile
    B-->>G: 可信用户和租户
    Note over G: 固定租户策略快照，检查输入
    alt 输入命中
        G->>O: 提交命中事实
        G-->>C: 内容阻断
    else 输入可转发
        G->>B: 原始凭据及原始请求
        B-->>G: X-Request-ID 和模型响应
        Note over G: 检查后按序交付，命中则停止交付
        G-->>C: 安全内容或明确终止
        G->>O: 提交终态或立即命中事实
    end
    O->>A: 服务签名，持久重试
    A->>A: 验证绑定，事件及摘要提交
    A-->>O: 提交确认
    Note over A: 会话和目录持久 dirty，异步汇总
~~~

### 4.3 模块职责与改动范围

表中“新增”是拟建文件，不是现有实现。Gateway 路径基于 com/dataelem/gateway，backend 路径基于 src/backend/bisheng。

| 范围 / 模块 | 做什么 | 不做什么 |
|---|---|---|
| Gateway 新增 filter/DshContentSafetyFilter | 精确匹配两个模型路由，组织缓存、快照、检查和终止 | 不处理登录、席位或 backend 模型授权 |
| Gateway 新增 filter/DshModelRoutingFilter、client/DshModelProxyClient | 单次上游请求、连接与订阅生命周期、原头和流式转发 | 不再次调用默认 NettyRoutingFilter，不执行自动模型重试 |
| Gateway 新增 client/DshProfileClient、service/DshIdentityCache | 独立无凭据日志的 HTTP、缓存和请求合并 | 不用通用 WebClient DEBUG 头日志，不保存原始 Token |
| Gateway 新增 service/DshSensitivePolicyService、DshSensitiveScanner | 租户策略、编译快照、结构化文本扫描 | 不调用有原文日志和 BlockRecord 副作用的 filterNormal |
| Gateway 新增 protocol/DshChatSafetyAdapter、DshResponsesSafetyAdapter | 协议域、事件顺序、工具参数和终止事件 | 不改写普通模型正文，不重编号 Responses 事件 |
| Gateway 新增 service/DshSafetyOutboxService、client/ContentSafetyEventClient | SQL 事务、租约、签名发送和重试 | 不把内存队列视为已可靠记录 |
| backend 新增 dsh/api/endpoints/content_safety_events.py、domain/services/content_safety_ingest.py | 外部事实认证、绑定和接收编排 | Endpoint 不写 ORM，不主动连接 Gateway |
| backend 新增 dsh/domain/models/content_safety_event.py、repositories/content_safety.py | 事件事实、短事务、幂等、摘要和保留检查 | 不修改 dsh_model_call 或额度 |
| backend 既有 model_audit_write、model_audit_writer、model_audit_status | 合并外部条目、保留安全字段、识别不适用 | 不在 model.complete 中增加安全检查 |
| backend 既有 model_audit_queries、conversations、tree_build、management | 过滤、DTO、readiness、dirty 和命中汇总 | 不逐行查询事件，不全历史聚合事件 |
| 平台既有 DshPage、SystemPage/dsh、controllers/API、types | 策略表单、审计标签、过滤、详情和三语文案 | store 不请求 HTTP，不修改组件视觉规范 |
| Desktop enterprise/openai.js、responses.js、error-copy.js | 区分阻断和不可用，终止轮次及待执行工具 | 不执行客户端词库检查、不自动重试 |
| 部署与 worker | 入口封闭、凭据、DDL、汇总消费者、回填及监控 | 不在本轮执行迁移或部署 |

backend 新接收链为 Router → Endpoint → ContentSafetyIngestService → ContentSafetyRepository → SQL。签名校验是专用入站适配，复用现有 HMAC 算法、共享密钥和签名头配置；拟将无业务副作用的签名计算与比较逻辑提取为通用基础设施函数，由 SSO 和 DSH 各自适配器调用，不跨 API 引用 SSO 模块，也不复用其租户 bypass 或正文回放副作用。现有模型审计公共行操作通过同一仓储辅助逻辑保持一致。

### 4.4 profile 缓存与并发

本文 profile 指既有 GET /api/v1/dsh/profile：Gateway 携带原始 DSH Bearer Token，由 backend 验证签名、有效期、用户及租户有效状态和本地会话，再读取当前用户、租户资料。返回 user.id、user.username、user.display_name 及 tenant.id、tenant.name；Gateway 以 tenant.id 选择敏感词策略，以 user.id 记录审计身份。它是 backend 成功验证后的资料，不是 Gateway 直接解码 JWT payload 的结果；该接口不返回 session_id，也不授予模型或租户管理权限。下述缓存复用的是这一验证结果。

1. 键为 backend 部署命名空间加 SHA-256 完整原始 Token。命名空间随 backend 目标及信任配置变更而变化，不能只按 user_id 复用。值只含已验证用户、租户、验证时间和绝对截止时间，可选会话标识为空时保留未知。
2. 查 L1、Redis、profile。只有 HTTP 和 DSH 业务语义均成功、字段合法的 profile 才写正缓存。成功后读取同一 Token 的 exp 仅用于缩短寿命，不用于认定用户和租户；无法解码时不缓存该成功结果。
3. 以发起验证时的单调时钟设截止时间，存 Redis 时仅写剩余 TTL。Redis 读取原子获取值和 PTTL，L1 截止时间从该次查缓存的开始时刻计算并扣除耗时，不能从响应收到后重新给 30 秒。跨实例墙钟只辅助验证；NTP 偏差不超过 1 秒是部署前提，启用前由部署现有校时监控核验，5 秒到期余量另行扣减；校时异常的副本不接新检查请求。
4. 同副本按完整键维护有截止时间的共享验证；不同等待者共享结果，取消一个等待者不取消其他等待者。多副本使用短租约协调，只有当前 owner 可发布结果、释放租约，失去租约的旧查询不能覆盖新结果。共享 Redis 不可用时退回本机合并及并发预算，不承诺故障时全局严格一次。已过绝对期限的任务不得被新等待者复用；先取消持有的源再归还并发槽位。发布正缓存、删除无效缓存及释放租约均须owner校验，旧查询迟到401不能删除或负缓存覆盖新身份。
5. 1 秒预算包含等锁、连接、请求和解析；超时或队列满返回 check_unavailable。局部缓存可选写失败需要指标，不能延长旧值寿命。不得因缓存失败重试模型调用。
6. backend 明确身份失效时清正缓存；模型无权限或额度不足不清。明确无效凭据可负缓存 1 秒，基础设施异常不得负缓存。原始 Token 只在本次认证和转发需要的内存期间存在，不进入缓存、Outbox 或日志。

可信身份尚未取得时无法安全分配租户审计条目：保持明确鉴权错误或检查不可用，只记录无凭据的 Gateway 运维指标，不编造 tenant_id=0 的安全事件。已缓存身份的输入阻断可能先于注销提示，仍遵守 spec 的接受边界。

### 4.5 租户策略与管理授权

Gateway 新表 gt_dsh_sensitive_policy：tenant_id 唯一、version、enabled、input_enabled、output_enabled、words_types、custom_words、auto_reply、updated_by、updated_at。词库摘要来自发布包，策略保存为 builtin_digest；运行时快照键为租户、版本、内置摘要三元组。实例加载文件的摘要必须匹配策略预期摘要，不匹配时拒绝检查，不能用本机另一版本词库替代。

默认缺失记录等于关闭、版本 0；读取错误等于不可用。启用任何方向前必须有有效词和非空提示，并通过 §2.2 限制。复用 FileUtil 的分词语义、内置词加载和 ACPlus 字面匹配；去重，不新增忽略大小写、同音词或 Unicode 归一化规则。以发布健康检查核对所有副本的 builtin_digest，不允许相同快照静默对应不同词表。内置文件升级需要协调副本、策略预期摘要和生效版本；本期不承诺跨内置词库版本滚动升级不停服，无法满足预期摘要的副本明确不可用。普通自定义词修改仍遵循 5 秒策略更新规则。

DSH 使用局部 ACPlus 适配器构建完整的 BFS 失配链，修正既有构建器跳过多层后缀的漏检；命中结果在扫描收集时即限制为有界摘要并标记截断，不能先生成无界全命中列表再 limit。复用既有 addWords/indexOf 字面语义，不改全局旧应用过滤器。候选词库校验单独编译，不以相同租户/预期版本覆盖已提交匹配器缓存。

保存执行 version 条件更新，首次建立只允许 expected_version=0。事务提交后更新共享缓存并广播失效；广播丢失由 5 秒绝对寿命收敛。旧读取不能覆盖新版本，读取和写缓存耗时不能延长旧快照寿命。编译在有界执行池，失败不发布“启用但空词库”的快照；在途请求保持已取得的快照引用。

管理请求每次实时访问既有 backend 接口，不缓存管理授权：

1. GET /api/v1/user/info 获取当前用户和 leaf_tenant_id，角色标志只作辅助识别，不能单独授予保存权限。
2. 所有操作者均调用 GET /api/v1/dsh/admin/model-audit/settings?tenant_id={target}，由其现有 get_tenant_admin_user 和 authorize_admin 完成自然人、租户及有效管理范围校验；只读取结果，不改审计开关。即使 mode=OFF 或原文密钥不可用，只要该读接口成功且返回合法 DTO，就不额外要求启用原文审计。
3. 非超管必须 target 等于当前 leaf，并通过 GET /api/v1/user/tenants 在当前用户的 active 列表中确认目标存在且有效。超管明确选 target，并用 GET /api/v1/tenants/{target} 检查目标存在和状态；其可管理范围仍由第 2 步决定，不能用角色标志覆盖拒绝。

所有调用原样携带本次浏览器认证和既有作用域上下文，不借用 DSH profile 缓存。Gateway 状态变更接口还须校验 Origin 属于部署允许的管理站点，并沿用既有浏览器写操作防护；不能因为它向 backend 发的是 GET 就允许跨站写入。管理PUT先校验Origin和实时权限，成功后才读取原始正文；聚合上限8MiB以容纳1MiB词库最坏六倍JSON转义，JSON深度16并拒绝重复键、尾随值及非法UTF8。超限413，解码后词库仍限1MiB，成功/错误/超限/取消均释放缓冲。HTTP 200 中的业务失败、缺少字段、权限服务不可用均拒绝。GET /tenants/{id} 的现有 get_admin_user 仅允许平台管理员，不能把它作为 Child Admin 的统一探针。本设计复用这些通用读取接口，backend 不新增 Gateway 管理 RPC；管理动作低频，新增校验开销单独观测。

部署级开关默认关闭；开启后两个入口始终执行该控制链。商业功能失效不能使已开启检查静默变成透传：返回 check_unavailable 并告警。该判断不恢复 backend License 或席位准入；停用检查按 spec 作用于新请求，Outbox 投递独立继续。

T064 实施约定：SharedCache 发布传入读取起点建立的固定单调截止时间，不传可能已经过期的相对 TTL。专用 StringRedisTemplate 复用现有 connectionFactory，避免全局 JSON 序列化给 Lua 参数加引号；通过 Redis TIME 映射固定服务端截止，最终 PUT 再按该截止扣余量，排队、网络或取消后的迟到写入都不能续期。策略保存先按 expected_version+1 编译真实规范化快照，CAS 成功后直接采用它；缓存发布与广播限时 best effort，失败记录诊断但返回已提交版本。原始词库1MiB及Unicode校验在规范化和关闭分支之前执行，超限413；缓存权重同时计入树、去重词及 PolicySnapshot 持有的词库/回复元数据。

### 4.6 结构化扫描、有序交付与续读

输入以有界 UTF-8 JSON 解析，检查消息文本、可读 reasoning、工具说明、工具参数及结果；参数再次按 JSON 解码检查其中的业务字符串。工具参数对象键和字符串值分别检查，不把协议外壳、图片编码、凭据或审计上下文拼进去。同一消息连续文本块同属一个逻辑域，不同消息、choices、工具调用及独立文本域分别处理。未知或不可安全解析的可交付结构返回错误，不直接当安全透传。工具schema须区分属性名映射、结构关键字与default/const/enum/examples业务值，不能因为业务属性恰名properties而切换解析语义；同一reasoning item的连续content或summary文本各自组成域，两类及不同item仍独立。

两个精确 POST 路径增加优先于 catch-all 的独立 DSH route，URI 与 profile 的固定 backend 配置保持一致，不挂旧路由的 CacheRequestBody(String) 过滤器；否则正文可能先按 200 MB 全局上限缓存并产生未计入预算的副本。源配置与 docker/gateway/config/application.yml 都要同步路由定义，DM profile 继承该定义。旧应用敏感词、响应过滤和 PathRate 的应用正文分支跳过 DSH 托管标志，避免误扫和打印 DSH 原文；公共 WebFilter 及适用的通用限流仍保留，新 DSH 的并发由独立预算控制。部署级检查开启后，模型入口的上游连接交给专用 DshModelProxyClient 管理。前置检查过滤器只准备可信上下文；DshModelRoutingFilter 在现有 PathRateGlobalFilter（LOWEST_PRECEDENCE-90）之后、默认 NettyRoutingFilter 之前取得路由所有权，标记 already-routed，不再调用默认模型路由。其他公共 WebFilter 和前序限流仍执行。部署开关关闭才使用原有代理链。

每个请求只创建一次上游 HTTP 请求和一次响应订阅，沿用部署现有连接/模型读取超时，不开启重试和自动重定向。组装时复用现有 spring.cloud.gateway.httpclient.response-timeout 的正有限配置值作为模型Proxy与Manager同一I/O预算；仓库默认未设置该值，不能用connect-timeout冒充读取预算或自行引入45/60秒fallback。检测enabled=true但该既有预算缺失/非正时明确拒绝开启组装，默认检测关闭仍保持原启动，且完整回传配置关闭检查时管理和历史投递独立运行。客户端交付和后端读取有独立的完成信号；请求管理器持有唯一上游订阅，向客户端的有界交付通道取消不直接取消该订阅。只有内容阻断触发时才转后台续读，普通用户取消仍关闭上游。客户端收到阻断闭流后，上游仍由请求管理器持有至有界续读结束，且不写入默认代理会自动释放的 CLIENT_RESPONSE_CONN_ATTR。不得对响应 Flux 再 subscribe 一次，不得让默认 Netty 响应清理在续读结束前 dispose 连接。HTTP 头按代理规则过滤 hop-by-hop 和失效 Content-Length，保留有效原始 Authorization、正文及模型请求编号；请求目标仅来自固定 backend 配置。原始请求先完整限长校验再转发，上传空闲及总时限沿用部署代理预算并计入检查占用。

输出解码、扫描、交付分别维护进度：

- 每个逻辑文本域保留最长生效词长 L 减 1 个码点，扫描边界按 Unicode 码点，不按 UTF-16 char 数或 UTF-8 字节数。调用既有 ACPlus 时处理补充平面的索引差异，测试不得只用汉字 BMP 样本。
- SSE 解码支持 UTF-8 跨字节、多行 data、事件跨网络片段；为每个原事件建立可交付水位。只有该事件承载的全部文本都越过检查水位、依赖的工具参数已完整通过，才从有序队列交付；后面的元数据、usage、done 和终态不能越过它。
- 保持完整原事件及 Responses sequence_number，不为释放文本前缀切碎、拼造或重编号正常事件。多个域交错可能产生队头阻塞；其占用计入全局缓冲，达到上限则报错终止，不能提前交付未检查文本。该限制需要实际延迟测试。
- 工具调用按 call_id、choice/item 标识组装，完整解码并检查后才交付可执行参数。Responses 的 item.added、arguments.delta/done、item.done 和最终快照都受同一屏障约束。
- 完整快照与此前增量按文本域关联。相同快照独立校验，不能作为新的增量重复拼接；新增或变化内容交付前检查。协议绑定冲突报错，不能通过“修复”顺序或丢字段继续。
- 结束时检查并释放尾部；任何未结束文本或工具域均不能生成正常成功终态；若流以 backend 失败或客户端取消结束，已确认命中优先，否则未完成的适用检查报 ERROR 并记录终止原因，不把被截断的可检查内容报 PASSED。普通无命中响应保持正文、工具语义和事件次序。纯backend错误按已支持的错误外壳校验后保留原bytes；混入choices/output等未分类正文不能走错误透传快捷路径。Responses条目须由output_item.done或最终快照所含条目确认结束，只有arguments.done而条目被最终output遗漏时不能产生成功终态。

输入命中不向 backend 发模型请求。非流式响应完整检查后交付。流式命中立即停止客户端内容交付、生成命中事件，并转入有界续读：从命中时刻起独立 30 秒截止；不再解析交付业务内容，只继续消费到 backend 完成以争取结算。无续读额度则立即关闭，时间、剩余字节或上游异常先到先结束。

续读任务由请求管理器持有，不能随“已向客户端发送阻断结束”自动取消，也不能无限游离；释放所有 Netty DataBuffer、订阅和配额。Gateway 进程退出不能恢复模型流，backend 按断连处理，已提交命中 Outbox 仍可恢复。续读完成只上报 FINISHED、TIMED_OUT、LIMITED 或 DISCONNECTED 等观察状态，不写 backend 用量或伪造零消耗。

### 4.7 持久事件与接收事务

Gateway 事件种类为 DECISION、FINAL、DRAIN。普通已检查请求通常一条 FINAL；命中立即 DECISION，有后续续读状态时再写 DRAIN。每条包含输入、输出的完整阶段快照，事件量按模型 HTTP 请求增长，不按 Token 或 SSE 片段增长。

每个 Gateway 请求生成 UUID，原始事件 event_id 和 event_version 在成功记录时固定，重试不再生成新事件或版本。gt_dsh_safety_outbox 保存不可变事件及独立投递字段：event_id 主键、source_id、gateway_request_id、payload、payload_hash、status、attempts、next_attempt_at、lease_owner、lease_until、last_error_code、created_at、acked_at。

状态为 PENDING → INFLIGHT → ACKED；租约超时回到可领取，永久拒绝进 QUARANTINED 并告警。用条件更新领取和确认，不依赖所有数据库支持 SKIP LOCKED。Gateway 新表分别提供 MySQL 和 DM8 DDL，公共 MyBatis mapper 不使用 MySQL 专有 upsert、JSON 查询或分区语法，租约与去重均验证两种数据库。ACK 丢失重发相同事件，更新签名时间，不更新事实。后台限速与模型 HTTP 生命周期分离。

Outbox 写入成功后才称为“已记录”；写失败仍阻断命中，报告不可恢复缺口。检查已通过但仅审计记录失败时保留业务响应、报警并在 backend 显示 UNREPORTED，不重试模型、不伪造已可靠上报。Outbox 不能靠内存兜底声称持久性成立。

backend 专用接收端依次执行：

1. 限定方法、路径、64 KiB 正文及签名时间窗口，验证服务来源；解析严格事件结构后验证 ID、时间、版本及字段界限。
2. 根据已认证事件设置严格 TenantContext，清理浏览器残留的可见租户、管理范围和 bypass；上下文在 finally 恢复。每次 SQL 执行线程也在 verified_source 指定租户的 profile_scope 内建立严格上下文，不能假定线程池自动继承 ContextVar。调用方沿用共享 HMAC 配置认证为部署内 Gateway 服务；source_id 用于幂等和诊断，不能仅凭自报来源扩大部署已允许的租户范围，不依赖用户 Token 当前有效。
3. 在 SQL 事务内检查相同事件、载荷摘要和保留水位。相同来源与编号、相同内容返回已提交确认；同编号异载荷或同请求同版本异事实返回 409。不同版本来自毕昇的可信身份变化按事实接收，不作跨事件身份冻结或冲突拒绝。
4. 保存事件；沿用模型记录自身的归属和既有权限核对可关联性，无法确认时保存未关联事实。已关联或可建立外部条目时锁定主行、归并安全摘要、写持久 dirty。创建竞争遇唯一键冲突时回滚本次短事务并重读，不在失效事务中继续；因可信身份变化无法建立原关联时保留事件并按未关联事实确认，不覆盖其他归属的模型历史。
5. 事务提交后才 ACK。未关联事件可提交并确认事实，但不猜测模型主行。会话、目录汇总异步执行，ACK 不承诺树已经发布；readiness 和水位须表达延迟。

仅新增精确的 POST /api/v1/internal/dsh/content-safety-events 服务认证分支：跳过浏览器 JWT 准入，进入签名验证。不能把整个 internal/dsh 前缀加入 TENANT_CHECK_EXEMPT_PATHS，因为该列表还会开启 tenant bypass。应清空上下文后建立事件租户，未通过签名前不得查询业务表。

### 4.8 数据结构、关联和状态

backend 新表 dsh_content_safety_event 采用现有 SQLModel 基类和 dialect_helpers：

| 字段组 | 类型 / 用途 |
|---|---|
| event_id、source_id | UUID 文本 / 有界来源；唯一约束 source_id + event_id；另约束同来源/Gateway 请求/event_version 不重复 |
| tenant_id、user_id、model_id | BigInteger；身份取毕昇验证结果，模型取本次请求或调用事实，租户自动注入 |
| gateway_request_id、backend_request_id、audit_request_id | UUID；后两者可空，区分来源编号、模型编号和审计关联 |
| event_version、schema_version、event_kind、protocol | 有界整数或枚举；版本按同一来源、同一 Gateway 请求单调产生 |
| request_started_at、occurred_at、received_at | UTC 微秒时间；不把回传到达当事件发生 |
| payload_hash、stage_results、policy_version、builtin_digest | 摘要和结构化事实；JSON 用 JsonType，正文缺省且禁止接收 |
| hit_count、rule_refs、forwarded、drain_status、association_status | 有限诊断；rule_refs 为不含原词的规则标识 |

每条事件按 Gateway 从毕昇成功取得的身份和本次模型事实归档；可信身份结果变化予以接受，不以首个事件冻结所有后续版本的租户、用户或模型，不增加独立请求绑定表。索引 (tenant_id, source_id, gateway_request_id, event_version, event_id) 用于租户范围内的请求事件查询，不作为跨事件身份冻结机制。历史补报复用原持久化载荷，不按用户当前调租、退出状态重新生成或拒绝历史事实。

主表 dsh_model_audit_request 增加：

| 字段 | 作用与所有者 |
|---|---|
| record_origin MODEL / EXTERNAL_SAFETY | 原审计或外部条目；仅原生审计可将外部条目升级为 MODEL |
| model_entered、model_started_at | 可空；输入阻断明确 false，其余只由 backend 调用或原审计事实确认 |
| safety_source_id、safety_gateway_request_id | 单次检查关联；来源与 Gateway 请求组合唯一，避免同请求重复建行 |
| input_safety_state、output_safety_state、各阶段 version | 最新阶段状态；每阶段按来源内版本归并 |
| has_sensitive_hit、input_sensitive_hit、output_sensitive_hit | 已知命中，单调累积 |
| content_safety_state、content_safety_updated_at、policy_version、builtin_digest | 列表摘要；状态包含 UNREPORTED、PASSED、BLOCKED、ERROR、DISABLED、NOT_APPLICABLE |
| safety_projection_version、group_indexed_sensitive_hit | 并发水位和已计入会话的命中状态；禁止按事件条数累加 |

输入阻断用 gateway_request_id 建外部审计条目，model_entered=false，不生成 dsh_model_call；输出用模型响应 X-Request-ID 关联。转发后未取得模型编号时仅保存未关联事件，通过审计事件查询查看，不按用户、时间或模型猜关联。

外部条目的 effective_mode、model_result、response_result、usage_settlement 和 session_id 等未确认字段允许 NULL；content_status=NOT_CAPTURED，audit_status=NOT_APPLICABLE，不计入模型 NORMAL/ABNORMAL。状态派生先按 record_origin 分支，停滞扫描仅扫描真实模型条目；外部条目不要求模型终态或原文 manifest，不参与原文密钥就绪门槛。未知 model_name 用空字符串及其摘要建立可索引占位，界面仅显示模型编号；原生审计后到补齐名称和摘要，不让未知名称卡住全租户 readiness。输入阻断展示“不适用”，缺少原生审计的输出条目展示“未观测”；usage 缺失为 null，不用数值 0 替代。

仅有外部事件不证明模型执行；接收端可读取相同 tenant/user/model/request_id 的 dsh_model_call 或原生证据确认 model_entered，但不能由 forwarded 或收到响应头推断执行成功。查到调用用量可按既有补数逻辑展示，模型审计模式和 ASGI 交付结果仍不能编造。

NULL 表示未知的可选关联可由真实原审计补齐；安全事件采用毕昇可信结果并接受变化，模型审计仍保留其自身的执行和用量归属。无法确认关联时保存未关联事实，不以跨事件身份变化拒收，也不覆盖其他归属的模型历史。外部会话提示需复用既有 AuditContext 的字段校验：conversation_id、parent_conversation_id 为合法 UTF-8 的 1–256 字符；request_kind 为 chat/compaction/session-title；session_origin 为 main/subagent，父会话须有子会话、来源为 subagent 且不能指向自身。Gateway 仅提取这些可选字段，backend 接收时再次清洗；非法提示只影响关联，不阻断模型或关闭检查，不把原始 audit_context 或 message_sources 复制进事件。ConversationHint 的供应商亲和默认值不能代替 AuditContext 的审计绑定值，特别是缺失 request_kind 不能私自补 chat。未确认字段与已确认的空值须在合并规则中区分，原生审计提升来源时确认模型事实和关联。

主表 started_at 首次建立后固定；安全先到时使用经校验的 request_started_at，原审计后到将实际起点放 model_started_at。request_started_at 和 occurred_at 不得晚于签名保护的 sent_at 加 300 秒，发生时间不得早于请求开始超过 5 秒；历史重试不改这些时间且仍受保留水位约束，不用回调时间移动游标位置。

主行旧 mode CHECK 替换为明确的来源约束：MODEL 必须有非空 METADATA/CONTENT；EXTERNAL_SAFETY 的 effective_mode 为空。原 writer 在同一事务提升来源并补齐 mode，不留下半提升状态。旧字段安全默认值为 MODEL、无已知命中、UNREPORTED；原生 writer 不写安全字段，防止后写重置。T026仅对EXTERNAL_SAFETY的未知NULL补原生事实，已确认非空session/会话提示冲突仍拒绝，既有MODEL身份比较保持严格；model_started_at首次固定，安全started_at不移动。未收到原生对应终态的轴先保持RUNNING/PENDING，不将未知用量写成零。

请求汇总严格采用 spec AC-34 的六级顺序：命中 → 无命中时检查失败 → 缺少完整终态 → 两方向明确关闭 → 至少一个通过且其他终态合法 → 无实际适用检查的不适用。按阶段版本处理乱序，但旧版本命中仍须累积，不能因为整体 event_version 较旧而丢弃命中。UNREPORTED 可补为已知终态；已关闭、不适用和已完成阶段不得被后续 DRAIN 快照重新打开。相同阶段版本不同事实或不合法终态变更返回冲突，不能把较新的不完整快照覆盖已确定事实。

### 4.9 查询、会话投影和保留

主列表只读审计主表摘要。必备主表索引为 (tenant_id, has_sensitive_hit, started_at, request_id)；方向和状态高频组合另验证 (tenant_id, content_safety_state, started_at, request_id)，用户/模型组合经执行计划再增加索引，不单独索引布尔值。

事件索引包括唯一 (source_id,event_id)、详情 (tenant_id,audit_request_id,occurred_at,id)、未关联列表 (tenant_id,association_status,request_started_at,id)、清理 (tenant_id,received_at,id) 及上述请求事件查询索引。事件详情分页，不在默认列表 JOIN、GROUP BY 历史事件或逐行读事件。

请求按 (started_at,request_id) 升序 keyset 取 limit+1，使用时间大于或时间相等且 ID 大于的可移植条件，不使用方言元组比较或 OFFSET。游标沿用既有实现，绑定当前租户和用户显式提供的用户、模型、时间及安全过滤条件；更换显式条件拒绝旧游标。默认最近 7 天，单次窗口最多 31 天，超限拒绝，不执行全历史 COUNT。本期不要求默认相对窗口跨页固定；默认范围随时间推进不单独判作用户更改筛选条件，不增加服务端查询会话、新版冻结窗口游标或额外验收门槛。 主请求Repository.page新增可选now端口，传now时在仓储内计算默认上下界，指纹仅绑定规范化的显式filters；Service不得把隐式上下界写成显式筛选或解析重签游标。未传now的既有内部查询保持原语义。

所有批量摘要更新、投影领取、回填和清理的 UPDATE/DELETE 显式限定当前 tenant_id、目标编号及版本或租约条件；不能把 SELECT 自动租户过滤误认为覆盖了写语句。事件与主摘要同事务更新持久 group_index_pending；即使 audit_status 不变也置 dirty。没有可用 conversation_key 的条目先标记“未关联已处理”，不永久保留 group dirty；原审计后到补齐关联时再次置 dirty。会话增加 sensitive_hit_count/has_sensitive_hit，目录节点增加 own/branch 命中计数；按每请求前次已投影状态计算差量，重复和先后到达不重复计数。来源升级时审计状态计数可变，但条目数不再加一；模型调用和用量始终取 dsh_model_call。

汇总消费者进入明确租户范围，有限批次和 SQL 租约；利用既有会话 dirty 与目录代际发布，合并短期更新。拟新增 Celery 默认队列投影任务，Beat 按持久 dirty 记录枚举租户和调度，包含有历史补报的停用租户，不能只枚举 active 租户；跨租户枚举仅取得待处理租户编号，具体处理仍回到严格租户范围；每个执行进程使用同一服务和严格租户范围，不依赖 API 进程本地内存。worker 未运行时主列表仍准确，目录 readiness 显示 PREPARING，不伪装完整无命中。

简单命中目录筛选走汇总索引；组合用户、模型、时间沿用有界候选查询。达到预算返回 scan_limited 和恢复/刷新提示。会话按请求开始窗口入选，不按后到安全事件的接收时间替换时间口径。组合条件必须由同一条请求同时满足：例如同一会话上月命中、昨天未命中，最近 7 天的命中过滤不能仅凭全会话 has_sensitive_hit 返回它。有时间条件时，汇总索引只产生候选，仍按有界请求检查完整条件；不能把“某请求满足时间”和“另一个请求命中”相交。会话全量计数与筛选命中数分别标注，后者只有实际计算后才显示。

保留规则：

- 明细自动清理默认关闭；30 天仅用于容量评估。启用保留需配置经确认的窗口及可回放要求，事件摘要保留到对应主审计删除。明细删除后 DTO 显示 details_status=PURGED，不回退为 UNREPORTED。
- Gateway 已确认 Outbox 副本可按运维保留窗口清理，初值 7 天；未确认事件不按普通 TTL 直接删除。永久拒绝、超过明确补报范围或磁盘高水位须告警，不记为 ACKED。
- 主审计按时间保留清理前，持久保存每租户 audit_deleted_before 水位；接收和原审计后写均拒绝水位之前、已不存在主行的建行；仍存在的有效主行可以继续接收后到事实。清理先排除仍在执行的记录，不能用水位屏蔽尚在保留的有效请求。水位与清理进度拟保存在审计 setting 的扩展字段，不与 mode/version 更新互相覆盖。默认水位为空，不删除历史。
- 离散删除须在同一审计维护契约中先保存请求 tombstone；本期不提供绕过水位或 tombstone 的删除入口。后续实现若新增这类入口，必须一并交付 tombstone，不能只执行裸 DELETE。
- 清理租户内按时间及 ID 有限批次进行。回放仅覆盖仍有事实或归档的窗口；已经清理的明细不承诺可任意重建。接收过期补报返回 410，保留最小拒绝诊断，不复活记录。

### 4.10 前端和 Desktop

平台沿 DshPage 当前入口增加“敏感词控制”配置区域，沿用现有租户选择。配置走 Gateway；审计请求、详情、未关联安全事件走 backend 的既有审计权限边界。Gateway 不可达时配置区域明确不可用，不影响无 Gateway 部署的模型、额度和审计功能。

词库、输入/输出方向、提示等作为一次原子保存，使用 Checkbox 和保存按钮；不把“拨动后仍需保存”的行为伪装成 Switch 即时设置。运行开关若使用 Switch 则独立立即提交，等待锁定、失败回弹，并基于已保存的有效词库校验。沿用现有表单/审计布局，不增加新的组件样式。

依据当前 UI 规范，状态使用 Tag，计数才使用 Badge。已落地组件优先；无已落地组件时沿用当前页面实现。过滤切换清游标和缓存，列表显示输入/输出命中及汇总，详情显示阶段和策略。外部条目隐藏原文入口；N/A、未知、已清理均区别展示。

API wrapper 留在 controllers/API，新取数遵循当前根 AGENTS 约定的 @tanstack/react-query v4，不新增 react-query v3 用法或开展全站迁移。当前分支 platform/package.json 只直接声明 v3；tasks 单列补充 workspace 已锁定的 v4.44.0 直接依赖，并在本特性设置组件内提供局部 QueryClientProvider，不更换全站 v3 Provider。新键补齐 zh-Hans/en/ja；错误文案只写 packages/locales 源文件并走生成流程，触及旧硬编码文件时按项目规则迁出。

Desktop 将 content_blocked/content_filter 统一映射为不可重试的 CONTENT_FILTERED，check_unavailable 映射为 CONTENT_CHECK_UNAVAILABLE。Responses 必须在普通事件 sequence_number 校验前识别合法 error 事件；不把阻断变成 UPSTREAM_ERROR。终止时清掉当前轮次的待执行工具，不用错误结束的 block-end 触发执行；只有完整参数通过并且该轮正常结束才进入工具执行。实现阶段必须沿 adapter 的 finish 事件追到实际工具 runner 调用点验证该屏障；若现有 runner 提前执行，应在该消费边界阻止错误轮次的执行，不只修改提示文案。

运行配置采用既有配置入口：Gateway 新增 DshSafetyProperties（dsh.content-safety.*），默认 enabled=false，backend 目标复用已配置 bisheng-api-url，另设稳定 backend-namespace 和 source-id。回传直接使用 Gateway 的 bisheng.gateway-hmac-secret 与 backend 的 sso_sync.gateway_hmac_secret（既有环境变量 BS_SSO_SYNC__GATEWAY_HMAC_SECRET），两端值必须一致；签名头沿用双方既有 signature-header / signature_header，默认 X-Signature。不新增 DSH 独立密钥变量或密钥登记表。接收端按需读取既有配置；密钥未配置时该接收端返回不可用，验签失败按认证失败处理，不新增模型 runtime 对 HMAC 配置的初始化前置校验。实际密钥沿用部署安全配置注入，不写入 Git、示例 YAML 或日志；不新增 backend Gateway URL，不在旧 YAML 增加未识别的顶层键。

### 4.11 迁移与启用顺序

静态迁移图当前单 head 为 work110_dsh_local_sessions；实施时必须重新核对，而不是沿用本次静态结论。既有表列、CHECK、索引变化走该分支 Alembic DDL；新 SQLModel 表由项目发现机制创建，若同批修订依赖则显式声明顺序。任何回填、清理或重建都用独立 dry-run/apply 运维程序，不在 revision 中 SELECT 后 UPDATE。

1. backend 先部署表结构、专用接收、DTO 兼容、受控合并和保留闸门。列的 server_default 可提供旧行初值；实际摘要/树回填另跑有进度的操作。
2. 启动投影 worker，逐租户有限批次重建，验证 readiness 与无跨租户结果；旧安全状态仍 UNREPORTED。
3. 发布平台和 Desktop 的新状态、错误与工具屏障，再发布 Gateway 检查及投递；部署开关保持关闭。
4. 对账两种数据库 DDL、双方既有共享 HMAC 配置和时钟，验证服务回传、profile 目标及所有公开入口。入口必须经过 Gateway，backend 模型端口仅受信网络可达。
5. 先选测试租户启用，再逐租户扩大。停用只影响新请求，在途保持快照、待投递继续发送。数据结构和事实不随回滚删除；回滚旧 DTO 前必须停用新事件并确认外部条目兼容读取。

## 5. 已知坑与防护

| # | 已核实事实 / 风险 | 不处理的结果 | 设计处理位置 |
|---|---|---|---|
| 1 | Chat 与 Responses 使用不同 adapter | 只包 LangChain 漏检 Responses | §4.6 两协议扫描 |
| 2 | filterNormal 会输出原文并保存 BlockRecord | 新功能引入额外正文泄漏 | §4.3 仅复用词库/ACPlus |
| 3 | 通用 WebClient DEBUG 输出请求头 | DSH Token 进入日志 | §4.4 独立 ProfileClient |
| 4 | profile 请求和模型请求都有 X-Request-ID | 审计关联到身份请求 | §6.2 只取模型响应编号 |
| 5 | 外部事件可能早于异步主行 | 命中丢失、重复主行或关联到其他归属 | §4.7–§4.8 短事务、可信事实接收与受控关联 |
| 6 | 现有审计状态仅 NORMAL/ABNORMAL，mode 不可空 | 外部条目被误判失败或运行中 | §4.8 状态和来源约束 |
| 7 | backend ASGI 完成只代表发给 Gateway | 输出拦截被误写成 backend 交付失败 | §6.3 安全结果独立于原执行结果 |
| 8 | Chat Desktop 要求 content_filter 和 [DONE] 配合闭流 | 只断流会变成 STREAM_CLOSED | §6.3 区分协议闭流和成功终态 |
| 9 | Responses error 在当前 Desktop 统一转上游错误 | 阻断原因丢失，工具或错误展示不准 | §4.10 专用错误映射 |
| 10 | 只在 audit_status 变化时置会话 dirty | 模型成功但新命中时目录不更新 | §4.9 安全字段独立触发 |
| 11 | tenant exempt 列表同时打开 bypass | 服务签名端点错误跨租户查询 | §4.7 精确服务认证与严格租户上下文 |
| 12 | 新表 create_all 不改变旧表列和 CHECK | 仅新增 ORM 后旧库运行失败 | §4.11 DDL 与运维分离 |
| 13 | 已确认 spec 的汇总包含“不适用” | 只照旧方案五状态建 DTO 会丢组合 | §6.4 与 AC-34 一致 |
| 14 | 事件量随请求累积，独立表也有容量代价 | 用索引存在冒充容量已验证 | §7.2 双库真实压测 |
| 15 | 租户详情接口只允许平台管理员，普通租户管理员使用不同授权入口 | 合法 Child Admin 无法管理策略 | §4.5 既有 DSH 管理读接口和本人租户列表 |
| 16 | 默认代理清理与客户端响应生命周期相关 | 后台续读被提前取消，或二次订阅造成重复模型调用 | §4.6 专用上游所有权与单次订阅 |
| 17 | 会话汇总是全会话事实，窗口内命中必须验证同一请求 | 返回只有历史命中、当前窗口无命中的会话 | §4.9 有界候选核验 |
| 18 | 现有 catch-all route 通过 CacheRequestBody(String) 缓存正文，codec 上限为 200 MB | 专用过滤前后出现额外副本，32 MiB/全局预算失效 | §4.6 精确路由与独立缓冲 |
| 19 | 现有 AC.update 仅一层失配回退；真实 acbcca 漏掉词表 acbcc/bcx/cca 中 cca@3 | 多层重叠后缀漏检 | §4.5 DSH 局部 BFS 失配链与独立子串 oracle |
| 20 | 现有 ACPlus 先收集所有重叠匹配；1万字符/256合法前缀词实测耗尽64MiB测试堆 | 小于文本预算的请求也可能因命中数量耗尽堆 | §4.5 收集阶段限制摘要，不生成无界列表；实际 JVM 峰值仍待压测 |
| 21 | 管理入口若使用自动DTO解码，授权前可能按全局200MB聚合正文 | 无权请求也占用大缓冲，词库字段检查过晚 | §4.5 先授权，再8MiB原始聚合与1MiB解码限制 |
| 22 | schema结构关键字、业务属性名和默认业务数据有不同语义；真实探针复现误拦与漏检 | 把合法类型关键字当正文或跳过default业务值 | §4.6 按schema上下文区分，default/const/enum/examples进入业务JSON扫描 |
| 23 | 错误透传快捷分支若只看error字段，会原样交付混载choices/output的未检查正文 | 错误形态绕过检查 | §4.6 仅合法纯错误外壳透传，混载结构明确不可用 |
| 24 | Responses参数done并不证明整个输出条目结束；最终output可遗漏此前added条目 | 未结束工具被误报PASSED并交付completed | §4.6 必须item.done或被最终快照确认结束 |

| 25 | Responses同消息连续part按content_index独立扫描会漏跨part词，delta/done/final观察又可能互相抹除 | 已支持文本跨块绕检，甚至part.done提前泄漏尾部 | §4.6同逻辑域连续检查，§9保留有界首尾/条目尾屏障和混合观察候选预算 |
| 26 | react-query开发logger会输出保存错误的Axios配置；实际Card未显示model_started_at | 草稿/请求凭据进入开发日志；请求时间与模型执行时间无法区分 | §9局部安全logger及独立模型开始时间详情行 |
| 27 | 现场ConfigService为YAML BaseModel加载器，SSOSyncConf文档的自动env覆盖并未实现 | 容器收到共享HMAC env仍无法验签 | 部署复用既有`!env`构造器显式引用env_file，实际load/readback确认，不将key明文写YAML |
| 28 | 管理visibility复用要求online的模型调用快照 | 离线私有配置被拒，上线再收窄会形成公开窗口 | T197/T198独立治理快照保留tenant/Root校验，调用快照继续要求online |

## 6. 对外契约与依赖

### 6.1 策略管理 API（Gateway 提供）

基础路径 /api/sensitive/dsh；使用现有浏览器认证转 backend 管理校验，拒绝仅有 DSH Token 的策略管理。

| 接口 | 合同 |
|---|---|
| GET /settings?tenant_id= | 返回该目标租户策略、version、builtin_digest、有效词数及限额；缺失记录返回默认关闭、version=0 |
| PUT /settings?tenant_id= | expected_version、enabled、input_enabled、output_enabled、words_types、custom_words、auto_reply；条件保存，返回生效版本和最长 5 秒提示 |
| GET /capabilities?tenant_id= | 部署级能力、配置可用性和公开限制；不能用缺失能力响应替代已经开启策略的检查 |

成功沿用 Gateway ResultData；业务失败同时检查 status_code，保存版本冲突返回明确 409。无权限 403、格式错误 400、词表超限 413、依赖不可用 503。既有 saveWords/wordsDetail/testWords 不扩展为 DSH 存储或执行接口。

### 6.2 外部安全事件 API（backend 提供）

POST /api/v1/internal/dsh/content-safety-events，仅服务认证，无 query 参数。UTF-8 JSON 包装为 sent_at 和不可变 event；签名头沿用双方既有配置，默认 X-Signature。

接收端使用 DSH 的真实 HTTP 状态和错误 envelope；成功直接返回 receipt 对象，不包平台 resp_200。Gateway 必须同时核对 HTTP 200、receipt=COMMITTED 和本次 event_id，不能把任意 2xx 或仅入队结果当确认。正文只限长读取一次，签名验证后从同一 raw bytes 做严格 DTO 解析；不复制旧 SSO dependency 的 request._receive 回放实现。校验错误只返回错误类型和安全字段路径，不回显输入值、签名或正文。

签名算法及密钥直接复用既有 Gateway—backend 互信：HMAC-SHA256(secret, upper(METHOD) + LF + PATH + LF + 完整原始正文)，签名输出为小写十六进制，比较采用常量时间比较。Gateway 读取 bisheng.gateway-hmac-secret，backend 读取 sso_sync.gateway_hmac_secret，两端配置相同值；签名头读取各自既有配置，默认 X-Signature。路径固定为接收路径，不含查询；时间、来源和事件编号均在签名保护内。发送时间默认允许前后 300 秒，重试重新生成 sent_at 和签名，event 不变。密钥轮换沿用已有共享配置的双方协调更新，不新增独立 key_id 协议或另一套密钥配置。共享密钥认证 Gateway 服务身份，事件按部署已允许的租户范围和严格租户上下文处理；不接受请求指定回传目标。

| event 字段 | v1 类型 / 约束 |
|---|---|
| schema_version | 整数 1；未知版本拒绝，不能忽略新增安全阶段 |
| source_id / event_id / gateway_request_id | 来源 1–64 字符；两个 UUID；同一次已记录事件重试不变 |
| backend_request_id | UUID 或 null；只来自本次模型响应头 |
| tenant_id / user_id / model_id | 十进制正整数字符串，范围 int64；避免 JS 精度丢失，backend 验证后转整数 |
| session_id | 可空；非空必须来自已验证上下文，不取未验证 Token 声明 |
| protocol / event_kind / event_version | CHAT 或 RESPONSES；DECISION/FINAL/DRAIN；同一 Gateway 请求从 1 递增 |
| request_started_at / occurred_at | RFC3339 UTC；事件原始时间重试不变 |
| stage_results | input/output 各一个状态；PASSED/BLOCKED/ERROR/DISABLED/NOT_APPLICABLE/UNREPORTED |
| stage_versions | input/output 各一个非负整数；UNREPORTED 对应 0，已观测状态版本为 1 至 event_version；状态改变取当次 event_version，后续快照保持未改变阶段的版本 |
| policy_version / builtin_digest | 版本及 SHA-256 摘要；不回传词库正文 |
| hit_count / hit_count_truncated / rule_refs | 非负整数、截断标志、有界规则标识；不含原词和原文片段 |
| forwarded / drain_status | 明确是否转发；续读状态为 NOT_REQUIRED/RUNNING/FINISHED/TIMED_OUT/LIMITED/DISCONNECTED，仅表示观察，不当作执行/计量事实 |
| conversation | 可空对象，仅含 conversation_id、request_kind、session_origin、parent_conversation_id 中经校验的字段；总 UTF-8 不超过 4 KiB，不含完整 audit_context 或 message_sources |

事件载荷摘要只覆盖 event，排除 sent_at 等投递包装。定义递归键排序、无空格 UTF-8 JSON；字段只用整数、字符串、布尔、null、数组和对象，禁止浮点 NaN/Infinity，固定时间字符串不二次格式化。Java/Python 使用同一固定向量验证签名和摘要，不依赖序列化器默认键顺序。

成功 HTTP 200，body 返回 event_id、receipt=COMMITTED、duplicate、association_status、audit_request_id。只有事务已提交才能返回该 receipt；未关联也只确认事实，不保证存在主摘要。400 非法格式，401 签名/时间失败，403 来源租户不允许，409 同事件异载荷或同请求同版本异事实，410 已超审计保留水位，413 超限，503 接收依赖不可用。超时、断连、5xx 和 429 可重试；404/405 表示接收版本未就绪、2xx 缺少有效提交确认表示协议异常，均保留待投递并退避告警，不冒充成功。明确的格式、权限、冲突和过期拒绝进入隔离诊断，不标 ACKED；其他未分类响应也不得丢弃待投递事实。

backend 数字业务码继续归 DSH 261，不新占模块。拟使用 26170–26175 对应接收鉴权、事件非法、事件冲突、事件过期、事件不可用及事件超限；当前分支实施前重新扫描全仓 Code 字面量确认未占用再登记。Gateway 的 content_blocked/check_unavailable 是外部 ClientCode，不伪装成已有额度或账号错误。

### 6.3 模型协议和 Desktop

模型入口仍为 POST /api/v1/dsh/chat/completions、POST /api/v1/dsh/responses。正常请求原始 Bearer 和原始有效模型正文转发；客户端自报租户或请求用途不决定检查。profile 直连部署内 backend，不经过 Gateway 自身路由。

| 场景 | 结果 |
|---|---|
| 输入 JSON/结构非法或超过支持上限 | HTTP 400，error.code=invalid_request，安全提示说明格式或限制；不伪装成敏感词命中 |
| 输入或非流式输出命中 | HTTP 403，DSH error envelope，error.code=content_blocked，message 为已保存阻断提示 |
| 检查基础设施失败且尚未开始响应 | HTTP 503，error.code=check_unavailable |
| Chat 流式命中 | 一个 finish_reason=content_filter 的终止 chunk，随后 [DONE] 关闭协议；不再发 stop/tool_calls 成功终态或伪造 usage |
| Chat 流式检查失败 | event:error，DSH error envelope，code=check_unavailable，随后结束 |
| Responses 流式命中/检查失败 | event:error，type=error，code 分别 content_blocked/check_unavailable，包含 request_id 和安全提示，随后结束；无正常完成事件 |
| backend 原有失败 | 保留原错误与用量语义，不改成内容命中 |

Chat 终止 chunk 可附加 content_safety={code,message,request_id} 扩展，供新 Desktop 保留原因；旧客户端仍可识别 content_filter 和 [DONE]。Responses error 不是正常带 sequence_number 的模型事件，客户端先识别错误再校验正常事件序列。

Gateway 生成的错误使用 Gateway 请求 UUID；已取得 backend 模型编号则另提供 X-Backend-Request-ID，backend 的正常 X-Request-ID 原样保留。内部事件明确区分两个编号，不从错误显示编号反推模型执行。错误不含命中原文、凭据或未经清理的上游报文。

### 6.4 审计查询与 DTO（backend 提供）

既有 /api/v1/dsh/admin/model-audit 权限、封装和缓存禁止策略不变：

| 接口 / 扩展 | 消费方 |
|---|---|
| GET /requests 及会话、目录查询：has_sensitive_hit、sensitive_direction=INPUT/OUTPUT/BOTH、content_safety_state | 平台组合过滤；BOTH 表示两方向都命中，不是任意方向 |
| GET /requests/{id}：来源、model_entered、阶段状态、命中方向、策略/词库摘要、观察时间、details_status | 平台详情；NULL 状态按来源和是否执行显示未知或不适用 |
| 新增 GET /requests/{id}/content-safety-events：cursor、limit，按 occurred_at/event_id 分页 | 单请求事件明细 |
| 新增 GET /content-safety-events：时间、关联状态、请求编号和游标 | 未关联事实查看，不从事件列表替代主审计列表 |
| /query-readiness、conversation-groups、conversation-tree | 安全汇总版本、更新时间、命中计数及 scan_limited |

AuditRequestMetadata 的 effective_mode、model_result、response_result、usage_settlement、session_id 增加可空支持；audit_status 增加 NOT_APPLICABLE，content_safety_state 单独含 NOT_APPLICABLE，不能与原模型审计状态混用。DTO 是加法及有限联合扩展，旧前端不认识这些状态，必须先兼容发布再开检查。

安全方向和请求汇总可组合；has_sensitive_hit=false 只表示无已知命中，不筛出“已通过”的同义集合。内部 Python 服务提供 ingest(event, verified_source) 和按审计授权的查询；Repository 接收调用方事务，不能经由 Endpoint 调另一个 API。

### 6.5 依赖与破坏面

| 依赖 | 风险和约束 |
|---|---|
| backend profile 的用户/租户响应及本地 DSH 凭据 | schema 变化或目标配置错误使检查不可用；不降级信任客户端租户 |
| user/info、user/tenants、DSH 审计 settings 与租户详情 | 显示标志不独立授权；由既有 DSH 管理运行时校验目标，普通租户管理员不能使用超管专属详情接口 |
| Gateway ACPlus、FileUtil、CustomerConfig | 修改分词或大小写语义会改变全部租户命中结果，必须版本化并回归旧应用 |
| DshRoute 的 X-Request-ID 和错误包 | 丢头或反向代理改编号会产生未关联事实；不能用 profile 编号代替 |
| Chat/Responses 的事件与工具完成语义 | 新事件类型需显式接入；不能按未知事件透传正文 |
| MySQL/DM8、Redis、Celery 及现有审计查询 | Redis 故障有受限直查；SQL 故障显式缺口；worker 故障不伪装目录已完整 |
| UI 规范及 Desktop 工具执行屏障 | 不新增视觉模式；未通过或轮次错误时不执行待调用工具 |

本功能不新增系统二进制、第三方缓存库、消息平台或搜索服务。运行时信任配置、SQL、Redis 和任务执行环境均为现有部署能力。

## 7. 验证策略、可观测和评审

### 7.1 验证层次

- 单元：身份缓存寿命、未命中合并/取消、词库边界、逻辑文本域、UTF-8/SSE、工具参数、两种协议终态；请求状态 36 组合及旧命中保持。
- API/SQL 集成：签名跨语言向量、租户上下文隔离、同事件异载荷、可信身份变化可接收、模型归属关联、事件先到/后到/并发、两侧重启、确认丢失、原 writer 不覆盖安全字段、幂等投影及保留水位。
- 跨仓库 E2E：Desktop 两协议和工具轮次、平台租户配置和过滤、无 Gateway 原功能、关闭开关透传、旧 Gateway 应用回归；不以 mock 或 HTTP 200 代替真实验收。
- 执行这些验证属于后续实现阶段。本轮只检查设计、源码锚点、链接、AC 覆盖和契约一致性。

### 7.2 性能与容量验证

用真实 MySQL、DM8 分别构造百万和千万主请求，每请求 1–3 事件，覆盖租户倾斜、低/高命中率、用户/模型/时间组合、深游标页、长会话、补报和持续写入。记录执行计划、扫描行数、排序、p95/p99、锁等待、索引体积和回填影响，与相同环境现有查询基线比较。

结构门槛为默认列表没有全事件扫描、历史 GROUP BY 或每行事件查询，ACK 不在内存入队后提前返回，事件重复不放大计数。压测数据不足时不能声称容量已经通过；暂不编造在线延迟 SLO，实测后给用户报告可支持的负载和限制。

profile 独立测冷/热、Token 刷新、多副本、Redis 故障下的调用量、额外 SQL 读取和等待；估算 profile QPS≈模型 HTTP QPS×身份未命中率，不能按 SSE 片段计算。缓存命中不能掩盖模型鉴权仍需访问 backend。

容量示例：日 100 万请求×2 事件×1 KiB 约 1.91 GiB/日、57.2 GiB/30 天，未计行、索引、Outbox、副本和备份。此为算术示例，不是当前生产规模或实测压缩率。

### 7.3 手工验收路径和指标

后续测试环境准备两个租户，各一租户管理员、普通用户和一个超管；凭据从测试登录取得，不写进文档或仓库。先经平台 DSH 敏感词控制保存自定义测试词，等待不超过 5 秒，再使用测试 Token 请求两个原有模型入口；响应字段和 tools 按已支持 schema 填写。

~~~bash
curl --fail-with-body -i "$GATEWAY_ORIGIN/api/v1/dsh/chat/completions" \
  -H "Authorization: Bearer $DSH_TEST_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @chat-input-hit.json
curl --fail-with-body -N "$GATEWAY_ORIGIN/api/v1/dsh/responses" \
  -H "Authorization: Bearer $DSH_TEST_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @responses-stream.json
~~~

测试文件为测试阶段现场生成的协议样例，本轮尚未创建。输入命中应无 backend 模型调用并有安全条目；输出命中使用可控模型上游构造跨事件词和工具参数，在审计页确认关联及真实用量。不要要求真实模型随机输出指定词来证明扫描正确。

再断开接收端，生成命中并重启 Gateway，恢复后核对同事件仅一份、命中请求仅计一次；丢弃一次 ACK 验证重复确认。模拟超 30 秒的上游，确认 Gateway 终止续读，backend 用量可能为未知。以另一租户管理员访问策略、请求详情、事件及游标，均不得越权。

指标分组：profile 命中/未命中/合并/队列及延迟；策略版本/缓存年龄/摘要不一致；检查命中/错误/缓冲占用/编译及续读额度；Outbox 待投递数量、最老年龄、隔离数、最后成功；接收冲突/重复/提交延迟；主摘要与会话/树的水位差和 scan_limited。

日志只记录请求/事件编号、来源、策略版本、状态和错误类型；不含 Token、Cookie、正文、命中原词。事件ID、用户、租户不直接作为无限维度 Prometheus 标签，可放受控诊断日志和聚合面板。

### 7.4 AC 承接

| 需求组 | 完整 AC 引用 | 设计位置 |
|---|---|---|
| 入口、独立运行和兼容 | AC-01、AC-02、AC-03、AC-04、AC-05 | §2.1、§3.1、§4.2、§6.3 |
| 租户策略和管理 | AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12 | §4.5、§6.1 |
| 可信定位、缓存和故障 | AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-59 | §4.4 |
| 文本、协议和工具 | AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26 | §4.6、§6.3 |
| 阻断、错误和计量 | AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-57 | §4.6、§6.3 |
| 检查状态与最小事实 | AC-33、AC-34、AC-35、AC-36 | §4.7、§4.8、§6.4 |
| 关联、可靠投递和幂等 | AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-58 | §4.7、§4.8、§6.2 |
| 展示、筛选和汇总 | AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50 | §4.9、§4.10、§6.4 |
| 保留、历史、双库、启停和三语 | AC-51、AC-52、AC-53、AC-54、AC-55、AC-56 | §4.9、§4.10、§4.11、§7.1 |

### 7.5 本轮评审方式

按仓库 sdd-review design 的 24 项清单检查接手所需的现状、决策、坑和契约，并进行 Constitution Check。评审报告另存 design-review.md；“静态设计评审通过”不代表实现、性能或真实环境验收通过。用户确认 design 前不创建 tasks 或业务代码。

## 8. 后续改进与暂不投入

- 在线明细 30 天只用于评估；保留和归档另行配置确认，不默认缩短现有证据期。
- 大数据分区、外部搜索、跨期统计和导出在执行计划或容量实测达到瓶颈后再评估，避免同时引入双库分区兼容和运维复杂度。
- profile backend 本身约 8 次读取的去重优化不在本期；不为了 Gateway 缓存修改 F110 认证真相。
- 跨多个实时模型通道的统一内容安全契约、按用户/部门覆盖及语义审核需独立需求，不挂接到本功能的默认行为。
- 多文本域交错的队头阻塞、JVM 内存放大、长尾补报与大型租户回填均是待实测的限制，不能作为“已有索引/有缓存所以没有风险”的结论。

## 源码与规范锚点

以下为已存在的核查入口；新增文件仅在 §4.3 标为拟新增，不制造不存在的源码链接。跨仓库路径均相对其仓库根。

| 仓库 | 路径 / 入口 |
|---|---|
| BiSheng | [models.py](../../../src/backend/bisheng/dsh/api/endpoints/models.py)、[DshRoute](../../../src/backend/bisheng/dsh/api/responses.py)、[access_runtime](../../../src/backend/bisheng/dsh/access_runtime.py) |
| BiSheng | [审计写入](../../../src/backend/bisheng/dsh/domain/repositories/model_audit_write.py)、[writer](../../../src/backend/bisheng/dsh/domain/services/model_audit_writer.py)、[状态](../../../src/backend/bisheng/dsh/domain/schemas/model_audit_status.py) |
| BiSheng | [请求查询](../../../src/backend/bisheng/dsh/domain/repositories/model_audit_queries.py)、[会话投影](../../../src/backend/bisheng/dsh/domain/repositories/model_audit_conversations.py)、[目录构建](../../../src/backend/bisheng/dsh/domain/repositories/model_audit_tree_build.py) |
| BiSheng | [HTTP 租户中间件](../../../src/backend/bisheng/utils/http_middleware.py)、[HMAC 算法](../../../src/backend/bisheng/sso_sync/domain/services/hmac_auth.py)、[管理 API](../../../src/backend/bisheng/dsh/api/endpoints/model_audit_admin.py) |
| Gateway | src/main/java/com/dataelem/gateway/filter/{SensitiveWordsFilter,CustomResponseFilter,LicenseExpiredGlobalFilter}.java；utils/{FileUtil,HmacSignatureUtil}.java；config/{CustomerConfig,SpringCustomConfig}.java |
| Desktop | packages/dsh-desktop-enterprise/{openai,responses,error-copy}.js |
| 平台 | [DSH 导航](../../../src/frontend/platform/src/pages/DshPage/sections.ts)、[审计 API](../../../src/frontend/platform/src/controllers/API/dshModelAudit.ts)、[审计类型](../../../src/frontend/platform/src/types/dshModelAudit.ts) |
| UI 规范 | [规范入口](../../../src/frontend/packages/ui/docs/index.md)、[组件总览](../../../src/frontend/packages/ui/docs/components/index.mdx)、[Checkbox](../../../src/frontend/packages/ui/docs/components/checkbox.mdx)、[Switch](../../../src/frontend/packages/ui/docs/components/switch.mdx)、[Tag](../../../src/frontend/packages/ui/docs/components/tag.mdx) |

## 修订历史

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-10-23 | 初版设计；承接已确认的 59 条 AC | 用户确认 spec，要求产出并评审 design；尚未实现 |
| 2026-10-23 | 自审修正管理授权探针、专用代理生命周期和会话组合条件口径 | 静态代码与契约复核；保持已确认需求 |
| 2026-10-23 | 撤回固定分页窗口与跨事件身份冻结两项复审意见，同步 spec、接收及分页契约 | 用户明确沿用既有分页并接受毕昇可信身份变化；未进入 tasks 或业务实现 |
| 2026-10-23 | 回传复用现有 HMAC 密钥、签名头及规则；补明 profile 的服务端验证和返回字段 | 用户确认使用相同密钥配置并询问 profile 定义；仅同步设计及评审文档 |
| 2026-10-23 | 用户确认 design，进入 tasks 拆解及静态评审；补明既定 v4 约定的依赖与局部 Provider 接线 | 用户明确仅产出任务文档，暂不修改业务代码；主决策与对外接口不变 |
| 2026-10-24 | Wave8完成事务投影、Profile有界合并、管理入口和Unicode扫描；同步实际边界与后续唯一竞争恢复 | 集中回归通过，仍不代表入口接线或双库验收 |
| 2026-10-23 | Wave 1–4 基础设施、DTO、HMAC/reducer、Gateway 边界与 Desktop 文案实施细节同步 §9 | 用户授权实现；测试证据及未执行门禁单列 implementation-verification，不代表全特性交付 |

## 9. 实施细节同步（2026-10-24）

Wave 1 按已批准执行计划补齐：新事件 ORM 同时进入显式租户模型登记，避免 create_all 发现与首次租户注册快照顺序不同而漏过滤；组/树响应 DTO 在既有查询 schema 文件声明，后续任务负责接线。阶段状态与阶段版本按 §6.2 固定，Java/Python/TypeScript 保持一致。Gateway 大字段使用 MySQL MEDIUMTEXT / DM8 CLOB，UTC 微秒时间，不沿旧处理器写本地时区。

F111 Alembic revision 只扩展既有表；新增整表继续由模型发现创建。引用既有单 head，约束检查复用大小写兼容的 schema helper。downgrade 默认拒绝破坏性收缩，不在迁移中按现有数据状态分支；应用回退保留事实，空库收缩由独立运维停止写入、判空和双库演练完成。基础设施一致性任务增加持久化迁移回归测试；这些补充不改变 spec AC、共享 HMAC、身份和分页取舍。

Wave 1 真实回归补充 T133/T134：审计 metadata 不能把新增 DTO 字段名直接当 ORM 属性，需显式映射阶段快照和来源别名；未验证明细可用性时只返回未知或待确认，不为命中标记伪造明细可用。Platform 旧标签接收可空状态时使用既有 UNKNOWN 文案，最终外部条目语义仍由原定 UI 任务补齐。Gateway Outbox 显式含 tenant_id 与 event_version，source_id 最长 64；关闭策略的词源/自定义词/回复/摘要可空，两库同义，enabled 后由策略服务校验有效词库。

Wave 3 固定的后续接口：HMAC helper 的 compute_hmac_signature/compare_hmac_signatures 与纯 reduce_safety(existing,event)；Desktop 导出 CONTENT_SAFETY_ERROR_COPY 和 resolveContentSafetyError，固定三语与租户安全提示分开。Gateway profile 身份的 expiresAt 允许未知（null）：可信 profile 仍可用于本请求，缓存必须拒绝未知截止时间，不因不能解码 Token 推断身份或伪造有效期。可选会话提示清洗后再生成有界事件，提示问题不抹掉核心安全事实。

Wave 4 已实现上述 helper/reducer 与五个 Gateway 边界客户端/存储及 Desktop 归一化模块。profile 与代理持有专用 HTTP 连接生命周期，禁止自动重试、重定向和凭据日志；身份/策略缓存仍由后续任务实现。策略存储以 tenant_id 与 version 的条件写执行 CAS；Outbox 使用条件租约认领及 owner 校验 ACK，仅更新投递列，快照不可变，事件阶段版本只随状态变化递增。未知 Token 到期不缓存；profile 不返回 session_id。可选会话提示无效时只丢弃提示，核心事件照常生成。SQL 原子性和两库执行仍需真实环境验收，当前本地 Mockito 不作双库证明。

事件 Repository 只在调用者事务内 flush，不自行 commit 或在失败的 begin 块里 rollback 后继续查询。唯一键竞争的恢复由接收编排（T030）退出整个失败事务后，以新 Session 重读和重做完整幂等合并；不能只保存事件而漏掉同事务主摘要。事件哈希覆盖原始 event 的规范 JSON，DTO 默认填充或可选提示清洗不改变原始载荷摘要。

现有 ACPlus 的 AC.update 失配链仅回退一层再查根，实测会漏多层重叠后缀（words=[acbcc,bcx,cca]，text=acbcca 漏 cca@3）。DSH 匹配器复用 ACPlus 的扫描能力，在本功能构建环节按完整失配链建立跳转，覆盖该回归；不调用旧 filterNormal 或改变旧应用过滤器的副作用。

T022 事件存储已实现严格租户读、幂等查询、保留闸门和调用者拥有的 flush。UUID 存储统一小写以消除数据库文本排序差异，载荷哈希仍依据原始 wire 表示；接收 Receipt 回显请求 event_id。保留水位使用设置行锁与清理协调，其同租户并发开销列入后续真实库压测观察，不以单元测试证明容量。

T058 身份缓存已实现：L1 正/负合计 LRU 最多4096条，Redis值最多4KiB且仅含六个身份/时间字段；重复JSON键、未知字段、未来验证时间和超长有效期均拒绝。Redis同步操作在 boundedElastic 执行，端到端deadline和单调时钟持续校验，不从完成时刻重设寿命；超过1秒墙钟/单调偏差时拒绝新检查。T060已增量接入本机有界合并和跨副本owner租约；真实多进程验收仍待后续任务。

Wave 6 已完成 T022/T058/T064；Gateway13类195测试及真实隔离Redis端口验证通过，证据边界见implementation-verification。候选编译不占用已提交版本键，CAS后不再竞争编译资源；恰20项命中不标截断，观察到第21项才标记，收集始终有界。AC局部terminal output链接避免每字符扫描非终端失配链。未接线入口、回传、页面或后续owner fencing，不宣称全特性交付。

策略管理补齐：settings和capabilities均携带明确目标tenant_id并实时走同一管理授权。AdminClient在既有实时链成功后返回/user/info校验的可信用户编号，供updated_by使用；旧Void授权入口保持兼容，不从body/header自报操作者取值。Origin允许范围复用bisheng.homeUrl规范化的scheme/host/effectivePort，配置路径不参与比较；写请求缺失/多值/null/含路径/假前缀Origin拒绝，homeUrl无效明确不可用，不新增配置或后台RPC。该返回契约补齐列为T135，未变更已确认权限策略。

T069 冻结后续扫描边界：newDomain(label) 创建独立请求内逻辑域，feedDecodedText(domain,text)/completeDomain(domain) 返回不可变 Outcome(blocked,checkedThrough,observedUnits,hitCount,hitCountTruncated,ruleRefs)。水位采用绝对UTF16单位，与AC索引兼容；尾部按Unicode码点保留，不拆补充平面字符。不同消息/choice/工具不能拼词，外部请求的Domain拒绝；阻断不再开放、完成幂等。增量UTF8与JSON解析属于协议适配器，scanner接收已解码文字并安全处理回调间拆分的代理项。

Wave7完成前置测试与T135可信操作者返回：管理授权先从既有/user/info的user_id读取严格正int64，再通过全部实时目标校验才返回AdminIdentity；旧authorize继续then()。投影Repository接口冻结merge_audit(session,event)返回主行或None，先有同事务已保存事实，不提交、不ACK、不自行新事务重试；可信身份变化仅影响可关联性，不能覆盖原模型归属。

Wave8：merge_audit仅合并同事务已保存事实，原主行归属优先；未确认backend编号或身份/模型不匹配保留UNASSOCIATED，不猜关联。主摘要和事实关联均显式tenant/id/version条件更新，started_at固定，安全变化独立置dirty且不写模型用量。T030需区分追加冲突与主行全局唯一冲突：新事务按严格租户仍不可见的冲突不能通过bypass寻找其他租户，保存事实为未关联，避免无限重试。

T070扫描的错误域不可重新feed或complete成PASSED；阻断域稳定返回同一有限摘要，完成幂等且禁止重开。管理入口在可选策略服务缺失时仍可报告available/configuration_ready=false和真实部署开关，读取/保存返回503，不伪造已关闭策略。完整条件化Spring接线由补充T138/T139验收。Wave8集中测试与Redis小验证仅证明各模块边界，完整模型链、跨进程租约、MySQL/DM8和容量均保留后续验收。

Wave9冻结协议适配器内部边界：构造接收CompiledPolicy与DshSafetyProperties，accept(byte[])/complete()/cancel()返回有序完整事件List<byte[]>，inspectNonStreaming(byte[])返回正常原bytes或明确错误正文，state()/outcome()提供有限安全结果。可信request_id后续由请求管理器注入，不生成新的业务编号。输入沿实际DSH schema：Chat工具arguments可为任意合法JSON，Responses必须对象；二次解码后独立扫描键和值。外部事件深度16不扩为模型工具参数的限制。历史和输出Citation.title属于可读文本，URL独立opaque；response.failed/incomplete中的可读输出快照仍检查，普通错误诊断保持既有失败语义。

Wave10已完成原生writer提升和三种适配器：输入严格UTF8/JSON并保留原bytes，HTTP400/invalid_request遵循§6.3；Chat任意JSON工具参数与Responses object参数保持当前backend差异，不给模型JSON套外部事件深度16。输出队列按完整原事件绑定域水位与工具屏障，Chat终态content_filter+[DONE]，Responses明确type=error；正常usage含nullable/detail字段不归一化。工具参数增量自身与每次完整快照均检查，不能由安全done覆盖危险增量。进度快照先独立检查，再以UTF16长度/SHA256确认既有前缀，仅新后缀进入原域；不能绑定的变化拒绝。结束冻结有限Outcome并释放持有正文/条目/队列容量，Chat工具名称只保存非空观察标志。请求编号注入、上游所有权、全局配额和入口接线仍由T086/T139等后续任务完成，不代表特性已端到端可用。


Wave12 backend实施对齐：EXTERNAL_SAFETY的模型状态固定NOT_APPLICABLE，纯状态派生及停滞worker在activity/facts/原文读取前排除外部条目，保留原批次用于cursor；原生MODEL规则不放宽。状态刷新独立比较has_sensitive_hit与group_indexed_sensitive_hit以置dirty。请求到会话投影使用既有行锁，同事务按request的state_version+safety_projection_version+pending条件完成，Group写限定tenant/key及前次三计数；SELECT继续严格租户自动过滤。未关联只清pending、不设置已计入水位，后续原生关联可再投影。每次默认100、允许1–200个，单项失败新事务恢复，游标返回真实批次进度。条目、异常、命中分别差量计数，安全变化同事务递增safety_summary_revision；跨进程持久领取租约仍由T050的worker边界实现，未在Request上增加新租约列。


Wave12 Desktop实施对齐：Chat收到content_filter即结算明确错误与安全文字/推理前缀，return使SSE reader取消释放，不再等待DONE或允许坏尾帧/EOF覆盖确定命中。Responses transport在普通sequence校验前保留flat/nested安全错误及HTTP结构化错误，避免pi-ai包装成普通上游错误；工具block-end等待整轮正常done，并核对明确completed状态、wire完整object JSON及SDK实际对象/argumentsError。参数无效先记录，到正常终态才拒绝工具，后到安全错误仍优先；max-tokens保留安全文字、由既有BlockAssembler丢弃工具，不制造成功或自动重试。实际插件pi-ai为0.87.1；既有max-token replay hash不匹配时降级可见文字重放，不改写其hash为可匹配未执行工具的值。实际runner屏障及locale当前显示入口接线仍留T118/T117。


T086请求管理器每副本唯一实例持有16检查/8续读槽及64MiB编码预算；Chat原事件与当前行存在两份编码缓冲，对待检查字节保守预留两份，原事件放行后转为单份delivery、退回额外份。上传先完整32MiB限长，idle与总截止复用既有注入I/O预算，不增加YAML。客户端通道为按demand交付的有界FIFO，慢或未订阅时限到停止持有；completion仅观察，不拥有上游。命中先冻结BLOCKED与check→drain所有权再回调安全prefix，避免同步取消降级/泄漏；独立hit起算30s及剩余响应字节，终止清空adapter真实引用和所有订阅/额度。DECISION/FINAL/DRAIN幂等串行调用既有boundedElastic Recorder，只保存有界快照；正常响应bytes不重编码，Gateway合成错误root.request_id固定为gateway UUID；已取得有效backend编号则另提供X-Backend-Request-ID，正常backend X-Request-ID与正文原样保留；未知backend编号仍留空，不虚构关联。


T117接线复查补齐：Host Node的navigator不能代表renderer当前语言，现有failureMessage对两个安全码直接显示failure.message，不查询新字典。增加T136前置测试/T137两adapter可选同步localizeContentSafety(code,defaultMessage)回调后，T117的client/index才负责真实locale注册/当前语言构造/卸载，保持每任务最多两维护文件。仅CONTENT_CHECK_UNAVAILABLE已知Gateway固定英文及无自定义提示的fallback调用本地化；CONTENT_FILTERED任何非空安全租户提示保持，即使恰等固定英文。普通账号错误保持原行为；回调非法返回/异常不能覆盖明确安全分类。未提供回调保持兼容。此补齐不改变需求，不将只注册copy当已接通。


Wave13查询内部端口冻结：ContentSafetyQueryRepository(session).request_events(request_id,cursor=None,limit=20)返回items/next_cursor/details_status；unassociated_events(now=None,start_at=None,end_at=None,user_id=None,model_id=None,cursor=None,limit=20)按request_started_at默认7天、最多31天，显式筛选和租户绑定cursor，不冻结默认相对窗口。事件详情使用已声明索引的本地主键id作同时间tie-break，与对外event_id区别；只分页查经授权的request关联事件。主列表批量查真实用量/姓名，不查事件；known safety摘要的list details_status可保守PENDING，详情端区分AVAILABLE/PURGED/UNREPORTED。INPUT过滤包括双向命中，OUTPUT同理，BOTH要求同一条请求两标志都为真，不拼会话不同请求。

编号复核按原§6.3补正：Gateway生成安全错误body.request_id始终为Gateway UUID；流式正常响应已发的backend X-Request-ID保持，另携带X-Backend-Request-ID。Desktop只对明确归一化安全错误优先显示body的Gateway编号，普通账户/额度错误仍沿旧header优先。T086曾误沿backend编号的实现已修，T136/T137补齐对应消费回归。


Wave14接收与查询实施对齐：接收端在既有有界阻塞池、严格tenant scope中最多尝试三个完整新事务，原wire事件哈希先于DTO清洗；Receipt标量在Session附着时取得，COMMITTED仅在成功提交及退出Session后返回。首次merge唯一键冲突后严格重读并重做完整归并；当前租户目标可见也不能证明全局source/Gateway绑定可用，连续两次merge冲突时，第三个新事务仍通过追加幂等、哈希与保留闸门，只保存未关联事实。不得bypass探查外租户、伪造关联或吞掉append/commit失败；正常可见并发winner继续首次重试完整归并。调用方超时不ACK，底层已开始事务可稍后完成，重试仍幂等。

T038主列表按页批量读取Call、RESPONSE_FAILURE证据及姓名，无逐条事件查询；详情只输出白名单有限元数据，不含payload_hash、正文或tenant信息。事件按时间/id升序limit+1，游标绑定租户与全部显式筛选；严格验证游标对象、时间及UUID类型，非法输入统一查询错误。空续页只要同请求仍有保留事实便为AVAILABLE，不误报PURGED。请求列表details_status仍可PENDING，由按需详情请求确认。

T044沿既有树构建的同一state锁事务维护结构、模型摘要、安全摘要三水位。COPY记录会话own命中数，AGGREGATE沿原Path累加branch命中数；构建期间任一水位变化即废弃未发布代并重启，PUBLISH同时发布三水位。租户补扫、READY/CLEANUP和progress均识别安全水位未发布；命中dirty仅由已有请求到会话投影递增一次，不新增树或改变模型异常计数。

T088入口预检查使用Spring PathPattern与专用路由一致的匹配语义，仅两种POST协议；编码字符或matrix参数等同一路径仍进入managed检查并由后续路由使用固定协议目标。若解码后等于目标但PathPattern不匹配（如编码斜杠），部署开关开启时在catch-all缓存正文前返回400 invalid_request；关闭保持既有行为。预检查在正文订阅前取得可信profile和租户策略快照，部署关闭透明；租户关闭保留独立模型链。仅观察原401/403、至多64KiB严格JSON的已知身份失效错误，保留原buffer/flush边界，不因cache失效失败改写响应；不把配额、席位、许可或普通鉴权失败归为身份失效。实际模型所有权接管及条件Bean仍由T090/T139完成。


组装任务补齐：T098实际声明仅telemetry与Dispatcher，不能隐含跨文件Configuration。新增T138容器前置测试/T139单一Configuration实现，位于Wave27/28；按既有构造端口真实组装和生命周期验收，完整配置但检查关闭仍支持策略管理及历史投递，缺配置不影响旧模型。没有新增需求或独立配置体系。

接收端部署租户范围澄清：现有SSOSyncConf不含source租户白名单，source_id仅幂等/诊断。本期共享HMAC认证本backend的Gateway服务；multi_tenant.enabled=false只允许既有DEFAULT_TENANT_ID，启用时覆盖本backend租户作用域，事件仍按严格单租户处理。不得将自报source_id变为扩权开关，不检查用户Token或租户当前active状态以拒绝历史事实；未允许范围403。签名只对固定接收path，不含query；HTTP适配传入request.url.path，直接传含query的非法path拒绝。

T032来源范围拒绝使用common/errcode/dsh中唯一认证错误类型的显式tenant_forbidden()工厂，沿用已登记业务码与ClientCode，仅返回实例的HTTP状态403；类默认及原签名错误保持401，缺配置/依赖503。不借用模型未授权、租户当前不可用或工具权限错误，不新分配业务码/翻译键；T032增加该既有文件为第二目标，仍保持每任务两文件上限。运行时错误码唯一性检查也包括继承的Code，不能用另一个同码子类绕过。


T117当前语言接线：client使用现有LocaleRuntime独立namespace注册两码zh/en/ja固定文案；若目录没有ja，用已有addLanguage登记ja并fallback en，仅持有自己的disposer。只保证本安全文案三语，其余既有界面沿词典fallback。同步subscribe将固定copy写入同源session cookie，名称含完整authority（Cookie本身不隔离端口）；载荷为{owner,messages}，随机UUID owner仅用于卸载所有权，不是身份/鉴权字段。按copy去重发布，卸载仅删除仍由本实例持有的完整值，避免同值双窗口误删新publisher。Host在已认证connection/request公开waterfall内严格校验唯一cookie、2048编码字符上限、精确结构及两码SSOT白名单，只把messages投影入请求AsyncLocalStorage。adapter同步回调读取该scope，不建立全局last-language缓存、不转发Cookie或文案到broker/backend，不改变分类/请求编号/tenant自定义提示。

该实现已用真实LocaleRuntime、认证Host入口及实际注册adapter验证，GUI为独立Electron有限范围原错误消费组件显示，不等同完整应用启动或Session.prompt/Agent排队链。原生工具执行屏障继续T118，入口/卸载回归由新增T140固化；队列followup的语言scope继承作为T118联动观察，不据直调adapter探针宣称已验证。


T032实现端口：verify_source(raw,headers,method,path,now=None)同步返回frozen VerifiedSafetyEnvelope(raw_event,verified_source)，不读SQL、不消费HTTP流；上层HTTP适配负责限长只读一次。先限制原始64KiB、固定POST/path及共享key，再对唯一签名头常量时间比较，随后严格UTF8/JSON（重复键/浮点/NaN拒绝）与Envelope DTO、±300秒和部署scope校验。默认get_content_safety_service仅注入惰性Session工厂，不加载模型runtime或SSO登录能力；get_settings在认证时才读取原配置。任何DTO清洗/默认均不回写原event，后续hash仍覆盖原始事实。


T090真实传输内存复核：Spring writeWith的首帧屏障在writer零需求时预取一个DataBuffer，先用0字节prelude承接可避免其缓存实际模型字节；该prelude不改变对外body。更深层实际Netty写入缓冲仍可能在HTTP未完成时持有整个非流式响应，因此不能在manager downstream.onNext返回时把HTTP持有期排除出64MiB全局额度。T090增加Manager为第二生产目标，原T089单测试文件独立维护回归；订阅正文前显式取得HTTP writer租约，已交给transport的字节从delivery计费转为writer-held，直到一次实际writeWith结束（成功、错误或取消）才归还。保持单次写响应及T088一次完整错误观察，不逐帧多次write，不依赖Netty内部API/反射。

保守计费包括本响应已发送完成但writer整体尚未结束的编码字节，最多沿既有32MiB响应限制；会减少长流并发余量，优先维持全局上界。初始16检查/8续读不等于承诺16个满额长流同时可用，吞吐与堆占用仍由T128实测；无新SLO。旧直接manager.body消费者沿原消费归还，HTTP路由必须登记租约，取消/写前失败均幂等释放，确定命中后的独立drain继续保留。


T090最终writer清理：guard只负责沿既有ioTimeout终止写入信号，不能在timeout/cancel时立即退款。Mono.usingWhen的error/cancel清理通过公开Spring native response与Reactor Connection.dispose/onDispose关闭实际下游，并等事件循环下一turn完成缓冲释放后close租约；成功写完直接close。租约开始拒绝clientGone，abort标志及优先订阅stopped覆盖begin→shutdown→guard间隙。模型owner完成不是拒绝HTTP writer的条件，确定命中的独立模型续读不随下游取消而中断。真实慢TCP timeout/socket-close/manager-close已验证32MiB缓冲释放后额度归零，吞吐/heap与完整链验收仍属后续任务。


Wave18 HTTP/配置落地：content_safety_events仅注册精确POST，query前拒且不读流，原request.stream累计最多64KiB，不信Content-Length且不改_receive；原raw/Headers/METHOD/url.path验签后才构造惰性service，直接返回ContentSafetyReceipt。已登记业务错保留状态，断连/取消向上传播不假ACK；其他依赖错误仅记录类型并503，不含正文/SQL。两份Gateway YAML的两精确POST路由order=-10、URI引用既有bisheng.bisheng-api-url，无CacheRequestBody；Path显式matchTrailingSlash:false与预检查一致。默认enabled:false，backend-namespace/source-id留空由启用时既有Properties校验，不增加密钥或codec上限。普通及DM配置继承与关闭透传由真实Gateway路由工厂/默认Netty及Profile/Proxy验证；完整Spring组件组装仍T139。


Desktop队列语言实施修订：真实公开SessionController.queue证明后续请求沿首轮AgentLoop driver继承ALS，单独connection/request scope不足以代表queued请求语言。宿主使用现成inbox inserted/claimed/discarded公开事件：按session+稳定Message.id捕获入队时固定copy，insert仅pending，claim才晋升当前turn，discard/匹配turn-end/agent dispose及unload回收。display-only旁路不进入Message/source、持久日志、attribution或模型请求。两adapter通过可选同步contentSafetyFormatterFor({sessionId,purpose})在实际stream开始取得冻结formatter，未来turn/入队不改在途提示；无factory沿旧localizeContentSafety，异常/非法值安全fallback，不影响普通模型。无session及title/compaction沿发起时请求ALS；原tenant提示/分类/编号不改。T144/T145与T146/T147分别先测试后实现；不引入第三方patch或全局last-language。


Wave20入口实施：CustomMiddleware只在既有DSH_CREDENTIAL_ROUTES登记精确POST接收path，复用原六类上下文清理/finally恢复，不改TENANT_CHECK_EXEMPT_PATHS或引入prefix bypass；HMAC/严格事件tenant及SQL仍由各自现成边界完成。旧SensitiveWordsFilter和CustomResponseFilter在最前仅依据可信Boolean.TRUE MANAGED_ATTR返回原exchange给chain，不读旧cache/包装响应/调用filterNormal/原文日志；用户Header不授予标记。普通DSH路径原本已自然避开旧URL分类，新增guard为显式隔离与内部改写防御，旧应用命中/BlockRecord行为不变。


T147落地约束：入队时缺少合法显示提示同样捕获为显式missing，claim不沿旧driver ALS补值；active存在但copy缺失时不生成formatter。index只接新factory，不同时交旧localize回调，防止undefined触发legacy callback复活旧语言；无session/辅助调用由factory本身读取发起请求scope。所有当前语言旁路按session+Message.id/turn匹配并回收，已取得formatter不随生命周期变化。Host侧取固定copy快照，无模型/Message/source字段或第三方修改。


Wave22 Gateway实施：ContentSafetyEventClient按订阅重签sent_at，原Outbox payload经UTF8及严格JSON校验后原字节嵌入envelope；固定既有backend origin+接收path、共享SSO签名helper/key/header。每次专有连接不重定向/自动重试；<=3秒绝对预算扣本地包装和HMAC耗时，覆盖连接、headers及完整有界严格回执。只有200/COMMITTED/同event_id且结构合法才返回ACK disposition，Client不更新Outbox；永久拒绝隔离、其他失败退避由后续Dispatcher负责，Bean由T139条件组装。PathRate仅精确DSH POST或可信Prepared协议跳旧body/日志，默认关闭也同样；已配置规则继续tryAcquire原canonical completions/responses key，编码与matrix等价路径同时匹配原配置或相同canonical配置，避免别名绕过已有限流且不记录matrix私密值。旧方法、邻近路径、普通应用及HTTP200/body429合同不变。


Wave22 backend落地：主请求Service沿Repository.page(now=...)计算窗口，不注入隐式筛选；原管理授权→profile_scope→仓储链保留。新增请求事件与仅未关联事件分页端点均沿同管理授权、no-store及平台响应封装，不添加Gateway RPC；列表保持摘要，单详情才按需取limit1事件判断AVAILABLE/PURGED/UNREPORTED。readiness通过现有tree_state/tree_progress组合已发布安全水位与真实published_at，0是合法已发布版本；未发布、落后/dirty或失败明确未就绪。


T102 Platform接口接入：经原wrapped request读取Gateway snake-case ResultData解包，保留preserveError供409识别且不自动重试；capabilities明确不可用与404/network/业务失败区分。GET/PUT使用原同源身份、tenant参数、AbortSignal及no-store，写入只投影可编辑字段。事件分页沿backend端点校验有限白名单元数据、nullable字段和decimal int64身份，conversation按256码点校验；旧审计缺安全字段保持undefined，不制造PASSED/false。组/树转发三项安全筛选包含false，模型审计二态筛选仍沿原DTO，不混内容六态与NOT_APPLICABLE展示语义。


Wave24目录查询实现：会话与树的时间、用户、模型及安全条件通过同一关联Request EXISTS核验，正向安全汇总仅作已就绪候选优化；筛选内未实际计算命中数保持null，全会话计数与筛选范围独立。安全汇总仅在当前发布代、修订一致且无本租户待索引/失败时就绪，已发布版本0有效。组页新增一次有界CASE/EXISTS就绪查询，子查询显式关联State.tenant_id，其他租户待处理记录不降低当前租户就绪状态。Repo可选now保留旧内部兼容；实际API时钟接线由T152/T153配对实施。

Wave24持久回传调度：Dispatcher独立SmartLifecycle，每秒单轮、有限并发16与最多100条批次，轮次UUID owner防同实例ABA。发出和结果写回均检查原租约，最终由Service的SQL CAS确认；仅成功隔离持久写后告警，无合法COMMITTED回执不ACK。1秒至5分钟指数抖动重试；每分钟至多一页ACKED/acked_at七天清理，MyBatis方言分页不COUNT并以相同状态/时间守卫删除。close仅取消本实例订阅，不能中断的SQL不新增周期工作；真实驱动超时与双库行为留T120。Bean接线仍由T139负责。


T153实际组、树及组内请求Service现均向既有Repo查询传self.now()；默认范围在Repo计算且不写显式筛选fingerprint，下一页时钟推进仍接受，显式条件与租户变化仍拒游标。历史location及parent定位保持不加默认窗口。两旧固定NOW构造记录的HTTP测试仅各自注入查询clock，不改变全局运行时。


Wave24 Platform实现：设置页独立v4 QueryClientProvider与目标tenant查询键，Checkbox草稿及原子保存，版本冲突保留草稿、刷新仅更新expected_version后显式重试；切租户卸载旧表单且旧mutation不污染新租户。权限沿原实时后端准入，不增加403业务分支。检查关闭/能力不可用/读取失败有独立呈现，不制造PASSED。安全三筛选保留false/BOTH交集，默认相对窗口仅作提示，显式双端>31天禁搜索。新Card最多3个Tag，模型四轴与usage继续独立，EXTERNAL_SAFETY或未进入模型无原文入口。事件详情仅展开后分页读取，PURGED保留原主摘要，所有值React纯文本；失败重试记录准确attemptCursor，刷新失败不误跳续页。

共享UI接入仅补本仓workspace本地依赖，不升级现有第三方闭包。Platform尚未全站采用共享主题，故新功能通过Vite从公开tokens/preset即时生成作用域CSS；普通规则限定.dsh-content-safety，主题顺序/触屏规则保留，keyframes命名隔离，不加全站preflight或修改共享库样式。旧平台root --radius与其他utility保持原值，新UI仅作用域内用landed Button/Checkbox/Textarea/Tag。


T107请求页面接线：安全筛选与nullable模型事实经原API不作二次推导；刷新只用applied查询并清游标/展开，未提交draft保留。请求hook把结果绑定query对象、revision、groupKey；effect启动前的新scope首render不展示前次page，AbortSignal及迟到结果双重隔离。目标租户变化以key重建整个请求页面，目录/筛选/分页/展开状态不跨租户遗留。没有新增HTTP、全站状态库或客户端假PASSED/usage0。


T098有限诊断实现：固定Counter16/Gauge13/Alert5，内存仅枚举及标量，快照不可变、累计计数饱和、不保存异常/身份/正文。未知未采样gauge不报健康0；最后成功是历史事实，ACK或数据库样本逆序到达均只取最大提交时间。真实Dispatcher只在持久SQL成功后计ACK/重试/隔离，CAS0记租约失效。原7参构造为noop兼容。独立每分钟statsLoop在boundedElastic后台固定4状态COUNT/MIN/MAX元数据采样与安全日志输出，正常与告警分INFO/WARN；不在模型请求或投递轮次加stats SQL。采样实际任务持有slot至SQL及export结束，订阅取消不释放仍运行任务的slot，慢SQL/日志导出不拖原投递循环。固定4个返回状态不代表数据库扫描CPU有界，实际索引/EXPLAIN/驱动timeout与远端存储pressure测量仍须后续环境验收；其它组件真实观察接线由T157–T164完成。


T104管理入口：沿/dsh现有准入/浏览器配置与URL tab导航增敏感词控制；子租户管理员按真实授权链可编辑自身leaf_tenant_id（旧身份fallback tenant_id），global super才目录选择目标。leaf显示名与编号一致，身份标识变化重建面板。首次打开配置才取数；同DSH页切tab仅hidden保留目标与草稿，切回不丢输入或自动保存，遵守Tabs规范。部署或management关闭卸载业务表单。新增tab使390px溢出由旧5tab23px扩大到117px，已仅加TabsList外滚动容器收口，无全局组件视觉变化，键盘可达最后tab。真实账号授权仍由Gateway实时backend链核验，不信页面角色。T108组件接收可选父进度，T109既定Panel源传progress并接未关联页面，缺进度只报准备中，不按0计数假就绪。


T167扫描端口：既有tree_pending_tenants可选include_group_pending默认False，旧调用不改变；内容安全Worker使用True，将已完成hierarchy但仅group_index_pending的后到安全事实纳入租户候选。仍以Tenant目录驱动相关EXISTS、只返回100个keyset编号、包含停用/归档，不扫描无dirty的RUNNING模型租户，不在Worker内写SQL或拉事实正文。


T158身份诊断接线口径：HIT为实际成功L1/共享身份返回，MISS为一次真实profile订阅，MERGED为已有job额外准入等待者；负缓存拒绝不充成功命中或重复物理错误。profile latency在物理成功/失败/取消结束时采样，不含随后Redis发布，同次终止仅观察一次。Verifier从原锁内active/queue读标量，不按等待者cancel虚增可用槽。旧构造noop兼容，T139注入同一Telemetry；不新增profile/Redis调用、滑动TTL或更改身份/错误优先级。


T162请求诊断：检查命中沿真实DECISION一次计数，后续DRAIN不重计；CHECK_ERROR独立于模型原业务错误、普通取消/关闭及SQL记录失败。bytes/check/drain沿原预算锁读取真实全局状态，HTTP未结束传输所持bytes仍保留。RECORDING_GAP仅原缓存persist失败点一次增量并保留固定告警；不改变模型响应、订阅数、用量或错误优先级，旧构造保持noop兼容。


T160策略诊断：缓存年龄复用既有单调采样点及固定validUntil，不新增探针或延长L1/Redis有效期；编译active为原Semaphore真实已持有permit，更新与采样同锁避免旧样本覆盖新状态。固定busy/node/weight容量拒绝一次、输入400/413仍原语义，摘要不一致在实际拒绝边界一次告警；旧构造noop，生产Redis适配构造将同Telemetry传内部matcher。T050沿既有DSH Beat配置加入周期dirty扫描，所有任务事实与持久readiness复用既有API assembly，不新增模型运行时接收密钥依赖。


T170 → Platform开发预优化须保留共享UI的包内依赖图；实际锁定的UI merge1.14与Platform merge2.6并存，Vite5按裸包名合并会删除UI语义字号类。optimizeDeps.include仅预编译@bisheng/ui，生产Rollup保持原包边界；不升级全站依赖或用业务样式覆盖设计组件。验证同时包含实际dev DOM、Platform原cname及生产三语合成预览，不能等同账号E2E。


T052/T054 → 明细清理必须显式include_audits=False：即便租户已有另一次主审计cleanup_before及续跑游标，也只删本次明细窗口，保留主摘要和全部主清理checkpoint/cursor。主审计清理命令独立提交水位后才分批继续，默认不产生自动保留期。


T175 → 两个事件请求UUID的显式筛选先校验完整UUID并lower，cursor绑定同一规范值；数据库列保持索引等值比较，不依赖MySQL常见ci collation，也不改用户已接受的默认相对时间窗口。


T173 → Gateway全局legacy null serializer与新严格契约隔离：Outbox copy后的私有provider使用标准JSON null；DSH capabilities digest在局部DTO显式标准null。全局旧应用JSON配置保留，接收DTO与Platform parser不允许空串替代null；回归必须消费真实SpringCustomConfig mapper/codec，不能只测new ObjectMapper。


T030保留期复审 → 持久receipt优先仅确认事实存在，不能授权其后再次投影旧missing主行。exact duplicate在归并前仍同事务检查租户水位；Expired时保留原COMMITTED receipt但跳过关联修复，保留窗口内或合法仍存旧主继续归并，新事实仍按原410拒绝。


### 交付 work120 兼容说明（2026-10-24）

T176：最终迁移链为 work110_dsh_local_sessions → f062_unified_model_access → f062_credit_multiplier → f111_dsh_content_safety。F111 尚未发布，接续当前目标唯一 head；两份已发布积分 revision 字节保持不变，由持久哈希回归保护。不能在组合版本保留两个 head 或修改已发布积分 DDL。真实旧版本升级与当前模型 fresh bootstrap 分别验收，不能用当前 create_all 冒充旧库。

T177：路由保留 work120 的 capabilities、skills、work、unified_policy、web-session 全部入口，新增独立安全回传；middleware 只增加精确 POST /api/v1/internal/dsh/content-safety-events，保留 web-session 原认证边界，无宽泛 internal 豁免。T178：当前管理页默认 credits，七个可见页签含 content-safety，operations 仍隐藏；非法 tab 回退延续目标逻辑。安全投影不参与积分倍率、原始用量、账单用量或余额结算。

T181–T184：bootstrap 夹具由完整模型/反射集合验收，目标已有日语 unified 文案和 sandbox 错误三语缺项独立补齐；不改旧翻译、冻结基线或界面视觉。


T185/T186：Responses保留同item同channel各part的实际delta及显式done观察；完整item/final快照独立检查，不能覆盖已观察内容。相邻同类型part按索引拼接，reasoning.summary与content分开、不同item/tool隔离；part.done不提前解除末尾L−1屏障，直到完整item安全水位。只保留有界Unicode安全首尾并计入既有metadata/buffer预算，显式空观察不可当未观察。delta/done混合的候选后缀去重后每边界至多64，工作集同时计入剩余buffer，歧义或预算超限安全ERROR，不能指数增长或默认为PASSED。原32配对扩60，主独立Gateway882项PASS，另1800固定语义对照补充。该修复恢复AC-21、AC-22、AC-23，不改变spec或引入新配置。

T188–T191：策略局部QueryClient关闭原始error对象日志，仍保留页面失败反馈/草稿/CAS冲突；请求详情沿既有dl行独立显示model_started_at、未知或不适用，header与排序仍是稳定请求开始。两项候选审查MEDIUM均已配对RED/GREEN关闭，无新视觉模式。

T192：当前Desktop既有Undici兼容patch使用Object.create克隆handler/controller，会使private字段的回调方法接收者失配。完整回归实际三超时/unhandled错误；按宿主patch契约修原维护patch及原测试，不以直接改node_modules或依赖升级隐去此问题。联调期间真实客户端使用独立临时Profile，修改依赖前仅退出本轮进程。


T197/T198实际治理边界补齐：`get_dsh_model_metadata_snapshot`只供已授权管理员的visibility GET/PUT，复用原始tenant/Root共享/模型类型/provider owner核查但允许offline；`get_dsh_model_snapshot`固定要求online，所有模型调用及目录仍用原口。使新模型可offline创建→私有范围CAS并GET确认→上线，避免为设置权限制造可公开调用窗口，不更改既定敏感词架构。


现场测试合同：Gateway合成错误的公开X-Request-ID为Gateway UUID，已知Backend ID另在X-Backend-Request-ID；普通转发保原编号并附已知Backend ID。MODEL审计使用Backend ID，输入EXTERNAL_SAFETY使用Gateway ID，测试不得互换。旧backend普通管理拒绝实际是HTTP200/业务19801，Gateway只对此已确证码精确映射403，未知业务失败仍503（T199/T200）。
