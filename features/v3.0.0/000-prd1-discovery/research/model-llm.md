# model-llm

## summary
模型管理面（llm_server/llm_model 双表 + 租户隔离 + Root→Child FGA 共享 + 5 组系统默认模型配置）和统一调用抽象 BishengLLM（按 model_id 解析、19 类服务商映射 langchain client、全链路流式）已经非常完整，GOV-05「配置一次、租户内共享」的底座现成；模型下线的明确错误态（LlmModelOfflineError 10012 等）也已存在。但 PRD DEV-02 需要的「OpenAI/Anthropic 兼容入站模型直连代理」在代码库中完全不存在（仅有的 /api/v2/assistant/chat/completions 是零鉴权的助手外壳，model 字段传的是 assistant_id），且无个人 API key 实体、无按名称解析模型的路径；计量存在三条互不打通的轨道（telemetry MODEL_INVOKE 全覆盖但在 ES、llm_token_log/llm_call_log 结构合适但只在 workflow 节点写入、Redis 每日服务商级限流计数），均无 key 维度，「按 key 的用量账单」需在此之上新建。

## current_state
【表与租户模型】模型管理后端在 /Users/lilu/Projects/bisheng/.claude/worktrees/prd1-cred-alignment/src/backend/bisheng/llm/ 模块（DDD 布局）。核心表两张（domain/models/llm_server.py）：`llm_server`（服务商：name 租户内唯一 uk_llm_server_tenant_name、type=CHAR(20) 服务商类型、config JSON 存凭据与端点、limit_flag/limit 每日调用上限、tenant_id）与 `llm_model`（server_id+model_name 组合唯一 server_model_uniq、name 显示名、model_name 调用参数名、model_type=llm/embedding/rerank/asr/tts、status 0正常/1异常/2未知、online bool 上下线、tenant_id 镜像父行）。多租户：子租户经 strict_tenant_filter 只见自有行，Root 服务商经 OpenFGA `llm_server#shared_with→tenant:{leaf}` tuple 共享（LLMDao.aget_shared_server_ids_for_leaf，FGA 不可用时 fail-closed 返空），列表合并后打 is_root_shared_readonly（services/llm.py get_all_llm L382-500）。系统级默认模型选择在 `tenant_system_model_config`（F022，domain/models/tenant_system_model_config.py）：knowledge/assistant/evaluation/workflow/linsight 五个 key per-tenant，aresolve() 返回 (value, inherited_from_root, fallback_blocked)。【管理 API】llm/api/router.py 挂 /api/v1/llm：GET ''（列表，登录即可）、POST/PUT/DELETE ''（服务商 CRUD，get_tenant_admin_user 门槛，Root 行仅超管可写 _assert_root_writable）、GET /info（单服务商详情）、POST /online（模型上下线）、以及 F022 五组系统模型配置端点 + workbench ASR/TTS 直调；写路径落审计（_write_llm_audit）。【凭据存储——已核实非 Fernet】llm_server.config 是**明文 JSON**（JsonType 列）存 openai_api_key/api_key/endpoint 等；全仓 Fernet 只在 core/config/settings.py（config.yaml 密码），llm 模块零加密。防护全在读/写路径：列表 get_all_llm 构造 LLMServerInfo 时 exclude={"config"} 整体剔除；详情 get_one_llm（services/llm.py L551，docstring 明言"Contains key"）对租户管理员**返回明文 key** 供编辑；更新时 JsonFieldMasker.update_json_with_masked（utils/mask_data.py，api_key 类字段掩码为 '********'，正则识别掩码值避免回写覆盖真 key）；审计只落 sha256 前 16 位指纹（_llm_api_key_hash L92）。另有 endpoint_whitelist 配置对非超管建服务商做端点白名单校验（llm_server.py L157）。【调用面】唯一抽象 = BishengLLM（domain/llm/llm.py，继承 BishengBase+BaseChatModel）：按数字 model_id 解析（**无按名称解析路径**），经 LLMDao.aget_model_by_id/aget_server_by_id（wrapper_bisheng_llm_info Redis 缓存 key_prefix llm:server:/llm:model: + LLM_CACHE TTLCache ttl=60）+ share_fallback 处理 Root 共享行；_llm_node_type 字典把 19 种 LLMServerType（const.py：openai/azure/qwen/zhipu/anthropic/deepseek/volcengine/MindIE…）映射到 langchain client（ChatOpenAIReasoning/ChatAnthropic=langchain_anthropic/ChatQwen…，core/ai/__init__.py）+ params_handler（把 server.config 凭据翻译成各家参数）。流式：_stream/_astream 原生透传，_generate 对 streaming 模型聚合流以保 on_llm_new_token 回调。初始化校验链（_init_client L220-232）即模型收回的现成错误态：模型行删除→LlmModelConfigDeletedError、服务商删除→LlmProviderDeletedError、类型不符→LlmModelTypeError、online=False→LlmModelOfflineError(10012，common/errcode/server.py L71，支持 ignore_online 逃逸)。消费方全走 LLMService.get_bisheng_llm(model_id=…)（已核实 grep）：assistant（api/services/assistant_agent.py L229/245）、workflow 四类节点（workflow/nodes/{llm,agent,rag,input}）、工作台 chat（workstation/domain/services/chat_service.py）、频道、知识库、灵思（linsight/domain/services/workbench_impl.py 直用 BishengLLM）。【入站兼容协议——已核实不存在模型直连代理】全仓无任何把请求直转底层模型的 OpenAI /v1/chat/completions 或 Anthropic /v1/messages handler。仅有：(a) POST /api/v2/assistant/chat/completions（open_endpoints/api/endpoints/assistant.py L33）——OpenAI 报文格式**外壳**，req.model 传的是 assistant_id（UUID），实际跑助手 agent，支持真流式 SSE/伪流式，**零鉴权**、get_default_operator() 代系统配置的默认用户（与开放 API 鉴权 PRD 判定的匿名越权同源）；(b) POST /api/v1/workstation/chat/completions（workstation/api/endpoints/chat.py L94）——工作台自家聊天 SSE，非 OpenAI 协议、登录态。"/v1/messages" 只出现在 xinference 出站 client。【计量三轨】① telemetry（全覆盖、每次调用）：BishengLLM 的 generate/stream 四方法被 wrapper_bisheng_model_generator(_async)/limit_check 装饰，成功/失败都经 upload_telemetry_log（llm/domain/utils.py L192-250）发 MODEL_INVOKE 事件到 telemetry ES + F042 emit_metric 指标行，字段含 input/output/cache/total token（parse_token_usage 兼容 usage_metadata/token_usage 多形状）、model_id/server_id/app_id/app_type/user_id/TTFT/时延/status/is_stream。② MySQL 账单表（F017，结构合适但覆盖残缺）：llm_token_log（tenant_id/user_id/model_id/server_id/session_id/prompt/completion/total_tokens，全索引）+ llm_call_log（status/latency_ms/endpoint/error_msg 每次调用一行含失败），由 LLMTokenTracker/ModelCallLogger 写入、缺 tenant ContextVar 时抛 TenantContextMissingError 拒写（INV-T13：记 caller leaf tenant）；但入口 LLMUsageCallbackHandler（workflow/callback/llm_usage_callback.py）**只在 workflow llm 节点注册**（workflow/nodes/llm/llm.py L123，grep 全仓仅此一处）——助手/工作台/灵思/频道调用不落这两张表。读侧 QuotaService._count_tokens_monthly（role/domain/services/quota_service.py L656）按 tenant_id/user_id 对 llm_token_log 做月度 SUM 供 model_tokens_monthly 配额。③ Redis 每日限流计数：model_limit:{date}:{server_id} INCR 超 llm_server.limit 抛"Quota used up"（llm/domain/utils.py L98-118）——服务商级/天，无 per-user/per-key。【个人 API key】后端不存在任何 API key 实体（grep database/models + user 模块零命中）；v2 开放面零鉴权靠 default_operator（open_endpoints/domain/utils.py get_default_operator，顺带 set tenant ContextVar）。【前端】模型管理页 = platform pages/ModelPage/manage/index.tsx（服务商表格 + 模型 online Switch → controllers/API/llm.ts L86 POST /api/v1/llm/online）+ ModelConfig.tsx（服务商/凭据表单）+ SystemModelConfig.tsx 与 tabs/（五组系统模型配置，含 inherited/fallback banner）。

## key_files
- src/backend/bisheng/llm/domain/models/llm_server.py — llm_server/llm_model 双表 + LLMDao（CRUD、online/status 更新、Root 共享 FGA 查询、Redis 缓存装饰）；config JSON 明文存凭据
- src/backend/bisheng/llm/domain/llm/llm.py — BishengLLM 统一调用抽象：19 种服务商→langchain client 映射（_llm_node_type）、params_handler 凭据翻译、流式 _stream/_astream、offline/删除校验链
- src/backend/bisheng/llm/domain/llm/base.py — BishengBase：model_id→(model_info,server_info) 解析入口，含 Root 共享 fallback 与 telemetry 必填字段（app_id/app_type/user_id）
- src/backend/bisheng/llm/domain/services/llm.py — LLMService（1549 行）：get_all_llm（剔凭据+FGA 共享合并）、get_one_llm（含明文 key）、get_bisheng_llm 工厂、JsonFieldMasker 掩码合并更新、api_key sha256 审计指纹
- src/backend/bisheng/llm/api/router.py — /api/v1/llm 管理 API：服务商 CRUD、POST /online 上下线、F022 五组系统模型配置端点（envelope 含 inherited_from_root）
- src/backend/bisheng/llm/domain/utils.py — 每次调用的 telemetry MODEL_INVOKE 上报（token/TTFT/status）+ Redis 每日服务商限流 + parse_token_usage 多厂商 token 提取 + llm:server/model Redis 缓存装饰器
- src/backend/bisheng/llm/domain/models/llm_token_log.py — F017 token 用量表（tenant/user/model/server/session + prompt/completion/total），月度配额 SUM 数据源；无 key 维度
- src/backend/bisheng/llm/domain/models/llm_call_log.py — F017 每次调用审计表（success/error、latency_ms、endpoint、error_msg），为「未来按次成本核算」预留
- src/backend/bisheng/workflow/callback/llm_usage_callback.py — LLMUsageCallbackHandler：on_llm_end→双表落账；全仓唯一注册点在 workflow/nodes/llm/llm.py L123——其它调用面不写账单表
- src/backend/bisheng/open_endpoints/api/endpoints/assistant.py — 现存唯一 OpenAI 格式入站端点 /api/v2/assistant/chat/completions：助手外壳非模型直连，零鉴权走 get_default_operator，SSE 流式组装可参考
- src/backend/bisheng/role/domain/services/quota_service.py — _count_tokens_monthly（L656）：llm_token_log 月度 SUM（Python 算月初界，MySQL/DM8 双兼容）——账单聚合查询的现成范式
- src/backend/bisheng/common/errcode/server.py — 模型失效错误态族：NoLlmModelConfig/LlmModelConfigDeleted/LlmProviderDeleted/LlmModelOffline(10012)/InitLlmError——GOV-05 能力收回可直接复用
- src/backend/bisheng/llm/domain/models/tenant_system_model_config.py — F022 per-tenant 系统默认模型选择（5 key），aresolve 含 Root 继承/阻断语义
- src/frontend/platform/src/pages/ModelPage/manage/index.tsx — 「既有模型管理页」（GOV-05 锚点）：服务商列表 + 模型 online Switch；同目录 ModelConfig.tsx 凭据表单、SystemModelConfig.tsx 系统模型配置
- src/backend/bisheng/open_endpoints/domain/utils.py — get_default_operator：v2 开放面现行「鉴权」=系统配置默认用户 + 手动 set tenant ContextVar——新直连面须替换的旧机制

## reuse
- GOV-05「模型配置一次、租户内共享」底座现成：llm_server/llm_model per-tenant + Root→Child FGA 共享 + 助手/工作流/工作台/灵思已同源消费同一份配置（LLMService.get_bisheng_llm，src/backend/bisheng/llm/domain/services/llm.py L1157）；工场应用运行时注入模型通道可直接复用该工厂，零新建配置面成立
- 模型收回→明确错误态已有完整错误族：LlmModelOfflineError(10012)/LlmModelConfigDeletedError/LlmProviderDeletedError/LlmModelTypeError（common/errcode/server.py L47-77，BishengLLM._init_client 校验链），加上前端上下线 Switch（platform ModelPage/manage/index.tsx → /api/v1/llm/online）——GOV-05「能力收回得到明确错误态」的模型侧可直接映射
- DEV-02 流式能力已通：BishengLLM._stream/_astream 对 19 类服务商全链路流式（llm/domain/llm/llm.py L336-356）；OpenAI SSE chunk 组装与 OpenAIChatCompletionReq/Resp schema 可参考 open_endpoints/api/endpoints/assistant.py 与 api/v1/schemas（含伪流式降级、reasoning_content 透传）
- 计量地基三件可复用：① telemetry MODEL_INVOKE（llm/domain/utils.py upload_telemetry_log）已对每次模型调用全覆盖记录 input/output/cache/total token+模型+应用+用户，装饰器层挂点即「在 BishengLLM 统一落账」的现成注入位；② llm_token_log/llm_call_log 表结构（F017）与 INV-T13 租户归属规则、TenantContextMissingError fail-closed 语义可扩展 key 维度直接当账单表；③ QuotaService._count_tokens_monthly 的 MySQL/DM8 双兼容聚合 SQL 范式可复制成按 key/按模型的账单查询
- MCP「模型清单查询」工具数据源现成：get_all_llm 已做租户过滤+Root 共享合并+凭据整体剔除（exclude config），按 online 过滤即可输出可用模型清单
- Anthropic 出站客户端已在依赖树内（langchain_anthropic.ChatAnthropic，core/ai/__init__.py L1），Anthropic 兼容入站面的下游调用无需新增依赖
- 凭据脱敏工具链可复用：JsonFieldMasker（utils/mask_data.py）掩码+掩码识别回写合并、_llm_api_key_hash sha256 指纹审计——新增 key 管理/账单 UI 的凭据展示可沿用
- 服务商级每日调用限流（Redis model_limit:{date}:{server_id}，llm/domain/utils.py L98）可作为按 key 限流的实现参照（同为 INCR 计数模式）

## gaps
- OpenAI 兼容 /v1/chat/completions 模型直连代理端点：零现状。需新建入站路由（协议解析、按 key 鉴权、模型名→llm_model 解析、译成 BishengLLM 调用或直透 upstream、SSE 流式、OpenAI 原生错误体、usage 回填响应）
- Anthropic 兼容 /v1/messages 入站端点：仓内完全没有 Anthropic 入站协议处理（/v1/messages 仅存在于 xinference 出站 client），报文/流式事件/错误体全套需新写
- 按「模型管理原名」解析模型：现有解析只认数字 model_id（BishengBase.get_model_server_info），无 name→model 查找路径；且 LLMModel.name/model_name 均无租户内唯一约束（model_name 只在 server 内唯一），需定义歧义规则并可能补约束
- 个人 API key（DEV-01）实体与鉴权中间件：后端无任何 API key 表（grep 零命中）；v2 现行 default_operator 零鉴权机制必须被替换，key→user→tenant ContextVar 的解析链需新建（与开放 API PRD 的 bs-sak- 服务账号密钥体系对齐）
- 按 key 的用量账单：llm_token_log/llm_call_log 无 key 维度字段；两表写入目前只覆盖 workflow llm 节点（LLMUsageCallbackHandler 唯一注册点），直连面及其它调用面需统一落账（建议下沉到 BishengLLM wrapper 层）；账单查询 API（按 key 归属、token+调用次数、按模型拆分）与持有人自查/管理员查询界面全部新建
- 「租户管理员配置的可用模型范围」按 key/按应用收窄：现状 online=true 即全租户可用，无 per-key/per-app 模型白名单机制（GOV-05 应用能力声明写模型名→审批→运行时注入的关联表与校验均需新建）
- 能力收回的应用侧联动：模型侧错误态已有，但「应用声明使用的模型被下线→owner 在发布面/资源面可见失效提示」的声明关联与提示面为零

## risks
- 凭据明文存储与 C6 落差：llm_server.config 明文 JSON 存 api key，get_one_llm 对租户管理员返回明文；PRD 强调底层账号零暴露，若直连代理长期持有转发凭据，是否本期升级加密存储（涉及存量迁移+DM8 双库）是成本敏感决策
- 收回生效延迟：模型/服务商信息有 Redis 缓存（llm:server:/llm:model: 前缀）+ 进程内 LLM_CACHE(ttl=60s)，下线/删除后最长一个 TTL 内仍可能初始化成功——GOV-05「明确错误态」若要求即时生效需做缓存失效设计
- token 提取双轨口径不一致：账单若基于 LLMUsageCallbackHandler._extract_token_usage（只认 llm_output.token_usage/usage）而 telemetry 走 parse_token_usage（兼容 usage_metadata/流式 chunk/cache token），同一调用两处计数可能不同；按 key 账单必须统一到一套提取逻辑，否则与既有配额（model_tokens_monthly）对不上账
- 高频直连面的写放大：llm_token_log/llm_call_log 每 call 双 INSERT（MySQL 同步），Claude Code 等本地 agent 直连是高频场景，DM8 环境有历史写放大事故（灵思 -7120），账单落库需评估批量/异步化
- C3 租户上下文：直连面绕开 JWT 中间件，LLMTokenTracker/ModelCallLogger 在 ContextVar 缺失时抛 TenantContextMissingError（fail-closed），key 鉴权中间件必须承担 set_current_tenant_id 职责，否则计量整面拒写；多租户共享模型下须沿用 INV-T13（记 caller leaf tenant）避免 Root/Child 记账串扰
- C5 错误码体系冲突：OpenAI/Anthropic 协议要求各自原生错误体（非 resp_200 包裹、非 MMMEE 码），需要一层协议错误映射；现存 /api/v2/assistant/chat/completions 用 500+裸字符串是反面教材，且该端点零鉴权本身是活的越权面（开放 API PRD 已判定），新直连面不能沿用其 default_operator 模式
- 限流缺口：现有限流仅服务商级/天（Redis INCR），无 per-key 限流轮子（记忆与代码一致：全仓无限流基建）；直连面暴露给本地工具后滥用防护需从零建
- 「模型名即原名」的名称歧义是产品级风险：租户内跨服务商同名 model_name 合法存在（如两个服务商都配 qwen-max），解析规则不定义清楚会导致应用声明绑定到错误凭据

## open_questions
- DEV-01 个人 API key 与《开放 API 鉴权 PRD》的服务账号密钥（bs-sak-）是否同一实体/同一鉴权中间件（仅 scope 与前缀不同），还是独立表？按 key 账单的 key_id 外键指向哪张表？
- 「模型名即平台模型管理原名」指 LLMModel.name（显示名）还是 model_name（调用参数名）？租户内同名冲突（跨服务商）时的解析规则：报错、要求唯一约束、还是 server/name 组合名？
- 直连面架构选型：统一译成 BishengLLM 再出（自动继承 telemetry/限流/错误分类/离线校验，但 Anthropic 入站语义经 OpenAI 化转换有损，如 cache_control、tool_use 块），还是同协议直透 upstream+旁路计量？Anthropic 入站是否只对 anthropic 类型服务商开放？
- 按 key 账单数据源：扩展 llm_token_log 加 key_id 并把落账下沉到 BishengLLM 层全面覆盖（顺带补齐助手/灵思等既有调用面的账单缺口），还是新表只覆盖直连面？账单聚合粒度（日/月）、按模型拆分的展示口径与数据保留期？
- GOV-05「可用模型范围」首版是否= 既有 online 全租户粒度即满足（key 只看租户内 online 模型），还是要求 per-key 模型白名单？应用能力声明中的模型与个人 key 的模型范围是否同一套机制？
- 凭据加密存储是否纳入本期（存量 llm_server.config 迁移 + DM8 兼容 + get_one_llm 读路径收紧），还是维持明文仅靠读侧脱敏？
- 直连面的限流策略需要产品定义：per-key QPS/日调用/月 token 上限各要哪些？超限错误按 OpenAI 429 语义还是平台错误码？
