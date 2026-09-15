# Design: F067 通用开放能力的统一远程 MCP 服务

> **本文档定位 — 现状快照（Why this How）**
>
> - [spec.md](./spec.md) 定义做什么和验收边界。
> - 本文定义统一 MCP 服务为什么采用当前方案、现有系统基线、对外合同与实现护栏。
> - `tasks.md` 在 Design ★ 确认后创建，记录实施顺序与实际偏差。

**关联**: [spec.md](./spec.md) · [discovery.md](./discovery.md) · [release-contract.md](../release-contract.md)
**版本**: v3.0.0-beta1
**最后更新**: 2026-09-15
**状态**: ✅ Design 已于 2026-09-15 确认；尚未生成 `tasks.md`

---

## 1. 目标与非目标

- **目标**：在每个 BISHENG 部署内提供一个统一、远程、可发现的 MCP 服务，把 F053 正式开放的 43 项业务路由能力（41 HTTP + 2 WebSocket，不含 `auth/whoami`）转换为稳定工具；MCP 与开放 API 共用身份、权限、业务服务、结果语义和审计。
- **非目标**：不把现有 `mcp_manage` 客户端改造成服务端，不新增业务能力或密钥体系，不为每个工具复制一套业务实现，不依赖单机内存维持授权或业务会话，也不替换现有 `/api/v2`。

---

## 2. 关键约束与 Constitution Check

- 遵循 [docs/constitution.md](../../../docs/constitution.md) C1–C8；本方案的共享能力层保持 `Transport Endpoint → Domain/Application Service → Repository → DB`，权限仍只经 F048，跨副本状态不落本地文件或进程内会话。
- 遵守版本契约 **INV-29～35**：MCP 只能使用 F053/F066 已签发凭据与 S/D/PAT 规则；PAT 数据范围优先于管理员短路；身份或权限不可判定时失败关闭。
- 锁文件当前解析 `mcp==1.27.1`。服务端只使用该版本已有的 Streamable HTTP 与低层 Server/会话管理能力；升级 SDK 必须重跑协议与多副本回归。
- 一个部署只有一个逻辑 MCP 地址。后端可以有多个无状态副本，但不得要求客户端固定到某个副本。
- MCP 工具参数是 JSON；认证信息只来自 HTTP 请求头。文件类工具不得接收服务器本地路径，避免把节点文件系统变成外部合同。
- 当前正式文档有 44 个条目，其中 42 HTTP + 2 WS；`GET /api/v2/auth/whoami` 是认证诊断，不属于 PRD §3 业务映射，因此本期业务覆盖基线是 43 项（41 HTTP + 2 WS）。
- F067 不新增数据库表、Alembic revision 或错误码段；协议错误使用 MCP/JSON-RPC 标准错误，业务错误复用对应开放 API 的既有状态码与业务码。

### Constitution Check

| 条款 | 结论 | 设计落实 |
|---|---|---|
| C1 分层 | 通过 | HTTP 与 MCP 都只调用共享能力 Service；MCP transport 不直接查 ORM |
| C2 双 DB | 通过 | 无新 schema；共享业务能力继续走既有 MySQL/DM8 兼容路径 |
| C3 多租户 | 通过 | 每次请求从凭据设置 tenant ContextVar，结束时按 token 恢复 |
| C4 权限 | 通过 | 复用 `current_permission_actor` 与业务 Service 的 F048 action 检查，不直连 OpenFGA |
| C5 错误码 | 通过 | 不占新模块；透传既有业务码，协议层使用标准 JSON-RPC 码 |
| C6 密钥 | 通过 | 文档只写占位符；日志、审计、结果不记录 Authorization 或文件内容 |
| C7 前端 store | 不涉及 | 本 Feature 无站内前端状态改造 |
| C8 多节点 | 通过 | Streamable HTTP 无状态；业务会话仍在 DB/Redis/对象存储，不以进程内 MCP session 为真相 |

---

## 3. 方案对比与选定

### 决策 1：服务部署形态与传输

- **备选**：
  - A. 新建独立 MCP 容器和端口——可独立扩缩，但需要复制配置、生命周期、鉴权上下文和商业网关路由。
  - B. 挂载到现有 FastAPI 应用，采用有状态 Streamable HTTP——接入简单，但 MCP session 要求副本亲和或共享 session store。
  - C. 挂载到现有 FastAPI 应用，采用无状态 Streamable HTTP——复用部署入口且不要求副本亲和。
- **选定**：C。对外地址固定为 `$BASE/api/v2/mcp`，与 `/api/v2` 共享后端端口和商业网关入口；每个 HTTP 请求重新认证，MCP transport session 不承载业务授权状态。
- **原因**：当前业务能力、凭据 ContextVar、审计 flusher 与应用生命周期都在 `bisheng.main`；C 同时满足“一个服务地址”和 C8 多副本要求。A 会制造第二套运行面，B 会把进程内 session 变成隐式基础设施依赖。
- **何时该重新考虑**：MCP 流量需要独立 SLA/扩缩容，或 SDK 后续协议能力明确要求服务端持久 session 时，再拆独立进程；拆分前必须先提供共享 Redis/DB session 真相与同一身份上下文。

### 决策 2：业务能力复用方式

- **备选**：
  - A. 从 OpenAPI schema 自动生成工具并通过本机 HTTP 回调 `/api/v2`——初始代码少，但 multipart、二进制、SSE、WS 和错误信封无法可靠自动转换；还会产生递归 ASGI/网络调用与重复审计。
  - B. MCP handler 直接复制每个 endpoint 的业务调用——交付快，但 43 项能力会形成两套参数校验、权限与错误分支。
  - C. 建立显式 `OpenCapabilityRegistry`，把 HTTP endpoint 的业务编排下沉为共享能力 Service，HTTP 与 MCP 仅做各自 transport 转换。
- **选定**：C。每项能力显式登记 `tool_name / source_routes / scope / modes / input_model / handler / result_kind`；现有 v2 endpoint 逐项改为调用同一 handler。
- **原因**：`OPEN_API_SCOPES` 已是 43 项业务路由和 scope 的可枚举基线，但现有 endpoint 直接调用多个业务 Service，尚无可安全复用的 transport-neutral 层。显式注册能处理例外，又可用测试证明没有漏映射。
- **何时该重新考虑**：正式 OpenAPI 文档具备稳定、完整的 operation id、文件/流式扩展和 MCP 映射元数据，并能生成等价契约测试时，可考虑代码生成；在此之前不以自动生成替代人工能力声明。

### 决策 3：认证分两阶段、复用 F053 上下文

- **备选**：
  - A. 使用 MCP SDK 自带 token verifier，独立实现 scope 与委托——会形成第二套凭据解释和缓存失效规则。
  - B. 连接初始化时认证一次，后续工具调用信任 MCP session——撤销、过期和权限变化不能按既有上界影响长连接。
  - C. 抽取 F053 现有认证上下文：每个 transport 请求完成凭据与身份准入；工具发现按 registry 过滤；每次 `call_tool` 再按工具声明校验 scope/mode 并安装 permission actor。
- **选定**：C。`verify_open_api_access` 与 MCP auth adapter 共用一个 `OpenApiAccessContext` 服务，不共享 FastAPI endpoint marker 这一 transport 细节。
- **原因**：现有 `verify_open_api_access` 已处理凭据、PAT 两层开关与数据范围、S/D、特权目标、tenant/visible tenant 以及 permission actor；只复用底层服务才能保持 INV-35 且支持 MCP 的“同一路径、不同工具 scope”。
- **何时该重新考虑**：平台正式引入 OAuth/OIDC MCP authorization server 时，允许替换 transport 凭据交换；交换后的 principal、scope、租户、委托和 F048 执行合同仍不得分叉。

### 决策 4：工具粒度与流式/交互适配

- **备选**：
  - A. 一个万能 `call_api(method, path, body)` 工具——工具数量少，但模型可以构造任意路径，无法可靠做发现过滤和参数描述。
  - B. 按业务组提供少数巨型工具，以 `action` 字段分支——schema 宽泛，权限和必填项难以静态表达。
  - C. 每项正式业务操作一个稳定工具；HTTP 流式调用在一次工具调用内收集到业务边界，WS 交互转换为“一次用户回合一次工具调用”。
- **选定**：C。工具名见 §4.3；SSE/WS 的中间事件可通过 MCP progress 通知发送，但最终 `CallToolResult` 必须包含完整结果，客户端不能只靠 progress 才能取得业务结果。
- **原因**：显式工具能按 scope/mode 精确过滤。MCP `call_tool` 是请求/结果模型，不能把原始 WebSocket 直接冒充 MCP transport；以回合为边界保留 session id、等待输入、停止和终态语义。
- **何时该重新考虑**：MCP 标准形成跨客户端一致的长期任务/双向交互原语后，可将长任务映射到标准 task；工具名和已有输入输出仍需兼容版本管理。

### 决策 5：结果、错误与文件合同

- **备选**：
  - A. 所有结果转成自然语言文本——模型易读，但会丢字段、错误码和分页合同。
  - B. 只返回原 API JSON 字符串——字段完整，但二进制与 MCP 错误状态不可表达。
  - C. 返回统一结构化结果，保留 API 业务信封；二进制用 MCP blob/embedded resource，上传用受限 base64 文件对象或原 API 已允许的 `file_url`。
- **选定**：C。普通结果写入 `structuredContent`；失败置 `isError=true` 并保留 `status_code/status_message/http_status/data`。工具参数禁止 `file_path`、`user_id` 和认证字段。
- **原因**：MCP transport 没有“每个工具自己的 HTTP status”，显式 `http_status` 和业务码才能保持调用方可判定性；base64/URL 适配避免读取任意节点路径并满足 C8/C6。
- **何时该重新考虑**：平台提供带同凭据授权的对象存储 resource server 后，大文件可改用短期 MCP ResourceLink；在此之前不得返回裸 MinIO 路径或节点文件路径。

### 决策 6：覆盖守卫与审计粒度

- **备选**：
  - A. 只维护文档清单——代码演进后容易静默漏工具。
  - B. 每个 MCP HTTP 请求复用现有 `OpenApiAuditMiddleware`——一个请求可能包含 discovery 或多个 JSON-RPC 消息，无法保证逐工具审计且会把路径当成业务目标。
  - C. 构建期/测试期比较 registry 与 `OPEN_API_SCOPES`，运行期由每个工具 handler 显式复用 `OpenApiCallAuditService` 记一条调用审计。
- **选定**：C。`/api/v2/mcp` 从普通 v2 endpoint 审计中排除，避免 transport 与 tool 双记；认证失败仍记 MCP transport 拒绝，成功/业务失败按工具逐条记录。
- **原因**：代码中正式 scope registry 可枚举 43 个业务 source route；显式差集能阻止漏映射。逐工具审计才具有 actor/subject/tool/scope/result 的业务意义。
- **何时该重新考虑**：如果 MCP SDK 禁止 JSON-RPC batch，可简化“一请求多调用”分支，但仍保留逐工具审计；若审计服务改为统一事件总线，只替换 sink，不改变字段合同。

---

## 4. 系统现状与目标结构（接手必读）

### 4.1 当前基线

- `bisheng/api/router.py` 把正式开放路由挂在 `/api/v2`，统一依赖 `verify_open_api_access`。
- `bisheng/open_api/domain/scopes.py` 的 `OPEN_API_SCOPES` 登记 43 个业务 route、scope、可用模式；`auth/whoami` 使用 `scope=None`，不在业务清单中。
- `bisheng/open_api/api/dependencies.py:verify_open_api_access` 同时安装 tenant、visible tenant、`OpenApiPrincipal` 与 `PermissionActor`，并在请求结束恢复 ContextVar。
- `bisheng/open_api/api/middleware.py` 按 HTTP/WS 请求写 `open_api.call` 审计；ContextVar 的 principal 也复制到 ASGI `scope`，避免外层中间件读不到子任务上下文。
- `bisheng/open_endpoints/api/endpoints/` 的各 endpoint 目前直接编排业务 Service；这是 F067 必须抽共享能力层的主要改造点。
- `bisheng/mcp_manage/` 只负责 BISHENG 作为客户端连接第三方 MCP（stdio/SSE/Streamable HTTP）并转为 LangChain Tool；它不是服务端模块。

### 4.2 目标数据流

**工具发现**：

`POST /api/v2/mcp (initialize/tools/list)` → `OpenApiAccessContext` 每请求认证并解析 S/D/PAT → `OpenCapabilityRegistry.list_for(principal)` 按 scope/mode 过滤 → MCP SDK 返回当前可用工具定义。

**工具执行**：

`tools/call` → 重新认证 → registry 按 tool name 取得声明 → 校验 scope/mode/输入 → 安装 tenant/principal/permission actor → 共享 Capability Service → 既有业务 Service/F048 → `McpToolResultAdapter` → 逐工具审计 → finally 恢复全部 ContextVar。

**异步业务**：

`Capability Service` → 由 F053 `OpenApiExecutionSnapshot` 固化最小主体 → Celery/后台执行边界重新校验凭据与 PAT 数据范围 → 业务结果回到当前工具调用或既有 session/result 查询工具。MCP 不把完整凭据写入任务载荷。

### 4.3 工具目录与 source route

工具名是 F067 对外稳定合同；参数沿用对应正式 API 字段，经 §4.4 的统一转换。`source route` 用于覆盖测试，不表示 MCP 内部发起 HTTP 请求。

| scope | MCP 工具 | source route |
|---|---|---|
| `workflow:read` | `bisheng_workflow_get` | `GET /api/v2/flows/{flow_id}` |
| `workflow:invoke` | `bisheng_workflow_invoke` | `POST /api/v2/workflow/invoke` |
| `workflow:invoke` | `bisheng_workflow_stop` | `POST /api/v2/workflow/stop` |
| `workflow:invoke` | `bisheng_workflow_chat` | `WS /api/v2/workflow/chat/{workflow_id}` |
| `assistant:read` | `bisheng_assistant_list` | `GET /api/v2/assistant/list` |
| `assistant:read` | `bisheng_assistant_get` | `GET /api/v2/assistant/info/{assistant_id}` |
| `assistant:invoke` | `bisheng_assistant_chat_completion` | `POST /api/v2/assistant/chat/completions` |
| `assistant:invoke` | `bisheng_assistant_chat` | `WS /api/v2/assistant/chat/{assistant_id}` |
| `assistant:invoke` | `bisheng_speech_recognize` | `POST /api/v2/llm/workbench/asr` |
| `assistant:invoke` | `bisheng_speech_synthesize` | `POST /api/v2/llm/workbench/tts` |
| `chat:invoke` | `bisheng_daily_chat_completion` | `POST /api/v2/workstation/chat/completions` |
| `chat:invoke` | `bisheng_daily_config_get` | `GET /api/v2/workstation/config` |
| `chat:invoke` | `bisheng_daily_session_list` | `GET /api/v2/chat/list` |
| `chat:invoke` | `bisheng_daily_session_get` | `GET /api/v2/chat/info` |
| `chat:invoke` | `bisheng_daily_attachment_upload` | `POST /api/v2/knowledge/upload` |
| `knowledge:read` | `bisheng_knowledge_list` | `GET /api/v2/filelib/` |
| `knowledge:read` | `bisheng_knowledge_file_list` | `GET /api/v2/filelib/file/list` |
| `knowledge:read` | `bisheng_knowledge_retrieve` | `POST /api/v2/filelib/retrieve` |
| `knowledge:read`（仅 S） | `bisheng_knowledge_download_statistic` | `GET /api/v2/filelib/download_statistic` |
| `knowledge:read` | `bisheng_knowledge_qa_get` | `GET /api/v2/filelib/detail_qa` |
| `knowledge:read` | `bisheng_knowledge_qa_query` | `POST /api/v2/filelib/query_qa` |
| `knowledge:read` | `bisheng_citation_get` | `GET /api/v2/citation/{citation_id}` |
| `knowledge:write` | `bisheng_knowledge_create` | `POST /api/v2/filelib/` |
| `knowledge:write` | `bisheng_knowledge_update` | `PUT /api/v2/filelib/` |
| `knowledge:write` | `bisheng_knowledge_delete` | `DELETE /api/v2/filelib/{knowledge_id}` |
| `knowledge:write` | `bisheng_knowledge_clear` | `DELETE /api/v2/filelib/clear/{knowledge_id}` |
| `knowledge:write` | `bisheng_knowledge_file_upload` | `POST /api/v2/filelib/file/{knowledge_id}` |
| `knowledge:write` | `bisheng_knowledge_file_delete` | `DELETE /api/v2/filelib/file/{file_id}` |
| `knowledge:write` | `bisheng_knowledge_files_delete` | `POST /api/v2/filelib/delete_file` |
| `knowledge:write` | `bisheng_knowledge_chunks_upload` | `POST /api/v2/filelib/chunks` |
| `knowledge:write` | `bisheng_knowledge_text_chunks_upload` | `POST /api/v2/filelib/chunks_string` |
| `knowledge:write` | `bisheng_knowledge_qa_add` | `POST /api/v2/filelib/add_qa` |
| `knowledge:write` | `bisheng_knowledge_qa_add_related` | `POST /api/v2/filelib/add_relative_qa` |
| `knowledge:write` | `bisheng_knowledge_qa_delete` | `DELETE /api/v2/filelib/qa/{qa_id}` |
| `knowledge:write` | `bisheng_knowledge_qa_update` | `POST /api/v2/filelib/update_qa` |
| `knowledge:write` | `bisheng_knowledge_metadata_fields_add` | `POST /api/v2/knowledge/add_metadata_fields` |
| `knowledge:write` | `bisheng_knowledge_metadata_fields_update` | `PUT /api/v2/knowledge/modify_metadata_fields` |
| `knowledge:write` | `bisheng_knowledge_metadata_fields_delete` | `DELETE /api/v2/knowledge/delete_metadata_fields` |
| `knowledge:write` | `bisheng_knowledge_metadata_fields_list` | `GET /api/v2/knowledge/get_metadata_fields/{knowledge_id}` |
| `knowledge:write` | `bisheng_knowledge_file_metadata_add` | `POST /api/v2/knowledge/file/add_user_metadata` |
| `knowledge:write` | `bisheng_knowledge_file_metadata_update` | `PUT /api/v2/knowledge/file/modify_user_metadata` |
| `knowledge:write` | `bisheng_knowledge_file_metadata_delete` | `DELETE /api/v2/knowledge/file/delete_user_metadata` |
| `knowledge:write` | `bisheng_knowledge_file_metadata_list` | `POST /api/v2/knowledge/file/list_user_metadata` |

### 4.4 对外数据合同

#### 请求头

```text
Authorization: Bearer <BISHENG_API_KEY>      # 必填
X-On-Behalf-Of: <user_id>                    # D 模式按 F053 规则必填；不进入 tool arguments
X-End-User: <external_user_partition>        # 可选，仅沿用 F053 会话分区语义
```

MCP SDK 所需的协议头由 SDK 处理；服务端不从 MCP session id 推导身份。客户端每次请求都必须发送认证头。

#### 工具输入

- path/query/body 字段扁平为一个 JSON object，字段名、类型、必填项、默认值和上限来自正式 API Pydantic contract。
- `user_id`、`tenant_id`、`on_behalf_of`、`authorization`、服务器 `file_path` 不进入任何工具 schema。
- 文件统一为 `{"file_name": string, "mime_type": string|null, "content_base64": string}`；原 API 明确支持 `file_url` 的能力可二选一传 `file_url`。解码后继续受原 API 文件类型、大小、配额和安全检查约束。
- WS 对应工具以单轮输入调用：`workflow_id/assistant_id + chat_id/session_id（可选）+ 本轮输入`；返回下一次等待输入或终态，不暴露 WebSocket 帧。

#### 工具结果

```json
{
  "ok": true,
  "status_code": 200,
  "status_message": "SUCCESS",
  "http_status": 200,
  "data": {}
}
```

- 普通成功：完整对象放 `structuredContent`；文本摘要只作辅助，不是字段真相。
- 业务失败：`isError=true`，结构中保留对应 API 的 `status_code/status_message/http_status/data`。
- 参数或未知工具错误：使用 MCP/JSON-RPC 标准错误，同时不执行业务 Service。
- 二进制结果：返回 MCP embedded blob，并在结构中给出 `file_name/mime_type/size`；不回传服务器路径。
- 流式/交互：progress 可承载中间事件；最终结果必须包含 `session_id/chat_id/events/terminal_state`，取消或断连不伪造成功，也不自动替代显式 stop 语义。

#### 客户端配置示例

```json
{
  "mcpServers": {
    "bisheng": {
      "type": "streamable-http",
      "url": "https://<BISHENG_HOST>/api/v2/mcp",
      "headers": {
        "Authorization": "Bearer <BISHENG_API_KEY>"
      }
    }
  }
}
```

代表他人时只在可信客户端配置中增加 `X-On-Behalf-Of`；示例文档不得出现真实凭据。

### 4.5 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `bisheng/open_mcp/server.py` | 创建 MCP Server、注册 list/call handler、暴露无状态 Streamable HTTP ASGI app | 不认证业务主体，不调用 ORM |
| `bisheng/open_mcp/registry.py` | 声明 43 个工具的名称、schema、source route、scope、modes、handler、结果类型 | 不从 URL 动态执行任意 endpoint |
| `bisheng/open_mcp/auth.py` | 把 MCP HTTP 请求接入共享 `OpenApiAccessContext`，保证每请求 set/reset | 不实现新 token verifier，不缓存永久授权 |
| `bisheng/open_mcp/result.py` | API 业务结果、错误、流和二进制到 MCP 内容的转换 | 不改写业务成功/失败结论 |
| `bisheng/open_mcp/tools/*` | 薄工具绑定和文件/交互参数适配 | 不复制业务授权或持久化逻辑 |
| `bisheng/open_endpoints/domain/services/*` | HTTP 与 MCP 共用的 transport-neutral 能力编排 | 不感知 MCP JSON-RPC 或 FastAPI Response |
| `bisheng/open_api/domain/services/access_context.py` | 从现有 dependency 抽出凭据、S/D/PAT、tenant、permission actor 生命周期 | 不根据 tool 参数确定身份 |
| `bisheng/open_api/domain/services/call_audit_service.py` | 接收 HTTP/MCP 统一调用审计事件并批量写既有表 | 不记录请求正文、密钥或文件内容 |
| `bisheng/main.py` | 把 `/api/v2/mcp` 与 SDK lifespan 纳入现有 app | 不创建第二端口或节点本地 session store |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `mcp_manage` 名字像服务模块，实际只有出站客户端 | 在其中加入 server 会把内外两个方向的生命周期和依赖混在一起 | 新建 `bisheng/open_mcp/`；`mcp_manage/` 保持不变 |
| 2 | `verify_open_api_access` 通过 FastAPI endpoint 上的 marker 找 scope；MCP 的 43 个工具共用一个 HTTP endpoint | 直接复用 dependency 会得到“endpoint 未登记”，或只校验一次公共 scope | `open_api/domain/services/access_context.py` + `open_mcp/registry.py` |
| 3 | ASGI 外层中间件读不到依赖子任务里仅写 ContextVar 的 principal | MCP 审计会丢 actor/subject，甚至串用后续请求身份 | auth context 显式传 principal；逐工具审计不依赖外层回读 ContextVar |
| 4 | `/api/v2/mcp` 会命中现有 `OpenApiAuditMiddleware` 前缀 | 不排除会同时生成 transport 和 tool 两条成功审计，统计翻倍 | `open_api/api/middleware.py` 精确排除 MCP 路径，MCP handler 逐调用记账 |
| 5 | 正式 API 文档 44 条包含 `auth/whoami`，业务 scope registry 只有 43 条 | 把“44”写死会误造诊断工具或永远报告漏 1 项 | coverage test 比较 source route 集合并显式 allowlist 排除 whoami |
| 6 | 当前正式文档的 `download_statistic` 使用安全 `file_name`，代码快照仍可见旧 `file_path` 形态 | MCP 若照旧代码生成会暴露节点路径并违反 C8；也说明单看路由代码不能代表正式合同 | F067 实施前先让 F053 route、文档和测试一致；registry 只接收 `file_name` |
| 7 | `knowledge/get_metadata_fields` 是读操作名称，但当前正式 scope 是 `knowledge:write` | 凭语义猜 scope 会让 PAT 意外获得元数据能力 | registry 的 scope 只能来自 `OPEN_API_SCOPES`，不得按工具名重分类 |
| 8 | MCP 工具列表可见只证明 credential scope；具体资源仍需业务 action | 仅在 discovery 过滤会造成跨资源越权 | 每次 handler 进入既有业务 Service/F048；见 `open_mcp/auth.py` |
| 9 | MCP tool arguments 不能安全代表本机上传文件 | 接受 `/tmp/x` 或 `/app/data/x` 会读取某个副本文件并泄漏路径 | `open_mcp/result.py` 只接受 base64/既有 file_url，临时文件沿既有安全上传生命周期 |
| 10 | MCP 请求可能被商业网关缓冲或剥离非标准头 | 直连后端可用、商业部署却初始化失败或 D 模式恒失效 | 网关验收必须覆盖 Streamable HTTP、`X-On-Behalf-Of`、`X-End-User` 和长响应 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `$BASE/api/v2/mcp` | 无状态 Streamable HTTP MCP endpoint | Claude Desktop、IDE、智能体平台、自动化客户端 |
| §4.3 的 43 个稳定工具名与 JSON schema | MCP `tools/list` / `tools/call` | 外部 MCP 客户端与模型 |
| §4.4 `McpToolResult` | structured content / error / embedded blob | 调用方的自动重试、分页、错误处理与文件消费 |
| `OpenCapabilityRegistry` | 内部 Python registry | MCP server、覆盖测试、工具文档生成 |
| transport-neutral capability handlers | 内部 async Python API | 现有 `/api/v2` endpoint 与 MCP tools |
| `open_api.call` + `target_type=mcp_tool` | `audit_log` 事件 | 管理审计、故障追踪 |

工具名移除或输入字段破坏性变更必须按对外 API 的版本治理处理；不能因 HTTP route 重命名而静默改变 MCP tool name。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F053 `ApiCredential` / `OpenApiPrincipal` / S-D / execution snapshot | Python domain contract + DB/Redis | principal 字段、委托强制规则或 5 秒失效上界变化会直接影响 MCP |
| F066 PAT data scope | tenant policy + permission actor | 若只在 HTTP dependency 应用，MCP PAT 会绕过管理员收窄 |
| `OPEN_API_SCOPES` | route/scope/modes registry | 新增/删除正式 route 未更新 MCP 时必须让 coverage test 失败 |
| F048 permission application API | `current_permission_actor` + business action | 不得从 MCP 直接调用 OpenFGA 或 SQL Grant 兜底 |
| 各业务 Service | Python async/sync contracts | endpoint 中若仍残留独占编排，API/MCP 结果会漂移 |
| `mcp==1.27.1` | Python SDK | Streamable HTTP lifecycle、错误/structuredContent 行为升级时可能变化 |
| 商业网关/反向代理 | HTTP path/header/stream forwarding | 路径未代理、body limit 太小或 buffering 会导致 MCP 失败 |
| MinIO/临时上传服务 | 文件输入输出 | 不得改用本地路径；多副本必须通过对象存储保持可读 |

---

## 7. 测试与可观测

### 7.1 分层策略

- **单元测试**：registry 工具名唯一、schema 无身份字段、scope/mode 过滤、结果/错误/二进制转换、ContextVar finally reset、审计脱敏。
- **契约测试**：从 `OPEN_API_SCOPES` 计算 43 个 source route，与 registry 做双向差集；明确排除 `auth/whoami` 和 B.2 空 scope。每个共享 handler 用同一输入分别经 HTTP adapter 与 MCP adapter，比较业务码、data 和副作用。
- **集成测试**：真实 ASGI MCP client 覆盖 initialize/list/call；S、D、PAT、撤销后复用连接、权限变化、OpenFGA/Redis 故障、multipart/base64、SSE 聚合、WS 单轮适配和取消。
- **E2E**：MySQL + Redis + OpenFGA 环境验证工作流、助手、知识读写、日常对话各至少一条成功/拒绝；商业网关再跑相同 smoke。DM8 由集中回归验证共享 handler 与审计写入。

### 7.2 手动验证

实现后从 `src/backend/` 执行（token 只放环境变量，不出现在 shell history 或日志）：

```bash
export BISHENG_MCP_URL='https://<BISHENG_HOST>/api/v2/mcp'
export BISHENG_API_KEY='<BISHENG_API_KEY>'
uv run python scripts/verify_open_mcp.py --url "$BISHENG_MCP_URL" --token-env BISHENG_API_KEY
```

脚本至少输出：协议初始化结果、可见工具数、缺失/多出 source route、选定只读工具结果、撤销后拒绝结果；任何凭据值必须掩码。

### 7.3 可观测

- 审计：`audit_log.action='open_api.call'`、`target_type='mcp_tool'`、`target_id=<tool_name>`，metadata 包含 channel、credential/actor/subject、scope、result、error_code、latency、trace_id，不含 arguments。
- 结构化日志：`open_mcp.tool_call`（tool/scope/mode/result/latency）、`open_mcp.coverage_mismatch`、`open_mcp.auth_failed`、`open_mcp.protocol_error`。
- 健康判据：MCP server 注册失败或 coverage 不完整时，不把 MCP endpoint 标记为可用；不得影响 `/health` 对基础进程的判断，也不得绕过发布验收。

---

## 8. 发布、后续改进与不做事项

### 8.1 发布顺序

1. 先完成共享 capability handler 和 HTTP 等价回归，保证 `/api/v2` 零行为变化。
2. 注册 43 个工具并让覆盖测试通过；生成工具文档和配置示例。
3. 挂载 `/api/v2/mcp`，更新商业网关 path/header/body/stream 配置。
4. 先用只读服务账号 smoke，再验证 D、PAT、写入、流式/交互和撤销。
5. 对外公布地址前确认审计、脱敏和 API/MCP 差集均为空。

**回滚**：F067 无 schema/data migration；发现协议、网关或工具问题时可撤回 `/api/v2/mcp` 路由并回滚后端镜像。共享 capability 重构必须保持 `/api/v2` 等价，因此回滚前后 API 数据合同不变；回滚只使 MCP 地址暂时不可用，不得撤销或改写既有凭据。

### 8.2 后续 / 不做

- 不把 B.2 应用工场扩展空 scope 预注册成隐藏工具；其业务与授权合同未发布。
- 不提供万能 HTTP 代理工具；它会绕过工具发现与 schema 边界。
- 不把 MCP session 作为登录 session，也不在内存中保存永久 principal。
- 暂不拆独立服务；当前没有独立容量/SLA 证据，拆分只会增加身份和部署漂移面。
- 暂不承诺 MCP 原生 task/resource server；待协议和主流客户端形成稳定互操作后再评估。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-15 | 初版：确定同进程无状态 Streamable HTTP、43 项显式 registry、共享能力层、两阶段认证、结构化结果与逐工具审计 | Spec ★ 已确认，进入 Design |
