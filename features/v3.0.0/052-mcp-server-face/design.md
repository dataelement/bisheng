# Design: MCP Server 工具面与统一检索门面（六类工具 + 文件级过滤门面 + `delegate` 入口拒绝）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（47 条 AC、边界、决议 1–12）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策（含被否决的备选）、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档、只留"今天的状态"；但每个决策保留"为什么 + 被否方案"和坑。推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。
>
> **代码事实口径**：本文所有 `文件:行号` 均按 `3.0-vibe`（HEAD `fe10f75ea`，含 F048 + beta2 F053/F066 开放 API 底座 + F054/F055 MVP-核心）在 2026-09-16 核实，路径以 `src/backend/bisheng/` 为根（前端另注 `platform/` = `src/frontend/platform/src/`；SDK 路径以 `src/backend/.venv/lib/python3.11/site-packages/` 为根）。行号会漂移，符号名不会——落地前以符号名重定位。凡文档锚点已在代码中消失的，标「已失效」。
>
> **本文是"要建成的样子"**：F052 尚未开工——树上零 MCP *服务端*代码（`grep -rn "from mcp" bisheng/` 只命中 `mcp_manage/clients/{sse,stdio,streamable,base}.py` 四个客户端），零会话解耦的检索门面。实现后按现状覆盖本文。
>
> **全自动模式**：2026-09-16 用户已豁免本 Feature 的 ★ 暂停点；§3 每条决策均标「全自动模式定案」，理由与备选留痕供追溯。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [release-contract.md](../release-contract.md)（INV-27～31 / INV-36；表 3 F052 行；错误码表 **263** 段由本 Feature 落定）· 姊妹 [F049 design](../049-openapi-auth-baseline/design.md)（已归档，D2「主体解析器」段仍有效）· [beta2 F053 spec](../../v3.0.0-beta1/053-openapi-auth-and-identity/spec.md)（现行开放 API 底座）· [F054 design](../054-app-domain-runtime/design.md) D10（数据面落点）· [F055 design](../055-app-publish-pipeline/design.md) D13 / D15 · [F053 tasks](../053-dev-cli-skills/tasks.md) T046（接入信息区）· [F051 spec](../051-model-protocol-gateway/spec.md) AC-10～12（名称解析）· [F057 spec](../057-bisheng-sdk/spec.md) AC-11～16（SDK retrieve）
**版本**: v3.0.0
**最后更新**: 2026-09-16（初版，全自动模式定案；尚未开工）

---

## 1. 目标与非目标

- **目标**：两件事。① 在平台 API 进程内、`/api/v2/mcp` 路径下起一个标准 **MCP Server**（streamable-http、无状态、JSON 响应），凭 `bs-sak-` / `bs-pat-` 密钥鉴权、一律模式 S、工具清单按权限位过滤、每次调用计审计、拒绝一切委托——让本地 coding agent 零改造调平台六类工具（检索 / 知识库清单 / 模型清单 / 身份组织 / 应用数据 / 应用状态日志）。② 把「文件级过滤 + fail-closed」的检索能力从聊天服务里抽成一个**会话解耦的统一检索门面** `RetrievalFacadeService`（入参 = 执行身份 + 查询 + 可选声明白名单），MCP 检索工具、v2 `POST /filelib/retrieve`、F055 托管运行期、F057 SDK retrieve 四处共用；F050 模式 D「集合相等」由它兜底。
- **非目标**（防扩范围）：模型协议面与模型调用（F051，本 Feature 只做清单工具）；CLI / 技能包 / 接入信息区界面（F053，本 Feature 只交付 MCP 地址字段）；SDK（F057）；服务账号 / 密钥 / 权限位定义 / 开放能力层开关本身（beta2 F053 已交付，本 Feature 只消费并翻转 `identity:read` 可签发）；模式 D 准入与验收（F050）；能力声明冻结 / 审读 / 注入通道 / 收回错误态 16273（F055，本 Feature 只给出「能力已收回」信号）；每应用数据库服务端 `AppDataService` 与 manager 数据面 RPC（F054 T086/T087，**树上尚不存在**，本 Feature 只接线）；QA 库 / 个人库经门面检索；per-tool 授权粒度；MCP 限流与账单；平台内对话检索链的取向翻转（决议-9）；SSE / 有状态 MCP 会话 / 服务端主动通知（D1）。

---

## 2. 关键约束

> 全局铁律（C1–C8）一律遵循 [`docs/constitution.md`](../../../docs/constitution.md)，本节不重抄。以下只写本 Feature 特有的硬约束。

| # | 约束 | 出处 / 后果 |
|---|---|---|
| K1 | **MCP 面不新增常驻进程 / 端口**：随 API 进程条件挂载（`settings.open_platform.enabled`），未部署时路径 404、零常驻负担 | spec 决议-1 / AC-37；先例 `api/router.py:139-141` 对 `dev_toolkit_router` 的条件 include |
| K2 | **鉴权语义与 `/api/v2` 完全同一**：同一 `validate_bearer`（`open_api/domain/services/credential_validator.py:117`，Redis 缓存 TTL 由 `core/config/open_platform.py:49-52` 封顶 5s）、同一租户 / 可见租户 ContextVar 装配、同一 `PermissionActor`；**但 MCP 面没有端点 marker**（Starlette `Mount` 不是 `APIRoute`，`router_rpc` 的 `verify_open_api_access` 依赖对它不生效，`dependencies.py:100` 读 `conn.scope["endpoint"]` 会得到 None → 26031）——鉴权必须由 MCP 自己的 ASGI 闸完成（D2） | AC-02 / AC-05 / AC-06；INV-27 / INV-28 |
| K3 | **一律模式 S、拒绝一切委托**：持 `delegate` 的密钥在入口按位拒（复用 26051）；任何身份传递头（`X-On-Behalf-Of` / `X-End-User` 及 `*-on-behalf-of` / `*-end-user` 变体）一律拒（新码 26303），**不得**像 v2 那样解析它们（`identity_service.py:61 resolve_request_identity`） | AC-28～30；INV-31 |
| K4 | **主体两类皆可**：`service_account` 与 `natural_person`（PAT）都是模式 S「自身身份」（spec 2026-08-28 订正；伴生 PRD §4.10.8 明写「个人令牌只会看到检索与知识空间清单两个工具」）；PAT 的租户策略与 `data_scope`（F066）按 `dependencies.py:86-98` 原样执行 | AC-03 |
| K5 | **`/api/v2` 下的两条守卫测试**必须适配：`test/open_api/test_open_api_route_matrix.py:37-41` 遍历 `app.routes` 中 `/api/v2` 前缀路由并取 `route.endpoint`（`Mount` 无 `endpoint` → AttributeError）；`test_openapi_schema_contract.py:34-52` 要求 OpenAPI 文档中的 `/api/v2/**` 操作与 beta2 契约文件相等（`Mount` 不进 `app.openapi()`，故不撞） | D1 |
| K6 | **错误码 263 段**（本 Feature 落定）：`common/errcode/mcp_face.py`，`McpFaceError(BaseErrorCode)` 基类带 `http_status`；子段 `26300–26319` MCP 传输 / 工具面、`26320–26339` 统一检索门面（四处调用方共用）、`26340+` 保留。**不占** 260 段（`open_api.py:219` 注释保留段 26032–26039 / 26045–26049 由 `test/open_api/test_error_codes.py:49-51` 钉死）。每个新码三语文案同 PR（`packages/locales/src/api_errors/{zh-Hans,en,ja}.json`，CI `pnpm check-i18n`） | C5；release-contract 错误码表 |
| K7 | **门面 fail-closed 只作用于门面调用面**：`PermissionServiceUnavailableError`（19002）/ `PermissionBackendUnavailableError`（19201）原样上抛，由 v2 handler 映射 503（`open_api/api/exception_handlers.py:54-68`）、由 MCP 错误层映射 `permission_unavailable`；**不改** `KnowledgeSpaceChatService` 平台内对话路径的任何行为（决议-9；核实结论见坑 3） | AC-24 / AC-44；INV-30 |
| K8 | **审计不记检索正文、响应不回显密钥**：审计 metadata 只含工具名 / 目标摘要（id 列表）/ 结果类别 / 时延；任何 MCP 响应体与日志不得出现 `bs-sak-` / `bs-pat-` 前缀字符串 | AC-07 / AC-47；NFR-2 |
| K9 | **应用类工具 owner 收窄是业务规则前置拦截**：`AppQueryService._require_log_access`（`app_runtime/domain/services/app_query_service.py:263-290`）对 `_OWNER_ONLY_ENTRIES={cli,mcp}` 已按「先比租户、再比 owner、管理员不放行」实现；但 `get_instance → _load_visible :246-261` 与 `PublishStatusService._require_viewer`（`app_publish/domain/services/publish_status_service.py:181-197`）**仍放行租户管理员**——本 Feature 给两者加 `entry` 参数（D9） | AC-34～36 |
| K10 | **多节点默认**：MCP 面无状态（每个工具调用 = 一次 HTTP POST），不得引入进程内会话表；凭据失效只靠 Redis（K2 的 5s 上界） | C8；memory `feedback_multinode_default_assumption` |
| K11 | **`mcp==1.27.1` SDK 的两处默认值必须显式覆盖**：`FastMCP(host="127.0.0.1")` 时自动装 DNS-rebinding 防护、只放行 `localhost` Host 头（`mcp/server/fastmcp/server.py:178-183`）——经 nginx / 网关的真实 Host 会被 421 拒；`StreamableHTTPSessionManager.run()` 必须作为 lifespan 上下文进入，否则 `handle_request` 抛 RuntimeError（`mcp/server/streamable_http_manager.py:99-140`） | D1；坑 1 / 坑 2 |

**Constitution Check（自查）**：C1 新包 `open_api/mcp/` 是入口层（与 `open_api/api/` 平级），只调领域服务与 `permission.application`，不直接碰 ORM；`knowledge/domain/services/retrieval_facade_service.py` 是领域服务，不 import 任何 `api/`。C2 无新表、无 Alembic。C3 MCP 闸无条件 `current_tenant_id.set(principal.tenant_id)` + `visible_tenant_ids.set({1, tenant})`（复刻 `dependencies.py:76-80`）；组织查询在该 ContextVar 下走自动过滤。C4 所有可见性判定经 `permission.application.business_authorization.batch_check_business_actions` / `runtime.list_visible_objects`，无 OpenFGA 直连；owner 收窄是业务规则、显式不依赖权限运行时。C5 见 K6。C6 密钥明文不落盘不进日志不进响应（K8）。C7 前端仅 F053 消费一个只读字段，经 `controllers/API/`。C8 见 K10。RULE-5：`open_api/mcp/*` 只 import 本模块 `open_api/api/dependencies.py` 的导出与各模块的 `domain/services`，不 import 其它模块的 `api/`。

---

## 3. 方案对比与选定

> 每条：备选 / 选定 / 原因 / 何时该重新考虑。均为 **全自动模式定案**（2026-09-16）。

### D1：MCP 传输形态 = FastMCP streamable-http · **stateless + json_response** · 挂载 `/api/v2/mcp`

- **备选**：
  - A. **独立进程 / 端口**（`uvicorn` 起第二个 app）— 部署干净；但每环境多一个进程 + nginx location + 网关放行，鉴权与租户注入要跨进程重做；违反 K1
  - B. **同进程、`app.mount("/api/v2/mcp", fastmcp.streamable_http_app())`**，无状态（每请求新 transport）、JSON 响应（不开 SSE 流）
  - C. 同进程、有状态会话 + SSE（`stateless_http=False`）— 支持服务端通知 / 进度；但会话表落在进程内（K10 违规）、nginx `/api` location 无 `proxy_buffering off`（`docker/nginx/conf.d/default.conf:117-130` 只给 `/apps/` 关了缓冲）、商业网关对长响应未验证
  - 路径：`/mcp`（顶级）vs `/api/v2/mcp`（v2 前缀下）
- **选定**：**B**，路径 **`/api/v2/mcp`**（单一稳定 URL，客户端不追加任何子路径；`FastMCP(streamable_http_path="/")` 使挂载点本身就是端点）。`FastMCP(name="bisheng", stateless_http=True, json_response=True, host="0.0.0.0", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))`；`main.py` lifespan 内 `async with mcp_server.session_manager.run():`（K11）；`app.mount` 仅在 `settings.open_platform.enabled` 为真时执行（K1，先例 `api/router.py:139`）。
- **原因**：六类工具全是「请求-响应」型薄封装，无一需要流式或服务端推送；无状态让「撤销 / 到期 / 权限位编辑即时生效」（AC-05 / AC-06）**结构性**成立——不存在需要主动断开的已建会话，每次 `tools/call` 都重新过 `validate_bearer`；JSON 响应让 nginx（`proxy_read_timeout 300s`）与商业 Java 网关（`docs/architecture/11-gateway.md:37` 代理 `/api/v2/**`）零改造穿透；`/api/v2` 前缀让所有部署形态（compose nginx `location ~ ^(/workspace)?/api`、systemd 114 `bisheng-lilu.conf`、网关）现成放行。`Mount` 不是 `APIRoute`：不会被 `router_rpc` 依赖覆盖（所以 D2 自建闸）、不进 `app.openapi()`（`test_openapi_schema_contract` 不撞）、但会撞 `test_open_api_route_matrix`（K5，改测试用 `isinstance(route, (APIRoute, APIWebSocketRoute))` 过滤 + 单独断言 Mount 存在与否随开关）。
- **何时该重新考虑**：出现需要服务端推送的工具（审批结果订阅、长任务进度）→ 改 `stateless_http=False` + `json_response=False`，届时会话状态必须落 Redis（SDK `event_store` 可插拔）、nginx `/api` 补 `proxy_buffering off`；MCP 流量成为 API 进程负载源 → 抽独立进程，工具面契约不变（决议-1 已预留）。

### D2：鉴权落点 = 自建 ASGI 闸 `McpAccessGate` 包住 FastMCP app，复用 `validate_bearer` 与 v2 的执行身份装配；**不用** FastMCP 自带 `token_verifier`

- **备选**：
  - A. `FastMCP(token_verifier=BishengTokenVerifier(), auth=AuthSettings(...))` — SDK 原生；但 `AuthSettings.issuer_url` / `resource_server_url` 为必填（`mcp/server/auth/settings.py:15-29`，OAuth RS 元数据语义）、401/403 响应体是 `WWW-Authenticate` 形态（`mcp/server/auth/middleware/bearer_auth.py:78-100`）与 v2 信封不一致、且 `AuthenticationMiddleware` 只给 `request.user`，装不上租户 / 权限 ContextVar
  - B. **自建 ASGI 闸**：`open_api/mcp/gate.py: McpAccessGate(app)`——每请求：取 `Authorization` → `validate_bearer` → PAT 策略（复用 `dependencies.py:86-98` 逻辑）→ **`delegate` 位 → 26051**（不看 marker，直接按位）→ **任何身份头 → 26303** → `current_tenant_id` / `visible_tenant_ids` / `current_open_api_principal` / `current_permission_actor` 四个 ContextVar 装配 → 调内层 app → `finally` 逐个 reset。失败 → `JSONResponse(http_status, exc.to_dict())`（与 `open_api/api/exception_handlers.py:41` 同形）+ `scope["open_api_error_code"]`
  - C. 把 `verify_open_api_access` 挂成 `Depends` — Mount 不是 APIRoute，FastAPI 依赖不生效
- **选定**：**B**。为不复制 `dependencies.py:76-153` 的装配块，把 `open_api_access_context` 拆成两段并导出：`admit_open_api_principal(conn) -> (principal, pat_data_scope)`（校验 + PAT 策略）与 `open_api_execution_scope(conn, principal, *, data_scope) -> AsyncContextManager`（四个 ContextVar + `PermissionActor` 构造 + 自然人 admin 事实解析）；`open_api_access_context` 本身改为「admit → marker / delegate / scope / 身份头 / 模式判定 → execution_scope」的组合，对外行为与现有 `test/open_api` 40 个测试文件逐字不变。MCP 闸只调这两段，在两段之间插入 K3 的两条拒绝。
- **原因**：AC-02「拒绝连接、不列出工具」= HTTP 层拒（`initialize` 请求本身 401/403，MCP 客户端表现为连接失败）；AC-28「通道入口 / 首次能力协商」= 同一处；v2 与 MCP 的凭据语义「同一条代码」而非「两份相同的代码」，撤销 5s / 编辑即时生效不必再验一遍。自然人 PAT 的 super/tenant-admin 事实解析（`dependencies.py:131-142`）随 `open_api_execution_scope` 一起复用——PAT 持有人若是管理员，其 MCP 检索同样享受管理员短路（伴生 PRD D17 改判，2026-08-28），但**租户过滤不放开**（`visible_tenant_ids={1, tenant}`）。
- **何时该重新考虑**：平台接入 OAuth 2.1 授权服务器（伴生 PRD D18 已明确本期不做）→ 那时切到 A，闸只保留 ContextVar 装配。

### D3：工具注册表 = 声明式 `TOOL_REGISTRY` + 子类化 `FastMCP` 覆盖 `list_tools` / `call_tool`

- **备选**：
  - A. 逐工具用 `@mcp.tool()` 注册 + 在每个 handler 体内判位 — 漏一处即静默放宽；清单无法按位过滤
  - B. **`open_api/mcp/registry.py: TOOL_REGISTRY: tuple[McpToolSpec, ...]`**（`name / category / scope / requires_app_runtime / handler / input_model / description`），`server.py: class BishengMcpServer(FastMCP)` 覆盖 `async def list_tools()`（`mcp/server/fastmcp/server.py:315`）按 `get_current_open_api_principal().scopes` 与 `settings.app_runtime.enabled` 过滤，覆盖 `async def call_tool(name, arguments)`（`:343`）先查注册表：不存在 → 26301；存在但缺位 → 26302（`data.required=<scope>`）；应用类且运行时层未部署 → 16207；再 `super().call_tool(...)`
- **选定**：**B**。工具 ↔ 权限位映射（DEV-01 ① / 伴生 B.2）：

| 类别 | 工具名 | 权限位 | 依赖运行时层 | 服务端 |
|---|---|---|---|---|
| ① 检索 | `bisheng_knowledge_search` | `knowledge:read` | 否 | 门面 `retrieve`（D5） |
| ② 清单 | `bisheng_knowledge_list` | `knowledge:read` | 否 | 门面 `list_accessible_knowledge` |
| ③ 模型清单 | `bisheng_model_list` | `model:invoke` | 否 | `LLMService.get_all_llm` + **F051 名称解析**（D10） |
| ④ 身份组织 | `bisheng_identity_get_user` / `bisheng_org_tree` / `bisheng_dept_members` | `identity:read` | 否 | 租户全量 DAO 读（D8） |
| ⑤ 应用数据 | `bisheng_app_db_tables` / `bisheng_app_db_schema` / `bisheng_app_db_rows` / `bisheng_app_db_row_update` / `bisheng_app_db_row_insert` / `bisheng_app_db_row_delete` | `app:manage` | **是** | F054 `AppDataService`（D9，树上未落） |
| ⑥ 应用状态日志 | `bisheng_app_status` / `bisheng_app_logs` | `app:manage` | **是** | `PublishStatusService.get_publish_status` + `AppQueryService.get_instance / get_logs`（D9） |

- **原因**：清单过滤 + 调用校验两者都做（决议-6）；子类覆盖是 SDK 允许的最小侵入——`FastMCP.__init__` 在 `_setup_handlers` 里把**绑定方法** `self.list_tools` / `self.call_tool` 注册给低层 `Server`，子类方法自然生效；`bisheng_` 前缀避免与 agent 本地其它 MCP server 撞名。
- **何时该重新考虑**：工具数 > 30 或需要按租户开关工具 → 注册表改 DB 驱动，过滤逻辑不变。

### D4：错误形态 = `McpToolError(ToolError)`，`str()` 即 JSON 三要素；传输层拒绝走 v2 信封

- **备选**：A. 返回正常结果里带 `{"ok": false}` — agent 会当成功处理；B. 抛裸异常 — SDK 变成 `isError=True` + `str(e)` 文本（`mcp/server/lowlevel/server.py:583-584 _make_error_result`），三要素丢失；C. **抛 `McpToolError`，其 `__str__` 输出 `{"code", "category", "reason", "next_step", "data"}` JSON** → SDK 原样放进 `CallToolResult(isError=True, content=[TextContent(text=json)])`
- **选定**：**C**（工具层）+ HTTP 信封（传输层：无 / 无效凭据 26001/26002、依赖不可用 26030、`delegate` 26051、身份头 26303 → `JSONResponse(http_status, {status_code, status_message, data})`）。`category` 枚举（`open_api/mcp/errors.py`）：`credential_invalid | scope_missing | delegate_only | identity_header_refused | unreachable | capability_revoked | not_your_app | runtime_disabled | permission_unavailable | invalid_argument | scope_too_large | internal`；映射表 `ERROR_CATEGORY_MAP: dict[int, tuple[category, next_step_key]]` 覆盖 26001/26002/26003/26030/26051/26301–26306/26320–26323/19002/19201/16207/16101/16161/16254/16162/16205，未映射的 `BaseErrorCode` → `internal`（`reason` = 其 `Msg`，`next_step` = 「稍后重试或联系管理员」，**永不**回显异常正文）。`next_step` 文案**由后端自有**：`open_api/mcp/errors.py: NEXT_STEP_COPY: dict[int, dict[str, str]]`（zh-Hans / en / ja 三语，按 `Accept-Language` 选、缺省 zh-Hans）——**不放** `packages/locales/api_errors`：后端进程不装前端 locale 包、读不到那份 JSON（坑 18），且 `next_step` 只给 agent 看、SPA 永不渲染；`api_errors` 三语仍只放每个码的主文案（C5 常规）。
- **原因**：AC-09 三要素 + AC-04「指明缺位」+ AC-11 / AC-27「同一响应」都要求错误是**结构化且可 JSON 解析**的；`isError=True` 是 MCP 客户端唯一稳定识别失败的位。
- **何时该重新考虑**：MCP 规范正式化 `CallToolResult.structuredContent` 在错误上的语义（1.27.1 只对成功结果填 `structuredContent`，`server.py:575-577`）→ 把 JSON 移过去，`content` 保留人可读文本。

### D5：统一检索门面 = `knowledge/domain/services/retrieval_facade_service.py`，引擎从聊天服务**抽出**而非复制；执行身份 = `RetrievalIdentity(actor, login_user)`

- **备选**：
  - A. 门面内部 `KnowledgeSpaceChatService(request=None, login_user)` 直接调 `aretrieve_chunks` — 最省；但该类构造需 `Request`（`knowledge_space_chat_service.py:57-58`）且 `_permission_service` / `_visibility_service`（`:61-76`）把 `self.request` 透传给 `KnowledgeSpaceService` / `KnowledgeFileVisibilityService`，`None` 是否安全无人保证；且 AC-19「会话解耦」变成靠约定
  - B. **抽出**：新建 `knowledge/domain/services/retrieval_engine.py: RetrievalEngine(login_user, version_repo=None)`，把 `_retrieve_and_filter :393` / `_aretrieve_chunks_for_kb :809` / `_aretrieve_chunks_for_knowledge_base :869` / `_resolve_kb_target_file_ids :695` / `_resolve_kb_file_ids_by_tags :907` / `_attach_document_update_time :788` **整体搬入**（不带 `request`；`KnowledgeFileVisibilityService(request=None, login_user)` 的 `request` 形参保留、核实其判定链不读 `self.request`——坑 4），`KnowledgeSpaceChatService.aretrieve_chunks :726` 改为**薄委托**到引擎（签名、400 行为、返回形状一字不变——决议-9 平台内路径不翻转）；门面在引擎之上做**可及性预判 + 白名单 + 上限 + 收回信号 + 身份 fail-closed**
  - C. 门面另写一条检索链 — 第三条强度不一的路径，正是伴生 B.1 已核实的分叉再现
- **选定**：**B**。接口（契约见 §4.2 ③）：`RetrievalFacadeService.retrieve(identity, req) -> RetrievalFacadeResult`、`list_accessible_knowledge(identity) -> list[AccessibleKnowledge]`、`check_reachable(identity, knowledge_ids) -> ReachabilityReport`、`is_supported_knowledge_type(type) -> bool`（`SUPPORTED_KNOWLEDGE_TYPES = {NORMAL=0, SPACE=3}`）。执行身份 `RetrievalIdentity(actor: PermissionActor, login_user: UserPayload)`，门面体内 `set_current_permission_actor(identity.actor)` → 执行 → reset（调用方不必自己装，但 v2 / MCP 已装时取同一对象无副作用）；`identity is None` 或 `actor.subject_id` 为空 → 26320 拒绝（AC-23）。构造器 `RetrievalIdentity.from_open_api_principal(principal)`（S：`subject_type=principal.authorization_subject_type`；D：`user` + `effective_user_id`——F050 只需传模式 D 的 principal）与 `RetrievalIdentity.from_user(user_id, tenant_id, *, data_scope=ALL)`（F055 访问用户；管理员事实由 `resolve_permission_actor` 解析）。
- **可及性判定**（一次批量，不逐库串行）：`KnowledgeDao.aget_list_by_ids(targets)` → 过滤 `type ∈ {0,3}` → `batch_check_business_actions(login_user, resource_type="knowledge_space", ids, actions=("visible",))` 与 `resource_type="knowledge_library"`（资源类型名以 `api/services/f048_permission_runtime.py` registry 为准）`actions=("use",)`——与今天两条链各自的门一致（`_require_space_view_permission :90-92` 用 `visible`；`ensure_knowledge_use_async` 用 `use`），故「集合相等」在两种类型上分别成立。**未指定目标 + 无白名单** → `list_accessible_knowledge`：常规主体走 `runtime.list_visible_objects(actor, resource_type=…, max_results=RETRIEVAL_SCOPE_MAX)`（`permission/application/runtime.py:222`），管理员短路主体走租户内 DB 扫描（同 `KnowledgeService.get_knowledge :506-515` 的 admin bypass；PAT `data_scope=personal_only` 不得走 bypass——同 `:511-515`）；候选 > `RETRIEVAL_SCOPE_MAX=200` → 26323（不静默截断）。
- **白名单语义**（AC-21 / AC-46）：`whitelist=None` = 无白名单；`whitelist=[]` = 空范围 → 任何目标皆不可及 26321。有白名单时：显式目标 ∉ 白名单 → 26321（与不存在同响应）；白名单条目**行不存在 / 已删除 / 类型不再受支持** → **26322 `KnowledgeCapabilityRevokedError(data.knowledge_id)`**，整请求失败、不剔除续跑；白名单内存在但执行身份不可见 → 未显式指定时静默不出现（AC-21 第二句），显式指定时 26321。**「应用侧授权已收回」由 F055 在调用门面前按能力状态判定并直接抛 16273**（它拥有能力状态，门面不感知）——门面的 26322 只覆盖「库本身没了」这一类；F055 AC-53 把 26322 也转成 16273。
- **上限与可见截断**：`RETRIEVAL_TOP_K_MAX=200`（与 v2 `RetrieveReq.top_k le=200` 一致，`open_endpoints/domain/schemas/filelib.py:47`）、`RETRIEVAL_MAX_CONTENT_MAX=60000`、`RETRIEVAL_TARGETS_MAX=50`；`top_k` / `max_content` 超限 → 夹到上限并在 `RetrievalFacadeResult.truncated_params` 列出（AC 边界「超出即按上限截断并在响应中可见」）；目标数超限 → 26323。
- **原因**：B 让「开放面唯一检索路径」（AC-26）与「平台内取向不变」（决议-9）同时成立——引擎只有一份，聊天服务与门面是两个**入口**，强度由引擎保证；抽出后门面天然无 `Request`，AC-19 会话解耦是结构事实。三种「不可及」同一响应、白名单收回可区分，是 spec 决议-7 / 决议-10 / AC-46 的字面要求。
- **何时该重新考虑**：文档知识库引入文件级权限模型 → 引擎不变，门面验收样本补例（决议-3）；QA 库要经开放面检索 → `SUPPORTED_KNOWLEDGE_TYPES` 加 1 并给引擎加 QA 召回分支。

### D6：v2 `POST /filelib/retrieve` 收敛 = 端点改调门面；请求 / 响应 schema 不变；空 `knowledge_base_ids` 语义保持 400

- **备选**：A. 端点不动（现状已是文件级双层过滤 + fail-closed，见坑 3）— 但 AC-11 / AC-27「三种不可及同一响应」不成立（现为 404 `NotFoundError` / 403 `SpacePermissionDeniedError` / 10962 三态）；B. **改调 `RetrievalFacadeService.retrieve(RetrievalIdentity.from_open_api_principal(principal), ...)`**，`RetrieveReq` / `RetrieveResp` 不改；C. 顺带把 `knowledge_base_ids` 改可选（= 全部授予范围，AC-22）
- **选定**：**B**，不做 C。`RetrieveReq.knowledge_base_ids min_length=1` 保留（对外契约「除结果集因过滤收窄外无变化」，AC-25）；AC-22「未指定目标 → 全部授予范围」只在 MCP 工具与 SDK 上提供。`kb_filters`（tag 过滤）原样透传引擎。错误：不可及 → 26321（HTTP 404，`data.unreachable_ids`），替换现三态；权限不可用 → 19002/19201 原样（handler 503，删除现 `:721` 的 `OpenApiAuthDependencyUnavailableError` 包装——26030 是「凭据校验依赖不可用」，检索期的权限引擎故障用它是语义错位）；F066 26044 判定在 `PermissionActor.data_scope` 层自动继承，`test/open_api/test_data_scope_matrix.py` 必须仍绿。`docs/api/filelib-retrieve.md:181-186 / :287` 「default operator 是否对该 KB 有 view 权限」订正为门面口径。
- **原因**：AC-41「同 key 经 v2 与经 MCP 集合相等」由「同一门面 + 同一执行身份构造器」结构性保证；不改契约是 AC-25 硬要求。
- **何时该重新考虑**：外部集成方明确需要「不传 ids = 全范围」→ 走 v2 版本化契约变更（F058 一类），非本 Feature。

### D7：MCP 逐调用审计 = `open_api.mcp.tool_call` 一个 action，在 `call_tool` 包装层写；`OpenApiAuditMiddleware` 对 `/api/v2/mcp` 前缀**跳过**

- **备选**：A. 沿用中间件 — 只会记 `POST /api/v2/mcp`，无工具名 / 目标（`open_api/api/middleware.py:100-160` 按 `METHOD route_path` 记 `open_api.call`）；B. 中间件 + 工具层双记 — 每次调用两行；C. **工具层单记**（`open_api/mcp/audit.py: audit_tool_call(principal, tool, target_summary, outcome, latency_ms)` → `open_api_call_audit_service.enqueue(AuditLog(action="open_api.mcp.tool_call", target_type="mcp_tool", target_id=<tool>, audit_metadata={credential_id, actor_kind, actor_id, resource_owner_user_id, tool, category, target:{knowledge_ids|app_id|dept_id|user_id}, outcome:"success"|"denied:<code>"|"error:<code>", latency_ms, trace_id}）`）；传输层拒绝（闸内 401/403）也用同一 action、`target_id="-"`
- **选定**：**C**。中间件 `__call__` 首行加 `path.startswith("/api/v2/mcp")` 短路。action 登记三处 lockstep：`database/models/audit_log.py:198 _UI_VISIBLE_V2_ACTIONS`（`open_api.` 前缀已在 `_V2_NAMESPACE_TO_ACTION_PREFIX :296`）、`platform/controllers/API/log.ts:153 V2_ACTIONS`、`platform/public/locales/{zh-Hans,en-US,ja}/bs.json` 键 `openApiMcpToolCall`（派生规则见 `test/app_runtime/test_audit_action_registry_lockstep.py` docstring）。**不记** `query` 正文、不记片段、不记 `arguments` 全文（只记目标 id 摘要）。
- **原因**：AC-07 要求归属到工具名与目标；批量入库 `OpenApiCallAuditService`（`call_audit_service.py:18`）现成、有界；决议-12 高频分层留给 F056。
- **何时该重新考虑**：审计写放大成瓶颈 → 与 F056 高频事件分层一并处理（口径不变）。

### D8：身份 / 组织工具 = 租户全量 DAO 读（不经 `aget_tree(login_user)` 的可管范围计算），字段白名单，跨租户与不存在同响应

- **备选**：A. 复用 `DepartmentService.aget_tree(login_user)`（`department/domain/services/department_service.py:1085`）— 它按 `login_user` 的部门管理员 / 租户管理员子树计算可见范围，服务账号无任何管理身份 → **空树**；B. **新建 `department/domain/services/org_directory_service.py: OrgDirectoryService`**（`atree() / amembers(dept_id, page, size, keyword) / aget_user(user_id)`），在 `current_tenant_id` 下走自动过滤的 DAO 全量读（`Department` / `UserDepartment` / `User` / `UserTenant`），**不做任何范围收窄**（AC-31）
- **选定**：**B**。出参白名单：用户 = `{user_id, user_name, departments:[{dept_id,name,path}], roles:[name], status:"active"|"disabled"}`；部门 = `DepartmentTreeNode` 子集 `{dept_id, name, parent_id, path, sort_order, source, status}`（`department/domain/schemas/department_schema.py:85-99`），**去掉** `is_tenant_root / mounted_tenant_id`（租户拓扑不属组织信息）。凭据类字段（`password`、`token_version`、`external_id`、任何 token）**结构性不进 schema**。点查：`UserTenantDao.aget_active_user_tenant(user_id)` 租户 ≠ 当前 → 26306（与不存在同响应）；服务账号在独立 `service_account` 表（beta2）、无 `user` 行 → 组织结果天然不含（决议-11）。
- **原因**：spec AC-31「本租户全量、无收窄」与既有部门树接口的「按可管范围」语义正交，复用会得到错误的空结果；一个只读服务放在 department 模块是它的领域归属（C1）。
- **何时该重新考虑**：产品决定从能力侧收窄（只允许点查、不给列举，PRD-1 DEV-02 ② 末句）→ 从注册表摘掉 `bisheng_org_tree` / `bisheng_dept_members` 即可。

### D9：应用类工具 = 服务端方法加 `entry` 参数做 owner-only；数据工具接线 F054 `AppDataService`（假设签名）；缺 insert / delete 向 F054 提回写

- **备选**：A. 工具层自己比 `owner_user_id` 再调服务 — 两处判定、可漂移；B. **服务方法加 `entry: str = "detail"` 形参**：`PublishStatusService.get_publish_status(app_id, *, actor, entry)` → `_require_viewer(app, actor, entry)` 在 `entry in {"cli","mcp"}` 时只认 owner（管理员不放行）；`AppQueryService.get_instance(app_id, *, actor, entry)` → `_load_visible` 同理；`get_logs` 已有 `entry=LOG_ENTRY_MCP`（`app_query_service.py:46-50`）
- **选定**：**B**。actor 构造与 `app_publish/api/endpoints/deploy.py:200-213` 完全同形：`UserPayload(user_id=resource_owner_of(principal), user_name=principal.actor_name, user_role=[], tenant_id=principal.tenant_id, is_global_super=False)`——`resource_owner_of`（`publish_pipeline_service.py:111`）对无归属人的主体抛 16205，PAT 主体（`resource_owner_user_id=None`）因此**天然不能用应用类工具**（PAT 也签不出 `app:manage`，双保险）。**调用期取归属人当前值** → AC-36 自动成立。不可及应用（不存在 / 他租户 / 非 owner）统一映射为 **26305 `not_your_app`**（16101 / 16161 / 16254 / 16205 四码在工具层折叠，响应不带 owner 名）。**数据工具**：F054 T087 `app_runtime/domain/services/app_data_service.py: AppDataService` 在 HEAD `fe10f75ea` **树上不存在**（`grep AppDataService bisheng/` 无命中；F054 tasks.md:696-718 T086a/T086/T087a/T087 均 `[ ]`），**本波次的 data-plane 切片正在同期实现它**——本文按 F054 design D10（`:266-278`）**假设**其签名为 `list_tables(app_id, *, actor, entry) / get_schema(app_id, table, *, actor, entry) / read_rows(app_id, table, *, page, size, order, actor, entry) / update_row(app_id, table, pk, values, *, actor, entry)`，写操作在 F054 侧计审计 `app.data_row_edit`（`app_runtime/domain/constants.py:107` 已登记）。F054 D10 的 manager RPC 清单**只有 PATCH 单行**、无 insert / delete——spec 决议-8「行级增删改」需要 F054 补 `insert_row / delete_row`（manager `POST /v1/apps/{id}/db/tables/{t}/rows` / `DELETE .../rows/{pk}`）；本 Feature 在 F054 tasks「跨 Feature 回写受理」登记该请求，工具 `bisheng_app_db_row_insert / _delete` 随其落地启用（T031 标注）。
- **原因**：AC-35「租户管理员名下服务账号的密钥同样拒」要求判定在服务层且不受权限运行时短路影响——`entry` 参数让「只有一处实现」（F055 design D15 的原则）继续成立；工具层不得直连 manager（F054 D10 明令）。
- **何时该重新考虑**：F054 落地 `AppDataService` 后签名若与假设不同 → 只改 `open_api/mcp/tools/apps.py` 的适配层，记 tasks 偏差。

### D10：模型清单工具 = `LLMService.get_all_llm` 过滤 `online ∧ model_type=='llm'`；`qualified_name` **只经 F051 的解析函数**，F051 未落地前工具不注册

- **备选**：A. 本 Feature 自定「`{server_name}/{model_name}` 即限定名」占位 — F051 决议-2 定分隔规则与歧义判定，本 Feature 自定就是第二份规则（F051 AC-10「三处同源」被破坏）；B. **工具实现依赖 `bisheng.llm.domain.services.model_name_resolver`（F051 design 待定名，由 F051 tasks 落）导出的 `resolve_callable_names(tenant_id) -> list[CallableModel{name, qualified_name, is_ambiguous, model_type, is_chat, server_name}]`**；导入失败（F051 未合入）→ 注册表把 ③ 标 `unavailable`、不进清单、直调 26301
- **选定**：**B**。出参 `{name, qualified_name, model_type, is_chat, server_name, callable_name}`（`callable_name` = 歧义时 `qualified_name`、唯一时 `name`——即 F051 AC-10「可直接用于调用的名称」）。`model:invoke` 的 `issuable=False → True` 翻转归 F051（`scopes.py:145`），本 Feature **不动**——位不可签发时工具无从被列出，两者顺序无关。
- **原因**：spec 决议-4 + F051 AC-10「名称解析规则是唯一出处」。
- **何时该重新考虑**：无。

### D11：`identity:read` 可签发翻转归本 Feature；MCP 地址 = `/api/v1/dev-toolkit/versions` 增 `mcp` 段

- **备选**（地址）：A. 新端点 `GET /api/v1/service-accounts/access-info` — 多一个端点；B. **扩展 F053 `dev_toolkit/api/endpoints/distribution.py:56 get_dev_toolkit_versions` 返回体加 `"mcp": {"url": f"{resolve_public_base_url(request)}/api/v2/mcp", "transport": "streamable-http", "auth": "bearer"}`**（该 router 只在 `open_platform.enabled` 时挂载，`api/router.py:139-141` → AC-37「地址不出现」零代码成立；`resolve_public_base_url` `open_api/api/public_base_url.py:77` 已被技能包使用）；F051 的 `model.base_url` 留同级槽位（本 Feature 写 `"model": None`，F051 填）
- **选定**：**B**（地址）；`scopes.py:154 identity:read issuable=False` → `True`（`requires_open_platform=True` 不变），同步改 `test/open_api/test_scope_issuability.py:66-68 / :176` 与 `test_scopes.py:49` 的钉住集合（`model:invoke` 仍不可签发）。
- **原因**：地址不含凭据、匿名可读无害（F053 CLI 本就匿名探测该端点，`distribution.py:7`）；「同一份接入信息真相」避免 F053 T046 再拼一遍 URL。
- **何时该重新考虑**：接入信息需要按服务账号个性化（如 per-SA 的 MCP 子路径）→ 那时才建 A。

### D12：测试策略 = 进程内 ASGI 直连的真 MCP 客户端 + 注册表驱动矩阵 + 引擎级 fake；集合相等在 CI 中间件分组

- **选定**：`test/open_api/conftest.py` 增 `mcp_client` fixture：`httpx.ASGITransport(app)` + `mcp.client.streamable_http.streamable_http_client(url, http_client=...)`（`mcp/client/streamable_http.py:601-605`，1.27.1 已支持注入 `httpx.AsyncClient`）+ `ClientSession.initialize / list_tools / call_tool`；矩阵测试遍历 `TOOL_REGISTRY` 生成「仅持 X 位」用例（防漏，仿 `test_data_scope_matrix.py`）；门面单测用 fake 引擎（记录调用、返回可控 Document）+ monkeypatch `batch_check_business_actions` / `list_visible_objects`；**集合相等（AC-40～43）与 fail-closed（AC-44）** 用例放 `test/knowledge/test_retrieval_facade_equality.py`，标 `@pytest.mark.e2e`，CI 中间件阶段跑（MySQL + Redis + OpenFGA + Milvus/ES），本地无中间件默认跳过。
- **原因**：AC-01「任何标准 MCP 客户端零改造」只有用真客户端才算验；本地无中间件（HARNESS.md），集合相等必须在 CI。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（要建成的样子）

**A. MCP 工具调用**（一次 `tools/call` = 一次 `POST /api/v2/mcp`）

`MCP 客户端 POST /api/v2/mcp（Authorization: Bearer bs-sak-…；JSON-RPC）` → nginx `/api` / 网关 `/api/v2/**` → `main.py app.mount("/api/v2/mcp", McpAccessGate(mcp_server.streamable_http_app()))`（仅 `open_platform.enabled`）→ **`McpAccessGate`**（`open_api/mcp/gate.py`）：`admit_open_api_principal` → `delegate` 位 → 26051 · 身份头 → 26303 → `open_api_execution_scope`（四个 ContextVar）→ FastMCP `StreamableHTTPASGIApp` → 低层 `Server` 分发 `initialize` / `tools/list` / `tools/call` → **`BishengMcpServer.list_tools`**（按位 + 运行时层过滤）/ **`call_tool`**（注册表校验 → handler）→ handler 调领域服务（门面 / `OrgDirectoryService` / `PublishStatusService` / `AppQueryService` / `AppDataService`）→ 成功：`CallToolResult(structuredContent=dict)`；失败：`McpToolError` JSON（D4）→ `audit_tool_call`（D7）→ `finally` reset ContextVar。

**B. 门面检索**（四个调用方同一条）

`调用方构造 RetrievalIdentity` → `RetrievalFacadeService.retrieve(identity, RetrievalRequest)` → 身份 fail-closed（26320）→ 参数夹取上限（可见截断）→ **范围解析**：显式目标 / 白名单 / 全部授予（D5）→ **可及性批判**（一次 `aget_list_by_ids` + 每类型一次 `batch_check_business_actions`；白名单条目缺失 → 26322；任一目标不可及 → 26321）→ `RetrievalEngine.retrieve_many(targets, query, tag_filters, max_content)`（`asyncio.gather` 逐库：知识空间 `_retrieve_and_filter` 双层 `visible` 过滤；文档库 库级 `use` + 同一 `_retrieve_and_filter`）→ 扁平 `[:top_k]` → `_attach_document_update_time` → `RetrievalFacadeResult`。权限引擎异常（19002 / 19201）在任何一步**原样上抛**、不产生结果。

**C. v2 `POST /filelib/retrieve`**：`verify_open_api_access`（不变）→ `retrieve_chunks`（`open_endpoints/api/endpoints/filelib.py:689`）→ `RetrievalIdentity.from_open_api_principal(get_current_open_api_principal())` → 门面 → `RetrieveResp`（不变）。

### 4.2 关键数据结构 / 字段约定（对外契约）

**① MCP 接入**

| 项 | 值 |
|---|---|
| URL | `{public_base_url}/api/v2/mcp`（`resolve_public_base_url`；114 = `http://192.168.106.114:4101/api/v2/mcp`） |
| 传输 | MCP streamable-http，`stateless`，`json_response`（`Content-Type: application/json`；`GET` 流 405） |
| 鉴权 | `Authorization: Bearer bs-sak-…` 或 `bs-pat-…`；查询参数 / cookie 一律不认（`extract_bearer_token` 只读该头） |
| 传输层拒绝 | HTTP 401 `{status_code:26001|26002}` · 503 `26030` · 403 `26051`（delegate）· 403 `26303`（身份头）· 404（开关关闭，路径不存在） |
| 客户端配置示例（Claude Code）| `claude mcp add --transport http bisheng http://…/api/v2/mcp --header "Authorization: Bearer bs-sak-…"` |

**② MCP 工具入参 / 出参**（所有出参经 `structuredContent`；`isError` 见 D4）

| 工具 | 入参 | 出参 |
|---|---|---|
| `bisheng_knowledge_search` | `query: str(1..2000)` · `knowledge_ids: list[int] \| None`（省略 = 全部授予范围）· `top_k: int = 10`（≤200）· `max_content: int = 15000`（≤60000）· `tags: dict[int, list[str]] \| None` | `{chunks:[{knowledge_id, knowledge_type, knowledge_name, document_id, document_name, chunk_index, content, document_update_time}], total, effective_scope:[knowledge_id], truncated_params:{top_k?, max_content?}}` |
| `bisheng_knowledge_list` | `name: str \| None` · `limit: int = 200` | `{items:[{knowledge_id, name, type: "library"\|"space", description}], total}`（集合 = 显式授予 ∩ 支持类型；QA / 个人库不出现） |
| `bisheng_model_list` | — | `{models:[{name, qualified_name, callable_name, model_type, is_chat, server_name}]}` |
| `bisheng_identity_get_user` | `user_id: int` | `{user_id, user_name, status, departments:[{dept_id,name,path}], roles:[str]}` |
| `bisheng_org_tree` | — | `{departments:[{dept_id, name, parent_id, path, sort_order, source, status, children:[…]}]}` |
| `bisheng_dept_members` | `dept_id: str` · `page=1` · `size=50`（≤200）· `keyword?` | `{members:[{user_id, user_name, status}], total}` |
| `bisheng_app_status` | `app_id: str` | `{app_id, app_state, instance:{phase, health, current_version_id, started_at, restart_count}, publish:{pending_reason, current_version, pending_version, deployment, approval:{instance_id, status, submitted_at, decided_at, reject_reason, approver_names}}}`（`publish` = `PublishStatusService.get_publish_status` 原样字段，F055 design §4.2 ②；`instance` = `AppQueryService.get_instance` 原样） |
| `bisheng_app_logs` | `app_id` · `tail: int = 200`（≤2000）· `since?: str` · `keyword?` | `{lines:[str], app_state, pending_reason}`（= `get_logs(entry="mcp")` 原样 + F053 T034 ② 补的两字段） |
| `bisheng_app_db_tables` / `_schema` / `_rows` / `_row_update` / `_row_insert` / `_row_delete` | `app_id` · `table` · `page/size/order` · `pk` · `values: dict` | F054 `AppDataService` 返回体原样透传（无 DDL；写操作审计在 F054） |

**③ 门面契约**（`knowledge/domain/schemas/retrieval_facade.py`）

```
RetrievalIdentity(actor: PermissionActor, login_user: UserPayload)         # frozen dataclass
  .from_open_api_principal(principal)  .from_user(user_id, tenant_id, *, data_scope=DATA_SCOPE_ALL)
RetrievalRequest(query: str, knowledge_ids: list[int] | None = None,
                 whitelist: list[int] | None = None, top_k: int = 10, max_content: int = 15000,
                 tag_filters: dict[int, list[str]] | None = None)
RetrievalChunk(knowledge_id, knowledge_type, knowledge_name, document_id, document_name,
               chunk_index, content, document_update_time)
RetrievalFacadeResult(chunks: list[RetrievalChunk], total: int, effective_scope: list[int],
                      truncated_params: dict[str, int])
AccessibleKnowledge(knowledge_id, name, type, description)
ReachabilityReport(reachable: list[int], unreachable: list[int], revoked: list[int])
RetrievalFacadeService.retrieve(identity, req) / list_accessible_knowledge(identity, *, name=None, limit=200)
                      / check_reachable(identity, knowledge_ids, *, whitelist=None) / is_supported_knowledge_type(t)
常量 SUPPORTED_KNOWLEDGE_TYPES={0,3} · RETRIEVAL_TOP_K_MAX=200 · RETRIEVAL_MAX_CONTENT_MAX=60000
     · RETRIEVAL_TARGETS_MAX=50 · RETRIEVAL_SCOPE_MAX=200
```

**④ 错误码 263 段**（`common/errcode/mcp_face.py`；`McpFaceError(BaseErrorCode)` 带 `http_status`）

| 码 | 类 | HTTP | category | 说明 |
|---|---|---|---|---|
| 26301 | `McpUnknownToolError` | 404 | `unreachable` | 注册表无此工具（含 F051 未落地时的 ③、F054 未落地时的数据工具） |
| 26302 | `McpToolScopeMissingError` | 403 | `scope_missing` | `data.required=<scope>`；与 26003 分开：26003 是 HTTP 端点缺位，本码是工具缺位（一码一义） |
| 26303 | `McpIdentityHeaderRefusedError` | 403 | `identity_header_refused` | 「MCP 面不承载委托」（AC-30） |
| 26304 | `McpToolArgumentInvalidError` | 400 | `invalid_argument` | `data.errors` 为 pydantic 摘要 |
| 26305 | `McpAppNotOwnedError` | 403 | `not_your_app` | 非你名下应用 / 不存在，同响应、不带 owner 名（AC-34） |
| 26306 | `McpIdentityNotFoundError` | 404 | `unreachable` | 用户 / 部门不存在或跨租户，同响应（AC-32） |
| 26320 | `RetrievalIdentityMissingError` | 403 | `internal` | 执行身份缺失或无法确立（AC-23） |
| 26321 | `KnowledgeUnreachableError` | 404 | `unreachable` | `data.unreachable_ids`；不存在 / 未授予 / 类型不支持 / 白名单外 同响应（AC-11 / AC-27） |
| 26322 | `KnowledgeCapabilityRevokedError` | 409 | `capability_revoked` | `data.knowledge_id`；白名单条目已删除 / 不再受支持（AC-46） |
| 26323 | `RetrievalScopeTooLargeError` | 400 | `scope_too_large` | 目标 > 50 或授予范围 > 200，请显式指定 |

复用不新增：26001 / 26002 / 26030（凭据）、26051（delegate）、16207（运行时层未部署）、19002 / 19201（权限引擎，503 / `permission_unavailable`）。

**⑤ 审计**：`action="open_api.mcp.tool_call"`、`target_type="mcp_tool"`、`target_id=<tool 名或 "-">`、metadata 见 D7。

**⑥ 接入信息**：`GET /api/v1/dev-toolkit/versions` 增 `mcp: {url, transport, auth}`（D11）。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `open_api/mcp/server.py` | `BishengMcpServer(FastMCP)` 装配（D1 参数）、`list_tools` / `call_tool` 覆盖、注册表 → `add_tool` | 不鉴权、不碰 ContextVar |
| `open_api/mcp/gate.py` | `McpAccessGate` ASGI 闸：admit → K3 两拒 → execution_scope → 传输层错误信封 → 传输层审计 | 不认识任何工具 |
| `open_api/mcp/registry.py` | `TOOL_REGISTRY` / `McpToolSpec` / `visible_tools(principal)` / `require_tool(principal, name)` | 不执行工具 |
| `open_api/mcp/errors.py` | `McpToolError`、`ERROR_CATEGORY_MAP`、`to_tool_error(exc)`（任意异常 → 三要素） | 不定义错误码（那在 `common/errcode/mcp_face.py`） |
| `open_api/mcp/audit.py` | `audit_tool_call(...)`、`audit_transport_refusal(...)` | 不写 query 正文 |
| `open_api/mcp/tools/{knowledge,models,identity,apps}.py` | 六类 handler：入参 pydantic 模型、构造执行身份 / actor、调领域服务、把结果整形为 §4.2 ② | 不做权限判定（门面 / 服务层做）、不直连 manager |
| `open_api/api/dependencies.py` | 拆出 `admit_open_api_principal` / `open_api_execution_scope`（D2）；`open_api_access_context` 行为不变 | — |
| `knowledge/domain/services/retrieval_engine.py` | 从聊天服务搬出的检索引擎（双层过滤、tag 解析、更新时间水合） | 不判可及性、不知道白名单 |
| `knowledge/domain/services/retrieval_facade_service.py` | 门面：身份 fail-closed、范围解析、可及性、白名单、上限、收回信号、清单 | 不创建会话、不写消息 |
| `knowledge/domain/services/knowledge_space_chat_service.py` | `aretrieve_chunks` 薄委托引擎；对话链其余不变 | — |
| `department/domain/services/org_directory_service.py` | 租户全量组织只读（D8） | 不收窄、不返回凭据字段 |
| `app_publish/domain/services/publish_status_service.py` · `app_runtime/domain/services/app_query_service.py` | 加 `entry` owner-only（D9） | — |
| `dev_toolkit/api/endpoints/distribution.py` | `versions` 增 `mcp` 段（D11） | — |
| `common/errcode/mcp_face.py` | 263 段 | — |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `FastMCP(host="127.0.0.1")`（默认）自动装 `TransportSecuritySettings(allowed_hosts=["127.0.0.1:*","localhost:*",…])`（`server.py:178-183`）；DNS-rebinding 校验对 `Host: 192.168.106.114` 返回 421 | 本地测试全绿、上 114 经 nginx 全 421 | D1：显式 `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)`（nginx / 网关已是入口信任根） |
| 2 | `StreamableHTTPSessionManager.handle_request` 要求先进入 `run()` 任务组（`streamable_http_manager.py:99-140`），且 `run()` 只能进一次 | 挂载了但 lifespan 没进 → 每个请求 RuntimeError 500；uvicorn `--workers N` 每进程各进一次是正确的 | `main.py lifespan` 内 `async with mcp_server.session_manager.run():`（只在开关开时） |
| 3 | v2 `POST /filelib/retrieve` **今天已是文件级双层过滤 + fail-closed**：`aretrieve_chunks :726 → _aretrieve_chunks_dispatch :836 → _retrieve_and_filter :393`（`build_index_prefilter :120` + `post_filter_retrievable_files :237`，`knowledge_file_visibility_service.py:217` 明写 no creator/admin fallback），权限引擎故障由 `permission_action_service.py` 抛 19002 → `filelib.py:722` 包成 26030。Discovery / 伴生 B.1「只做库级一次校验」结论**已过时**；`filelib.py:700-702` 注释与实现一致 | 按 spec 字面「从库级升级到文件级」去重写检索链 = 造第三条路径 | D5 抽出而非重写；D6 只改错误形态与身份构造；`docs/api/filelib-retrieve.md:287` 才是失实处 |
| 4 | `KnowledgeSpaceChatService` / `KnowledgeFileVisibilityService` / `KnowledgeSpaceService` 构造都收 `request: Request`，但检索判定链（`_require_action` / `batch_check_business_actions` / `resolve_permission_actor`）读的是 `login_user` 与 ContextVar，`self.request` 只在会话 / 上传路径用 | 假设「必须有 Request」→ 门面伪造 Request 或绕不开聊天服务 | T101 搬出引擎时用 `request=None` 构造可见性服务并加守卫测试；若发现判定链读 `self.request`，改为可选并记偏差 |
| 5 | `resolve_permission_actor(login_user)` **先读 ContextVar** `current_permission_actor`（`permission/application/identity.py:40-42`）——v2 与 MCP 闸已装的 actor 会覆盖 `login_user` 派生；F055 / F050 调门面时若忘装 actor，就按 `login_user` 派生（自然人事实正确，但服务账号会被当 `user` 类型） | 服务账号执行身份类型错位 → FGA 查错主体 → 全部不可见（fail-closed 方向，但结果错） | D5：门面体内自己 `set_current_permission_actor(identity.actor)`，调用方无需关心 |
| 6 | `aretrieve_chunks` 对空 `knowledge_base_ids` 抛 `HTTPException(400)`（`:746`）；`KnowledgeTypeNotSupportedError` 是 10962；`NotFoundError` 404；空间权限 `SpacePermissionDeniedError` 18040 —— 三种「不可及」今天是**三个可区分响应** | 以为不可及已统一 | D5 门面在引擎之前做批判并统一为 26321；引擎内部异常只在「批判通过后行被并发删除」这类竞态才会冒出 → 门面兜成 26321 |
| 7 | `KnowledgeService.get_knowledge` 的 admin bypass（`knowledge_service.py:507-519`）对 `data_scope != all` 关闭；服务账号永不为管理员（beta2 `PermissionActor` 对 service_account 强制清零 super/tenant_admin，`open_api/domain/context.py:47-53` 注释） | 在门面「全部授予范围」枚举里给服务账号走 DB 扫描 = 全租户泄露 | D5 只对 `actor.super_admin ∨ tenant_admin` 且 `data_scope==ALL` 走扫描 |
| 8 | `get_open_api_operator_async()`（`open_endpoints/domain/utils.py:62-81`）会对自然人调 `init_login_user`（多 1 次 Redis / FGA）并对服务账号构造 `force_non_admin` 的 `UserPayload` | 门面执行身份若经它构造，每次检索多两次远程调用 | `RetrievalIdentity.from_open_api_principal` 直接构造 `UserPayload(is_global_super=False, user_role=[])`，管理员事实取自已装 actor |
| 9 | `_OWNER_ONLY_ENTRIES` 只在 `_require_log_access` 生效；`get_instance → _load_visible :246-261` 与 `PublishStatusService._require_viewer :181-197` 放行租户管理员与超管 | 应用状态工具违反 AC-35 | D9 `entry` 参数 |
| 10 | `AppQueryService._load :237-244` 会 `set_current_tenant_id(app.tenant_id)` **覆盖** ContextVar，之后再比租户就恒真 | 工具层在服务返回后做租户比对 = 无效 | 租户比对由服务层按 actor 做（`:266-284` 注释已说明）；工具层不重复判 |
| 11 | `OpenApiAuditMiddleware` 按前缀 `/api/v2` 无差别记 `open_api.call`（`middleware.py:22-27`） | MCP 每次调用双记、且那条只有 `POST /api/v2/mcp` | D7 中间件短路 |
| 12 | `test_open_api_route_matrix.py:37-41` 对 `app.routes` 取 `route.endpoint`；`Mount` 无该属性 | 挂载后整个测试文件 AttributeError | T203 改为只遍历 `APIRoute` / `APIWebSocketRoute`，另加 `test_mcp_mount_present_iff_open_platform_enabled` |
| 13 | `settings.open_platform.enabled` 是进程级 YAML 键（`core/config/open_platform.py:8`），`api/router.py:139` 在**导入期**判断；`main.py` 挂载亦在 `create_app` 期判断 → 翻开关必须重启；114 `config.yaml` 未跟踪、新增顶级键让老镜像拒启 | 改了 yaml 不重启 / 先加键后发代码 | 部署顺序：先发代码、再加键、全量重启（memory `project_compose_vs_systemd_form_divergence`） |
| 14 | `mcp` 低层 `call_tool` 对 handler 异常统一 `_make_error_result(str(e))`（`lowlevel/server.py:583-584`）——异常类型信息丢失，只剩字符串 | 想靠异常类让客户端区分失败类别 = 不可能 | D4：JSON 进 `str(e)` |
| 15 | FastMCP 的 `Context.request_context.request`（`server.py:1154`）在 stateless 模式下是当次 `Request`，但**在 `list_tools` 里没有 Context 参数** | 想从 Request 拿 principal 过滤清单 → 拿不到 | 用 ContextVar `get_current_open_api_principal()`（闸已装） |
| 16 | `resource_owner_of(principal)`（`publish_pipeline_service.py:111-123`）对 `resource_owner_user_id=None` 抛 16205 而非当 0 | PAT 主体调应用工具得到「归属不符」而非「缺位」 | 注册表先判 `app:manage`（PAT 签不出该位 → 26302 先于 16205） |
| 17 | 服务账号在 beta2 是独立 `service_account` 表（无 `user` 行），组织查询天然不含；但 `UserPayload.user_id` 对服务账号取的是 `authorization_subject_id`（服务账号 id，非 user id） | 用该 id 去 `UserDao.aget_user` 会拿到**同 id 的自然人** | 门面 / 工具层**从不**用服务账号的 `user_id` 查 `user` 表；应用类工具用 `resource_owner_of` |
| 18 | `pnpm check-i18n`（`src/frontend/scripts/check-i18n.mjs`）对后端码的识别靠正则 `Code:\s*int\s*=`（`:105`）——写成 `Code = 26301` 的类**不被计入**、缺三语也不报；三语键一致性（`:78-88`）对 `packages/locales/src/api_errors/*.json` 生效、多一语少一语都拦；后端进程**不装**前端 locale 包，`api_errors` JSON 在运行期读不到 | 错误码类写法漏 `: int` → 无三语也绿；把 `next_step` 放进 `api_errors` → 后端拿不到、只能再复制一份 | T001 子类一律 `Code: int = 263xx`；`next_step` 三语放后端 `errors.py: NEXT_STEP_COPY`（D4），T203a 断言 `ERROR_CATEGORY_MAP` 每码三语齐全 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `POST /api/v2/mcp`（§4.2 ①）+ 六类工具（§4.2 ②） | MCP streamable-http | 开发者本地 agent；F053 T041 跨 Feature 旅程；PAT 持有人的 AI 助手（两工具） |
| `RetrievalFacadeService.retrieve / list_accessible_knowledge / check_reachable / is_supported_knowledge_type` + `RetrievalIdentity`（§4.2 ③） | 内部 Python | v2 `filelib.retrieve_chunks`（本 Feature）· **F055** T057（`from_user(访问用户)` + `whitelist=能力声明`）/ T060 预检（`is_supported_knowledge_type` / `check_reachable`）· **F057** SDK retrieve 的服务端（经 v2 端点或 F055 注入通道）· **F050** AC-43（`from_open_api_principal(模式 D principal)`） |
| 26322 `KnowledgeCapabilityRevokedError(data.knowledge_id)` | 异常 | F055 AC-53 转 16273 |
| `GET /api/v1/dev-toolkit/versions.mcp.url` | HTTP | F053 T046 接入信息区 |
| `open_api.mcp.tool_call` 审计行 | audit_log | F056 查询面 |
| `PublishStatusService.get_publish_status(..., entry=)` / `AppQueryService.get_instance(..., entry=)` | 内部 Python（加参，缺省行为不变） | F055 发布面 / F054 详情页（无感） |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `validate_bearer` / `open_api_access_context` 装配块（beta2 F053） | 内部 Python（本 Feature 拆分导出，行为不变） | `test/open_api` 40 个测试文件是回归护栏 |
| `PermissionActor(data_scope)`（F066）· `batch_check_business_actions` / `runtime.list_visible_objects`（F048） | 内部 Python | `list_visible_objects` 有 5000 上限；门面自设 200 |
| `KnowledgeSpaceChatService` 三个私有检索方法（F029 / F030） | 代码搬迁 | 搬后聊天服务的 `test/knowledge` 既有用例必须仍绿 |
| `AppQueryService.get_logs(entry=LOG_ENTRY_MCP)`（F054 已预埋）· `PublishStatusService.get_publish_status`（F055） | 内部 Python | 加 `entry` 是本 Feature 改动，F055 design §4.2 ② 字段原样透传 |
| **F054 `AppDataService`（T086/T087，HEAD 树上不存在；本波次 data-plane 切片同期实现）** | 内部 Python（签名按 D9 假设：`list_tables / get_schema / read_rows / update_row(..., actor, entry)`） | 落地后签名若异 → 只改 `tools/apps.py`、记 tasks 偏差；insert / delete 需 F054 补 RPC（T209 回写请求） |
| **F051 `resolve_callable_names`（未落地）** | 内部 Python | 未落地时工具 ③ 不注册（26301） |
| `mcp==1.27.1`（uv.lock 已有） | 依赖 | 升级需复核 K11 两处与 D4 的 `_make_error_result` 行为 |
| nginx `/api` location · 网关 `/api/v2/**` 代理 | 部署 | JSON 响应无长连接，现配置即可；114 系统形态与 compose 形态各验一次 |

---

## 7. 测试与可观测

- **单元（本地可跑，无中间件）**：`test/open_api/test_mcp_*.py`（闸 / 注册表矩阵 / 错误三要素 / 审计 / 开关 / delegate 与身份头拒绝 / 密钥零回显）用 `mcp_client` fixture + monkeypatch 领域服务；`test/knowledge/test_retrieval_facade.py`（身份 fail-closed / 范围解析 / 白名单三态 / 上限截断可见 / 26321 同响应 / 26322）用 fake 引擎；`test/knowledge/test_retrieval_engine_extraction.py`（搬迁等价：聊天服务 `aretrieve_chunks` 与引擎同输入同输出）。
- **集成（CI 中间件分组，`-m e2e`）**：`test/knowledge/test_retrieval_facade_equality.py`——样本按 AC-40：未授予库、同一空间部分文件无权（单文件直接授权 / 自定义模式脱钩 / 文件夹差异三种来源各一）、文档库库级、白名单外库、被代表用户；三处（MCP / v2 / 门面直调）集合相等；`fga_down` 三处零结果明确错误（AC-44）；撤销后 ≤ 5s 拒绝（AC-05）。
- **114 手动**（`bash /opt/bisheng-ops/deploy.sh` 后；`config.yaml` `open_platform.enabled: true`）：① `curl -s -o /dev/null -w '%{http_code}' -X POST http://192.168.106.114:4101/api/v2/mcp` → 401；② `claude mcp add --transport http bisheng http://192.168.106.114:4101/api/v2/mcp --header "Authorization: Bearer <bs-sak-…>"` → `/mcp` 列出与权限位一致的工具；③ 用非管理员 `shuiwu` 名下服务账号（只授 1 个知识空间且其中 1 个文件单独收权）验证 `bisheng_knowledge_search` 不返回该文件；④ 撤销密钥 → 5s 内工具调用 401；⑤ `app_runtime.enabled: false` 的环境上两类应用工具不在清单、直调 16207。
- **日志 / 指标**：闸与工具层各一条结构化日志 `open_api.mcp | tool=… credential_id=… outcome=… latency_ms=…`（不含 query）；门面复用引擎既有 `permission_filter | …` 行（`knowledge_space_chat_service.py:463-471` 搬入引擎）；审计行按 D7。

---

## 8. 后续改进 / 不打算做的事

- **有状态会话 / SSE / 服务端通知**（D1）；**OAuth 2.1 RS 元数据 / `token_verifier`**（D2）；**MCP 限流与按 key 账单**（PRD-1 §5.2）；**第三方 MCP 网关化**（§5.2）；**QA 库检索**（决议-10）；**文档知识库文件级权限**（决议-3）；**审计高频分层**（决议-12 → F056）；**应用数据工具的写二次确认**（决议-8「何时重新考虑」）。
- **tools/list 分页**：SDK 支持 cursor，本版工具 ≤ 15 个，一页返回。
- **触发重写的条件**：MCP 规范把错误结构化正式化 → D4 迁移；工具 > 30 → D3 改 DB 驱动。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-16 | 初版（全自动模式定案 D1–D12；坑 1–18；263 段错误码；门面契约 §4.2 ③） | F052 design/tasks 编写工作流 |
| 2026-09-16（续） | 接手续写：全部 `文件:行号` 按 HEAD `fe10f75ea` 重新 grep 核实并订正（`_attach_document_update_time :788`、`distribution.py:56`、`filelib.py:689/:722`、`test/open_api` 40 文件等）；**D4 `next_step` 三语改为后端自有 `NEXT_STEP_COPY`**（原拟放 `api_errors` 的 `<code>.next_step` 键作废——后端运行期读不到前端 locale 包，坑 18 重写）；D9 / §6.2 标注 `AppDataService` 由本波次 data-plane 切片同期实现 | 前序 agent 中断，全自动模式续写定案 |
