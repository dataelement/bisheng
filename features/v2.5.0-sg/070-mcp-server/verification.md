# MCP Server：验证证据

**Feature ID**: 070-mcp-server  
**Status**: LOCAL_VERIFIED_WITH_BASELINE_FAILURES
**Updated**: 2026-10-16
**Branch**: feat/2.5.0-sg

## 当前调整与历史证据

最新路由策略及证据见“2026-10-16 统一路由白名单验证”。此前的非空显式授权测试为历史证据，已由用户本次确认覆盖，不能作为当前验收要求。

2026-10-09 用户确认默认开启和 MCP 任意来源跨域，新增 AC-14、改写 AC-01/AC-12。
下方 E-001～E-006 与初版验收矩阵为历史证据；旧的 Host/Origin 拒绝和默认关闭不再作为当前验收结论。
新证据 E-007～E-009 覆盖本次变化，未改变的检索、Token 和身份行为复用原测试。

## 结果与环境边界

本地实现与定向回归通过。运行环境为项目 `src/backend/.venv` 的 Python 3.10、锁定 SDK 1.27.1。
真实 SDK/HTTP/TCP、主应用生命周期和中间件均有可执行证据；外部业务基础设施使用受控替身。
未使用真实 Token、知识数据或生产服务，不将本地结果表述为线上验证。

## 证据表

| Evidence | Code state / Scope | Command / Step | Result |
|----------|--------------------|----------------|--------|
| E-001 | 实施前 baseline；REST/权限/来源/Token | 下列四个原测试文件 | 109 passed, 4 failed；四个失败为旧同步角色查询替身，与当前异步实现不符。 |
| E-002 | 新测试先于实现 | `python -m pytest test/mcp_server/test_mcp_server.py -q` | exit 2；缺少尚未实现的 McpServerConf，符合新功能缺失的失败原因。 |
| E-003 | 初步协议实现 | 同上；之后新增超时与方法/配置检查 | 22 passed；扩展协议与共享服务组 33 passed。发现并修正默认配置未执行字段 validator 导致无端口 Host 不匹配。 |
| E-004 | 共享检索提取与角色替身修正后 | E-001 原范围，加显式路由用例 | 118 passed；原 external_id、检索/来源与 Token 行为保持兼容。 |
| E-005 | 最终代码与全部相关测试 | 下列最终回归命令 | PASS，exit 0；181 passed，25 warnings，6.55 秒。 |
| E-006 | 新模块及受影响代码 | Ruff、AST、架构守卫、diff、配置/文档结构检查 | PASS；新模块 lint/format 通过，既有文件无新增诊断，无架构 VIOLATION；仅既有 RULE-7 警告。 |

E-005/E-006 受影响 Python 代码与测试状态 SHA-256：`64eec82623780740997412da56a9b913456c861b90126d2384cded7474491e91`。
按排序后的相对路径与字节计算，范围为修改的 Python 文件、新 MCP/共享服务及新测试；之后只更新文档状态。
测试警告为依赖与 SDK 兼容 API 弃用提示，不是失败；未运行无关全量测试。

baseline 命令，cwd `src/backend`：

```bash
.venv/bin/python -m pytest \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/developer_token/test_developer_token_dependency.py -q
```

最终回归命令，cwd `src/backend`：

```bash
.venv/bin/python -m pytest \
  test/mcp_server \
  test/open_endpoints/test_filelib_retrieve_service.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/developer_token/test_developer_token_dependency.py \
  test/developer_token/test_developer_token_service.py -q --tb=short
```

## 验收覆盖

| Acceptance | Evidence | 说明 |
|------------|----------|------|
| AC-01 | E-005 | disabled HTTP 404，主应用装配。 |
| AC-02 | E-005 | 原生 SDK 初始化、唯一工具、平铺/严格输入和输出 Schema；规范/尾斜杠路径。 |
| AC-03～05 | E-005 | 真实 HTTP 状态 + 业务码；实际 Token service 非空路由要求及旧行为。 |
| AC-06 | E-005 | 成功/空结果、结构化输出、真实 TCP SDK 调用及来源装配。 |
| AC-07 | E-005 | 共享编排拒绝时不解析来源，复用现有知识权限与混合知识库回归。 |
| AC-08 | E-005 | 未知工具、额外身份参数、输入上限、无效 ID 与空问题。 |
| AC-09 | E-005 | 业务失败脱敏、检索超时、来源超时保留原降级语义。 |
| AC-10 | E-005 | 并发绑定身份、清除继承管理/bypass 状态、原始 TCP 断开及时释放、实际 factory 管理会话。 |
| AC-11 | E-005 | 原 REST 的 external_id、权限、来源、结果顺序和总超时回归。 |
| AC-12 | E-005 | Host/Origin、非 POST、默认关闭、生命周期启动/失败/关闭。 |
| AC-13 | E-005, E-006 | 无依赖/迁移/业务数据变更；新增日志安全字段、语法与分层，TCP 联调。 |

## 协议端到端的具体边界

`test_real_network_sdk_through_main_middleware` 启动真实 Uvicorn 在临时 loopback 端口，
使用官方 SDK/HTTPX 完成 `/mcp` 握手、列表、调用和真实 401 响应。
`test_real_network_disconnect_closes_tool_scope` 通过 TCP 取消请求，断开后 0.5 秒内释放业务作用域，早于 1 秒测试检索 deadline。
同时测试真实 Repository 构造使用同一个受管理 AsyncSession，但没有执行实际 SQL。

全局测试前置替身使无关 assistant 路由产生 metaclass 冲突、JWT 异常类型成为 MagicMock，
主应用测试因此隔离无关业务路由与异常类型；MCP 注册、中间件和 lifespan 为真实代码。
业务服务、鉴权 DAO 与基础设施初始化使用替身，不证明真实数据权限或线上性能。

## 静态检查范围与限制

新 MCP 模块、共享检索服务和新测试执行完整 Ruff 检查及格式检查。
既有大文件只保留最小必要 diff，Ruff 按诊断码/消息与 HEAD 比较，避免清理历史问题或大范围格式化。
实施过程中识别的既有 Ruff 诊断：settings.py 45 条、main.py 1 条、filelib.py 43 条；不得声称这些整文件 lint 全部通过。
架构守卫没有 VIOLATION；settings.py 有既有 RULE-7 警告，相关常量未修改。
积分模块两个用户文件在实施前后 SHA-256 相同。

## 尚未验证 MANUAL_REQUIRED

- 真实 MySQL/Redis/OpenFGA/Milvus/ES/MinIO 与实际 Token/知识库的集成。
- DM8 实机；macOS 不提供 DM8 驱动，需要现有 Linux/CI 环境。
- 正式域名 HTTPS、代理 Host/Origin/CORS、配置缓存及重启后的实际可达性。
- 真实数据规模下的性能和并发容量。

按 [接入说明](usage.md) 开启测试部署后，验证实际 Token 的有权和无权知识库、片段来源可达性，
再关闭配置并确认 MCP 404 与原 REST 仍可用；不自动修改线上数据或权限。

## 静态检查命令

```bash
.venv/bin/ruff check bisheng/mcp_server \
  bisheng/open_endpoints/domain/services/filelib_retrieve_service.py \
  test/mcp_server test/open_endpoints/test_filelib_retrieve_service.py \
  test/developer_token/test_developer_token_dependency.py
.venv/bin/ruff format --check bisheng/mcp_server \
  bisheng/open_endpoints/domain/services/filelib_retrieve_service.py \
  test/mcp_server test/open_endpoints/test_filelib_retrieve_service.py
```

## 2026-10-09 调整验证

| Evidence | Scope / Command | Result |
|----------|-----------------|--------|
| E-007 | 修改测试先于生产实现；`pytest test/mcp_server/test_mcp_server.py test/mcp_server/test_main_integration.py -k 'transport_accepts or legacy_server_config or cors_preflight'` | exit 1；8 failed，正确复现旧默认关闭、Host/Origin 拒绝与全局 CORS 拦截预检。 |
| E-008 | `.venv/bin/python -m pytest test/mcp_server -q --tb=short` | PASS；37 passed，5.62 秒，含真实 SDK/TCP、Token 错误、MCP CORS/其他路径隔离与取消清理。 |
| E-009 | 最终相关回归与静态检查 | PASS；190 passed，25 warnings，6.46 秒；新文件 Ruff/format 通过，旧 main/settings 无新增 lint，AST/架构/文档检查通过。 |

当前 AC-01、AC-12、AC-14：默认开启；显式 false 可关闭；任意 Host/Origin 通过；MCP 预检及成功/401 响应 ACAO=* 且没有 ACAC；其他 REST/相邻路径 CORS 保持原样。
真实基础设施、DM8 与正式部署仍为 MANUAL_REQUIRED。旧 DB 显式 enabled=false 仍关闭，不自动迁移该值。

E-009 命令（cwd src/backend）：

```bash
.venv/bin/python -m pytest test/mcp_server \
  test/open_endpoints/test_filelib_retrieve_service.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/developer_token/test_developer_token_dependency.py \
  test/developer_token/test_developer_token_service.py \
  test/api_rate_limit/test_api_rate_limit_middleware.py -q --tb=short
```

本次 code review：仅 MCP 路径取消来源限制；预检不需要 Token，实际请求依然鉴权；新 wrapper 不修改其他 REST Origin 策略。
显式 false/旧 allowlist 兼容、未知 Host/Origin、成功/401 CORS、邻近非 MCP 路径均有测试。
保留初版真实业务基础设施替身边界，未部署、未操作真实配置/权限或知识数据。

## 2026-10-16 统一路由白名单验证

- 用户已确认取消 MCP 额外限制；任务 T008～T009，REQ-002/003/007/008/009，重点 AC-04/11。
- 代码状态：`feat/2.5.0-sg` / `6b01f9556` 加本次工作区 diff。生产变更仅删除 Token 服务中 MCP 专用参数/拒绝分支及 MCP 调用参数，共四行。
- `None`/空列表不启用路由过滤；非空 METHOD_PATH/PATH/PREFIX 仍要求匹配，拒绝时 HTTP 403/19812 且业务未执行。实际 Token 有效性、绑定用户/租户、IP、限流、每请求认证与实际任务身份不变。空白名单不表示匿名访问、获得资源权限或自动支持新 HTTP 方法。

| Evidence | Command / Scope | Result |
|---|---|---|
| E-010 红灯 | `pytest test/mcp_server/test_mcp_server.py -k real_token_route_rules -q --tb=short`，生产修改前 | 2 failed、6 passed、29 deselected，4.19 秒；None 和空列表被额外限制拒绝，其他规则匹配符合原语义 |
| E-011 绿灯 | `.venv/bin/python -m pytest test/mcp_server/test_mcp_server.py test/developer_token/test_developer_token_dependency.py -q --tb=short` | 73 passed、28 warnings，5.30 秒；真实 Token 服务 + SDK 握手/列工具/检索 + HTTP 拒绝；其余凭证/IP/限流/身份路径通过 |
| E-012 相关回归 | 下列完整命令；受控外部端口，真实 SDK/HTTP/TCP、SQLite | 322 passed、12 failed、62 warnings，16.81 秒 |
| E-013 HEAD 对照 | `git archive HEAD src/backend` 隔离快照，同一命令及同一 Python 环境 | 314 passed、同样 12 failed、57 warnings，16.84 秒；失败测试 ID 一致 |
| E-014 失败范围独立验证 | `.venv/bin/python -m pytest test/knowledge/test_knowledge_document_entry_resolver.py -q --tb=short` | 13 passed、66 warnings，0.46 秒；组合运行失败属于基线已有的测试隔离问题，日志有 tenant context=1 与 fixture tenant=7 不一致 |
| E-015 静态检查 | 四个变更 Python 文件 Ruff；三个文件格式检查；两生产文件架构守卫；AST、文档引用/示例和 diff | Ruff 无诊断；Token 服务格式检查有两处 HEAD 已存在差异，均在未改代码处，不扩大格式化；其他门禁通过 |

相关回归命令（cwd `src/backend`，Python 3.10.19，锁定依赖与现有 `.venv`）：

```bash
.venv/bin/python -m pytest test/mcp_server test/developer_token test/api_rate_limit \
  test/knowledge/test_mcp_knowledge_query_service.py \
  test/knowledge/test_mcp_knowledge_repository.py \
  test/knowledge/test_mcp_knowledge_content_service.py \
  test/knowledge/test_mcp_knowledge_ingestion_service.py \
  test/knowledge/test_knowledge_document_entry_resolver.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/open_endpoints/test_filelib_retrieve_service.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_file_source_url.py -q --tb=short
```

日志在 `/tmp/bisheng-mcp-route-policy-{red,targeted,regression,baseline,resolver-isolated}-20261016.log`。12 个基线失败均在未修改的入口解析测试文件，组合执行查不到 fixture 租户数据或触发错误消息断言；没有修改或跳过这些用例，不能将 E-012 宣称为全绿。

AC-04/11 的目标契约及相关鉴权路径本地 PASS（E-011）；整体回归为 PASS_WITH_BASELINE_FAILURES。使用文档、F070/F078 当前规格已统一，保留并标记初版历史策略。已确认影响为现有空白名单 Token 也可进入 MCP，包括绑定用户有权使用的写工具；不会修改 Token 的已存白名单或文件权限。回退本次局部代码即可恢复额外限制，不涉及 Schema/数据回退。

本次未提交、推送或部署，未修改真实 Token/数据库/配置，未执行远程写工具。真实部署/代理和多用户业务资源仍为 MANUAL_REQUIRED；部署后可用专属 Token 分别验证空白名单连接、非空规则拒绝及资源权限，不能以本地替身等同线上验收。
