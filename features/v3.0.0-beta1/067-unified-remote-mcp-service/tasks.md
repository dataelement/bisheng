# Tasks: F067 通用开放能力的统一远程 MCP 服务

**关联规格**: [spec.md](./spec.md)
**关联设计**: [design.md](./design.md)
**工具合同**: [tool-contracts.md](./tool-contracts.md)
**版本**: v3.0.0-beta1

---

## 状态·
| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-09-15 按中粮 SeedMind Apifox 10 API allowlist 确认 |
| design.md | ✅ 已评审 | 2026-09-18 确认 API 全量冻结、MCP 单向适配、标准错误输出与最小公共能力抽取 |
| tasks.md | ✅ 已拆解 | 2026-09-18 完成 21 项任务、5 个 Wave 与发布门禁拆分 |
| 实现 | 🟡 本地实现基本完成，待补齐 E2E 与集中验收 | 19 / 21 完成。T020 覆盖仍不完整；T021 仍需集中环境、商业网关与 DM8 证据 |

---

## 开发模式与硬门禁

- **按 Wave 推进**：同一 Wave 中无依赖的任务可并行；不得跳过依赖任务。
- **后端 Test-First**：每组实现先提交会失败的测试，再完成最小实现使其通过。测试统一放在 `src/backend/test/open_mcp/`，E2E 放在 `src/backend/test/e2e/`。
- **Gate A — API 冻结**：T001 先让现有 10 个 `/api/v2/filelib/` API 基线测试可执行并冻结接口逻辑、请求/响应、错误和副作用。此后每个 Wave 都必须重跑该基线；F067 不得修改任何现有 API 接口逻辑。
- **Gate B — 协议与安全**：registry、输入/输出合同、错误结果、认证上下文和上传安全测试通过前，不得挂载 MCP 服务。
- **Gate C — 范围完整性**：registry 与 10 API allowlist 的双向差集必须为空；工具多一个或少一个都阻断发布。
- **Gate D — 公共抽取限制**：优先直接复用既有 application/domain Service。只有出现真实重复，且 T001 快照可证明 API 行为零差异时，才允许抽取最小、传输无关的公共 capability；HTTP/MCP 参数、响应和错误适配不得进入该 capability。
- **Gate E — 发布验证**：单元/契约/集成/E2E、架构守卫、直连和商业网关 smoke 均完成后，才能把 MCP 地址标记为可用。
- **集中环境边界**：MySQL、Redis、OpenFGA、DM8 和商业网关用集中环境/CI 验证；本地测试不得伪称为真实中间件或 DM8 证明。

---

## Tasks

### Wave 0 — 冻结 API 基线与准备依赖

- [x] **T001**: 修复并冻结 10 项现有开放 API 契约基线
  **文件**: `src/backend/test/knowledge/test_v2_filelib_unified.py`, `src/backend/test/open_mcp/test_api_freeze_contract.py`, `src/backend/test/open_mcp/fixtures/filelib_api_contracts.json`
  **逻辑**:
  - 修复旧测试仍 monkeypatch 已移除的 `get_default_operator_async` / `resolve_operator` 等失效锚点，改为当前 `get_open_api_operator_async` / `get_open_api_operator`，只改测试，不改 API。
  - 为 design §4.3 的 10 个 source route 冻结路由、参数位置、字段、默认值、成功响应、主要错误信封、HTTP 状态、调用顺序和关键副作用；知识资源输出按当前 `actions`，文件标签按结构化 `TagItem[]` 记录，不引入 `permission_ids` 或标签名称数组。
  - 分别覆盖知识资源类型 0/1/3、空结果、分页、批量删除顶层数组、文件上传 multipart，以及权限/不存在/业务状态拒绝。
  **测试**: `uv run pytest test/knowledge/test_v2_filelib_unified.py test/open_mcp/test_api_freeze_contract.py`
  **覆盖 AC**: AC-07, AC-19, AC-20, AC-25
  **依赖**: 无

- [x] **T002**: 编写 MCP SDK 与配置合同测试
  **文件**: `src/backend/test/open_mcp/test_sdk_contract.py`, `src/backend/test/open_mcp/test_settings.py`
  **逻辑**:
  - 断言实际解析的 MCP SDK 版本不低于 `1.27.2`，Streamable HTTP 能协商设计指定的协议版本，且输入/输出 schema 根节点为 object。
  - 先定义 `open_mcp` 配置合同：请求体/base64/下载大小限制、允许的文件 URL host、transport Host/Origin、连接/读取超时和重定向上限；默认值必须安全，非法或无上限配置启动失败。MCP 本版不暴露旧 API 的异步 `callback_url`。
  **测试**: `uv run pytest test/open_mcp/test_sdk_contract.py test/open_mcp/test_settings.py`
  **覆盖 AC**: AC-01, AC-20, AC-21
  **依赖**: 无

- [x] **T003**: 升级 MCP SDK 并落地服务端配置
  **文件**: `src/backend/pyproject.toml`, `src/backend/uv.lock`, `src/backend/bisheng/core/config/open_platform.py`, `src/backend/bisheng/core/config/settings.py`
  **逻辑**:
  - 将 MCP SDK 升级并锁定到 `>=1.27.2` 的兼容版本，不回退到已知会话鉴权漏洞版本。
  - 新增独立 `OpenMcpConf` 并接入 `Settings.open_mcp`；不复用出站客户端 `McpConf`，不改变现有开放 API 配置语义。
  **测试**: T002 全部通过；现有配置加载测试通过
  **覆盖 AC**: AC-01, AC-21
  **依赖**: T002

### Wave 1 — 认证、注册表、结果与上传基础层

- [x] **T004**: 编写共享开放访问上下文测试
  **文件**: `src/backend/test/open_mcp/test_access_context.py`, `src/backend/test/open_api/test_dependencies.py`, `src/backend/test/open_api/test_data_scope_matrix.py`, `src/backend/test/open_api/test_identity_e2e.py`
  **逻辑**:
  - 覆盖 S/D/PAT 凭据解析、scope/mode、tenant/visible tenant、principal、PermissionActor 的安装和 finally 恢复。
  - 覆盖缺失/过期/撤销凭据、主体失效、委托准入失败、PAT 管理员仍受数据范围约束、授权依赖故障时失败关闭。
  - 断言现有 FastAPI dependency 的 endpoint marker、错误信封和 HTTP 状态不变；MCP 可显式传入工具声明的 scope/modes，而不是伪造 endpoint。
  **测试**: `uv run pytest test/open_mcp/test_access_context.py test/open_api/test_dependencies.py test/open_api/test_data_scope_matrix.py test/open_api/test_identity_e2e.py`
  **覆盖 AC**: AC-08～AC-18
  **依赖**: T001

- [x] **T005**: 抽取传输无关的 `OpenApiAccessContext` 并接入 MCP 认证
  **文件**: `src/backend/bisheng/open_api/domain/services/access_context.py`, `src/backend/bisheng/open_api/api/dependencies.py`, `src/backend/bisheng/open_mcp/__init__.py`, `src/backend/bisheng/open_mcp/auth.py`
  **逻辑**:
  - 从现有 dependency 抽取凭据验证、S/D/PAT、租户、principal、PermissionActor 生命周期；公共层不读取 MCP 参数、不依赖 FastAPI endpoint marker。
  - 现有 dependency 继续作为薄 HTTP wrapper，保留原校验顺序、异常、状态和 ContextVar 行为；MCP wrapper 每次 list/call 都重新认证且绝不缓存永久授权。
  **测试**: T004 与 T001 全部通过
  **覆盖 AC**: AC-08～AC-18, AC-19
  **依赖**: T004

- [x] **T006**: 编写 10 工具 registry 与 schema 契约测试
  **文件**: `src/backend/test/open_mcp/test_registry.py`, `src/backend/test/open_mcp/test_contracts.py`
  **逻辑**:
  - 对 design §4.3 allowlist 与 registry 做双向差集，断言工具恰好 10 个、名称唯一、source route/scope/modes/PAT/handler 全部一一对应，禁止从 `OPEN_API_SCOPES` 自动扩展。
  - 逐工具校验 `title/description/inputSchema/outputSchema/annotations`，并递归断言每个成功输出 property 都有业务语义与适用范围说明；排除 `authorization/user_id/tenant_id/on_behalf_of/file_path` 等身份或本地路径字段。
  - 固定批量删除 `{"file_ids": [...]}`、上传 base64/file_url 二选一、知识资源 `actions`、结构化 `TagItem[]` 和逐工具 output model；禁止 `actions → permission_ids`、`TagItem → name`。
  **测试**: `uv run pytest test/open_mcp/test_registry.py test/open_mcp/test_contracts.py`
  **覆盖 AC**: AC-04～AC-06, AC-13, AC-24～AC-26
  **依赖**: T001, T003

- [x] **T007**: 实现 MCP 合同模型与固定 allowlist registry
  **文件**: `src/backend/bisheng/open_mcp/contracts.py`, `src/backend/bisheng/open_mcp/registry.py`
  **逻辑**:
  - 为 10 个工具定义显式输入与成功输出 DTO；所有模型都以 JSON object 为根，每个成功输出字段均声明业务含义、枚举和适用资源类型，并与 `tool-contracts.md` 完全一致。
  - registry 显式声明工具元数据、source route、scope、modes、PAT 可用性、annotations、handler 和结果类型；范围不随路由或 SDK 自动发现增长。
  **测试**: T006 全部通过
  **覆盖 AC**: AC-04～AC-06, AC-24～AC-26
  **依赖**: T006

- [x] **T008**: 编写 MCP 成功结果与错误归一化测试
  **文件**: `src/backend/test/open_mcp/test_results.py`, `src/backend/test/open_mcp/test_errors.py`
  **逻辑**:
  - 成功结果必须同时返回符合 outputSchema 的 `structuredContent` 和内容等价的 JSON `TextContent`；删除/清空等空成功固定为 `{"success": true}`。
  - 参数、权限和业务错误返回 `isError=true`、无 `structuredContent`，模型可见 JSON 至少含非空 `error.code/error.message`；已有业务码优先复用，兼容 `BaseErrorCode` 与 `HTTPException`。
  - 未知方法/未知工具/畸形 JSON-RPC 使用标准协议 error；未预期异常固定为 `-32603` 安全文案。所有 MCP 输出都不得出现 `status_code/status_message/http_status`、堆栈、请求头或内部路径。
  **测试**: `uv run pytest test/open_mcp/test_results.py test/open_mcp/test_errors.py`
  **覆盖 AC**: AC-20, AC-23, AC-25
  **依赖**: T003, T007

- [x] **T009**: 实现 compatibility 与 MCP result/error adapter
  **文件**: `src/backend/bisheng/open_mcp/compatibility.py`, `src/backend/bisheng/open_mcp/result.py`
  **逻辑**:
  - 按 `tool-contracts.md` 做 MCP 单向入参/出参转换，协议差异不得反向写入 API schema、endpoint 或公共业务 capability。
  - 实现 `McpErrorPayload`、稳定符号码、已有业务码透传、成功 structured output、tool error 与 JSON-RPC error 的明确分界；未知异常继续向协议层交由 `-32603` 处理并只写脱敏日志。
  **测试**: T008 与 T001 全部通过
  **覆盖 AC**: AC-19, AC-20, AC-23, AC-25
  **依赖**: T008

- [x] **T010**: 编写 MCP 文件入口安全测试
  **文件**: `src/backend/test/open_mcp/test_upload.py`
  **逻辑**:
  - 覆盖 JSON 解析前 body cap、严格 base64 校验、编码与解码大小上限、流式临时文件、超时/截断/异常后的 finally 清理。
  - `file_url` 仅允许配置的 HTTPS host；DNS 解析后固定批准 IP，拒绝私网/环回/链路本地/保留/CGNAT IP，每次重定向重新校验，下载流超过上限立即终止。仅精确匹配配置的 MinIO scheme/host/port 可使用部署所需例外；schema 明确排除 `callback_url`。
  - 禁止服务器本地路径，禁止调用会整响应入内存或允许任意 URL 的通用 `async_file_download`；测试零临时文件残留。
  **测试**: `uv run pytest test/open_mcp/test_upload.py`
  **覆盖 AC**: AC-13, AC-21, AC-23
  **依赖**: T003, T007

- [x] **T011**: 实现受控 base64/URL 上传适配
  **文件**: `src/backend/bisheng/open_mcp/upload.py`
  **逻辑**:
  - 在 MCP JSON 解析前执行请求体限制；base64 和 URL 下载均流式写入受控临时文件，并执行 design §5.12 的三层大小、SSRF、重定向、超时与清理护栏。
  - 安全适配完成后再交给既有文件类型、单文件大小、配额、解析参数和内容安全校验；不增加本地路径入口。
  **测试**: T010 全部通过
  **覆盖 AC**: AC-21, AC-23
  **依赖**: T010

### Wave 2 — 10 个业务工具

- [x] **T012**: 编写 6 个知识资源工具测试
  **文件**: `src/backend/test/open_mcp/test_knowledge_tools.py`
  **逻辑**:
  - 覆盖 `bisheng_knowledge_list/create/update/delete/clear/retrieve` 的完整输入、成功 DTO、空结果、分页、type 0/1/3、业务拒绝和资源动作检查。
  - 同一主体/等价输入分别走 API 与 MCP facade，对比业务含义、数据归属、关键副作用和权限边界；明确允许的差异只限 MCP object/structuredContent/error 包装。
  - 验证 PAT 只可调用 list/retrieve，D 模式主体与数据归属正确，调用时权限变化立即生效。
  **测试**: `uv run pytest test/open_mcp/test_knowledge_tools.py test/open_mcp/test_api_freeze_contract.py`
  **覆盖 AC**: AC-04, AC-07, AC-10～AC-20, AC-23, AC-25, AC-26
  **依赖**: T005, T007, T009

- [x] **T013**: 实现 6 个知识资源 MCP 工具
  **文件**: `src/backend/bisheng/open_mcp/tools/__init__.py`, `src/backend/bisheng/open_mcp/tools/knowledge.py`, `src/backend/bisheng/open_mcp/compatibility.py`; **仅在 Gate D 成立时可新增** `src/backend/bisheng/open_endpoints/domain/services/filelib_capability_service.py`
  **逻辑**:
  - 工具绑定只做 registry 调度、MCP 参数转换和结果适配；业务授权、状态判断、持久化与异步副作用复用既有业务 Service/F048。
  - 如果 endpoint 中确有无法复用且重复的业务编排，只抽取最小传输无关 capability；不得修改现有 endpoint 的校验、分支、调用顺序、异常和响应，也不得把 MCP 合同下沉到公共层。
  **测试**: T012、T001 及相关 knowledge/open_api 测试全部通过
  **覆盖 AC**: AC-04, AC-07, AC-10～AC-20, AC-23, AC-25, AC-26
  **依赖**: T012

- [x] **T014**: 编写 4 个文件工具测试
  **文件**: `src/backend/test/open_mcp/test_file_tools.py`
  **逻辑**:
  - 覆盖 `bisheng_knowledge_file_upload/list/delete/files_delete`；上传的 `content_base64` 与 `file_url` 必须二选一，完整传递文件名、MIME、父级、解析与异步参数。
  - 覆盖批量删除 object wrapper、分页、结构化 `TagItem[]`、空成功、资源权限/配额/类型/大小/状态错误及关键副作用。
  - 同一主体/等价输入分别走 API 与 MCP facade，比对业务语义与副作用；断言现有 multipart 和顶层数组 API 合同未变。
  **测试**: `uv run pytest test/open_mcp/test_file_tools.py test/open_mcp/test_upload.py test/open_mcp/test_api_freeze_contract.py`
  **覆盖 AC**: AC-04, AC-07, AC-10～AC-23, AC-25, AC-26
  **依赖**: T005, T007, T009, T011

- [x] **T015**: 实现 4 个文件 MCP 工具
  **文件**: `src/backend/bisheng/open_mcp/tools/file.py`, `src/backend/bisheng/open_mcp/compatibility.py`; **仅在 Gate D 成立时可使用** `src/backend/bisheng/open_endpoints/domain/services/filelib_capability_service.py`
  **逻辑**:
  - 使用 T011 的受控上传入口和既有业务 Service/F048；只在 MCP 层转换 multipart/base64/file_url、query/path 展平、批量删除数组包装和成功 DTO。
  - 保持既有 API 文件类型、大小、配额、解析任务、删除副作用和错误链路不变；公共 capability 抽取继续受 Gate D 约束。
  **测试**: T014、T001 及相关 knowledge/open_api 测试全部通过
  **覆盖 AC**: AC-04, AC-07, AC-10～AC-23, AC-25, AC-26
  **依赖**: T014

### Wave 3 — MCP Server、挂载与审计

- [x] **T016**: 编写 Streamable HTTP、调用期认证与审计集成测试
  **文件**: `src/backend/test/open_mcp/test_server.py`, `src/backend/test/open_mcp/test_transport_auth.py`, `src/backend/test/open_mcp/test_audit.py`
  **逻辑**:
  - 用真实 ASGI MCP client 覆盖 initialize、tools/list、tools/call、协议错误、无状态/多请求生命周期和完整 10 工具发现；未知或 allowlist 外工具不可调用。
  - S/D/PAT 每个请求重新认证；复用既有连接后撤销凭据、停用主体或变更权限/数据范围，下一次调用必须拒绝，不得依赖旧 list 结果或 session principal。
  - `/api/v2/mcp` 不产生 endpoint 级重复审计；每次工具接受/拒绝只记一条 `open_api.call`、`target_type=mcp_tool`，含 credential/actor/subject/scope/result/error/latency/trace，且不含 token、header、arguments、文件内容。
  - 覆盖 body 超限 `413`、ContextVar 清理、授权依赖故障失败关闭和 server/registry 初始化失败时 MCP endpoint 不可用。
  **测试**: `uv run pytest test/open_mcp/test_server.py test/open_mcp/test_transport_auth.py test/open_mcp/test_audit.py`
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-08～AC-18, AC-20～AC-24
  **依赖**: T005, T013, T015

- [x] **T017**: 实现 MCP Server、路由挂载与逐工具审计
  **文件**: `src/backend/bisheng/open_mcp/server.py`, `src/backend/bisheng/main.py`, `src/backend/bisheng/open_api/api/middleware.py`, `src/backend/bisheng/open_api/domain/services/call_audit_service.py`
  **逻辑**:
  - 创建无状态 Streamable HTTP MCP app，注册固定 registry 的 list/call handler并纳入应用 lifespan；直接挂载 `/api/v2/mcp`，不借 `/api/v2` endpoint marker 推导单一 scope，不新增端口或节点本地身份 session。
  - `tools/list` 按当前 principal 的 scope/mode/PAT 过滤；`tools/call` 重新认证、重新检查声明和资源权限后调用工具。
  - 现有 HTTP audit middleware 只精确排除 MCP transport 路径，其他 `/api/v2` 行为保持不变；MCP handler 复用现有审计 service 逐工具记账并脱敏。
  **测试**: T016、T001 以及 `test/open_api/` 回归全部通过
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-08～AC-18, AC-20～AC-24
  **依赖**: T016

### Wave 4 — 文档、验证脚本与发布验收

- [x] **T018**: 编写生成文档与验证脚本的契约测试
  **文件**: `src/backend/test/open_mcp/test_generated_docs.py`, `src/backend/test/open_mcp/test_verify_script.py`
  **逻辑**:
  - 断言工具文档从 registry 生成且恰好覆盖 10 个工具，每项含用途、输入/输出 schema、annotations、成功例、主要错误例、认证头说明；示例只能用不可用占位符。
  - 验证脚本测试覆盖 initialize、双向覆盖差集、tools/list、选定只读工具调用、撤销后拒绝和非零退出码；输出必须掩码 token。
  **测试**: `uv run pytest test/open_mcp/test_generated_docs.py test/open_mcp/test_verify_script.py`
  **覆盖 AC**: AC-03～AC-06, AC-09, AC-24～AC-26
  **依赖**: T017

- [x] **T019**: 生成对外文档并实现验证脚本
  **文件**: `src/backend/scripts/verify_open_mcp.py`, `src/backend/scripts/README.md`, `docs/api/open-mcp.md`
  **逻辑**:
  - 脚本可从 `src/backend/` 运行，只从环境变量读取凭据，打印协议初始化、可见工具、缺失/多出 route、只读调用和撤销检查结果，任何凭据只显示掩码。
  - 文档提供统一 URL、Streamable HTTP 客户端配置、S/D/PAT 认证、10 工具完整合同、错误分界、上传限制、网关配置和排障说明；工具段落由 registry 生成或经测试证明与 registry 同源。
  **测试**: T018 全部通过；按 `src/backend/scripts/AGENTS.md` 更新脚本索引
  **覆盖 AC**: AC-02～AC-06, AC-09, AC-20～AC-26
  **依赖**: T018

- [ ] **T020**: 编写 F067 端到端测试
  **文件**: `src/backend/test/e2e/test_e2e_f067_open_mcp.py`, `src/backend/test/e2e/helpers/open_mcp.py`
  **逻辑**:
  - 在 MySQL + Redis + OpenFGA 环境对 10 个工具至少各完成一次成功调用，并覆盖 S、D、PAT 的发现/执行、权限与数据范围、撤销、主体失效、资源拒绝、审计、上传和错误输出。
  - 相同用例可配置为后端直连和商业网关两套 base URL；网关覆盖 path、`Authorization`、`X-On-Behalf-Of`、`X-End-User`、`413`、长响应和无临时文件残留。
  - DM8 集中回归至少验证 MCP facade 对既有业务 Service 的调用、结果 DTO 与审计写入；不得用 mock 结果替代 DM8 结论。
  **测试**: `uv run pytest test/e2e/test_e2e_f067_open_mcp.py -m e2e`
  **覆盖 AC**: AC-01～AC-26
  **依赖**: T017, T019

- [ ] **T021**: 执行最终质量门禁并记录验收结果
  **文件**: `features/v3.0.0-beta1/067-unified-remote-mcp-service/tasks.md`（仅勾选任务与记录真实偏差）；如合同发生已确认变更，同步更新 `spec.md` / `design.md` / `tool-contracts.md`
  **逻辑**:
  - 执行：`uv run pytest test/open_mcp/ test/open_api/ test/knowledge/test_v2_filelib_unified.py`、相关 knowledge 回归、`uv run ruff check`（仅本 Feature 变更 Python 文件）、仓库根目录 `scripts/arch-guard.sh`。
  - 在集中环境执行 T020；再用 `scripts/verify_open_mcp.py` 分别验证直连和商业网关。确认 registry 双向差集为空、所有 outputSchema 可校验、审计无重复/泄密、临时文件零残留、现有 10 API 快照零变化。
  - 任一失败不得标记实现完成；真实偏差按 SDD 规则先回写 design 并在需要时重新向用户确认，不得用放宽测试掩盖差异。
  **测试**: 上述门禁全部通过并保存 CI/集中环境证据
  **覆盖 AC**: AC-01～AC-26
  **依赖**: T020

---

## 实际偏差记录

> 只记录指向 design.md 的一句话索引，不在此复制论证。推翻已确认设计或扩出 10 API allowlist 时，必须先暂停并重新取得用户确认。

- 暂无。

## 验收记录

- 2026-09-18：本地单元、契约与 ASGI 集成用例已完成；F067 E2E 骨架已编写，但因本地未配置
  MySQL、Redis、OpenFGA、商业网关和 DM8 验收环境而按环境门禁跳过。当前用例已覆盖 S
  模式 10 工具成功链路、D/PAT 发现与执行、PAT 写拒绝、`file_url` 及直连/网关 `413`；尚未
  完整覆盖撤销、主体失效、资源拒绝、审计、网关 `X-End-User`、长响应与临时文件残留检查，
  因此 T020、T021 均保持未完成，不将现有 E2E 骨架或本地 mock/契约测试表述为集中环境或
  DM8 证明。
