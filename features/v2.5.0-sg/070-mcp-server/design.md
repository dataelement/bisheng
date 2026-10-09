# MCP Server：组件设计与实现边界

**Feature ID**: 070-mcp-server  
**Status**: CONFIRMED  
**Created**: 2026-10-08  
**Updated**: 2026-10-09

关联规格：[spec.md](spec.md)。本文件随规格由用户确认，后续实现遵循已评审任务。

## 1. 现有事实与依赖

- `main.py` 管理全局 FastAPI 与基础设施 lifespan；MCP 必须在其基础设施初始化后开始、销毁前停止。
- `mcp_manage/` 只实现 MCP Client，`pyproject.toml` 与 `uv.lock` 已具备官方 SDK 1.27.1。
- `open_endpoints/api/endpoints/filelib.py::retrieve_chunks` 负责用户上下文、检索、来源解析、超时与结果装配。
- `KnowledgeSpaceChatService.aretrieve_chunks` 拥有业务检索及权限过滤；本期不改算法。
- `DeveloperTokenService.authenticate_principal` 已负责凭证、绑定、IP、路由、限流和租户上下文，
  当前空路由白名单允许全部路由；MCP 要在保持原默认行为的前提下要求非空显式授权。
- `FilelibUserContextService.use_user` 拥有 REST external_id 代理语义，不修改其规则。
- 现有 `McpConf` 只有 `enable_stdio`；`get_mcp_conf` 读取 DB 系统配置并使用已有 100 秒 Redis 缓存。
- SDK 的 `streamable_http_app()` 延迟创建 session manager，必须在访问 `session_manager.run()` 前构建协议应用。
- FastMCP 工具不是 FastAPI endpoint，不能直接调用带 `Depends` 的函数期待框架注入。

## 2. 文件结构计划 File Structure Plan

以下均是拟建/拟修改路径，不代表已经实现。

```text
src/backend/bisheng/mcp_server/
  __init__.py
  api/
    __init__.py
    router.py                         # ASGI 入口、规范路径、配置及生命周期接口
    endpoints/
      __init__.py
      tools.py                        # 唯一工具注册、协议输入输出和脱敏错误
  domain/
    __init__.py
    schemas/
      __init__.py
      search.py                       # 不包含身份参数的严格输入
    services/
      __init__.py
      auth_service.py                 # Token service 适配、HTTP 状态、请求身份
      search_service.py               # 调用共享检索、业务资源作用域
      factory.py                      # 显式装配 Repository 与请求数据库会话

src/backend/bisheng/open_endpoints/domain/services/filelib_retrieve_service.py
                                      # 提取共享检索编排
src/backend/bisheng/open_endpoints/api/endpoints/filelib.py
                                      # REST 委托共享服务，保留现有入口签名
src/backend/bisheng/open_endpoints/api/dependencies.py
                                      # 装配共享服务，不改变 REST 用户依赖
src/backend/bisheng/developer_token/domain/services/developer_token_service.py
                                      # 可选的显式路由要求，原调用默认行为不变
src/backend/bisheng/core/config/settings.py
src/backend/bisheng/initdb_config.yaml  # server 子块模型与默认模板
src/backend/bisheng/api/router.py       # 集中暴露 MCP 入口供 main 挂载
src/backend/bisheng/main.py             # 挂载及合并 lifespan
src/backend/test/mcp_server/            # 新协议、鉴权、生命周期及上下文回归
src/backend/test/open_endpoints/       # 最小共享编排与 REST 兼容测试调整
```

没有 MCP ORM 或 Repository：新模块通过现有业务 Repository 取数据。
不创建无用途的数据库模型、迁移和仓储文件。不改用户现有积分模块 diff。

## 3. 组件职责

### 3.1 协议入口与生命周期

- 路由组合在全局 `api/router.py` 暴露，ASGI 挂载在 `main.py` 完成；不伪造 REST MCP 路由。
- 对 `/mcp`、等价 `/mcp/` 提供直接处理，统一鉴权路由键；不能靠尾斜杠重定向完成认证。
- 启动基础设施后读取有效配置；缺失 `server` 子块按默认开启处理，保留显式 enabled=false。
- 配置有效且开启时构建 FastMCP 与传输应用；每个 HTTP 请求独立进入 SDK session manager 生命周期，关闭时入口稳定返回 404。
- 启动时只保留静态工具注册；每个请求独立拥有 SDK task group，原始 TCP 断开和 task 取消均触发工具清理，避免锁定 SDK 常驻管理器在断连后遗留后台任务。
- 初始化异常要清理已创建资源，不能悄悄启动为无鉴权服务。
- 根据 2026-10-09 用户确认，不再读取 Host/Origin 白名单，SDK `enable_dns_rebinding_protection=false`；仍验证 Content-Type 与 Token，保留全部业务权限。
- 可选开关以启动快照为准，修改后需配置缓存刷新/到期并重启；Token 状态每次请求重新验证。

### 3.2 身份与显式授权

- 协议入口认证调用 DeveloperToken 的 domain service，不导入其他模块的 api dependency。
- 给既有鉴权服务增加仅 MCP 使用的显式路由要求，缺省关闭此要求，保持所有原调用方行为。
- 每个请求，包括握手、列表、通知、调用及不支持的方法，均按实际 HTTP 方法和规范 `/mcp` 路由鉴权。
- 非 POST 请求完成鉴权后返回 405，不交给 SDK 自动开启 GET SSE；CORS 预检继续由 CORS 层处理。
- 空白名单拒绝；非空白名单继续遵循既有 METHOD_PATH/PATH/PREFIX 匹配，不新增白名单语法。
- 身份保存在请求局部状态，在实际工具任务内明确恢复绑定用户/租户可见集；不使用模块全局当前用户。
- 请求结束或工具结束都在对应上下文中释放资源；不得跨 AnyIO task reset 另一 task 创建的 ContextVar token。
- 不以 JWT Cookie、Bearer 或默认操作员替代开发者 Token；不把 Token 放入工具输入输出。

### 3.3 共享检索编排

- 服务接收请求上下文、已确定业务用户、RetrieveReq、仓储和现有异步检索 runtime。
- 复用现有空间 chat service 构造、filters 映射、aretrieve_chunks、授权结果引用去重、来源服务和 RetrieveResp 装配。
- 总超时、来源超时降级、原始业务错误抛出与来源规则保持现状；REST endpoint 继续执行原 HTTP/业务响应映射。
- REST 在原 external_id 作用域内调用；MCP 在 Token 绑定用户作用域内调用。
- MCP factory 使用现有数据库 session helper，在实际工具任务中装配 Repository，
  一个调用一个受管理会话；不得复用跨请求 AsyncSession，不能把 `Depends` 对象作为业务参数。
- factory 属于 domain 层，只导入服务、仓储、schemas 和基础设施；不调用或跨导入 REST endpoint。

### 3.4 唯一工具与错误适配

- 显式注册 `search_knowledge`；输入 Schema 设置拒绝额外字段，调用时也校验，避免只约束列表元数据。
- MCP 专用上限遵循 spec，不改变 RetrieveReq 的 REST 上限。
- 正常返回现有 RetrieveResp，设置结构化输出及 JSON 文本输出；不得自动读取来源 URL 或生成答案。
- 用固定工具范围阻止调用未注册工具，身份参数不透传到共享服务。
- 鉴权失败在 ASGI HTTP 边界转换为真实 401/403/429/503；不经过主应用普通业务异常的 HTTP 200 包装。
- 工具内已知业务拒绝与超时映射为安全的 `CallToolResult.isError=true`；未知错误记录服务端上下文，客户端返回固定失败说明。
- 取消必须继续传播并触发清理，不能被通用错误处理捕获成成功。
- 日志记录工具名、Token ID、用户/租户 ID、trace ID、耗时与状态；不记录 Token、问题正文、结果片段或签名链接。

## 4. 配置契约

服务默认开启。默认模板仅保留可选关闭开关；已有 allowed_hosts/allowed_origins 由 Pydantic 忽略，不再影响运行：

```yaml
mcp:
  enable_stdio: true
  server:
    enabled: true
```

`McpServerConf` 仅保留 enabled=true。旧配置没有 server 块时开启，旧显式 false 继续关闭。
新增 `McpCorsMiddleware` 作为主应用最外层中间件，仅匹配 `/mcp`、`/mcp/`（考虑 ASGI root_path）。
该路径使用 `allow_origins/methods/headers=["*"]`、`allow_credentials=false`，预检直接返回；
普通及错误响应统一覆盖 ACAO=*，移除内层全局 CORS 的 ACAC，避免浏览器把通配来源与 Cookie 凭证组合。
其他 HTTP 路径、相邻路径和 WebSocket 继续既有中间件，不修改 BISHENG_CORS_ORIGINS。
不修改本地运行配置或线上 DB，不自动更新 Token 白名单。

## 5. 需求到设计的映射

| Requirement | Design elements |
|-------------|-----------------|
| REQ-001 | §3.1 规范路径、ASGI 挂载、启动快照和无状态 FastMCP |
| REQ-002, REQ-003 | §3.2 既有鉴权复用与显式 MCP 路由要求 |
| REQ-004 | §3.2 请求身份、§3.4 唯一工具与严格输入 |
| REQ-005, REQ-008 | §3.3 共享检索及 REST 保持兼容 |
| REQ-006 | §3.4 Schema、结果、真实鉴权状态和工具错误 |
| REQ-007 | §3.1 生命周期、§3.2 task 上下文、§3.3 请求会话与取消清理 |
| REQ-009 | §2 文件边界、§3 分层、不新增 ORM/依赖 |

## 6. 分级验证与交付

- V0：文档引用、ID 映射、diff、架构守卫与 Ruff；生产代码未写前不宣称行为通过。
- V2/V3：用最小 HTTP 集成测试验证鉴权和开关；使用真实 SDK ClientSession 验证握手、tools/list、tools/call，
  覆盖上下文并发、拒绝、异常、取消和路径，不只直接调用 Python 工具函数。
- 共享服务提取前运行一次相关 baseline；提取后复跑受影响的 REST external_id、检索权限与来源链接回归。
- 不按 AC 逐条复制测试；等价鉴权失败参数化，现有业务测试复用；记录命令、代码状态和结果。
- 本地协议集成使用可控业务替身时必须注明；真实 MySQL、OpenFGA、Milvus、ES、MinIO、DM8、代理部署分别记录证据或限制。
- 交付 `tasks.md`、`verification.md`、接入说明及发布/回退步骤；未通过或未执行项不得勾为完成。

2026-10-09 更新的测试重点：默认启动、旧显式关闭、任意 Host/Origin、预检成功/鉴权错误 CORS、REST 相邻路径策略不变。

## 7. 备选方案与取舍

- 独立 MCP HTTP 服务：部署、鉴权和内部调用链增加，首期不选。
- MCP 经 HTTP 回调已有 REST：可以复用响应，但引入内部凭证、额外网络和错误包装，首期不选。
- 自动把所有 OpenAPI 暴露为工具：旧默认操作员身份和写接口风险不可控，超出已确认范围。
- OAuth 与多工具权限管理：适合后续通用客户端和多工具需求，当前不引入。
