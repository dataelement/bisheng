# Design: F067 通用开放能力的统一远程 MCP 服务

> **本文档定位 — 现状快照（Why this How）**
>
> - [spec.md](./spec.md) 定义做什么和验收边界。
> - 本文定义统一 MCP 服务为什么采用当前方案、现有系统基线、对外合同与实现护栏。
> - `tasks.md` 在 Design ★ 确认后创建，记录实施顺序与实际偏差。

**关联**: [spec.md](./spec.md) · [discovery.md](./discovery.md) · [tool-contracts.md](./tool-contracts.md) · [release-contract.md](../release-contract.md)
**版本**: v3.0.0-beta1
**最后更新**: 2026-09-18
**状态**: ✅ Design 评审问题已整改并于 2026-09-18 确认；已生成 `tasks.md`

---

## 1. 目标与非目标

- **目标**：在每个 BISHENG 部署内提供一个统一、远程、可发现的 MCP 服务，把[中粮 SeedMind Apifox 文档](https://s.apifox.cn/a0e36780-865a-4179-b7df-b51a01d5ebcc)当前列出的 10 项知识资源/文件 HTTP API 一对一转换为稳定工具；MCP 与开放 API 共用身份、权限、业务服务、业务结果语义和审计，协议形态差异只在 MCP 兼容层处理。
- **非目标**：不把现有 `mcp_manage` 客户端改造成服务端，不新增业务能力或密钥体系，不为每个工具复制一套业务实现，不依赖单机内存维持授权或业务会话，也不替换现有 `/api/v2`。

---

## 2. 关键约束与 Constitution Check

- 遵循 [docs/constitution.md](../../../docs/constitution.md) C1–C8；MCP 调用链保持 `MCP Transport → Compatibility Facade → Domain/Application Service → Repository → DB`，权限仍只经 F048，跨副本状态不落本地文件或进程内会话。
- 遵守版本契约 **INV-29～35**：MCP 只能使用 F053/F066 已签发凭据与 S/D/PAT 规则；PAT 数据范围优先于管理员短路；身份或权限不可判定时失败关闭。
- 锁文件当前解析 `mcp==1.27.1`，实施前必须按[官方安全公告 GHSA-jpw9-pfvf-9f58](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-jpw9-pfvf-9f58)升级到已修复会话鉴权问题的 `mcp>=1.27.2` 并重新锁定。服务端只使用 Streamable HTTP 与低层 Server/会话管理能力；升级 SDK 必须重跑协议与多副本回归。
- 一个部署只有一个逻辑 MCP 地址。后端可以有多个无状态副本，但不得要求客户端固定到某个副本。
- MCP 工具参数是 JSON；认证信息只来自 HTTP 请求头。文件类工具不得接收服务器本地路径，避免把节点文件系统变成外部合同。
- 本期范围是独立的 10 项 API allowlist，不是 F053 全量开放路由。Apifox 后续新增接口、`OPEN_API_SCOPES` 其他路由或任何 WS/SSE 能力都不会自动扩入 F067。
- 本期 10 项 API 全部为普通 HTTP/JSON 业务操作（文件上传需转换 multipart），不需要对原始 SSE 或 WebSocket 业务协议做 MCP 适配。
- F067 不新增数据库表、Alembic revision 或业务错误码段；协议错误使用 MCP/JSON-RPC 标准错误，工具执行错误按 MCP `isError` 结果返回明确 `code/message`。已有稳定业务码时复用业务码，但不把 HTTP 状态或 API 错误信封带入 MCP 工具输出。
- 现有 10 项 `/api/v2` API 的接口逻辑、校验与分支、调用顺序、副作用、路由、参数位置、字段、默认值、响应字段、错误信封和 HTTP 状态是只读兼容基线；F067 不得修改它们。不能原样用于 MCP 的协议形态由 MCP 工具 schema 和 compatibility adapter 单向适配。

### Constitution Check

| 条款 | 结论 | 设计落实 |
|---|---|---|
| C1 分层 | 通过 | MCP compatibility facade 只调用既有业务 Service；MCP transport 不直接查 ORM，现有 HTTP endpoint 无须为 F067 改合同 |
| C2 双 DB | 通过 | 无新 schema；共享业务能力继续走既有 MySQL/DM8 兼容路径 |
| C3 多租户 | 通过 | 每次请求从凭据设置 tenant ContextVar，结束时按 token 恢复 |
| C4 权限 | 通过 | 复用 `current_permission_actor` 与业务 Service 的 F048 action 检查，不直连 OpenFGA |
| C5 错误码 | 通过 | 不占新业务码模块；已有业务失败复用业务码，MCP 专有失败使用稳定符号码，协议层使用标准 JSON-RPC 码 |
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
  - B. MCP handler 直接复制每个 endpoint 的业务调用——交付快，但 10 项能力仍会形成两套参数校验、权限与错误分支。
  - C. 建立显式 `OpenCapabilityRegistry` 与 MCP compatibility facade，由 facade 把 MCP 参数转换后调用既有业务 Service，并把业务结果/异常转换为 MCP 合同；现有 HTTP endpoint 的接口逻辑和编码路径保持不变。
- **选定**：C。每项能力显式登记 `tool_name / source_routes / scope / modes / input_model / handler / result_kind`。F067 先冻结现有 API 行为快照，再新增 MCP facade/mapper；现有 endpoint 不因 F067 重写校验、分支、调用顺序、响应或异常处理。
- **原因**：`OPEN_API_SCOPES` 可提供这 10 项路由的 scope 基线，但它不是 F067 的范围真相；F067 必须以显式 10 项 allowlist 进行注册和差集测试。MCP 与 HTTP 的输入载体和结果包装本来就不同，单向 compatibility facade 能复用既有业务 Service，同时避免为追求线缆级一致而改变已发布 API。公共复用优先使用现有 application/domain Service；确有重复业务编排时，只允许抽取最小、传输无关且无协议包装的公共 capability，并以 API 行为快照证明抽取前后零差异。MCP 参数、结果和错误的协议适配始终留在 MCP 层。
- **何时该重新考虑**：正式 OpenAPI 文档具备稳定、完整的 operation id、文件/流式扩展和 MCP 映射元数据，并能生成等价契约测试时，可考虑代码生成；在此之前不以自动生成替代人工能力声明。

### 决策 3：认证分两阶段、复用 F053 上下文

- **备选**：
  - A. 使用 MCP SDK 自带 token verifier，独立实现 scope 与委托——会形成第二套凭据解释和缓存失效规则。
  - B. 连接初始化时认证一次，后续工具调用信任 MCP session——撤销、过期和权限变化不能按既有上界影响长连接。
  - C. 抽取 F053 现有认证上下文：每个 transport 请求完成凭据与身份准入；工具发现按 registry 过滤；每次 `call_tool` 再按工具声明校验 scope/mode 并安装 permission actor。
- **选定**：C。`verify_open_api_access` 与 MCP auth adapter 共用一个 `OpenApiAccessContext` 服务，不共享 FastAPI endpoint marker 这一 transport 细节。
- **原因**：现有 `verify_open_api_access` 已处理凭据、PAT 两层开关与数据范围、S/D、特权目标、tenant/visible tenant 以及 permission actor；只复用底层服务才能保持 INV-35 且支持 MCP 的“同一路径、不同工具 scope”。
- **何时该重新考虑**：平台正式引入 OAuth/OIDC MCP authorization server 时，允许替换 transport 凭据交换；交换后的 principal、scope、租户、委托和 F048 执行合同仍不得分叉。

### 决策 4：工具粒度与 allowlist 治理

- **备选**：
  - A. 一个万能 `call_api(method, path, body)` 工具——工具数量少，但模型可以构造任意路径，无法可靠做发现过滤和参数描述。
  - B. 按业务组提供少数巨型工具，以 `action` 字段分支——schema 宽泛，权限和必填项难以静态表达。
  - C. Apifox allowlist 每个 API 业务操作对应一个稳定工具，不自动暴露其他开放 API。
- **选定**：C。工具名和完整 allowlist 见 §4.3；本期恰好 10 个工具。
- **原因**：用户已明确限定本次需求的 Apifox 接口范围。一对一映射能让参数、权限、副作用和覆盖测试都可精确表达。
- **何时该重新考虑**：需求方明确要求扩展 Apifox allowlist 时，先重新确认 spec/design，再增加工具；不以 API 自身新增作为自动扩围信号。

### 决策 5：结果、错误与文件合同

- **备选**：
  - A. 所有结果转成自然语言文本——模型易读，但会丢字段、错误码和分页合同。
  - B. 只返回原 API JSON 字符串——字段完整，但调用方无法按 schema 校验业务结果和错误状态。
  - C. 成功返回逐工具结构化结果，失败使用 MCP tool error result；上传用受限 base64 文件对象或原 API 已允许的 `file_url`。
- **选定**：C。成功对象直接写入 `structuredContent` 并符合逐工具 `outputSchema`；失败置 `isError=true`、不设置 `structuredContent`，模型可见 JSON 明确返回 `error.code/error.message`。工具参数禁止 `file_path`、`user_id` 和认证字段。
- **原因**：[MCP Tools 规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)已区分成功结构化结果、工具执行错误与 JSON-RPC 协议错误，无需复制 HTTP `status_code/http_status`。保留稳定业务错误码和安全消息即可让调用方判定失败；base64/URL 适配避免读取任意节点路径并满足 C8/C6。
- **何时该重新考虑**：平台提供带同凭据授权的对象存储 resource server 后，大文件上传可改用短期 MCP ResourceLink；在此之前不得接受裸 MinIO 路径或节点文件路径。

### 决策 6：覆盖守卫与审计粒度

- **备选**：
  - A. 只维护文档清单——代码演进后容易静默漏工具。
  - B. 每个 MCP HTTP 请求复用现有 `OpenApiAuditMiddleware`——一个请求可能包含 discovery 或多个 JSON-RPC 消息，无法保证逐工具审计且会把路径当成业务目标。
  - C. 构建期/测试期比较 registry 与 F067 显式 10 项 allowlist，运行期由每个工具 handler 显式复用 `OpenApiCallAuditService` 记一条调用审计。
- **选定**：C。`/api/v2/mcp` 从普通 v2 endpoint 审计中排除，避免 transport 与 tool 双记；认证失败仍记 MCP transport 拒绝，成功/业务失败按工具逐条记录。
- **原因**：以全量 `OPEN_API_SCOPES` 作为期望集合会错误地扩大范围；显式 allowlist 的双向差集既能阻止漏映射，也能阻止额外暴露。逐工具审计才具有 actor/subject/tool/scope/result 的业务意义。
- **何时该重新考虑**：如果 MCP SDK 禁止 JSON-RPC batch，可简化“一请求多调用”分支，但仍保留逐工具审计；若审计服务改为统一事件总线，只替换 sink，不改变字段合同。

---

## 4. 系统现状与目标结构（接手必读）

### 4.1 当前基线

- `bisheng/api/router.py` 把正式开放路由挂在 `/api/v2`，统一依赖 `verify_open_api_access`。
- 中粮 SeedMind Apifox 文档当前列出 10 个 `/api/v2` 知识资源/文件 API；这 10 项是 F067 唯一范围基线。
- `bisheng/open_api/domain/scopes.py` 的 `OPEN_API_SCOPES` 登记了更多业务 route；F067 只从中取用 allowlist 对应路由的 scope，不把全量 registry 当作 MCP 覆盖集合。
- `bisheng/open_api/api/dependencies.py:verify_open_api_access` 同时安装 tenant、visible tenant、`OpenApiPrincipal` 与 `PermissionActor`，并在请求结束恢复 ContextVar。
- `bisheng/open_api/api/middleware.py` 按 HTTP/WS 请求写 `open_api.call` 审计；ContextVar 的 principal 也复制到 ASGI `scope`，避免外层中间件读不到子任务上下文。
- `bisheng/open_endpoints/api/endpoints/` 的各 endpoint 目前直接编排业务 Service；它们的对外参数、响应与异常编码是 F067 的冻结基线。MCP facade 可以调用同一批既有业务 Service，但不要求先改造 endpoint。
- `bisheng/mcp_manage/` 只负责 BISHENG 作为客户端连接第三方 MCP（stdio/SSE/Streamable HTTP）并转为 LangChain Tool；它不是服务端模块。

### 4.2 目标数据流

**工具发现**：

`POST /api/v2/mcp (initialize/tools/list)` → `OpenApiAccessContext` 每请求认证并解析 S/D/PAT → `OpenCapabilityRegistry.list_for(principal)` 按 scope/mode 过滤 → MCP SDK 返回当前可用工具定义。

**工具执行**：

`tools/call` → 重新认证 → registry 按 tool name 取得声明 → 校验 scope/mode/输入 → 安装 tenant/principal/permission actor → `McpCompatibilityFacade` 重建既有业务调用参数 → 既有业务 Service/F048 → `McpResultAdapter` 显式映射为 MCP 输出 → 逐工具审计 → finally 恢复全部 ContextVar。

**异步业务**：

`McpCompatibilityFacade` → 由 F053 `OpenApiExecutionSnapshot` 固化最小主体 → Celery/后台执行边界重新校验凭据与 PAT 数据范围 → 业务结果回到当前工具调用或既有 session/result 查询工具。MCP 不把完整凭据写入任务载荷。

### 4.3 工具 allowlist 与 source route

工具名是 F067 对外稳定合同；本表是范围 SSOT。完整顶层入参与出参见 [tool-contracts.md](./tool-contracts.md)，并经 §4.4 转换为 MCP JSON Schema。`source route` 用于覆盖测试，不表示 MCP 内部发起 HTTP 请求。

| # | 业务能力 | scope | modes | PAT | MCP 工具 | source route |
|---:|---|---|---|---|---|---|
| 1 | 查询知识资源列表 | `knowledge:read` | S/D | 是 | `bisheng_knowledge_list` | `GET /api/v2/filelib/` |
| 2 | 创建知识资源 | `knowledge:write` | S/D | 否 | `bisheng_knowledge_create` | `POST /api/v2/filelib/` |
| 3 | 更新知识资源 | `knowledge:write` | S/D | 否 | `bisheng_knowledge_update` | `PUT /api/v2/filelib/` |
| 4 | 删除知识资源 | `knowledge:write` | S/D | 否 | `bisheng_knowledge_delete` | `DELETE /api/v2/filelib/{knowledge_id}` |
| 5 | 清空知识资源内容 | `knowledge:write` | S/D | 否 | `bisheng_knowledge_clear` | `DELETE /api/v2/filelib/clear/{knowledge_id}` |
| 6 | 检索知识资源分段 | `knowledge:read` | S/D | 是 | `bisheng_knowledge_retrieve` | `POST /api/v2/filelib/retrieve` |
| 7 | 上传文件到知识资源 | `knowledge:write` | S/D | 否 | `bisheng_knowledge_file_upload` | `POST /api/v2/filelib/file/{knowledge_id}` |
| 8 | 查询文件列表 | `knowledge:read` | S/D | 是 | `bisheng_knowledge_file_list` | `GET /api/v2/filelib/file/list` |
| 9 | 删除文件 | `knowledge:write` | S/D | 否 | `bisheng_knowledge_file_delete` | `DELETE /api/v2/filelib/file/{file_id}` |
| 10 | 批量删除文件 | `knowledge:write` | S/D | 否 | `bisheng_knowledge_files_delete` | `POST /api/v2/filelib/delete_file` |

### 4.4 对外数据合同

#### 请求头

```text
Authorization: Bearer <BISHENG_API_KEY>      # 必填
X-On-Behalf-Of: <external_user_id>           # D 模式传第三方用户唯一 ID；不进入 tool arguments
X-End-User: <external_user_partition>        # 可选，仅沿用 F053 会话分区语义
```

MCP SDK 所需的协议头由 SDK 处理；服务端不从 MCP session id 推导身份。客户端每次请求都必须发送认证头。

#### 工具输入

- 每个 registry 项必须显式声明 `title / description / input_model / output_model / scope / modes / annotations`；`tools/list` 输出的 `inputSchema` 和 `outputSchema` 由这些模型生成，不返回无字段说明的空泛 schema。10 个工具的 `readOnlyHint / destructiveHint / idempotentHint / openWorldHint` 固定值见 [tool-contracts.md §2.3](./tool-contracts.md#23-工具行为-annotations)，annotations 只影响客户端风险提示，不替代服务端授权。
- path/query/body 业务字段扁平为一个 JSON object，字段名、类型、必填项、默认值、枚举和上限以中粮 SeedMind Apifox 合同为对外基线，并由对应 Pydantic model 落地。
- Apifox 中的 `X-On-Behalf-Of` / `X-End-User` 只作为 MCP HTTP 请求头，不进入 tool arguments。`user_id`、`tenant_id`、`on_behalf_of`、`authorization`、服务器 `file_path` 也不进入任何工具 schema；业务主体只由受信任认证上下文确定。
- `bisheng_knowledge_files_delete` 将原 API 的顶层 `array<integer>` 包装为 MCP object `{"file_ids": integer[]}`，避免对输入字段产生多种实现。
- `bisheng_knowledge_file_upload` 将 multipart `file` 转换为 `{"file_name": string, "mime_type": string|null, "content_base64": string}`；原 API 支持的 `file_url` 与 `file` 二选一。MCP 必须先校验目标资源/父目录的写权限与租户边界，通过后才允许解码 base64 或发起 URL 下载；下载结束后既有业务 Service 仍再次鉴权以关闭权限变化窗口。base64 与 URL 路径必须经过 [tool-contracts.md §2.2](./tool-contracts.md#22-上传入口限制) 的 body/编码长度、流式落盘、目标地址、重定向、下载大小与清理限制，再进入原 API 的文件类型、单文件大小、角色总配额和内容安全检查。
- 实施时必须从 registry 生成并提交对外工具文档，每个工具包含用途、完整输入/输出 schema、成功示例与主要错误示例；生成结果必须与 [tool-contracts.md](./tool-contracts.md) 和 Apifox 合同一致并纳入契约测试。

#### 工具结果

```json
{
  "data": [],
  "page_size": 10,
  "has_more": false,
  "next_cursor": null
}
```

- 普通成功：逐工具成功 DTO 直接放 `structuredContent`，并必须符合该工具的 `outputSchema`；同时提供内容等价的 JSON `TextContent` 作为不支持 structured output 的客户端回退。MCP 不复制 API 的 `status_code/status_message/data` 信封，也不新增 `ok/http_status`。
- 空成功：删除、清空等 API 数据为空的操作返回 `{"success": true}`，使 MCP `outputSchema` 保持 object 根类型。
- 工具执行失败：返回 `isError=true`，不设置 `structuredContent`；模型可见 `TextContent` 使用 JSON `{"error":{"code":...,"message":"..."}}`，确保错误码和错误信息均明确可读。
- 无效 JSON-RPC 消息、未知方法或无法形成工具调用的协议错误：使用 MCP/JSON-RPC 标准错误且不执行业务 Service；进入 `tools/call` 后的业务参数/能力执行失败按上一条 tool error result 处理。
- 本期 10 项工具的业务结果均为 JSON，不定义二进制下载、SSE 或 WebSocket 结果适配。
- `structuredContent` 是 MCP 自身的成功输出合同，不要求现有 API 原始 JSON 直接通过 `outputSchema`；字段映射、联合类型和结果包装必须按 [tool-contracts.md §2.4](./tool-contracts.md#24-api--mcp-单向兼容规则) 显式实现，且不得反向要求 API 增删字段。`actions` 与结构化 `TagItem[]` 可被 MCP 原样表达，不做 `actions → permission_ids` 或 `TagItem → name` 转换。

#### 错误归一化合同

现有 API 继续使用当前 FastAPI 校验、`HTTPException`、`BaseErrorCode` 与全局异常处理链路，F067 不改变其任何接口逻辑、异常类型、错误信封或 HTTP 状态。MCP 专用 `McpCompatibilityAdapter` 负责把调用公共业务能力时得到的异常归一化为 `McpErrorPayload(code, message)`，再编码为 MCP 结果：

| 失败来源 | 现有 API 行为（冻结） | MCP adapter 映射 | 是否执行业务 Service |
|---|---|---|---|
| 缺失/无效/过期凭据，S/D/PAT transport 准入失败 | F053 既有 401/403/503 信封 | Streamable HTTP 401/403/503，不生成成功 JSON-RPC result | 否 |
| 无效 JSON-RPC、未知方法、未知工具、arguments 非 object | source API 不涉及此协议错误，其既有请求校验保持不变 | MCP/JSON-RPC 标准 error response | 否 |
| arguments 是 object 但 MCP `inputSchema` 校验不通过 | source API 不涉及此工具错误，其既有请求校验保持不变 | `isError=true`，`code=INVALID_ARGUMENT` 或 SDK 的等价稳定码，并返回可操作的安全 `message` | 否 |
| scope/mode 不允许 | source API 继续走既有 scope/mode 校验与错误编码 | `isError=true`；已有稳定业务码时复用，否则使用 `PERMISSION_DENIED`，并返回安全 `message` | 否 |
| 公共业务能力抛 `BaseErrorCode` | 当前全局异常处理保持不变 | `isError=true`，`code` 使用既有业务码，`message` 使用允许公开的业务消息 | 是 |
| 公共业务能力抛 `HTTPException` | 当前全局异常处理保持不变 | 提取允许公开的 detail，映射为稳定 MCP 符号码与 `message`；不返回 HTTP status 字段，不泄漏 header、堆栈或路径 | 是 |
| 未预期服务端异常 | 当前 500 处理保持不变 | 标准 JSON-RPC Internal Error（`code=-32603`、固定安全 `message`）；真实异常只进入脱敏日志 | 可能 |

MCP 专有符号码只在没有既有业务码时使用，固定映射如下；映射所依据的 HTTP status 只用于 adapter 内部分支，不进入 MCP 输出：

| MCP code | 适用情况 |
|---|---|
| `INVALID_ARGUMENT` | 工具 `inputSchema` 或业务前置参数校验失败 |
| `UNAUTHENTICATED` | 已进入 MCP 调用链后发现主体凭据上下文无效；transport 前置认证失败仍走 HTTP 401 |
| `PERMISSION_DENIED` | scope、mode、数据范围或资源授权拒绝，且没有既有业务码 |
| `NOT_FOUND` | 目标业务资源不存在，且没有既有业务码 |
| `CONFLICT` | 当前业务状态与请求冲突，且没有既有业务码 |
| `RATE_LIMITED` | MCP 工具调用被限流，且没有既有业务码 |
| `DEPENDENCY_UNAVAILABLE` | 可预期的下游依赖不可用或超时，且没有既有业务码 |
| `TOOL_EXECUTION_FAILED` | 其它已预期、允许向调用方公开的工具执行失败 |

所有 tool error result 均不设置 `structuredContent`；其 JSON `TextContent` 至少包含非空 `error.code` 与 `error.message`，可选在 `_meta["bisheng/error"]` 重复同一结构供客户端编程读取，但 `_meta` 不能替代模型可见内容。协议错误则使用标准 JSON-RPC `error.code/error.message`。支持既有 `HTTPException` 与 `BaseErrorCode` 是 MCP compatibility adapter 的责任；不得以 F067 为由要求既有 API 调用链先统一异常类型。契约测试冻结 API 错误行为，并分别断言 tool error 与 protocol error 的错误码、消息和信号字段，同时断言不存在 HTTP 信封字段。

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
| `bisheng/open_mcp/registry.py` | 声明 10 个 allowlist 工具的名称、schema、source route、scope、modes、handler、结果类型 | 不从 URL 动态执行任意 endpoint，不自动注册 allowlist 之外的 API |
| `bisheng/open_mcp/auth.py` | 把 MCP HTTP 请求接入共享 `OpenApiAccessContext`，保证每请求 set/reset | 不实现新 token verifier，不缓存永久授权 |
| `bisheng/open_mcp/contracts.py` | 定义 MCP 专用输入/成功输出 DTO 与 `McpErrorPayload` | 不替换或反向复用为现有 API response model，不直接暴露 ORM/SQLModel |
| `bisheng/open_mcp/compatibility.py` | 按 `tool-contracts.md` 重建既有调用参数，并把既有业务结果、`HTTPException` 与 `BaseErrorCode` 适配为 MCP 合同 | 不要求修改现有 API 接口逻辑、字段或异常类型，不以反射自动暴露新增字段 |
| `bisheng/open_mcp/result.py` | 成功 DTO 转换为 `structuredContent`，错误 DTO 转换为 `isError` + JSON `TextContent` | 不把 HTTP 状态/信封带入 MCP，不捕获并吞掉未知异常，不改写业务成功/失败结论 |
| `bisheng/open_mcp/upload.py` | 资源预检通过后的严格 base64 流式解码、受控文件 URL、业务兼容文件名和请求私有临时目录清理 | 不复用可读本地路径、长期 cache 或整响应入内存的通用下载入口；本版不暴露异步 `callback_url` |
| `bisheng/open_mcp/tools/*` | 薄工具绑定与文件/顶层数组参数适配 | 不复制业务授权、错误映射或持久化逻辑 |
| `bisheng/open_endpoints/domain/services/*` | MCP facade 复用的既有业务能力；确有重复时可在快照保护下抽取最小、传输无关的公共 capability | 不感知 MCP JSON-RPC；不承载 MCP 参数/输出/错误适配；F067 不改变现有 API 接口逻辑和对外合同 |
| `bisheng/open_api/domain/services/access_context.py` | 从现有 dependency 抽出凭据、S/D/PAT、tenant、permission actor 生命周期 | 不根据 tool 参数确定身份 |
| `bisheng/open_api/domain/services/call_audit_service.py` | 接收 HTTP/MCP 统一调用审计事件并批量写既有表 | 不记录请求正文、密钥或文件内容 |
| `bisheng/main.py` | 把 `/api/v2/mcp` 与 SDK lifespan 纳入现有 app | 不创建第二端口或节点本地 session store |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `mcp_manage` 名字像服务模块，实际只有出站客户端 | 在其中加入 server 会把内外两个方向的生命周期和依赖混在一起 | 新建 `bisheng/open_mcp/`；`mcp_manage/` 保持不变 |
| 2 | `verify_open_api_access` 通过 FastAPI endpoint 上的 marker 找 scope；MCP 的 10 个工具共用一个 HTTP endpoint | 直接复用 dependency 会得到“endpoint 未登记”，或只校验一次公共 scope | `open_api/domain/services/access_context.py` + `open_mcp/registry.py` |
| 3 | ASGI 外层中间件读不到依赖子任务里仅写 ContextVar 的 principal | MCP 审计会丢 actor/subject，甚至串用后续请求身份 | auth context 显式传 principal；逐工具审计不依赖外层回读 ContextVar |
| 4 | `/api/v2/mcp` 会命中现有 `OpenApiAuditMiddleware` 前缀 | 不排除会同时生成 transport 和 tool 两条成功审计，统计翻倍 | `open_api/api/middleware.py` 精确排除 MCP 路径，MCP handler 逐调用记账 |
| 5 | F067 的范围只是 Apifox 指定的 10 项 API，小于 `OPEN_API_SCOPES` 全量集合 | 从全量 scope registry 自动生成会把未授权能力也暴露为 MCP 工具 | 契约测试对 §4.3 allowlist 与 registry 做双向差集 |
| 6 | 批量删除 API 请求体是顶层 `array<integer>`，MCP tool arguments 必须是 object | 不显式定义包装字段会导致客户端与服务端合同分叉 | 固定使用 `{"file_ids": [...]}` |
| 7 | Apifox 说明中的代用户语义由 `X-On-Behalf-Of` 表达，不是普通业务参数 | 把 `user_id` 放入 tool arguments 会让模型尝试改变执行主体 | schema 排除身份字段，只从受信任请求头构建 principal |
| 8 | MCP 工具列表可见只证明 credential scope；具体资源仍需业务 action | 仅在 discovery 过滤会造成跨资源越权 | 每次 handler 进入既有业务 Service/F048；见 `open_mcp/auth.py` |
| 9 | MCP tool arguments 不能安全代表本机上传文件 | 接受 `/tmp/x` 或 `/app/data/x` 会读取某个副本文件并泄漏路径 | 文件工具只接受受限 base64/受控 file_url；见 `tool-contracts.md` §2.2 与 `open_mcp/upload.py` |
| 10 | MCP 请求可能被商业网关缓冲或剥离非标准头 | 直连后端可用、商业部署却初始化失败或 D 模式恒失效 | 网关验收必须覆盖 Streamable HTTP、`X-On-Behalf-Of`、`X-End-User` 和长响应 |
| 11 | 当前 `filelib` endpoint/Service 混有 `HTTPException` 与 `BaseErrorCode` | 若强行统一异常会改变已发布 API；若原样泄漏又会污染 MCP 协议 | API 异常链路保持不变；`open_mcp/compatibility.py` 显式兼容两类异常并生成含 `code/message` 的 MCP tool error result |
| 12 | base64 JSON 会同时放大请求体和解码内存，`file_url` 还是服务端主动出网；旧 API 的异步 `callback_url` 无法在 MCP 入口固定最终发送地址 | 只做“解码后文件校验”会在到达业务限制前耗尽内存或形成 SSRF | JSON 解析前 body cap、编码长度检查、流式临时文件、URL DNS pin/redirect/size 限制；MCP 本版删除 `callback_url` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `$BASE/api/v2/mcp` | 无状态 Streamable HTTP MCP endpoint | Claude Desktop、IDE、智能体平台、自动化客户端 |
| §4.3 的 10 个稳定工具名与 JSON schema | MCP `tools/list` / `tools/call` | 外部 MCP 客户端与模型 |
| §4.4 逐工具成功 DTO 与 `McpErrorPayload` | MCP `structuredContent` / tool error result | 调用方的分页、结果校验与错误处理 |
| `OpenCapabilityRegistry` | 内部 Python registry | MCP server、覆盖测试、工具文档生成 |
| `McpCompatibilityFacade` 与显式 mapper | 内部 async Python API | MCP tools；通过既有业务 Service 复用能力，不反向约束 HTTP endpoint |
| `open_api.call` + `target_type=mcp_tool` | `audit_log` 事件 | 管理审计、故障追踪 |

工具名移除或输入字段破坏性变更必须按对外 API 的版本治理处理；不能因 HTTP route 重命名而静默改变 MCP tool name。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F053 `ApiCredential` / `OpenApiPrincipal` / S-D / execution snapshot | Python domain contract + DB/Redis | principal 字段、委托强制规则或 5 秒失效上界变化会直接影响 MCP |
| F066 PAT data scope | tenant policy + permission actor | 若只在 HTTP dependency 应用，MCP PAT 会绕过管理员收窄 |
| 中粮 SeedMind Apifox 10 项 allowlist | 范围合同 | 只有重新确认 Spec/Design 才能增删工具 |
| `OPEN_API_SCOPES` | route/scope registry | 只取 allowlist 对应路由的 scope，不得以全量 registry 扩围 |
| F048 permission application API | `current_permission_actor` + business action | 不得从 MCP 直接调用 OpenFGA 或 SQL Grant 兜底 |
| 各业务 Service | Python async/sync contracts | MCP facade 必须覆盖 API endpoint 的业务编排语义；以 API 快照和副作用对比防止漂移，不能靠改 API 合同消除差异 |
| `mcp>=1.27.2` | Python SDK | Streamable HTTP lifecycle、错误/structuredContent 行为升级时可能变化；禁止回退到已知受影响版本 |
| 商业网关/反向代理 | HTTP path/header/stream forwarding | 路径未代理、身份头丢失、body limit 与 `open_mcp.max_inline_upload_bytes` 公式不一致或无限 buffering 会导致失败/资源放大 |
| MinIO/临时上传服务 | 文件输入输出 | 不得改用本地路径；多副本必须通过对象存储保持可读；MinIO origin 必须显式配置进受控 URL 目标 |

---

## 7. 测试与可观测

### 7.1 分层策略

- **单元测试**：registry 工具名唯一、schema 无身份字段、scope/mode/PAT 过滤、四项 annotations、`McpCompatibilityAdapter` 对 `HTTPException`/`BaseErrorCode` 的转换、成功 structured output、工具失败 `isError` + `code/message`、未预期异常 JSON-RPC `-32603` 且均无 HTTP 信封、顶层数组与文件适配、ContextVar finally reset、审计脱敏；上传覆盖畸形 base64、编码/解码/body 三层边界、清理，以及 file URL 的 scheme/host/IP pin/redirect/timeout/截断，并断言 schema 不含 `callback_url`。
- **契约测试**：先冻结 §4.3 的 10 个 source API 的接口逻辑、请求、成功响应和主要错误快照，后续 F067 测试必须断言快照不变；registry 与 allowlist 做双向差集，逐工具校验 `inputSchema/outputSchema/annotations` 与生成文档。相同业务场景分别走既有 API 和 MCP facade，比较业务码语义、关键业务数据与副作用；只有 MCP 成功 `structuredContent` 必须通过 `outputSchema`，错误结果必须无 `structuredContent` 且含非空 `error.code/error.message`。MCP 输出保留 `actions` 与结构化 `TagItem[]`，不增加 `permission_ids`、不把标签扁平为名称数组。
- **集成测试**：真实 ASGI MCP client 覆盖 initialize/list/call；S、D、PAT、撤销后复用连接、权限变化、OpenFGA/Redis 故障、multipart/base64/受控 URL 上传和批量删除数组包装；网关与直连分别验证 `413`、身份头转发和临时文件零残留。
- **E2E**：MySQL + Redis + OpenFGA 环境验证 3 个只读工具与 7 个写工具的主要成功/拒绝路径，并对 10 个工具至少各做一次成功调用；商业网关再跑相同 smoke。DM8 由集中回归验证 MCP facade 对既有业务 Service 的调用与审计写入。

### 7.2 手动验证

实现后从 `src/backend/` 执行（token 只放环境变量，不出现在 shell history 或日志）：

```bash
export BISHENG_MCP_URL='https://<BISHENG_HOST>/api/v2/mcp'
export BISHENG_API_KEY='<BISHENG_API_KEY>'
.venv/bin/python scripts/verify_open_mcp.py --url "$BISHENG_MCP_URL" --expected-profile full
```

脚本至少输出：协议初始化结果、可见工具数、缺失/多出 source route、选定只读工具结果、撤销后拒绝结果；任何凭据值必须掩码。

### 7.3 可观测

- 审计：`audit_log.action='open_api.call'`、`target_type='mcp_tool'`、`target_id=<tool_name>`，metadata 包含 channel、credential/actor/subject、scope、result、error_code、latency、trace_id，不含 arguments。
- 结构化日志：`open_mcp.tool_call`（tool/scope/mode/result/latency）、`open_mcp.coverage_mismatch`、`open_mcp.auth_failed`、`open_mcp.protocol_error`。
- 健康判据：MCP server 注册失败或 coverage 不完整时，不把 MCP endpoint 标记为可用；不得影响 `/health` 对基础进程的判断，也不得绕过发布验收。

---

## 8. 发布、后续改进与不做事项

### 8.1 发布顺序

1. 先冻结 10 项现有 API 的接口逻辑、请求、成功响应和主要错误快照；保持现有 endpoint 校验、分支、调用顺序、响应和异常处理不变，再新增 MCP compatibility facade/mapper。公共能力优先直接复用现有 Service；只有出现真实重复且可证明 API 行为零差异时，才抽取最小的传输无关业务 capability。
2. 注册 §4.3 的 10 个 allowlist 工具并让 registry/allowlist 双向差集及逐项映射覆盖测试通过；生成含完整输入/输出 schema 的工具文档和配置示例。
3. 挂载 `/api/v2/mcp`，配置 `open_mcp.max_inline_upload_bytes`、允许的文件 URL host、transport Host/Origin，并按 `tool-contracts.md` §2.2 同步商业网关 path/header/body/stream 上限；本版 MCP 不配置或接收 `callback_url`。
4. 先用只读服务账号 smoke，再验证 D、PAT、写入、文件上传和撤销。
5. 对外公布地址前确认审计、脱敏、allowlist 覆盖与 API→MCP 显式映射覆盖均完整；API/MCP 可有已记录的协议形态差异，但不得有未解释的业务语义差异。

**回滚**：F067 无 schema/data migration；发现协议、网关或工具问题时可撤回 `/api/v2/mcp` 路由、registry 与 compatibility adapter 并回滚后端镜像。现有 `/api/v2` 接口逻辑、合同和异常链路不属于 F067 改动面，因此回滚前后 API 行为不变；回滚只使 MCP 地址暂时不可用，不得撤销或改写既有凭据。

### 8.2 后续 / 不做

- 不预注册中粮 SeedMind Apifox 10 项 allowlist 之外的隐藏工具；不因其他 API 已发布就自动扩围。
- 不提供万能 HTTP 代理工具；它会绕过工具发现与 schema 边界。
- 不把 MCP session 作为登录 session，也不在内存中保存永久 principal。
- 暂不拆独立服务；当前没有独立容量/SLA 证据，拆分只会增加身份和部署漂移面。
- 暂不承诺 MCP 原生 task/resource server；待协议和主流客户端形成稳定互操作后再评估。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-15 | 初版（已由下行范围裁定取代）：确定同进程无状态 Streamable HTTP、43 项显式 registry、共享能力层、两阶段认证、结构化结果与逐工具审计 | Spec ★ 已确认，进入 Design |
| 2026-09-15 | 范围收缩为中粮 SeedMind Apifox 指定的 10 项知识资源/文件 API；删除其他业务组、WS/SSE/二进制下载适配设计，补充一对一 allowlist 与逐工具 schema 交付要求 | 用户明确以新 Apifox 文档为本次唯一能力范围 |
| 2026-09-18 | 冻结现有 API 入参、出参与异常链路；改为由 MCP 专用 schema、facade 和 mapper 单向兼容协议差异，删除“先改 endpoint/统一异常”的前置要求 | 用户明确现阶段不得改动已有 API 入参和出参 |
| 2026-09-18 | 修复设计评审项：审计统一复用 `audit_log`；输出合同对齐当前 API 模型；补充上传 body/base64/URL 安全边界、MCP 专用错误兼容映射和逐工具 annotations | Design 评审整改 |
| 2026-09-18 | 再次收紧 API 冻结边界为“不修改任何既有 API 接口逻辑”；MCP 成功输出改为逐工具 structured output，错误改为标准 tool error result；取消 `actions → permission_ids` 与 `TagItem → name` 的无依据转换，并限定公共抽取为传输无关业务 capability | 用户对 Design 二次评审的四项明确反馈 |
