# F083：实施任务

- Status: `IMPLEMENTED_LOCAL`
- Updated: `2026-10-26`
- 授权：用户在完整规格评审后回复“开始实施”，授权本规格任务拆解、实现和本地验证；不提交、合并、推送或部署。
- 分支：`codex/mcp-folder-retrieval`；基线 `a0c0b538cf95a7cacc3e5a6f8f481f4575e1ac8a`。
- 除使用文档外，代码路径均相对 `src/backend/`；相关测试按批次共用证据。

| 文档 | 状态 |
|---|---|
| spec.md / requirements.md / design.md | ✅ 已评审，用户已确认 |
| tasks.md | ✅ 已拆解，按项目 21 项清单自审 LGTM |
| verification.md | ✅ 本地证据与真实设施缺口已记录 |

## 基础设施

- [x] T001 新增范围预算错误。修改 `bisheng/common/errcode/knowledge_space.py`，新增继承 BaseErrorCode 的 McpFolderRetrievalScopeLimitError，Code=18007；固定安全提示，无目录/文件数量或 ID；无新配置、依赖、表或迁移。
  _Requirements: REQ-007_
  _Acceptance: AC-03, AC-06_
  _Verification: V-SCOPE, V-FLOW；错误类定义检查复用后续拒绝测试_
  _Depends: none_
  _Boundary: 仅错误码，先于业务实现_

## 后端 Domain

- [x] T002 目录范围测试先行。新增 `test/knowledge/test_mcp_folder_retrieval_service.py`、扩展 `test/knowledge/test_mcp_knowledge_repository.py`。范围服务接口 resolve_file_ids(knowledge_id,folder_id,recursive)；实际 SQLite 路径查询证明递归/直接层、相似目录隔离；受控权限证明多批完整、空范围、拒绝/异常、恰好 1000 和第 1001 个拒绝，先记录失败。
  覆盖 AC: AC-02, AC-03, AC-04, AC-06
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-007, REQ-009_
  _Acceptance: AC-02, AC-03, AC-04, AC-06_
  _Verification: V-SCOPE, V-PERMISSION；先行失败为测试任务证据_
  _Depends: T001_
  _Boundary: 仅测试，无外部设施_

- [x] T003 实现目录范围解析。新增 `bisheng/knowledge/domain/services/knowledge_mcp_folder_retrieval_service.py`，依赖既有 query.require_space/folder_path/visible 和 repository.scan_files；每批 100、file_name/id 升序续扫、status=2、最多 1000 成功候选；明确空集/无进展/超限，串行使用会话，无查询 SQL 或状态写入。
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-007, REQ-009_
  _Acceptance: AC-02, AC-03, AC-04, AC-06_
  _Verification: V-SCOPE, V-PERMISSION_
  _Depends: T002_
  _Boundary: 配对测试 T002，不改旧列表预算或权限规则_

- [x] T004 共享检索边界测试先行。修改 `test/open_endpoints/test_filelib_retrieve_service.py`、`test/knowledge/test_knowledge_space_chat_service_retrieve.py`；验证内部 file_ids_by_knowledge 的 None/空集/非空、空间完整覆盖、标签合并、不变更请求对象、来源签发前越界守卫；共享路径验证 strict_file_scope 传入 resolver.strict_explicit、拒绝缺失限域或非共享路径、保持旧默认调用实参，复用 resolver 已有严格映射行为测试。
  覆盖 AC: AC-03, AC-05, AC-06, AC-07
  _Requirements: REQ-003, REQ-005, REQ-006, REQ-008_
  _Acceptance: AC-03, AC-05, AC-06, AC-07_
  _Verification: V-RETRIEVAL, V-REGRESSION；先行失败与后续通过共享证据_
  _Depends: T001_
  _Boundary: 仅测试；不访问 Milvus/ES_

- [x] T005 实现内部范围透传。修改 `bisheng/open_endpoints/domain/services/filelib_retrieve_service.py`、`bisheng/knowledge/domain/services/knowledge_space_chat_service.py`。新增 keyword-only 内部 file_ids_by_knowledge，校验完整空间/正整数文件，保持 None 默认路径，空集短路，非空合入标签；strict_file_scope 仅新模式开启，复用 strict_explicit 并在来源签发前校验结果入口，不改 REST schema 或默认 resolver 行为。
  _Requirements: REQ-003, REQ-005, REQ-006, REQ-008_
  _Acceptance: AC-03, AC-05, AC-06, AC-07_
  _Verification: V-RETRIEVAL, V-REGRESSION_
  _Depends: T004_
  _Boundary: 配对测试 T004，禁用 preauthorized 权限豁免，无新存储条件或召回算法_

## 后端 API

- [x] T006 SDK 参数测试先行。修改 `test/mcp_server/test_mcp_tools.py`、`test/mcp_server/test_mcp_server.py`，已有工具清单扩展为十一，更新缺参测试参数表；新增新工具 FolderId 归一化、严格 recursive、必填字段、非法/重复/跨空间标签和未知字段拒绝、容量错误安全提示及超时清理验证。
  覆盖 AC: AC-01, AC-04, AC-06, AC-07
  _Requirements: REQ-001, REQ-004, REQ-007, REQ-008, REQ-009_
  _Acceptance: AC-01, AC-04, AC-06, AC-07_
  _Verification: V-PROTOCOL, V-FLOW, V-REGRESSION_
  _Depends: T001_
  _Boundary: 真实 SDK，受控运行时端口；只改既有集合不弱化身份断言_

- [x] T007 新请求和工具注册。修改 `bisheng/mcp_server/domain/schemas/content.py`、`bisheng/mcp_server/api/endpoints/content_tools.py`，新增 FolderRetrieveRequest 和 retrieve_folder_chunks；必填 external_id/query/knowledge_id/folder_id、默认 recursive=true/top_k=5/max_content=15000，过滤仅本空间单项 ANY，保留响应/嵌套模型无身份。
  _Requirements: REQ-001, REQ-005, REQ-008_
  _Acceptance: AC-01, AC-05, AC-07_
  _Verification: V-PROTOCOL_
  _Depends: T006_
  _Boundary: 配对测试 T006；旧工具函数不变_

- [x] T008 受控 SDK 端到端测试先行。修改 `test/mcp_server/test_mcp_knowledge_flow.py`；实际范围仓储+factory+SDK，目录含直接/子目录/兄弟/无权文件，检索后端受控且共享服务真实，证明范围透传、默认和 false、合法空范围及目标账号/租户拒绝；复用 T006 和既有并发取消清理，避免重复同义测试。
  覆盖 AC: AC-02, AC-03, AC-04, AC-05, AC-06
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-009_
  _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06_
  _Verification: V-FLOW_
  _Depends: T003, T005, T007_
  _Boundary: 仅本地 SQLite 和受控端口，不产生真实文件或权限变更_

- [x] T009 装配和安全错误映射。修改 `bisheng/mcp_server/domain/services/factory.py`、`bisheng/mcp_server/domain/services/tool_runtime.py`；新闭包先解析完整范围，空集在授权后返回空结果，非空使用现有 search_factory 和内部范围；只针对新工具+范围预算错误类返回固定提示，沿用 30 秒、身份、审计和清理。
  _Requirements: REQ-001, REQ-003, REQ-004, REQ-007, REQ-008, REQ-009_
  _Acceptance: AC-01, AC-03, AC-04, AC-06, AC-07_
  _Verification: V-PROTOCOL, V-FLOW, V-REGRESSION_
  _Depends: T003, T005, T007, T008_
  _Boundary: 配对测试 T006/T008；不改 Token、REST、配置和旧检索默认行为_

## 文档与交付证据

- [x] T010 更新 `docs/api/mcp-usage.md`：十一工具、必填账号、目录 ID 字符串兼容、默认递归/false/标签示例、1000 成功候选和 30 秒预算、空结果/超限错误、旧工具兼容。
  _Requirements: REQ-008, REQ-010_
  _Acceptance: AC-07_
  _Verification: V-DOC，示例和链接静态检查_
  _Depends: T009_
  _Boundary: 使用说明，无部署或配置改动_

- [x] T011 完成批次/最终相关回归、受控端到端和 L1/L2 自审；将命令、实际结果、代码状态和手工缺口记录到本目录 `verification.md`、`code-review.md`，更新任务状态。复用同一状态有效证据，不额外跑无关全量测试。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010_
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07_
  _Verification: V-PROTOCOL, V-SCOPE, V-PERMISSION, V-RETRIEVAL, V-FLOW, V-REGRESSION, V-DOC_
  _Depends: T010_
  _Boundary: MySQL/DM8/FGA/MinIO/Milvus/ES 实际设施未跑必须单列，不宣称生产验收_

## 批次、评审与实际偏差记录

- A：T001～T003；B：T004～T005；C：T006～T009；D：T010～T011。每批定向验证一次，最终相关回归合并执行。
- 任务拆解按项目 sdd-review tasks 二十一项清单自审：LGTM；无前端/Worker/数据库迁移任务。基础设施先行，测试均在配对实现前，允许先行红灯作为测试任务完成证据。
- 采用 `codex/mcp-folder-retrieval`：遵循当前开发环境默认分支前缀，且已有 `feat/2.5.0-sg` 引用无法再创建同名前缀下的 Git 分支；不改变目标集成分支，不自动合并。
- 为十一工具清单兼容，需要更新原 `test_mcp_server.py` 的 EXPECTED_TOOL_NAMES；已纳入 T006 和 design 文件计划，不改变旧测试的身份/鉴权断言。

- 最终检查点：T001～T011 全部完成；本地相关回归 383 passed，REST 账号兼容 17 passed，共 400 项；证据与 L1/L2 结果见 verification.md/code-review.md。
