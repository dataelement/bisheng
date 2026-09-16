# Design: 模型协议直连面（OpenAI 兼容子集 + `model:invoke` + 逐条调用审计）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（36 条 AC、边界、决议 1–8）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策（含被否决的备选）、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档、只留"今天的状态"；但每个决策保留"为什么 + 被否方案"和坑。推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。
>
> **代码事实口径**：本文所有 `文件:行号` 均按 `3.0-vibe`（HEAD `fe10f75ea`，含 beta2 F053 开放 API 底座）在 2026-09-16 核实，路径以 `src/backend/bisheng/` 为根（前端另注 `platform/` = `src/frontend/platform/src/`；`locales/` = `src/frontend/packages/locales/src/`）。行号会漂移，符号名不会——落地前以符号名重定位。
>
> **全自动模式说明**：用户已豁免本 Feature 的 ★ 暂停点。§3 每条决策均标「全自动模式定案」并留理由与备选，供事后追溯或翻案。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [release-contract.md](../release-contract.md)（表 1 **ModelCallRecord** 归本 Feature；INV-27 / INV-28 / INV-30 / INV-31）· [mvp-114-path.md](../mvp-114-path.md)（F051 不在纵切上）· [000-prd1-discovery/research/model-llm.md](../000-prd1-discovery/research/model-llm.md)
**上游 / 姊妹**: [F049 design](../049-openapi-auth-baseline/design.md)（历史；**实际底座 = beta2 F053**：`router_rpc` 单一依赖 `verify_open_api_access` + 端点 `@open_api_scope` marker）· [F055 design D13](../055-app-publish-pipeline/design.md)（能力总线模型项落点方向、`BISHENG_APP_TOKEN` 注入）· [F055 tasks T055 / T056](../055-app-publish-pipeline/tasks.md)（`hosted_app` 主体解析器、模型能力注入——本文 §6.2 依赖项）· [F054 contracts-runtime-manager.md §5](../054-app-domain-runtime/contracts-runtime-manager.md)（注入环境变量清单唯一来源，本文 D2 提回写请求）· [F053 design](../053-dev-cli-skills/design.md)（接入信息区 / `dev` 同名环境变量的消费方）
**版本**: v3.0.0
**最后更新**: 2026-09-16（初版；尚未开工，本文是"要建成的样子"，实现后按现状覆盖）

---

## 1. 目标与非目标

- **目标**：在 `/api/v2` 上开一条**裸协议透传**的 OpenAI 兼容子集——`POST …/chat/completions`（含 SSE 流式、工具调用）与 `GET …/models`——让讲 OpenAI 协议的本地引擎（Qwen Code / Codex CLI 对话补全模式 / Kimi Code）和托管应用只凭 base URL + 一把密钥 + 模型管理页原名就能调到租户已启用的对话模型；鉴权与身份完全复用 beta2 开放 API 底座（`model:invoke` 位、仅模式 S、`delegate` 入口拒绝、5 秒撤销上界）；模型名解析（含跨服务商同名的限定名规则）落在 `llm` 域、供 F052 模型清单工具与 F055 预检**同一函数**消费；每次到达模型解析阶段的调用写一行 **ModelCallRecord**（新表、异步批量写），token 数与平台既有 MODEL_INVOKE 遥测同源。
- **非目标**（spec 范围边界已定，此处防扩范围）：Anthropic 兼容面、embeddings / Responses / 其它 OpenAI 端点（只拒不转）；F052 MCP 模型清单工具本身；F058 会话契约；按 key / 按应用聚合账单与用量可视（v3.1）；per-key / per-app 限流与 token 上限；模型管理页改动；托管应用运行期凭据的签发 / 重签（F055 T055）、「当前生效能力声明」的定义（F055）、短时访问凭据的签发（F054）；接入信息区界面（F053 AC-44）；`delegate` ⊗ 三扩展位的签发期互斥（已由 beta2 `26050` 交付）。

---

## 2. 关键约束

> 全局铁律（DDD 分层 / 双 DB / 多租户自动注入 / 权限唯一入口 / 错误码 / 无硬编码密钥 / 前端 store 不直连 HTTP / 本地盘不承载共享状态）一律遵循 [`docs/constitution.md`](../../../docs/constitution.md) **C1–C8**，本节不重抄。以下只写本 Feature 特有的硬约束。

| # | 约束 | 出处 / 后果 |
|---|---|---|
| K1 | **鉴权只能复用、不能重写**：`router_rpc = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])`（`api/router.py:149`）是 `/api/v2` 唯一凭据校验路径；子 router 只能靠端点 `@open_api_scope(...)` marker 声明位与模式，**无标记即 26031 fail-closed**（`open_api/api/dependencies.py:101-102`）。凭据缓存 TTL ≤ 5s（`core/config/open_platform.py:13` 默认 3、`:47-50` 校验器夹到 5）、`delegate` 入口拒绝 26051（`dependencies.py:113-114`）、缺位 26003 带 `required`（`:115-116`）、身份头拒绝（`identity_service.assert_no_removed_identity_headers`，`:118`）全部**白吃**——AC-05 / AC-06 / AC-07 / AC-26 / AC-27 不写一行鉴权代码 | INV-27 / INV-31；`test/open_api/test_open_api_route_matrix.py:38-56` 断言每条 v2 路由都带 marker 且登记在 `OPEN_API_SCOPES` |
| K2 | **HTTP 状态必须真实且错误体必须是 OpenAI 形状**：v2 handler 已把 `BaseErrorCode` 映射成真状态（`open_api/api/exception_handlers.py:45-77`），但 body 是 BiSheng 信封 `{status_code,status_message,data}`；官方 `openai` 客户端只解析 `{"error":{message,type,code,param}}`——本面路径前缀下必须换体、且不能影响其它 v2 路径 | AC-08；D4 |
| K3 | **模型解析今天不存在**：`BishengBase.get_model_server_info` 只按数字 `model_id` 取模型（`llm/domain/llm/base.py:44-57`）；`(server_id, model_name)` 才唯一（`llm/domain/models/llm_server.py:102 server_model_uniq`），**跨服务商同名合法**；服务器名租户内唯一（`:95 uk_llm_server_tenant_name`） | AC-11 / AC-12；D5 |
| K4 | **可用范围 = `LLMService.get_all_llm` 的服务器集合**（`llm/domain/services/llm.py:398-505`：leaf 自有行 `strict_tenant_filter()` + FGA `shared_with` Root 服务器 + 继承的系统默认服务器，模型经 `bypass_tenant_filter()` 取）——但它返回 `LLMServerInfo` 给前端用、签名带 `operator: UserPayload`；本面需要**无 UserPayload、可缓存、fail-closed** 的版本。**坑**：`LLMDao.aget_shared_server_ids_for_leaf` 在 FGA 异常时 `return []`（`llm_server.py:492-512`）——对前端列表是"少看到"，对本面是**静默缩窄后放行**，违反 AC-35 | AC-09 / AC-35；D6 |
| K5 | **模型下线生效上界 60s = `LLM_CACHE` 的 TTL**（`llm/domain/const.py:45` `TTLCache(maxsize=30, ttl=60)`；`aget_model_by_id_with_share_fallback(cache=True)` 走它）；`update_model_online` 已调 `invalidate_llm_info_cache`（`utils.py:430-441`）但只清本进程。本面目录缓存 TTL 同样 ≤ 60s、多节点各自过期即可，不做主动跨节点失效（spec 决议-4） | AC-14 |
| K6 | **BishengLLM 的附赠与代价**：`LLMService.get_bisheng_llm(model_id=…, app_id, app_type, app_name, user_id, streaming, …)` → `BishengLLM`（`llm/domain/llm/llm.py:223`）= 19 家服务商映射、`bind_tools`（`:356-362`，`convert_to_openai_tool`）、`_astream`（`:376-384`）、`normalize_reasoning_content`、下线 / 删除 / 类型错误族（`common/errcode/server.py:53-78`，10009 / 10010 / 10011 / 10012 / 10013）、服务商日调用上限（`utils.py:118-126`）、自动 MODEL_INVOKE 遥测 + `emit_metric`（`utils.py:212-271`）。代价：① 遥测必填 `app_id / app_type / app_name / user_id`（`base.py:21-25`）；② 上限超出抛**裸 `Exception("… Quota used up")`**（`utils.py:126`）；③ 流式遥测只解析**最后一个 chunk** 的 usage（`utils.py:382-409` `wrapper_bisheng_model_generator_async`，`result=item`） | D1 / D10 / D13；坑 3、坑 5 |
| K7 | **审计写放大**：本面是高频面，`OpenApiAuditMiddleware` 已对每个 `/api/v2` 请求（含 401 / 403）写一行 `open_api.call` AuditLog（`open_api/api/middleware.py:98-157`，批量 `OpenApiCallAuditService`，队列 1000 / 批 100 / 1s，`call_audit_service.py:12-15`）。ModelCallRecord 必须是**独立表**（不进 `audit_log`，否则审计页被淹）、写入必须异步批量、**不能拖慢首字** | AC-20 / AC-24 / spec §3「审计写放大」；D9 |
| K8 | **token 口径唯一**：平台既有的模型用量账本是 MODEL_INVOKE 遥测事件（`ModelInvokeEventData.input_token/output_token/total_token`，`utils.py:236-253`，数值来自 `parse_token_usage`）；`llm_token_log`（`LLMTokenTracker.record_usage`）**只有工作流回调写**（`workflow/callback/llm_usage_callback.py:85`），无读侧消费。ModelCallRecord 的 token 数必须用**同一个结果对象上的同一个 `parse_token_usage`**，不另算 | AC-23；D10 |
| K9 | **开放能力层开关是进程级**（`settings.open_platform.enabled`，`core/config/open_platform.py:8`；先例 `api/router.py:140-141` `if settings.open_platform.enabled: router.include_router(dev_toolkit_router)`）；未开时本面**不挂 router → Starlette 裸 404**（不透露存在，AC-28），开后不依赖 runtime-manager / app-proxy（AC-29） | GOV-10 |
| K10 | **base URL 必须可从平台 origin 推导且部署形态无关**：`resolve_public_base_url(request)`（`open_api/api/public_base_url.py:77-96`：配置 `open_api.public_base_url` > `X-Forwarded-*` > Host）；nginx `location ~ ^(/workspace)?/api(/|$)` 直通后端并带 `X-Forwarded-Proto/Host`（`docker/nginx/conf.d/default.conf:117-124`），商业版网关代理 `/api/v2/**`（`docs/architecture/11-gateway.md`）——路径放 `/api/v2` 下即三种形态都可达 | AC-30；D2 |
| K11 | **SSE 经 nginx 必须逐块透传**：`default.conf:117-124`（`location ~ ^(/workspace)?/api(/|$)`）有 `proxy_read_timeout 300s`、**无 `proxy_buffering off`**——同一份配置里托管应用块 `:94` 是显式关了缓冲的（注释「缓冲会把流式响应攒成一坨」），`/api` 块没跟上，所以不能指望它；响应必须带 `X-Accel-Buffering: no` + `Cache-Control: no-cache`，且中途失败以 SSE 错误事件收尾后 `[DONE]` 并关闭（AC-16）。已有 SSE 精度参考：`assistant/domain/services/published_assistant_service.py:139-190`（无 tool_calls / usage，**不可直接复用**） | AC-16 / AC-18 |
| K12 | **托管应用路径被上游阻塞**：`api_credential.subject_kind` CHECK 只允许 `service_account / natural_person`（`open_api/domain/models/api_credential.py:42-44`）、`SUBJECT_RESOLVERS` 只有两项（`credential_validator.py:105-108`）、manifest `capabilities` 非空被 16231 拒（`app_publish/domain/services/manifest_validator.py:299-303`）、OBO 令牌只签不验（`app_runtime/domain/services/entry_authz_service.py:379-426`，`aud="bisheng-app-obo"`，头名 `X-BiSheng-Access-Token` `:175`）。本面对 AC-21 / AC-22 / AC-34 只能**先定钩子接口、后接线**（D7），任务标「依赖 F055 T055 / T056、F054 OBO 验签」。**2026-09-16 解除**：四处全部落地（CHECK 已含 `hosted_app`、`SUBJECT_RESOLVERS` 三项、`HostedAppDeclarationAdapter` / `AccessSubjectVerifier` 由 `app_publish/composition.py` 一并注册、`verify_obo_token` 已实现），T022–T024 改为真实断言，见 §6.2 | §6.2 |
| K13 | **`check-i18n.mjs:106` 只识别 `Code:\s*int\s*=` 写法**；`common/errcode/open_api.py` 全部用 `Code = NNNNN`，故 260 段的三语覆盖**没有**被 CI 校验。新文件 `model_face.py` 一律写 `Code: int = 262xx`，让 CI 真正拦缺文案 | C5；坑 12 |

**Constitution Check（自查）**：C1 新代码分 `open_api/api/endpoints/model_gateway.py`（端点）→ `open_api/domain/services/model_gateway_service.py`（编排）→ `llm/domain/services/model_catalog.py`（目录 / 解析，跨模块 domain 调用允许）→ `open_api/domain/repositories/model_call_record_repository.py`（ORM）；端点不 import 其它模块 `api/*`（RULE-5）。C2 新表全部 `dialect_helpers`，`VARCHAR` 不用 `CHAR`，无 JSON 过滤（D9）。C3 `verify_open_api_access` 已 `current_tenant_id.set(principal.tenant_id)`（`dependencies.py:76`），目录查询按当前租户；**写入器在后台任务里跑、无请求 ContextVar**——批量 INSERT 每行显式带 `tenant_id`（before_flush 兜底靠不住：`tenant_filter.py:233-241` 在无 ContextVar 时，单租户部署填 `DEFAULT_TENANT_ID`、**多租户部署直接 `return` 什么也不填**——那一行就会以 `tenant_id=None` 落库），`credential_mask` 水合的 `IN` 查询在 `bypass_tenant_filter()` 下做（批内跨租户）；无批量 UPDATE / DELETE。新表模块必须 import 进 `open_api/domain/models/__init__.py`（D9）。C4 本面不做资源级授权（可用范围是租户配置，不是 F048 资源权限）；`shared_with` 反查经 `permission.application`（K4，`get_permission_relation_api`）、无 OpenFGA 直连。C5 新模块 **262**（D11）。C6 密钥 / 服务商配置不进日志与记录（D14）。C8 目录缓存只是加速、真相在 DB；写入器队列是进程内缓冲、丢失可观测。

---

## 3. 方案对比与选定

> 每条 3 段：备选 / 选定 / 原因 + 何时该重新考虑。均为「全自动模式定案」。

### D1：协议面承载 = 自研薄层（OpenAI 请求 ⇄ `BishengLLM` 翻译），不引入现成代理、不做原始 HTTP 透传

- **备选**：
  - A. **现成代理**（LiteLLM / One-API 一类）单独部署，平台把服务商凭据同步过去 — 优点：协议长尾（Anthropic / embeddings）免费；缺点：第二份服务商凭据（AC-36 明文外泄面翻倍）、自带管理 UI / DB 要额外封（AC-36）、它不知道「租户可见且已启用」「Root 共享」「服务商日上限」——可用范围要靠同步，同步延迟 = 静默越权；商业版网关 / 信创部署再多一个组件
  - B. **原始 HTTP 透传**（只对 `LLMServerType.OPENAI` 一类服务商把 body 原样转发到 `base_url`）— 优点：零翻译损耗；缺点：19 家服务商里只有 openai / azure / vllm / deepseek 等一半讲 OpenAI 协议，其余（qwen / zhipu / spark / minimax / anthropic…）仍要翻译 → 两套代码；遥测 / 上限 / 下线错误族全要重做
  - C. **自研薄层**：pydantic 校验 OpenAI 请求 → `convert_to_messages` → `LLMService.get_bisheng_llm(...)`（K6）→ `ainvoke` / `astream` → 组装 OpenAI 响应 / chunk
- **选定**：**C**（全自动模式定案）
- **原因**：产品方案 §4.6「BishengLLM 复用度」与 spec 决议-1 已把 Anthropic 面排除，现成代理最大的收益（协议长尾）本版用不上，而其成本条条命中 AC-36 / AC-09；C 让「租户已启用模型 = 平台内助手 / 工作流能调的模型」这一等价（AC-15）成为结构性事实——同一个 `BishengLLM`、同一个 `limit_flag`、同一个 `LlmModelOfflineError`。翻译损耗只在 tool_calls / usage 两处需要精细组装（D8）。
- **何时该重新考虑**：v3.1 立项 Anthropic 面或 embeddings 承诺面（那时也优先在同一 base URL 下扩薄层，只有"三种以上协议同时承诺"才值得引代理）；`langchain` 抽象在流式 tool_calls 上出现不可修补的丢字段（坑 6 的检测手段能证明）。

### D2：挂载点与 base URL = `/api/v2/model/v1`，环境变量 `OPENAI_BASE_URL` / `OPENAI_API_KEY` + 平台保留名 `BISHENG_MODEL_BASE_URL`

- **备选**：
  - A. `/api/v2/openai/v1/…` — 路径把第三方名字写进平台契约；将来若在同一 base 下扩其它协议子集（决议-1「何时重新考虑」）名字就错了
  - B. 独立顶级前缀 `/model/v1`（不在 `/api/v2` 下）— 脱离 `router_rpc` 就要复制 K1 全部鉴权、审计中间件（`OPEN_API_V2_PREFIX`）、网关代理白名单、nginx location 四处
  - C. **`/api/v2/model/v1`**：子 router `prefix="/model/v1"` 挂进 `router_rpc`（`api/router.py:149-166`），端点 `POST /chat/completions`、`GET /models`
- **选定**：**C**（全自动模式定案）。**base URL = `{resolve_public_base_url(request)}/api/v2/model/v1`**（无尾斜杠），由新 helper `model_gateway_base_url(request)`（`open_api/api/public_base_url.py`）唯一产出；`GET /api/v2/auth/whoami` 响应新增字段 `model_base_url`（`WhoamiResponse`，`open_api/domain/schemas/credential.py`）——F053 `login` 与接入信息区都从这一个出口取值，不各自拼。
- **环境变量契约**（供 F053 `dev` 与 F054 runtime-manager 同名注入，本 Feature 只定名、不注入）：`OPENAI_BASE_URL` = base URL、`OPENAI_API_KEY` = 凭据明文（`bs-sak-…` 或应用运行期凭据）——官方 `openai` 客户端零配置直读；另设平台保留名 `BISHENG_MODEL_BASE_URL`（= 同值）作为与 `BISHENG_PLATFORM_API_BASE` 平行的稳定名，供技能包文案与不读 OpenAI 惯例变量的引擎使用。**保留 `/v1` 段**是因为多数引擎把「以 `/v1` 结尾」当作 OpenAI 兼容地址的启发式校验（Codex CLI provider 配置、部分 IDE 插件）。
- **原因**：C 白吃 K1 全部鉴权与 K7 审计；网关 / nginx 零改动（K10）；`/model/v1` 协议中性；官方客户端只在 base URL 后拼 `/chat/completions`、`/models`，不再补 `/v1`，故 base 里自带 `/v1` 是安全的。
- **何时该重新考虑**：runtime-manager 注入清单（F054 contracts §5）正式加入本组变量时若 F054 / F057 已用了别的名字——以本文为准回写它们（§6.1）；商业版网关若对 `/api/v2/model` 单独限流。

### D3：承诺面之外的路径 = 子 router 内显式 catch-all 拒绝路由（26201）+ Anthropic `/messages` 专用 26202；开关未开 → 整个子 router 不挂

- **备选**：
  - A. 不写多余路由，让未知路径落到 Starlette 默认 404 `{"detail":"Not Found"}` — 不是 OpenAI 错误体、且无凭据也 404、与 AC-02「明确的『本版不提供该端点』可读响应」不符
  - B. 逐个枚举 `/embeddings`、`/completions`、`/responses`、`/images/*`… 每个一条路由 — 清单会漏，且 `test_open_api_route_matrix.py:48-56` 要求每条真实路由登记进 `OPEN_API_SCOPES.endpoints`，枚举越多登记越多
  - C. **一条 `api_route("/{rest:path}", methods=[GET, POST, PUT, DELETE, PATCH])` catch-all**，标 `@open_api_scope("model:invoke", modes=("S",))`（**先过凭据与位判定再拒**——无凭据仍 401、缺位仍 403，不透露端点清单）；其中 `rest == "messages"`（Anthropic Messages API 路径）→ 26202「本版仅提供 OpenAI 兼容面」，其余 → 26201「本版不提供该端点」，HTTP 404、`type="invalid_request_error"`、`code="endpoint_not_supported"`；路由矩阵登记 `("*", "/api/v2/model/v1/{rest}")`（测试的 `actual_v2_routes()` 按 `route.methods` 展开，登记时按五个方法各一条）
- **选定**：**C**（全自动模式定案）
- **原因**：一条路由覆盖全部 OpenAI 协议族（`/embeddings`、`/completions`、`/responses`、`/images/generations`、`/audio/*`、`/files`、`/fine_tuning/*`、`/assistants`…）与 Anthropic 路径，不会漏；仍经 K1 依赖故不破 INV-27。Anthropic 单列一码是 AC-03 / AC-32 的可测试点（Claude Code 打到 `…/v1/messages`）。
- **开关未开（AC-28）**：`api/router.py` 中 `if settings.open_platform.enabled: router_rpc.include_router(model_gateway_router)`（仿 `:140-141`；`open_api/api/router.py` 今天只导出 `management_router` / `rpc_router`，`api/router.py:49-50` 以别名 `open_api_rpc_router` 引入——本面另导出 `model_gateway_router`，**不**塞进 `rpc_router`，否则条件挂载失效）；未开时路径不存在 → Starlette 404，与其它不存在路径无差别。**与既有 v2 子 router 的差别要说清**：`app:manage`（F055）的 `/api/v2/apps/**` 是**无条件**挂载、只靠位不可签发来关（`api/router.py:164`），本面是唯一条件挂载的 v2 子 router——因为 AC-28 要求「不透露存在」，403 缺位做不到。
- **两个既有测试因此要改口径**（T007 / T016）：① `test_open_api_route_matrix.py:44-56` 断言 `OPEN_API_SCOPES` 登记的端点集合 == 实际挂载集合，`app` 来自 `from bisheng.main import app`（`:4`，import 时按 config 求值开关，`monkeypatch` 事后改开关不会重挂）；② `test_openapi_schema_contract.py:34-56` 断言 `app.openapi()` 的 v2 操作集合 == 生成的 `openapi-v2-key-auth-api.json`。两者在**开关关闭的进程**里都会看到「登记 / 契约有、实际无」。处理：以 `exception_handlers.MODEL_GATEWAY_PATH_PREFIX` 为唯一来源，两测试在 `settings.open_platform.enabled` 为假时把该前缀下的操作从**期望集合**剔除（不改 `OpenApiScope` 数据类、不加字段）；开关开启态由 T012 switch 用例用 `importlib.reload(bisheng.api.router)` + 独立 `FastAPI()` 挂 `router_rpc` 断言存在。契约 json 用 `open_platform.enabled: true` 的 config 生成（生成脚本同样 `import bisheng.main`，`generate_openapi_contract.py:13`），因此 json 里恒含本面三条操作。`open_platform_enabled` / `open_platform_disabled` fixture 今天是 `test/open_api/test_scope_issuability.py:36-42` 的**模块内**定义，T005 把它们提升到 `test/open_api/conftest.py` 供本面各测试复用。
- **何时该重新考虑**：承诺面扩到 embeddings 时把它从 catch-all 前面"抠"出来成真路由，catch-all 不变。

### D4：OpenAI 错误体 = 本面前缀专属渲染 + 平台码映射表；`bisheng_code` 保留在 `error.code` 之外

- **备选**：
  - A. 改 `open_api/api/exception_handlers.py` 全局体形状 — 破坏既有 v2 客户契约（`openapi-v2-key-auth-api.json` + 客户脚本已按信封解析）
  - B. 在本面端点里 `try/except` 自己渲染 — 依赖层（26001 / 26003 / 26051）抛出时端点还没执行，接不到
  - C. **在 `_register_v2_handler` 的 `dispatch` 前加一层判断**：`path.startswith("/api/v2/model/v1")` → 走 `render_openai_error(exc)`；否则原逻辑不变。`RequestValidationError` 同样在该前缀下渲染成 `invalid_request_error`（`param` 取 `loc` 末段）。**依赖层错误也会经此路径**（`open_api_auth_exception_handler` 与 `dispatch` 都先看前缀）
- **选定**：**C**（全自动模式定案）。错误体：`{"error": {"message": "<可读原因>", "type": "<OpenAI 类型>", "code": "<稳定字符串>", "param": null|"<字段>", "bisheng_code": 262xx|260xx}}`——`bisheng_code` 是 OpenAI 体之外的扩展键，官方客户端忽略未知键、平台侧脚本据此精确分类。
- **映射表**（HTTP 状态 / `type` / `code`）：

| 平台码 | 场景 | HTTP | `type` | `code` |
|---|---|---|---|---|
| 26001 / 26002 / 26027 | 无凭据 / 无效 / 主体停用（AC-05） | 401 | `authentication_error` | `invalid_api_key` |
| 26003 | 缺 `model:invoke`（AC-06；message 含 `required=model:invoke`） | 403 | `permission_error` | `insufficient_scope` |
| 26051 | 委托专用密钥（AC-26；message 原文「委托专用、本地开发另签一把」） | 403 | `permission_error` | `delegate_only_credential` |
| 26004 / 26005 / 26010 / 26018 / 26019 | 委托类身份头 / `user_id` 入参（AC-27）：`X-On-Behalf-Of` 而主体非服务账号或密钥无 `delegate` → 26004（`OpenApiDelegationNotAllowedError`，403，`identity_service.py:76-77`）；`X-On-Behalf-Of` 值非法 → 26005（`:44-52`）；两头同时出现 → 26010（`OpenApiIdentityHeaderConflictError`，`:38-39`）；`X-End-User` 值非法 → 26018（`:55-57`）；旧式 `*-on-behalf-of` / `*-end-user` 头（`:25-30`）或 query / form / body 里的 `user_id`（`dependencies.py:191-214`）→ 26019。**26016 在本面不可达**——它是 `OpenApiDelegationHeaderRequiredError`（持 `delegate` 却没带 `X-On-Behalf-Of`，`:71-73`），而持 `delegate` 的密钥在依赖层已被 26051 更早拒（K1） | 400/403 按原码 | `invalid_request_error` | `identity_header_not_accepted` |
| **26205** | **合法值的 `X-End-User` 单独出现（AC-27 的底座缺口，坑 18）**：底座对它只做格式校验，合法即 `principal.model_copy(update={"end_user_id": …})` 静默放行（`identity_service.py:71-74`）——AC-27 要求「不得静默忽略该头继续执行」，故本面自己拒 | 403 | `permission_error` | `identity_header_not_accepted` |
| 26201 / 26202 | 端点不支持 / Anthropic 路径（AC-02 / AC-03） | 404 | `invalid_request_error` | `endpoint_not_supported` / `anthropic_protocol_not_supported` |
| 26203 | 请求体不合法（`RequestValidationError`、`messages` 为空等） | 400 | `invalid_request_error` | `invalid_request` |
| 26204 | 服务账号密钥附带访问凭据（AC-22） | 403 | `permission_error` | `access_token_not_accepted` |
| 26211 | 模型不存在（含他租户 / 非对话类 / 名称不匹配，AC-13） | 404 | `invalid_request_error` | `model_not_found` |
| 26212 | 模型已下线（AC-13 / AC-14） | 404 | `invalid_request_error` | `model_offline` |
| 26213 | 服务商已删除 / 已收回（AC-13） | 404 | `invalid_request_error` | `model_revoked` |
| 26214 | 裸名歧义（AC-12；`error.candidates=[限定名…]`） | 400 | `invalid_request_error` | `model_name_ambiguous` |
| 26215 | 能力未声明（托管应用，AC-34） | 403 | `permission_error` | `capability_undeclared` |
| 26216 | 目录 / 声明不可判定 → fail-closed（AC-35） | 503 | `server_error` | `model_catalog_unavailable` |
| 26217 | 服务商日调用上限（AC-15） | 429 | `rate_limit_error` | `provider_daily_limit_exceeded` |
| 26231 | 上游失败（连接 / 5xx / 初始化 10013） | 502 | `server_error` | `upstream_error` |
| 26232 | 上游拒绝请求（上游 4xx：上下文超长 / 参数不支持 / 内容拦截；message 带上游原文） | 上游状态（400/413/422），取不到则 400 | `invalid_request_error` | `upstream_rejected` |
| 26233 | 上游限流（上游 429） | 429 | `rate_limit_error` | `upstream_rate_limited` |
| 26234 | 流式中途中断（只在 SSE 错误事件出现） | — | `server_error` | `stream_interrupted` |
| 19002 / 19201 / 26030 | 权限引擎 / 凭据依赖不可用 | 503 | `server_error` | `service_unavailable` |

- **上游异常识别**：`openai.APIStatusError`（`status_code`、`message`）与各服务商 SDK 异常经 `classify_upstream_error(exc)` 归入 26231 / 26232 / 26233；无法识别 → 26231，message 取 `str(exc)` 前 500 字（**不含**服务商 URL / key，D14）。
- **原因**：AC-08 要求官方客户端能按其错误约定解析并让 agent 自行纠正；`type` / `code` 用 OpenAI 已有词汇（`authentication_error` / `permission_error` / `invalid_request_error` / `rate_limit_error` / `server_error`），`code` 用稳定 snake_case 字符串而非数字，客户端才能 `except` 到位。
- **何时该重新考虑**：`openai` SDK 大版本改错误体约定。

### D5：模型名基准 = `LLMModel.model_name`；限定名 = `{服务商名}/{模型名}`；解析算法固定

- **事实**：模型管理页「模型名称」输入框绑定的是 `model.model_name`（`platform/pages/ModelPage/manage/ModelConfig.tsx:297-303`，i18n `model.modelName` = 「模型名称」）；`LLMModel.name` 是「显示名」（`llm_server.py:58`）——spec 决议-3「用户在页面看到并输入的调用名」= `model_name`。
- **备选分隔符**：`::`（无生态先例）/ `@`（与 Ollama `name@digest`、部分网关的版本后缀撞）/ `:`（Ollama tag `qwen2.5:7b` 就在 `model_name` 里，撞）/ **`/`**（OpenRouter / LiteLLM 生态的 `provider/model` 写法，引擎已接受）
- **选定**：**`/`**（全自动模式定案）。`LLMServer.name` 租户内唯一（K3），限定名在租户内恒唯一。
- **解析算法 `resolve_model_name(tenant_id, requested) -> ResolvedModel`**（落 `llm/domain/services/model_catalog.py`，三处同源）：
  1. 取可用集合 `C`（D6：对话类 `model_type == 'llm'` 且 `online == True` 的模型，带服务器名 / 类型 / id）；
  2. **精确匹配 `model_name == requested`** → 命中 1 个：返回；命中 ≥ 2：抛 26214，`candidates` = 各命中的 `f"{server.name}/{model_name}"`；
  3. 命中 0 且 `requested` 含 `/`：对 `C` 中每个 `server.name` 满足 `requested.startswith(server.name + "/")` 的服务器，检查 `model_name == requested[len(server.name)+1:]`；命中 1 个返回（限定名在名称唯一时同样可用，AC-12）；命中 0 进第 4 步；命中 ≥ 2 结构上不可能（服务器名唯一）；
  4. 未命中：在**未过滤集合**里再查一次以区分原因——同名模型存在但 `online == False` → 26212；存在但 `model_type != 'llm'` / 属他租户 / 完全不存在 → 26211（**不区分**"没有"与"不属于你"，AC-13）；服务器被删（模型行残留、`server_id` 无对应）→ 26213。
- **`GET /models` 的 `id`**：`model_name` 在 `C` 内唯一 → 原名；否则每个同名项只给限定名（AC-12「模型列表对歧义模型只给出限定名」）；`owned_by` = 服务商名；扩展键 `bisheng_model_type="llm"`、`bisheng_qualified_name`（恒给限定名，供 agent 想写稳定名时用）。
- **原因**：精确匹配保证「页面看到什么名字、代码里就写什么」；先裸名后限定名保证 `model_name` 本身含 `/`（OpenRouter 风格 `qwen/qwen-2.5-72b`）且唯一时仍可裸名直调；第 4 步的两次查询只在失败路径发生，不影响热路径。
- **何时该重新考虑**：模型管理页引入租户内唯一名约束（本规则退化为空转，契约不改）。

### D6：可用范围计算与缓存 = `llm` 域新增 `model_catalog.py`（服务器集合 helper 从 `get_all_llm` 抽出）+ 进程内 60s TTL 缓存 + fail-closed

- **备选**：
  - A. 直接调 `LLMService.get_all_llm(operator=None)` 再过滤 — 它做前端专用的 `is_root_shared_readonly` / Root 租户名水合、每次两个额外查询（`_check_is_global_super`、`TenantDao`），且 FGA 异常被吞（K4）
  - B. 在 `open_api` 域自己写一份"租户可见服务器"查询 — 与 `get_all_llm` 漂移；F052 / F055 再各抄一份就是三份
  - C. **抽公共 helper** `LLMService.acollect_visible_server_ids(tenant_id, *, strict: bool) -> list[int]`（把 `llm.py:419-453` 的 own + shared + inherited 合并逻辑原地抽出——`leaf_id = get_current_tenant_id() or ROOT_TENANT_ID` 到 `llm_servers = list(own)` 为止，`get_all_llm` 改调它，行为不变）；`model_catalog.list_callable_chat_models(tenant_id) -> list[CallableModel]` = helper → `bypass_tenant_filter()` 下 `LLMDao.aget_server_by_ids` + `aget_model_by_server_ids` → 过滤 `model_type=='llm' and online`；`CallableModel(model_id, model_name, server_id, server_name, server_type, qualified_name, is_unique)`
- **选定**：**C**（全自动模式定案）
- **fail-closed（AC-35）**：给 `LLMDao.aget_shared_server_ids_for_leaf` 加 keyword-only `raise_on_error: bool = False`（默认行为不变，前端列表照旧"少看到"）；catalog 以 `raise_on_error=True` 调用，任何 FGA / DB 异常 → 26216（503），**绝不**用旧缓存或缩窄集合放行。
- **缓存**：`model_catalog` 内独立 `TTLCache(maxsize=256, ttl=settings.open_api.model_catalog_ttl_seconds)`（新 Settings 键，默认 30、上限 60；**键 = tenant_id**），命中 → 直接解析；未命中 → 重算。**只缓存成功结果**，异常不缓存。60s 上界（AC-14）由 `ttl ≤ 60` + `LLM_CACHE` 60s 共同保证：本面解析拿到 `model_id` 后 `get_bisheng_llm` 仍走 `aget_model_by_id_with_share_fallback(cache=True)`（K5），两层都 ≤ 60s。
- **原因**：C 让 F052 模型清单工具（AC-13）与 F055 预检（AC-07 / T060）`from bisheng.llm.domain.services.model_catalog import resolve_model_name, list_callable_chat_models` 即三处同源；缓存按租户而非按 key（AC-09「租户级、非 per-key」）。
- **何时该重新考虑**：租户数 × 服务器数让 `maxsize=256` 频繁淘汰（观测 `model_catalog.cache_miss` 指标）→ 改 Redis 缓存并加主动失效。

### D7：主体范围策略与托管应用钩子 = `ModelRangePolicy` 按 `actor_kind` 分派 + 两个 Port（能力声明读取 / 访问凭据验签）由 F055 / F054 注册

- **今天能落地的**：`OpenApiPrincipal`（`open_api/domain/context.py:11-33`；`actor_kind: Literal["service_account", "natural_person", "hosted_app"]` 在 `:15`，同文件 `:43` 的 `OpenApiExecutionSnapshot` 带同一 Literal——**2026-09-16 F055 T055 已把两处一起扩完，T022 据此去掉了测试夹具里的 `model_construct` 变通**）`actor_kind in {"service_account", "natural_person"}` → 租户级范围（D6），subject = 主体自身（`subject_kind = actor_kind`, `subject_id = actor_id`）。**自然人（PAT）今天不可能到达本面**：`_validate_personal_token` 只放行 `["knowledge:read"]`（`credential_service.py:295-296`），持 PAT 请求本面必 26003；本面不为它写特殊分支，只保证不崩。
- **钩子接口（本 Feature 定义、本 Feature 注册默认实现、F055 / F054 替换）**，落 `open_api/domain/services/model_range_policy.py`：
  - `class HostedAppDeclarationPort(Protocol): async def declared_model_names(self, app_id: str, tenant_id: int) -> frozenset[str] | None`——返回该应用**当前生效能力声明**中的模型名集合（原名或限定名，按 D5 规则解析后与 `C` 求交）；`None` = 无法读取 → 26216；空集 = 声明了零个模型 → 一切模型请求 26215。默认实现：抛 `NotImplementedError` 包装成 26216（未注册即 fail-closed）。F055 T056 注册真实实现（读 `AppDeployment.manifest.capabilities`，`app_publish/domain/models/app_deployment.py:158`）。
  - `class AccessSubjectVerifierPort(Protocol): def verify(self, token: str, *, app_id: str, tenant_id: int) -> AccessSubject | None`——`AccessSubject(user_id: int)`；验签失败 / 过期 / `app_id` 不匹配 → `None`。默认实现恒返 `None`。F054 把 `_issue_obo_token` 的 secret / aud / iss 常量抽到共享模块并提供 `verify_obo_token`（`entry_authz_service.py:379-426` 的对偶），注册为实现。
  - `register_hosted_app_declaration_port(port)` / `register_access_subject_verifier(port)`——进程启动期注册（**API 进程 lifespan 即可**：本面只在 API 进程执行，C8 无 worker 侧）。
- **hosted_app 分支**（`principal.actor_kind == "hosted_app"`；F055 T055 已在 `OpenApiPrincipal.actor_kind` Literal 与 `SUBJECT_RESOLVERS` 落地 —— **应用标识取 `principal.subject_ref`（= `app.id` uuid），不是 `actor_name`**，后者是应用显示名，见 §4.2 ④）：范围 = `declared ∩ C`；`/models` 只返回交集；请求模型 ∈ `C` 但 ∉ `declared` → 26215（与 26212 / 26213「已收回」可区分，AC-34）；`declared` 中的模型已下线 → 26212（F055 AC-53 据此在发布面标「已失效」）。subject：请求头 `X-BiSheng-Access-Token` 存在且验签有效 → `subject_kind="user"`, `subject_id=user_id`；不存在 → `subject_kind="app_self"`, `subject_id=None`（显式标注、不拒绝，spec 决议-5）；存在但无效 → **拒绝** 26204（伪造 / 过期的访问凭据不能落成「应用自身」——那会让归属可被操纵）。
- **服务账号分支**：请求头 `X-BiSheng-Access-Token` **存在即 26204**（AC-22，无论值是否有效）；`X-On-Behalf-Of` 由依赖层拒（26004 / 26005，K1），但 **`X-End-User` 依赖层会静默放行**（坑 18）——故 `resolve_range_and_subject` 的**第一步**就是 `if headers.get("X-End-User") is not None: raise ModelFaceIdentityHeaderRefusedError()`（26205），对全部 `actor_kind` 一视同仁（托管应用同样不承载委托）。
- **判定顺序固定**（可测试）：① 26205 身份头拒 → ② 26204 访问凭据拒（服务账号附带 / 托管应用验签失败）→ ③ 范围确立（26216 / 26215）→ ④ 名称解析（26211–26214）。先拒后判，保证「带了不该带的头」永远不会因为模型名恰好也错而收到 26211，agent 的纠错顺序才稳定。
- **原因**：范围与 subject 都不经任何请求头字段决定（决议-5）；Port 让 F051 今天就能把 hosted_app 分支写完并用 fake port 测通（T022–T025），F055 / F054 落地时只注册实现、不改本面；默认实现 fail-closed 保证「F055 没接、凭据却先出现了」不会放行。
- **何时该重新考虑**：F055 决定托管应用凭据的 `scopes` 不含 `model:invoke`（那时 26003 先于本策略生效，本策略永不触发——无害）。

### D8：请求翻译与流式组装 = pydantic `extra="allow"` 白名单透传 + `convert_to_messages` + `llm.bind(tools, tool_choice)` + 手工 chunk 组装

- **请求模型** `ChatCompletionRequest`（`open_api/domain/schemas/model_gateway.py`）：`model: str`、`messages: list[dict]`（≥ 1）、`stream: bool = False`、`stream_options: {include_usage: bool} | None`、`temperature / top_p / max_tokens / max_completion_tokens / stop / n / presence_penalty / frequency_penalty / seed / response_format / tools / tool_choice / parallel_tool_calls / user`，`extra="allow"`（AC-18「超出枚举的字段原样透传但不作承诺」——未知字段收进 `model_extra` 一并作为 `**kwargs` 透传给 `astream / ainvoke`）。**硬拒**：`n > 1`（`BishengLLM` 单候选）→ 26203；`model` 空 → 26203。**不改写**任何采样参数、不注入 system 提示（AC-17）；`messages` 原样经 `langchain_core.messages.utils.convert_to_messages`（识别 `system / user / assistant(+tool_calls) / tool(tool_call_id)` 字典，多模态 content 数组原样保留）。
- **实例化**：`LLMService.get_bisheng_llm(model_id=resolved.model_id, app_id="model_gateway", app_type=ApplicationTypeEnum.MODEL_GATEWAY（新增枚举值 `"model_gateway"`）, app_name=f"model_gateway:{principal.actor_kind}:{principal.actor_id}", user_id=principal.effective_user_id or principal.resource_owner_user_id or 0, streaming=req.stream, temperature=req.temperature, …)`——`user_id` 取法与 `open_endpoints/domain/utils.py:19-26 _principal_user_id` 一致（服务账号 → 资源归属人，遥测按人可追溯）。`tools` 存在 → `llm = llm.bind(tools=req.tools, tool_choice=req.tool_choice)`（`BishengLLM.bind_tools` 会再 `convert_to_openai_tool`，OpenAI 形状的 dict 进出不变）。
- **非流式**：`await llm.ainvoke(messages, **kwargs)` → `AIMessage` → `chat.completion`：`id="chatcmpl-"+uuid`、`choices[0].message = {role:"assistant", content, reasoning_content?, tool_calls:[{id, type:"function", function:{name, arguments(JSON 字符串)}}]}`、`finish_reason = "tool_calls" if tool_calls else "stop"`（上游给了 `length` / `content_filter` 则透传 `response_metadata.finish_reason`）、`usage = {prompt_tokens, completion_tokens, total_tokens}`（`parse_token_usage` 的 `ChatResult` 分支要求——用 `agenerate` 路径拿 `ChatResult`，或对 `AIMessage.usage_metadata` 直接取，两者数值一致，实现取后者但**同一份 `get_token_from_usage`**）。
- **流式**：`StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})`；`async for chunk in llm.astream(messages, **kwargs)`：
  - 首块先发 `delta={"role":"assistant","content":""}`；文本 → `delta.content`；`reasoning_content`（`extract_reasoning_content(chunk)`）→ `delta.reasoning_content`（DeepSeek / Qwen 思考模型的事实扩展键，官方客户端忽略）；`chunk.tool_call_chunks` → `delta.tool_calls=[{index, id?, type:"function", function:{name?, arguments}}]`（**index 由本面按 tool_call 出现顺序分配并稳定**，坑 6）；
  - 记住**最后一个 chunk**；结束时 `finish_reason`（`tool_calls` / `stop` / 上游 `length`）作为独立 chunk；`stream_options.include_usage` 为真 → 追加 `choices=[]` + `usage` 的 chunk（`parse_token_usage(last_chunk)`，K8）；最后 `data: [DONE]`；
  - 中途异常 → `data: {"error": {…26234 或分类后的上游码…}}` 一行 + `data: [DONE]`，生成器 `return`（AC-16 不挂起）；客户端断开（`request.is_disconnected()` 或 `asyncio.CancelledError`）→ 记录 `result="client_disconnected"`，不重试。
- **原因**：`BishengLLM` 的 `_astream` 已 `normalize_reasoning_content`（K6），tool_call 增量在 `AIMessageChunk.tool_call_chunks` 里齐全；手工组装比复用 `published_assistant_service` 精度高（后者无 tool_calls / usage，K11）。
- **何时该重新考虑**：langchain-openai 提供官方「chunk → OpenAI dict」序列化（届时替换组装函数、测试不变）。

### D9：ModelCallRecord = 独立表 `model_call_record` + 泛化的批量异步写入器；被拒调用由既有 `open_api.call` AuditLog 承接

- **备选**：
  - A. 写进 `audit_log`（`action="open_api.model_call"`）— K7：高频写淹审计页；`audit_log` 是 uuid 主键 + 多索引宽表，写放大在 DM8 上更糟
  - B. 加列到 `llm_call_log` / `llm_token_log` — 两表无 key / app / subject 维度且各有既定 owner；release-contract 表 1 已单独登记 ModelCallRecord
  - C. **新标准表**（`create_all` 建，无 Alembic）+ **`BatchedRecordWriter[T]`**（把 `OpenApiCallAuditService` 的队列 / 批 / 定时 / 关停逻辑抽成泛型基类 `open_api/domain/services/batched_writer.py`；`OpenApiCallAuditService(BatchedRecordWriter[AuditLog])` 保持公开名与常量、行为不变；`ModelCallRecordWriter(BatchedRecordWriter[ModelCallRecord])` 用 `ModelCallRecordRepository.ainsert_batch`）；`main.py` lifespan 起停两者（`:108 / :154` 旁）
- **选定**：**C**（全自动模式定案）
- **表**（`open_api/domain/models/model_call_record.py`，`SQLModelSerializable`）：见 §4.2 ④。**注册方式是坑**：`_TENANT_AWARE_MODEL_MODULES` 登记的是**包** `"bisheng.open_api.domain.models"`（`core/database/tenant_filter.py:107`），`_force_import_all_models` 只 import 包 `__init__`——`__init__.py` 今天显式 import 四个模块并列 `__all__`；新模块**必须**加进 `__init__.py` 的 import 与 `__all__`，否则 `create_all` 看不到这张表（升级不建表）、租户过滤也不发现它（坑 17）。`create_time` 用 `server_default=text("CURRENT_TIMESTAMP")`（同 `api_credential.py:82`，双 DB 已验证），不用 `func.now()`。索引：`ix_mcr_tenant_time (tenant_id, create_time, id)`、`ix_mcr_credential_time (credential_id, create_time)`、`ix_mcr_app_time (app_id, create_time)`——AC-24 三个筛选器各命中一条；服务账号 / 模型 / token 是记录列不建索引。
- **写入时机**：解析成功后 `record = ModelCallRecord(…result=None)` 先构造；调用结束（成功 / 上游失败 / 客户端断开）填 `result / tokens / latency_ms / ttft_ms / error_code` 后 `writer.enqueue(record)`；解析失败（26211–26216）也 `enqueue`（`result="model_unavailable"`，`requested_model` 保留、`model_id` 空）——AC-20「到达模型解析阶段…无论成功、上游失败或模型不可用」。**在解析前被拒**（401 / 403 / 26051）不写本表：中间件的 `open_api.call` 行已带 `credential_id / actor / scope / error_code`、`target_id="POST /api/v2/model/v1/chat/completions"`（`middleware.py:102-133`），即 AC-20 的「被拒调用审计事件」。
- **队列满 / 写失败**：`logger.error("open_api.model_call_record.write_failed | reason=…")` + `emit_metric("model_call_record", status="dropped")`——不阻塞请求、不静默（C8 末行）。队列上限 5000、批 200、1s（高于审计的 1000 / 100：本面每请求恰一行、体积小）。
- **查询 API**（供 F056）：`ModelCallRecordRepository.alist(tenant_id, *, credential_id=None, app_id=None, time_from=None, time_to=None, cursor=None, limit=100)`，排序 `(create_time DESC, id DESC)`（坑 9），游标 = `(create_time, id)`；`aiter_export(...)` 同条件生成器（F056 导出用）。本 Feature **不提供 HTTP 查询端点**（AC-24 的管理面接线归 F056）。
- **何时该重新考虑**：单租户日调用 > 1e6 行（那时按月分表或转 ES，读接口不变）。

### D10：token 口径 = MODEL_INVOKE 遥测同源；ModelCallRecord 不写 `llm_token_log`；未知 = NULL

- **备选**：写 `LLMTokenTracker.record_usage`（`token_tracker.py:38-72`，`user_id` 必填）— 它是工作流回调专用账本（K8），本面再写就是第三处；且服务账号无 `user_id`，只能借归属人。
- **选定**（全自动模式定案）：`BishengLLM` 包装器自动写 MODEL_INVOKE 遥测（`app_type=MODEL_GATEWAY`，AC-23「计入平台既有 token 用量口径」由此成立）；ModelCallRecord 的 `prompt_tokens / completion_tokens / total_tokens` 从**同一个最终结果对象**经 `parse_token_usage` 取（非流式 = `AIMessage`，流式 = 最后一个 chunk，与 `utils.py:389-408` 的 `result=item` 完全一致）；`total_tokens == 0 and prompt_tokens == 0` → 三列写 **NULL**（未知，AC-23），不估算。已知口径差异：遥测无「未知」概念、会记 0——登记为坑 5，不改遥测。
- **`llm_token_log` 不写**；将来 v3.1 账单按 spec 决议-6 在 **ModelCallRecord 上直接聚合**（已带 key / app / subject / model 维度），不反查遥测。

### D11：错误码 262 段 = `common/errcode/model_face.py`，base 26200，四个子段

| 子段 | 用途 | 本期启用 |
|---|---|---|
| 26200–26209 | 协议面 / 端点 / 请求形状 | 26201 端点不支持 · 26202 Anthropic 路径 · 26203 请求不合法 · 26204 访问凭据不被接受（服务账号附带 / 托管应用无效）· **26205 委托类身份头在本面不被接受**（补底座对合法 `X-End-User` 的静默放行，坑 18） |
| 26210–26229 | 可用范围与名称解析 | 26211 不存在 · 26212 已下线 · 26213 已收回（服务商删除）· 26214 裸名歧义 · 26215 能力未声明 · 26216 目录不可判定（503）· 26217 服务商日上限（429） |
| 26230–26249 | 上游与流式 | 26231 上游失败（502）· 26232 上游拒绝（透传状态）· 26233 上游限流（429）· 26234 流式中断（仅 SSE 事件） |
| 26250–26259 | 记录与账本（预留） | 本期无对外码；写入失败只记日志 / 指标 |

- 基类 `ModelFaceError(OpenApiAuthError)`——**继承 `OpenApiAuthError` 是为了白吃 `http_status` 属性与 `open_api_http_status()` 的 `issubclass(OpenApiAuthError)` 分支**（`exception_handlers.py:54-55`），不是语义上的"鉴权错误"；额外类属性 `openai_type: str`、`openai_code: str`（D4 表）。`Code: int = 262xx`（K13）。26232 的 `http_status` 在实例上覆盖（基类 `__init__` 已支持 `http_status=` kwarg，`open_api.py:11-21`）。
- 三语文案 `locales/api_errors/{zh-Hans,en,ja}.json`（**文件名是 `en.json`**，与 `platform/public/locales/en-US/` 的目录命名不同，别找错）同 PR；`docs/constitution.md` C5 表 26x 行加 `262 model_face` + 子段说明；`release-contract.md`「已分配模块编码」加 262 行（T001）。**权限位本身的三语文案不必补**：`openApiManagement.scopes.model_invoke.{label,desc}` 已在 `platform/public/locales/{zh-Hans,en-US,ja}/bs.json` 三语齐备（F049 登记位时随手写全了），D12 翻 `issuable` 后签发表单直接有文案。

### D12：`model:invoke` 翻 `issuable=True` + 端点登记 + 客户契约再生成

- `open_api/domain/scopes.py:139-147`：`endpoints=(("POST", "/api/v2/model/v1/chat/completions"), ("GET", "/api/v2/model/v1/models"), + catch-all 五条)`、删 `issuable=False` 与注释；`requires_open_platform=True` 保持（开关未开时签发表单不出现，AC-28 反向「无面无位」）。
- **受影响测试的完整清单（必须同批改，逐条 grep 核实过）**：
  1. `test/open_api/test_scope_issuability.py:66-69` — `@pytest.mark.parametrize("scope", ["model:invoke", "identity:read"])` 去掉 `model:invoke`，另加「开关开启即可签发」正向断言；
  2. 同文件 `:176` — `{"model:invoke","identity:read"}.isdisjoint(codes)` 改 `"identity:read" not in codes and "model:invoke" in codes`；
  3. 同文件 `:4` — 模块 docstring「``model:invoke`` / ``identity:read`` stay unissuable (F051 / F052 pending)」改只留 `identity:read`；
  4. `test/open_api/test_scopes.py:44-51` `test_only_app_manage_becomes_issuable_with_open_platform` — **函数名要改**（`test_app_manage_and_model_invoke_become_issuable_with_open_platform`），且 `:49` 与 `:50`（`codes == ALWAYS_ISSUABLE_OPEN_API_SCOPE_CODES | {"app:manage"}`）**两条断言都会红**；
  5. 同文件 `:35-41` `test_extension_scopes_are_not_issuable_without_open_platform` — **不用改**：`requires_open_platform=True` 保留，开关关闭时 `issuable_scopes()` 仍把它挡掉（`scopes.py:201`）；
  6. `test_open_api_route_matrix.py` 与 `test_openapi_schema_contract.py:34-56` — 见 D3 末段的「期望集合剔除」方案；契约 json 重跑 `features/v3.0.0-beta1/053-openapi-auth-and-identity/generate_openapi_contract.py` 再生成，**并把本面三条操作的 OpenAI 形状 response_model 挂上**（`GET /models` 用 `ModelList`，`POST /chat/completions` 用 `ChatCompletionResponse`；流式分支靠 `responses=` 补 `text/event-stream` 描述）。

### D13：上限与限流 = 沿用服务商 `limit_flag / limit`（typed 异常）；不新增任何闸

- `utils.py:126 / :136` 的裸 `Exception("… Quota used up")` 改为新类 `LlmProviderDailyLimitExceededError(Exception)`（同 message、同基类——既有 `except Exception` 调用方零感知），本面据类型映射 26217（429，`Retry-After` 不给：日限额到次日零点，写进 message）。**跨 Feature 副作用**：改的是 `llm` 域共享 util，登记 §6 / tasks 表。
- 不做 per-key / per-app 限流、不做 token 上限（AC-15 / AC-25）。

### D14：日志与脱敏 = 结构化 `model_gateway.call` 一行 / 请求；密钥 / 服务商配置 / 消息正文三不进

- 端点出口 `logger.bind(event="model_gateway.call").info(...)` 字段：`credential_id / actor_kind / actor_id / tenant_id / requested_model / model_id / server_id / is_stream / result / error_code / prompt_tokens / completion_tokens / latency_ms / ttft_ms / trace_id`。**不记** `Authorization`、`X-BiSheng-Access-Token`、`messages`、`tools` 内容、上游 URL / key（`LLMServer.config`）。错误 message 进响应前经 `redact_secrets(text)`（正则抹 `sk-…` / `bs-sak-…` / `Bearer …`），防服务商 SDK 把 key 回显进异常文本。
- ModelCallRecord `credential_mask` 用 `ApiCredential.key_mask`（前缀 + 末四位，INV-28）；`OpenApiPrincipal` 不带掩码且不为此改 beta2 契约，故请求路径入队时留空、写入器在 `write_batch` 前按 `credential_id` **批内一次 `IN` 查询水合**（在 `bypass_tenant_filter()` 下——写入器无请求 ContextVar、批内行跨租户，§2 C3），热路径零额外 DB 读。

---

## 4. 系统现状（接手必读）

> 本节写"落地后代码长什么样"；未开工前是目标形态，实现后按现状覆盖。

### 4.1 数据流

**对话补全（流式）**：
`POST /api/v2/model/v1/chat/completions` → `router_rpc` 依赖 `verify_open_api_access`（`dependencies.py:57-163`：凭据 → 租户 ContextVar → marker → `delegate` 拒 26051 → 位判定 26003 → 身份头拒 → `PermissionActor`）→ 端点 `chat_completions`（`open_api/api/endpoints/model_gateway.py`，`@open_api_scope("model:invoke", modes=("S",))`，`Depends(get_open_api_execution)`）→ `ModelGatewayService.complete(principal, request, req)`（`open_api/domain/services/model_gateway_service.py`）：① `ModelRangePolicy.resolve_range_and_subject(principal, headers)` → `(range, subject)`（D7 的四步判定序：`X-End-User` → 26205 / 服务账号附带访问凭据 → 26204 / 范围不可判定 → 26216 / 未声明 → 26215）② `model_catalog.resolve_model_name(tenant_id, req.model, range=range)`（D5 / D6；失败 → 26211–26216，仍 `enqueue` 记录）③ `LLMService.get_bisheng_llm(...)`（`limit_flag` 超 → 26217；10009 / 10010 / 10012 / 10013 → 26213 / 26212 / 26231）④ `bind(tools)` → `astream` → SSE 组装（D8）⑤ 结束 / 异常 / 断开 → `ModelCallRecordWriter.enqueue(record)` + 结构化日志（D14）→ `OpenApiAuditMiddleware` 另写一行 `open_api.call`（K7；SSE 尾部解析对本面无 `event:close` 结构、`sse_final_result` 恒 `success`——坑 10）。

**模型列表**：`GET /api/v2/model/v1/models` → 同一依赖 → `ModelRangePolicy.resolve_range_and_subject`（同样的 26205 / 26204 前置拒绝）→ `model_catalog.list_callable_chat_models(tenant_id)` → 按 range 过滤 → `ModelList`（D5 命名规则）。不写 ModelCallRecord（列表不是调用）。

**承诺面之外**：`/api/v2/model/v1/{rest}` → 同一依赖（无凭据仍 401）→ 26201 / 26202（D3）。

**开关关闭**：路径不存在 → 404 `{"detail":"Not Found"}`（D3）。

### 4.2 关键数据结构 / 字段约定（对外契约）

① **端点**（base URL = `{public_base_url}/api/v2/model/v1`）

| 方法 路径 | 位 / 模式 | 请求 | 响应 |
|---|---|---|---|
| `POST /chat/completions` | `model:invoke` / S | `ChatCompletionRequest`（D8） | `stream=false`: `ChatCompletionResponse`；`stream=true`: `text/event-stream`，每行 `data: {chat.completion.chunk}`，末 `data: [DONE]` |
| `GET /models` | `model:invoke` / S | — | `{"object":"list","data":[{"id","object":"model","created","owned_by","bisheng_model_type","bisheng_qualified_name"}]}` |
| `* /{rest}` | `model:invoke` / S | — | 404 OpenAI 错误体（26201 / 26202） |
| `GET /api/v2/auth/whoami`（既有） | `None` | — | 新增 `model_base_url: str` |

② **错误体**：`{"error":{"message","type","code","param","bisheng_code"}}`，映射表见 D4；HTTP 状态真实。流式中途错误：`data: {"error":{…}}\n\n` + `data: [DONE]\n\n`。

③ **环境变量名**（本 Feature 定名；F053 `dev` 与 F054 runtime-manager 注入）：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`BISHENG_MODEL_BASE_URL`。托管应用凭据变量名 `BISHENG_APP_TOKEN` 归 F055 D13（本面对其值只当 Bearer）。

④ **表 `model_call_record`**

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | BigInteger PK autoincrement | |
| `tenant_id` | Integer NOT NULL | 密钥租户（自动过滤） |
| `credential_id` | BigInteger NOT NULL | `api_credential.id` |
| `credential_mask` | VARCHAR(32) | `bs-sak-********xxxx` |
| `actor_kind` / `actor_id` / `actor_name` | VARCHAR(32) / BigInteger / VARCHAR(128) | 服务账号 / 自然人 / 托管应用。**`hosted_app` 的语义按 F055 T055 `resolve_hosted_app` 回填（2026-09-16 核实）**：`actor_id = hosted_app_subject.id`（每应用一行的代理主键，不是 `app.id`、也不是 owner 的 user id）、`actor_name = app.name`（**显示名**）、`resource_owner_user_id = app.owner_user_id`。应用的机器标识只有一个来源 —— `principal.subject_ref = app.id`（uuid），落到下一行的 `app_id` 列 |
| `resource_owner_user_id` | BigInteger NULL | 归属人（AC-20 可追溯） |
| `app_id` | VARCHAR(64) NULL | 托管应用（AC-21）。值 = `principal.subject_ref`（`app.id` uuid）；**声明读取、访问凭据验签、`ix_mcr_app_time` 查询三处都键在它上面**，写成 `actor_name` 会让三者同时指向一个显示名 |
| `subject_kind` / `subject_id` | VARCHAR(16) / BigInteger NULL | `service_account` \| `natural_person` \| `user` \| `app_self` |
| `requested_model` | VARCHAR(255) | 请求原文 |
| `model_id` / `server_id` | Integer NULL | 解析结果（失败为空） |
| `model_name` / `server_name` / `server_type` | VARCHAR(255) / VARCHAR(255) / VARCHAR(20) NULL | |
| `is_stream` | Boolean | |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | Integer NULL | NULL = 未知 |
| `result` | VARCHAR(32) | `success` \| `upstream_failed` \| `model_unavailable` \| `limit_exceeded` \| `capability_undeclared` \| `client_disconnected` |
| `error_code` / `http_status` | Integer NULL / Integer | 平台码 / 对外状态 |
| `latency_ms` / `ttft_ms` | Integer / Integer NULL | |
| `request_id` / `trace_id` | VARCHAR(64) / VARCHAR(64) | `chatcmpl-…` / `trace_id_var` |
| `create_time` | DateTime NOT NULL `server_default=text("CURRENT_TIMESTAMP")` | 索引见 D9 |

⑤ **`llm` 域公开函数**（三处同源）：`list_callable_chat_models(tenant_id) -> list[CallableModel]`、`resolve_model_name(tenant_id, requested, *, range: ModelRange | None = None) -> ResolvedModel`（异常 = D11 的 26211–26216 类）、`CallableModel.qualified_name`。

⑥ **Port**：`HostedAppDeclarationPort`、`AccessSubjectVerifierPort` 与注册函数（D7）；请求头 `X-BiSheng-Access-Token`。

⑦ **新 Settings 键**：`open_api.model_catalog_ttl_seconds: int = 30`（上限 60）。加在既有 `open_api` 子键下——**不是**新顶级键，老镜像不受影响。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `open_api/api/endpoints/model_gateway.py` | 三条路由、marker、`StreamingResponse` 头、把 `Request` 交给 service | 不解析模型、不组装 chunk |
| `open_api/domain/services/model_gateway_service.py` | 编排：范围 → 解析 → 实例化 → 调用 → 组装 → 记录 | 不查 ORM、不判凭据 |
| `open_api/domain/services/openai_codec.py` | OpenAI ⇄ langchain 翻译（messages、tools、chunk / response 组装、usage） | 无 I/O |
| `open_api/domain/services/model_range_policy.py` | 按 `actor_kind` 决定范围与 subject；Port 定义与注册 | 不读 manifest（F055 实现 Port） |
| `open_api/domain/services/model_call_record_writer.py` + `batched_writer.py` | 批量异步写；泛型基类 | 不做查询 |
| `open_api/domain/repositories/model_call_record_repository.py` | `ainsert_batch / alist / aiter_export` | 无业务判断 |
| `open_api/domain/models/model_call_record.py` | 表定义 | |
| `open_api/domain/schemas/model_gateway.py` | `ChatCompletionRequest / Response / Chunk / ModelList / OpenAIError` | |
| `open_api/api/exception_handlers.py` | 本面前缀的 OpenAI 错误体分支 `render_openai_error` | 不改其它 v2 路径 |
| `llm/domain/services/model_catalog.py` | 目录、缓存、名称解析（三处同源） | 不知道凭据 / 主体 |
| `llm/domain/services/llm.py` | 抽 `acollect_visible_server_ids`；`get_all_llm` 改调 | 行为不变 |
| `common/errcode/model_face.py` | 262 段 | |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 现存两个 v2 `chat/completions` 都不是模型直连：`open_endpoints/api/endpoints/assistant.py:35-36` 的 `model` 字段是 **assistant_id**（`UUID(req_data.model)`），`workstation.py:27` 是日常会话（建会话、持久化） | 拿它们"顺手改一改"当模型面 → 建会话、留正文，AC-17 / AC-19 全破 | D1 新路径、不碰两者 |
| 2 | `aget_shared_server_ids_for_leaf` FGA 异常时**返回空列表**（`llm_server.py:508-510`），前端列表只是少显示 Root 共享服务商 | 本面照抄 → FGA 抖动期间子租户密钥调 Root 共享模型得到 26211「不存在」，看起来像配置错；AC-35 要求 503 拒绝 | D6 `raise_on_error=True` |
| 3 | 服务商日上限超出是**裸 `Exception`**（`utils.py:126`）且发生在生成器包装器 `bisheng_model_limit_check` 里——`astream` 第一次迭代时才抛 | 按异常类型分类做不了；流式已发 `200` 头后才炸 → 客户端收到半截 | D13 typed 异常；D8 流式采用**"预取首块"**：端点先 `agen = llm.astream(...)`、`first = await anext(agen)`，此步抛 26217 / 26211 族 / 上游 4xx 时以普通 JSON 错误体返回（真 HTTP 状态），成功后才构造 `StreamingResponse`，生成器先 yield 已预取的 `first` 再续 `agen`。**不要**在外面再调一次 `bisheng_model_limit_check`——包装器内已 `INCR`，会计两次 |
| 4 | `BishengLLM` 遥测必填 `app_id / app_type / app_name / user_id`（`base.py:21-25`），`ApplicationTypeEnum` 无本面成员 | 借用 `DAILY_CHAT` 之类会把本面用量混进工作台统计 | D8 新增 `MODEL_GATEWAY` |
| 5 | 流式遥测的 usage 只看**最后一个 chunk**（`utils.py:382-409`），且遥测没有「未知」——取不到就记 0 | ModelCallRecord 若从累加或首块取，与遥测两套口径（AC-23 破）；反过来若照遥测记 0，AC-23「未知≠0」破 | D10：同一最后 chunk；记录侧 0 → NULL；差异登记 |
| 6 | langchain `AIMessageChunk.tool_call_chunks` 的 `index` 在部分服务商（qwen / zhipu 经各自 SDK）为 `None`，且同一 tool_call 的 `id` 只在首块出现 | 客户端按 `index` 聚合 arguments，`None` → 全部拼到一个调用里，多工具调用错乱 | D8 本面按首次出现顺序分配并缓存 `index`；测试用双工具调用夹具 |
| 7 | `open_api_scope` 的 `modes` 默认 `("S","D")`（`scopes.py:227`）——本面**必须显式 `modes=("S",)`**；另外 `LOCAL_DEV_TOOLKIT_SCOPE_CODES` 的 26051 判定看的是 `marker.scope`，catch-all 路由若标 `None` 就不会拒 `delegate` 密钥 | 持 `delegate` 的密钥打承诺面之外路径得到 26201 而非 26051（AC-26「不得只回参数错误码」） | D3 catch-all 也标 `model:invoke` |
| 8 | `_register_v2_handler` 的 `dispatch` 先于 `open_api_auth_exception_handler` 注册，且 `app.add_exception_handler(OpenApiAuthError, …)` 是**单独**一条（`exception_handlers.py:104`）——本面前缀分支要在**两处**都判 | 只改 `dispatch` → 401 / 403（依赖层抛的 `OpenApiAuthError`）仍是信封体，官方客户端报 "unexpected response" | D4 两处同判 |
| 9 | `create_time` 秒精度，同秒多行无序（backend AGENTS.md 已知陷阱） | 游标分页重复 / 漏行；导出与列表不一致 | D9 排序 `(create_time DESC, id DESC)`，游标含 `id` |
| 10 | `OpenApiAuditMiddleware._record_sse_result` 只认平台 SSE 的 `event:close` 结构（`middleware.py:71-95`），对本面 chunk 恒判 `success` | 审计页 `sse_final_result` 对本面永远 success，错误看 ModelCallRecord 才对 | 本面在中途错误时 `scope["open_api_error_code"]=码`（`mark_open_api_error`），审计行 `error_code` 至少正确 |
| 11 | `test_openapi_schema_contract.py:34-56` 断言 v2 全部 HTTP 操作 == `openapi-v2-key-auth-api.json` | 新路由不再生成契约 → CI 红；且 catch-all `{rest}` 会以五个方法进契约 | D12 再生成；契约 md 按类别文档补「模型协议面」章 |
| 12 | `check-i18n.mjs:106` 只匹配 `Code:\s*int\s*=`；260 段没被校验 | 抄 `open_api.py` 写法 → 漏三语不报错、线上英文兜底 | K13 |
| 13 | `settings.open_platform.enabled` 在 `api/router.py` **import 时**求值（`:140`）——测试里 `monkeypatch` 开关不会重新挂 router；`test_open_api_route_matrix.py:4` 与 `test_openapi_schema_contract.py` 都 `from bisheng.main import app`，单测进程默认开关**关闭**（`OpenPlatformConf.enabled` 默认 `False`，`open_platform.py:9`） | 单测以为"开关关了本面 404"其实 router 早挂上；反过来两个既有集合断言在开关关闭的进程里会因「登记有、实际无」直接红 | D3 末段：期望集合按 `MODEL_GATEWAY_PATH_PREFIX` 剔除；T012 用 `importlib.reload` + 独立 app 工厂验证两态 |
| 14 | `resolve_public_base_url` 的 Host 回退会按进程记一次 warning（`public_base_url.py:64-74`），文案写死"Skill packs" | 本面触发时日志误导运维 | T020 文案泛化为"外部客户端地址" |
| 15 | `RequestValidationError` 在依赖之前发生，`_authenticate_parse_failure`（`exception_handlers.py:133-147`）会重跑鉴权 | 本面无凭据 + 坏 body → 期望 401 不是 400；实现别把 400 分支放在鉴权前 | D4 沿用该顺序 |
| 16 | `X-BiSheng-Access-Token` 由 app-proxy 注入到**应用**（`entry_authz_service.py:175`），不是浏览器 → 本面调用时它必须由应用代码显式转发（SDK / 技能包教） | 应用不转发 → 全部 `app_self`，审计失去用户维度但不报错（spec 决议-5 允许） | F057 SDK / F053 技能包（§6.1 提醒） |
| 17 | `_TENANT_AWARE_MODEL_MODULES` 对 `open_api` 登记的是包名（`tenant_filter.py:107`，注释原文就写着 "package-level registration — the package `__init__` imports …"），发现靠 `open_api/domain/models/__init__.py` 的显式 import 链 | 新表文件写好、`metadata` 里却没有它：`create_all` 不建表，首次写入 `ProgrammingError: Table doesn't exist`，且租户过滤静默不覆盖 | D9 / T003：`__init__.py` 加 import + `__all__`；`test_database_contract.py` 风格断言表在 `SQLModel.metadata.tables` |
| 18 | **合法值的 `X-End-User` 单独出现时，底座不拒、静默采信**：`assert_no_removed_identity_headers` 把 `X-End-User` 列进 `allowed`（`identity_service.py:26`），`parse_identity_headers` 只校验格式（非法才 26018，`:55-57`），`resolve_request_identity` 走 `target_id is None` 分支后 `return principal.model_copy(update={"end_user_id": external_user_id})`（`:71-74`）——**没有任何拒绝**。同理 26016 只在「持 `delegate` 却不带 `X-On-Behalf-Of`」时抛，本面根本到不了（26051 更早） | 照抄「鉴权白吃」的结论 → AC-27「不得静默忽略该头继续执行」直接破；而且它破得很安静：请求正常返回 200，只是 `end_user_id` 被应用方随手指定了一个值 | D4 / D7：本面自己在 `resolve_range_and_subject` 第一步拒 **26205**；T012 有专门用例 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| base URL `{origin}/api/v2/model/v1` + `whoami.model_base_url` + 环境变量名 `OPENAI_BASE_URL / OPENAI_API_KEY / BISHENG_MODEL_BASE_URL` | HTTP / 字段 / 命名 | F053 接入信息区（AC-44）、`bisheng dev`（AC-27）、技能包模型一节（AC-17）；F054 runtime-manager 注入清单（contracts §5 **须回写加入三名**）；F055 T056；F057 指南 |
| `POST …/chat/completions`、`GET …/models`、错误体（D4） | OpenAI 兼容 HTTP | 本地引擎、托管应用（`openai` 官方客户端） |
| `llm.domain.services.model_catalog.{list_callable_chat_models, resolve_model_name}` | Python API | F052 模型清单工具（AC-13）、F055 预检 T060（AC-07） |
| `ModelCallRecordRepository.alist / aiter_export`、表 `model_call_record` | Python API / 表 | F056 审计查询面（AC-25） |
| `HostedAppDeclarationPort` / `AccessSubjectVerifierPort` + 注册函数；头名 `X-BiSheng-Access-Token` | Python Protocol | F055 T056（注册声明读取）、F054（注册 OBO 验签）、F057 SDK / F053 技能包（应用侧转发头） |
| `LlmProviderDailyLimitExceededError`、`LLMService.acollect_visible_server_ids`、`aget_shared_server_ids_for_leaf(raise_on_error=)` | Python API（`llm` 域改动） | 既有调用方零感知；新调用方可用 |
| `ApplicationTypeEnum.MODEL_GATEWAY` | 遥测枚举 | 统计页按应用类型筛选（ES 事件侧；`emit_metric` 指标行不带该维度，§7） |
| **模型能力的运行期错误码归属**：模型的「已收回」= 26212 / 26213、「未声明」= 26215，**一律走 262 段**；F055 的 `16273`（能力已被收回）/ `16274`（未在能力声明中的能力，`055 design` §错误码表 16270–16289）**只用于知识库等非模型能力** | 错误码边界 | F055 T058（发布面「已失效」按需计算时读本面规则）、F052（工具面报错口径） |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| beta2 F053 底座：`router_rpc` 依赖、`@open_api_scope`、`OpenApiPrincipal`、26003 / 26051 / 头拒绝、凭据缓存 ≤ 5s、`resolve_public_base_url`、`OpenApiCallAuditService` | 代码 | marker 语义变化（如 `modes` 默认）会静默放宽本面；坑 7 |
| `LLMService.get_bisheng_llm` / `BishengLLM` / `parse_token_usage` / `LLM_CACHE` 60s | 代码 | K5 / K6；服务商新增类型自动获得 |
| **F055 T055**：`hosted_app` 主体（CHECK 放宽迁移 + `SUBJECT_RESOLVERS` + `OpenApiPrincipal.actor_kind` Literal 扩） | 代码 | **✅ 已落地（2026-09-16 核实）**：`app_publish/domain/services/app_credential_service.py:resolve_hosted_app`，经 `app_publish/composition.py:register()` 注册 |
| **F055 T056**：注册 `HostedAppDeclarationPort` 实现；凭据 `scopes` 含 `model:invoke`；`BISHENG_APP_TOKEN` 注入 | 代码 / 契约 | **✅ 已落地**：`capability_bus_service.HostedAppDeclarationAdapter` + `derive_scopes` + `runtime_capability_env`。未注册 → 默认 fail-closed 26216（不是放行） |
| **F054**：OBO 验签实现（`verify_obo_token`）注册为 `AccessSubjectVerifierPort`；runtime-manager 注入 `OPENAI_BASE_URL` 等三名 | 代码 / 契约 | **✅ 验签已落地**：`app_runtime/domain/services/entry_authz_service.py:verify_obo_token` + `AccessSubjectVerifier`，同样由 F055 组合根注册（两个 Port 必须同进同退）。未注册 → 全部 `app_self`；未注入 → 应用需自拼。⚠️ **入口侧仍是 fail-open**：secret 缺失或与 `jwt_secret` 相同时 `_issue_obo_token` 不签、只记一条日志，应用会收到匿名访问 —— 该收紧归 F054（其代码注释已自记「OBO 有了消费方就要改 fail-closed」），本面这边的表现是全部落 `app_self` |
| F056：查询面与导出接线 | 前端 / 端点 | 本面只保证 repository 与索引 |
| 开关 `open_platform.enabled`、`open_api.public_base_url` | 配置 | 商业版网关形态必须配 `public_base_url`（否则 Host 回退可能是内网地址） |

---

## 7. 测试与可观测

- **单测（无中间件）**：`test/open_api/test_model_gateway_{auth,errors,resolution,stream,record,switch}.py` + `test/llm/test_model_catalog.py`；fake `BishengLLM`（`monkeypatch LLMService.get_bisheng_llm` 返回带脚本化 `astream / ainvoke` 的对象）；fake catalog rows；`fake_redis` / `open_api_db` 沿用 `test/open_api/conftest.py:28-97`。**官方客户端契约**：`openai.AsyncOpenAI(base_url=..., api_key=..., http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)))` 直打 ASGI，断言成功体 / 401 / 403 / 404 / SSE（含 tool_calls）能被 SDK 解析（`openai>=2.26` 已是后端依赖，`pyproject.toml:53`）。
- **集成（CI 中间件）**：真 Redis + MySQL 下的 catalog 缓存与 60s 上界、FGA 下线 → 26216、批量写入落表与游标分页；DM8 用例在 105 回归（新表 + `(create_time, id)` 排序）。
- **114 手动 / E2E**（tasks T026–T028）：`open_platform.enabled=true` → 签一把带 `model:invoke` 的 `bs-sak-` → `curl $BASE/models` → `openai` CLI 流式 → Qwen Code 配 `OPENAI_BASE_URL` 跑一次带工具调用的任务 → Claude Code 指向 base 得 26202 → 模型管理页下线该模型，≤ 60s 新调用 26212、在途流不断 → 撤销密钥 ≤ 5s 401 → `SELECT … FROM model_call_record ORDER BY id DESC LIMIT 5` 与 `audit_log` 的 `open_api.call` 各一行。
- **可观测**：结构化日志 `model_gateway.call`（D14）；`BishengLLM` 自带两条——ES 遥测事件 `ModelInvokeEventData`（**带 `app_type`，按 `model_gateway` 筛本面**）与 `emit_metric("model_invoke", …)`（`utils.py:264-270` 的 kwargs 只有 `model_id / status / is_stream / ttft_ms / total_ms`，**没有 `app_type`，指标行筛不出本面**——要按面看走 ES 事件或 `model_call_record`，别在 Grafana 上找一个不存在的标签）；新增 `emit_metric("model_call_record", status=written|dropped, batch_size=…)`、`emit_metric("model_catalog", status=hit|miss|unavailable)`。

---

## 8. 后续改进 / 不打算做的事

- **聚合账单 / 用量可视 / 限流 / token 上限**（v3.1）：在 `model_call_record` 上聚合（已带维度），入口加闸按 OpenAI 429 语义——不改现有契约。
- **Anthropic 面 / embeddings / Responses**：同一 base URL 下扩承诺面（决议-1），把对应路径从 catch-all 抠出。
- **目录缓存改 Redis + 主动失效**：D6「何时该重新考虑」。
- **不做**：把 `open_api.call` 与 ModelCallRecord 合并（K7）；给模型管理页加唯一名约束（决议-2 备选 ①）；`llm_token_log` 补维度（D10）。
- **AC-25「不做聚合账单 / 用量可视 / 上限」是有测试看住的**（T017 `test_no_aggregation_or_quota_surface`）：断言本面路由只有 §4.2 ① 那三条、`ModelCallRecordRepository` 无任何聚合方法、`OpenApiConf` 无 `*_limit` / `*_quota` 新键。SHALL NOT 类 AC 只写进「不打算做」章节是会漂的——半年后有人顺手加个 `/usage` 端点，没有任何东西会红。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-16 | 初版（D1–D14、坑 1–16、§4.2 契约、§6 依赖；全自动模式定案） | spec 定稿后按 HEAD `fe10f75ea` 核实代码事实编写 |
| 2026-09-16 | `/sdd-review design` 二轮（含 Constitution Check 复核）：**新增 26205 与坑 18**——原文把 AC-27 整条算作「底座白吃」，实测合法值的 `X-End-User` 单独出现时底座静默采信（`identity_service.py:71-74`），AC-27 会破，改为本面自拒；D4 身份头行的四个码逐一订正（26016 在本面不可达、补 26005 / 26018）；D7 增「四步判定序」；D12 受影响测试从 4 条补到 6 条（`test_scopes.py:44-51` 两条断言 + 函数名、`test_scope_issuability.py:4` docstring；并注明 `test_scopes.py:35-41` 不必改）；§7 订正 `emit_metric("model_invoke")` **不带 `app_type`**（只有 ES 事件带）；§2 C3 订正 before_flush 在多租户模式是「完全不填」而非填 `DEFAULT_TENANT_ID`；K11 补同文件 `:94` 的反证；§6.1 增「模型能力运行期错误码归 262、F055 16273/16274 只管非模型能力」一行；行号订正（`llm.py:419-453`、`open_api.py:11-21`）；补「权限位三语文案已齐」事实 | 逐条 grep 核实 `文件:行号` 与符号；AC 逐条回读 spec |
| 2026-09-16 | `/sdd-review design` 修订：D9 表注册改为「必须 import 进 `open_api/domain/models/__init__.py`」（原文误以为包级登记自动覆盖，新增坑 17）；D3 补条件挂载 vs `app:manage` 无条件挂载的差别、两个既有集合断言（路由矩阵 / OpenAPI 契约）在开关关闭进程下的处理与 fixture 真实位置；§2 C3 补写入器无 ContextVar 的显式 `tenant_id` / `bypass_tenant_filter()`；D4 身份头四码逐一落到 `identity_service.py` 行号；D7 补 `OpenApiPrincipal` 文件与第二处 Literal；`create_time` 改 `text("CURRENT_TIMESTAMP")`；行号订正（K1 / K6 / 坑 1 / 坑 5） | 逐条 grep 核实 `文件:行号` 与符号 |
