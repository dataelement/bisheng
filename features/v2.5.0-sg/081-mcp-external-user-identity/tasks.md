# F081：实施任务

- Status: `IMPLEMENTED_LOCAL`
- Updated: `2026-10-22`
- 授权：用户确认“按这份完整规格拆解任务并开始实施”，包含已记录的账号代理、跨租户及必填参数兼容变化。本轮不提交、推送或部署。
- 文件路径除文档外均相对 `src/backend/`；测试与实现组成批次，共用一次验证证据。

| 文档 | 状态 |
|---|---|
| spec.md / requirements.md / design.md | ✅ 已评审，用户已确认 |
| tasks.md | ✅ 已拆解并按项目 21 项清单自审 |
| verification.md | 实施期间记录 |

## 基础设施

无新配置、依赖、表、字段或迁移。新包仅补必要空 __init__.py，不引入运行逻辑。

## 后端 Domain

- [x] T001 身份及仓储回归测试先行。新增 `test/mcp_server/test_mcp_user_context_service.py`、`test/tenant/test_tenant_membership_repository.py`；使用受控用户候选/角色加载器及 SQLite 仓储，覆盖精确字符串、唯一当前关系、租户状态、多/单租户、只读失败与恢复，先记录失败。
  覆盖 AC: AC-03, AC-04, AC-05, AC-06, AC-08, AC-09
  _Requirements: REQ-003, REQ-004, REQ-005, REQ-006, REQ-009, REQ-011_
  _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-08, AC-09_
  _Verification: V-IDENTITY; 先行失败可作为测试任务证据，行为通过在实现批次记录_
  _Depends: none_
  _Boundary: 仅测试；不访问生产设施_

- [x] T002 公共身份 DTO。新增 `bisheng/mcp_server/domain/schemas/identity.py`；严格账号规范化、不可变执行身份，保留无身份通用基类，响应与嵌套 FolderScope 无账号。
  _Requirements: REQ-002, REQ-007_
  _Acceptance: AC-01, AC-03, AC-07_
  _Verification: V-IDENTITY, V-PROTOCOL_
  _Depends: T001_
  _Boundary: 仅 DTO；配对测试 T001/T005_

- [x] T003 只读 tenant 仓储。新增 `bisheng/tenant/domain/repositories/interfaces/tenant_membership_repository.py` 及 `implementations/tenant_membership_repository_impl.py`；BaseRepository 接口/实现，list_current_by_user 返回全部当前关系，find_tenant 按 PK，不先过滤失效状态；补空包文件。
  _Requirements: REQ-004, REQ-011_
  _Acceptance: AC-05, AC-06_
  _Verification: V-IDENTITY_
  _Depends: T001_
  _Boundary: 无 Service SQL、DAO 或迁移；配对测试 T001_

- [x] T004 统一身份解析服务。新增 `bisheng/mcp_server/domain/services/user_context_service.py` 并调整 `auth_service.py`；接收用户/租户仓储、模式及正常身份加载器；只读临时 bypass，唯一精确账号及当前租户，目标上下文六变量完整恢复，原 Token principal 只读，身份预算 30 秒。
  _Requirements: REQ-003, REQ-004, REQ-005, REQ-006, REQ-009, REQ-011_
  _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-08, AC-09_
  _Verification: V-IDENTITY_
  _Depends: T002, T003_
  _Boundary: 配对测试 T001；不复用 REST 代理的执行 bypass，不改共享 Token 校验_

## 后端 API 与执行装配

- [x] T005 协议测试先行。调整 `test/mcp_server/test_mcp_tools.py`、`test_mcp_server.py`；十 schema 账号必填、缺参/非法输入拒绝、握手无账号、Token 校验先行，两执行链路目标用户/审计及并发取消；测试工厂显式注入目标解析，不做生产回退。
  覆盖 AC: AC-01, AC-02, AC-04, AC-07, AC-08, AC-09, AC-10
  _Requirements: REQ-001, REQ-002, REQ-005, REQ-006, REQ-007, REQ-009, REQ-010_
  _Acceptance: AC-01, AC-02, AC-04, AC-07, AC-08, AC-09, AC-10_
  _Verification: V-PROTOCOL, V-AUTHORITY, V-ISOLATION_
  _Depends: T001_
  _Boundary: 仅测试；保留 folder_id、路由/CORS 断言_

- [x] T012 工厂/真实 HTTP 测试。修改 `test/mcp_server/test_search_factory.py`、`test_main_integration.py`；身份 session 先关闭、目标用户注入真实工厂，主应用 TCP 使用账号；保留传输、鉴权、生命周期回归。
  覆盖 AC: AC-01, AC-02, AC-04, AC-07, AC-08, AC-10
  _Requirements: REQ-001, REQ-005, REQ-006, REQ-007, REQ-010, REQ-011_
  _Acceptance: AC-01, AC-02, AC-04, AC-07, AC-08, AC-10_
  _Verification: V-PROTOCOL, V-AUTHORITY, V-ISOLATION, V-REGRESSION_
  _Depends: T005_
  _Boundary: 仅测试，测试先于装配最终验证；使用既有 TCP harness_

- [x] T013 目标权限与写入回查端到端。修改 `test/mcp_server/test_mcp_knowledge_flow.py`；真实 SDK/SQLite/知识服务，受控外部 Owner/FGA/存储/队列；同 Token 切换允许/拒绝目标，两写工具读取回查及操作者/租户，补旧检索同身份断言。
  覆盖 AC: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10
  _Requirements: REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011_
  _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10_
  _Verification: V-FLOW, V-AUTHORITY, V-ISOLATION_
  _Depends: T001, T005_
  _Boundary: 仅测试；不将受控端口结果称为真实基础设施验收，既有 Celery headers → ContextVar 不改_

- [x] T006 浏览及检索请求。修改 `bisheng/mcp_server/domain/schemas/browse.py`、`search.py`；十顶层请求的公共基类接入账号，嵌套与响应保持；搜索 DTO 去掉重复配置。
  _Requirements: REQ-002, REQ-007, REQ-010_
  _Acceptance: AC-01, AC-07, AC-10_
  _Verification: V-PROTOCOL_
  _Depends: T002, T005_
  _Boundary: 配对测试 T005；保留 FolderId_

- [x] T007 正文及写请求。修改 `bisheng/mcp_server/domain/schemas/content.py`、`ingestion.py`，只为顶层请求接入身份基类，保留响应及 50/10/80 MiB 限制。
  _Requirements: REQ-002, REQ-007, REQ-010_
  _Acceptance: AC-01, AC-07, AC-10_
  _Verification: V-PROTOCOL_
  _Depends: T006_
  _Boundary: 配对测试 T005；不改领域请求_

- [x] T008 发现/检索函数。修改 `bisheng/mcp_server/api/endpoints/query_tools.py`、`tools.py`；五注册签名使用 ExternalAccount，顶层 DTO 显式赋值；原检索审计随统一服务迁移，不泄漏输入。
  _Requirements: REQ-002, REQ-007, REQ-009_
  _Acceptance: AC-01, AC-07, AC-09_
  _Verification: V-PROTOCOL_
  _Depends: T005, T006_
  _Boundary: 配对测试 T005；保留 SDK 包装与未知字段拒绝_

- [x] T009 正文/写函数。修改 `bisheng/mcp_server/api/endpoints/content_tools.py`、`write_tools.py`；五注册签名和 DTO 增加必填账号，保留已有参数及输出。
  _Requirements: REQ-002, REQ-007, REQ-010_
  _Acceptance: AC-01, AC-07, AC-10_
  _Verification: V-PROTOCOL_
  _Depends: T007, T008_
  _Boundary: 配对测试 T005；不改 Owner 写入_

- [x] T010 生产身份工厂及路由装配。修改 `bisheng/mcp_server/domain/services/factory.py`、`api/router.py`；有界读取模式、受管理身份 session、仓储/正常角色加载，解析完成关闭后才进入目标业务；身份工厂可注入，两 runtime 共用。
  _Requirements: REQ-004, REQ-005, REQ-006, REQ-007, REQ-011_
  _Acceptance: AC-04, AC-05, AC-06, AC-07, AC-08_
  _Verification: V-IDENTITY, V-PROTOCOL, V-FLOW_
  _Depends: T004, T005, T012, T013_
  _Boundary: 配对测试 T001/T005/T012；HTTP Token 校验不变_

- [x] T011 两执行链路。修改 `bisheng/mcp_server/domain/services/tool_runtime.py`、`search_service.py`；解析并使用目标身份，剔除领域参数 external_id；九工具总预算含身份/装配，旧检索独立身份预算，安全错误及 Token/执行身份审计，取消恢复。
  _Requirements: REQ-001, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_
  _Acceptance: AC-02, AC-04, AC-07, AC-08, AC-09_
  _Verification: V-PROTOCOL, V-AUTHORITY, V-ISOLATION_
  _Depends: T004, T005, T010, T013_
  _Boundary: 配对测试 T005；写入不确定状态继续原语义_

## 文档和交付

- [x] T014 更新 `docs/api/mcp-usage.md`；所有工具示例补账号，说明可信后端固定账号、跨租户/管理员代理、必填升级、Token 绑定有效性及回退不撤销写入。
  _Requirements: REQ-010, REQ-012_
  _Acceptance: AC-10_
  _Verification: V-DOC_
  _Depends: T008, T009, T011_
  _Boundary: 文档静态验证，不部署_

- [x] T015 更新 F070/F078 相关身份约定。路径为 `features/v2.5.0-sg/{070-mcp-server,078-mcp-knowledge-tools}/` 的 spec/requirements/design/usage 中当前身份段落；历史验收原样保留并加版本说明。
  _Requirements: REQ-010, REQ-012_
  _Acceptance: AC-10_
  _Verification: V-DOC_
  _Depends: T014_
  _Boundary: 同一文档更正批次超过两文件，均仅身份约定；不重写历史记录_

- [x] T016 最终相关回归、任务/代码自审及证据。创建 `verification.md`、`code-review.md`，更新本 tasks 状态；执行 MCP/Token/相关 REST 和知识权限、Ruff/架构/文档检查，记录基线失败和真实环境人工项。
  覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012_
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10_
  _Verification: V-REGRESSION, V-DOC; 复用上述同状态有效证据_
  _Depends: T001, T002, T003, T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015_
  _Boundary: 无真实远程写入、提交、推送或部署；只读 review 不代替行为测试_

## 前端 Platform / Client、Worker

均无生产实现任务。上传任务身份只验证既有 tenant headers → ContextVar，不改 Worker。

## 实际偏差记录

- 实施分支使用 codex/mcp-external-user-identity，从 feat/2.5.0-sg 当前 HEAD 建立；无提交/合并/推送。
- StrictRequest 定义移到 identity.py，browse.py 保留兼容导入，避免公共身份基类与浏览请求循环导入。
- 既有测试全局预桩替换 User/历史 http_error；E2E 用真实 SQLModel 测试表运行原 UserRepository 查询，角色/FGA/存储/队列为受控端口，绝不宣称真实生产设施通过。

- 新包空 __init__.py 归入相应仓储任务，不计独立行为。T015 为同一身份说明更正批次，超过文件数量建议，但不含代码；T016 为交付文档/验证批次。
- 项目旧任务审查资料中的 DAO、JWT/REST 包装约定以根 AGENTS 的 Repository 分层及已确认 MCP 原生协议为准。
- T001/T005/T012/T013 为测试先行任务；按安全批次先建立测试再实现，不为同一代码状态重复全套验证。

## 任务计划自审

LGTM。已按项目 tasks-checklist 的 21 项检查：AC 全覆盖、测试先行、依赖存在、领域接口明确、无新增运行设施、无前端混用或 Worker 行为变化。T015/T016 文件数例外如上记录；尚未宣称任务完成或行为通过。

## 完成记录

T001～T016 本地任务已完成，任务/特性自审见 code-review.md。当前 MCP/身份/仓储 120 passed；最终相关回归 338 passed、1 项干净 HEAD 同样失败。Ruff、架构、文档检查通过。真实设施及部署均 MANUAL_REQUIRED，完整命令与证据见 verification.md。无提交、推送、合并或部署。
