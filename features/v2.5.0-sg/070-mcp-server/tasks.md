# MCP Server：执行任务

**Feature ID**: 070-mcp-server  
**Status**: LOCAL_VERIFIED
**Version**: v2.5.0-sg

用户于 2026-10-08 回复“开始实施”，确认 spec.md、requirements.md、design.md；在原范围内连续实现及验证。

| 步骤 | 状态 |
|------|------|
| spec.md | ✅ 已评审并获用户确认 |
| tasks.md | ✅ 已拆解并完成静态评审 |
| 实现 | ✅ T001～T007 完成；实际业务环境/DM8/正式部署验证待执行 |

## 任务

- [x] **T001**：建立 MCP 安全与协议回归，先确认未实现时失败。
  **文件**：`src/backend/test/mcp_server/`，`src/backend/test/developer_token/test_developer_token_dependency.py`。
  **逻辑**：HTTP 开关、鉴权状态/白名单，真实 SDK HTTP 握手/工具结果，未知工具/身份参数拒绝，并发及取消清理。
  **覆盖 AC**：AC-01～10、AC-12。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-006, REQ-007_
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-12_
  _Verification: E-002 失败证据；后续 E-003 通过证据_
  _Depends: none_
  _Boundary: 使用真实 SDK/HTTP，业务依赖可控替身；不操作真实数据_

- [x] **T002**：提取共享检索编排，保持 REST 外部身份、结果和超时兼容。
  **文件**：`bisheng/open_endpoints/domain/services/filelib_retrieve_service.py`，`bisheng/open_endpoints/api/endpoints/filelib.py`，`bisheng/open_endpoints/api/dependencies.py`，`test/open_endpoints/test_filelib_external_user_context.py`，`test/open_endpoints/test_filelib_retrieve_service.py`。
  **逻辑**：共享 Service 接收已解析用户和依赖，保留检索/来源超时及授权后的结果装配；REST 继续原身份作用域和错误映射。
  **覆盖 AC**：AC-06、AC-07、AC-09、AC-11。
  _Requirements: REQ-005, REQ-006, REQ-008, REQ-009_
  _Acceptance: AC-06, AC-07, AC-09, AC-11_
  _Verification: E-001 baseline；E-004 原 REST 与共享编排回归_
  _Depends: T001_
  _Boundary: 不改变检索算法、用户代理能力、响应 schema 或来源签发规则_

- [x] **T003**：接入开发者 Token 的 MCP 显式入口授权与请求身份。
  **文件**：`bisheng/developer_token/domain/services/developer_token_service.py`，`bisheng/mcp_server/domain/services/auth_service.py`。
  **逻辑**：可选非空路由要求，默认兼容旧调用；转换 401/403/429/503，在实际工具 task 恢复并复位身份与租户。
  **覆盖 AC**：AC-03、AC-04、AC-05、AC-10、AC-11。
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-007, REQ-008_
  _Acceptance: AC-03, AC-04, AC-05, AC-10, AC-11_
  _Verification: E-003 协议安全；E-004 Token 原行为回归_
  _Depends: T001_
  _Boundary: 不新增授权实体、不更新真实 Token、不改变旧 REST 白名单规则_

- [x] **T004**：实现严格工具输入、受管理依赖装配和唯一检索工具。
  **文件**：`bisheng/mcp_server/domain/schemas/search.py`，`bisheng/mcp_server/domain/services/factory.py`，`bisheng/mcp_server/domain/services/search_service.py`，`bisheng/mcp_server/api/endpoints/tools.py`，必要 `__init__.py`。
  **逻辑**：工具公开平铺参数与现有结构化结果；实际执行额外字段校验；在业务 task 内创建/释放数据库会话，调用 T002；安全映射已知拒绝、超时和未知错误，取消继续传播。
  **覆盖 AC**：AC-02、AC-06～10、AC-13。
  _Requirements: REQ-004, REQ-005, REQ-006, REQ-007, REQ-009_
  _Acceptance: AC-02, AC-06, AC-07, AC-08, AC-09, AC-10, AC-13_
  _Verification: E-003 SDK HTTP 与并发/取消；E-004 业务回归_
  _Depends: T002, T003_
  _Boundary: 不调用 LLM、不代理外部用户、不访问其他模块 API、不重复实现业务权限_

- [x] **T005**：挂载 MCP 入口及配置/生命周期。
  **文件**：`bisheng/mcp_server/api/router.py`，`bisheng/api/router.py`，`bisheng/main.py`，`bisheng/core/config/settings.py`，`bisheng/initdb_config.yaml`。
  **逻辑**：默认关闭，启动快照；规范路径无重定向；POST 使用无状态 SDK，非 POST 鉴权后 405；Host/Origin 保护；基础设施初始化后开启并优先关闭，初始化失败可靠清理。
  **覆盖 AC**：AC-01、AC-02、AC-12、AC-13。
  _Requirements: REQ-001, REQ-002, REQ-007, REQ-009_
  _Acceptance: AC-01, AC-02, AC-12, AC-13_
  _Verification: E-003 生命周期/安全及 E-005 主应用装配检查_
  _Depends: T004_
  _Boundary: 只改默认配置模板，不开启本地/线上运行配置；不增加依赖_

- [x] **T006**：完成相关回归、自审和接入交付。
  **文件**：特性目录 `verification.md`、`usage.md`、`code-review.md`；任务状态与最小测试修复。
  **逻辑**：运行一次最终相关回归、SDK HTTP 端到端、Ruff/架构守卫；记录证据和真实基础设施/DM8 限制；提供配置、Token 白名单、SDK 示例与关闭回退步骤。
  **覆盖 AC**：AC-01～13。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13_
  _Verification: E-005 最终回归与静态检查；复用有效批次证据_
  _Depends: T001, T002, T003, T004, T005_
  _Boundary: 不提交、不推送、不部署、不碰积分用户 diff_

## 已确认追加任务

- [x] **T007**：MCP 默认开启并开放任意来源，保留关闭及鉴权。
  **文件**：`bisheng/core/config/settings.py`、`bisheng/initdb_config.yaml`、`bisheng/mcp_server/api/router.py`、`bisheng/api/router.py`、`bisheng/main.py`、`test/mcp_server/test_mcp_server.py`、`test/mcp_server/test_main_integration.py`；特性规格、接入说明和验证记录。
  **逻辑**：先修改测试覆盖新行为，随后简化配置、关闭 SDK 来源限制；只对 MCP 路径安装独立最外层 CORS，保证预检、成功/错误响应和原 REST 隔离。
  **覆盖 AC**：AC-01、AC-02、AC-03～05、AC-12、AC-14。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-007, REQ-008, REQ-009_
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-12, AC-14_
  _Verification: E-007 新行为失败证据；E-008 新模块与相关回归；E-009 静态检查_
  _Depends: T006_
  _Boundary: 2026-10-09 用户已确认来源/DNS 防护变化；不改全局 REST CORS、不更改鉴权与资源权限、不部署_

## 任务评审

根据项目 tasks checklist 静态检查：REQ/AC 引用有效、文件范围明确、依赖无环、拒绝路径先于实现、现有测试复用、
无新 ORM/迁移/权限实体、无原接口收紧、无前端/Worker 任务，验证按业务风险分组而非按 AC 重复运行。结果 LGTM。

## 实际偏差记录

- 项目建议分支 `feat/2.5.0-sg/070-mcp-server` 与既有 `feat/2.5.0-sg` ref 冲突，Git 拒绝创建。改用 `codex/070-mcp-server`，不改起点或用户未提交文件。
- SDK 的常驻 session manager 在 HTTP 取消时不保证立即清理后台工具，改为每请求 session manager/task group；真实 TCP 断开监听在 SDK 消费完请求体后启动，避免争抢请求体。静态工具注册仍由 worker lifespan 管理，范围不变。
- 现有 Token 测试基线 4 处同步角色查询替身与当前异步实现不符，修正测试替身，不改生产鉴权行为。
- 共享检索提取保留原 REST 的函数签名和身份解析依赖；不新增无用途的 dependencies.py 改动。总超时由 REST/MCP 各自的外层用户/业务作用域负责，核心检索与来源解析编排共用。
- 测试目录遵守本特性 `test/mcp_server/`，采用真实 SDK/HTTP/TCP 与可控业务替身；不套用 REST E2E 模板创建/删除真实账号或数据。主应用测试为绕过既有全局测试替身的 metaclass/异常类冲突，隔离无关业务路由与 JWT 异常类型；MCP 入口与主中间件为真实实现。
- SDK 默认参数模型忽略额外字段，注册后显式设置 arg_model.extra=forbid 并更新 schema，已由身份参数拒绝回归覆盖。该元数据接口需要在未来 SDK 升级时复验，当前 uv.lock 未变。

## 完成证据

T001～T006 均通过任务级自审和对应验证，见 [verification.md](verification.md) E-002～E-006、[code-review.md](code-review.md)。
最终相关回归 181 passed；真实 SDK/TCP 和取消清理已验证。未提交、推送或部署；真实业务基础设施/DM8 仍为 MANUAL_REQUIRED。

2026-10-09：用户确认 T007；不删除既有关闭开关，只取消不再需要的 Host/Origin 配置与防护；后续证据覆盖新 AC，旧 181 passed 属于原策略历史记录。

T007 本地验证完成：37 项 MCP 定向测试通过；最终相关回归 190 passed，见 E-008/E-009。工作区并行出现的知识空间改动未由本任务编辑或暂存。
