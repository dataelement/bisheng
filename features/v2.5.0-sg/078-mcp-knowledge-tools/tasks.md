# Tasks: MCP 知识空间九工具

**关联规格**：[spec.md](spec.md)；**版本**：v2.5.0-sg。
用户于 2026-10-16 确认规格、50 MiB 文件 / 10 MiB 文本 / 80 MiB 请求体及实施。

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户明确确认 |
| tasks.md | ✅ 已拆解 | 依项目 21 项清单自审，LGTM；无独立 agent |
| 实现 | ✅ 本地完成 | T001～T018；73 项本功能测试通过，相关回归 308 通过、6 项 HEAD 已有失败 |
| 来源缺陷修复 | ✅ 本地完成 | T019～T020；MCP/入口解析 100 项通过；扩大预览回归 109 通过、7 项 HEAD 同样失败，见 verification §7 |
| 真实环境验收 | 🔲 待执行 | FGA/MinIO/ES/Milvus/Worker、MySQL/DM8、代理与压测；见 verification |

完成证据见 [verification.md](verification.md)，L1/L2 自审见 [code-review.md](code-review.md)。本地完成不代表已提交、合并、部署或生产验收。

## 执行约束

路径均相对仓库根。测试先于相应行为实现，红灯只证明缺失功能；实现完成仍须对应绿灯。所有新数据库查询封装在知识 Repository；不新增表、依赖、配置或 Worker。沿用既有解析投递的 tenant_id headers → Worker ContextVar，不修改该协议。MCP 原生响应、Token 身份与现有跨域策略保留。

### A：公共契约与浏览

- [x] **T001** 后端 API 测试：扩展 `src/backend/test/mcp_server/test_mcp_server.py`，新增 `src/backend/test/mcp_server/test_mcp_tools.py`。使用真实 SDK，验证十名称、严格 schema、未知身份字段、请求体超限和上下文清理；外部 I/O 受控，拒绝时不进入业务。
  覆盖 AC: AC-01, AC-02, AC-13, AC-16, AC-17
  _Requirements: REQ-001, REQ-010, REQ-012_
  _Acceptance: AC-01, AC-02, AC-13, AC-16, AC-17_
  _Verification: V-PROTOCOL；保存实施前红灯_
  _Depends: none_

- [x] **T002** 后端 Domain：新增 `src/backend/bisheng/mcp_server/domain/schemas/browse.py`、`content.py`。定义严格 ID、游标、列表/搜索和正文/来源参数及白名单结果；沿用 20/100 页大小、200/2000 查询长度等已确认契约。
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-012_
  _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-17_
  _Verification: V-PROTOCOL，配对 T001_
  _Depends: T001_

- [x] **T003** 后端 Domain：新增 `src/backend/bisheng/mcp_server/domain/schemas/ingestion.py`、`src/backend/bisheng/mcp_server/domain/services/tool_runtime.py`。严格文件名/文本/Base64、50/10/80 MiB 常量；在实际工具任务中设置身份并按请求装配领域服务，统一安全错误和审计。
  _Requirements: REQ-001, REQ-009, REQ-010, REQ-011, REQ-012_
  _Acceptance: AC-01, AC-11, AC-12, AC-13, AC-15, AC-16, AC-17_
  _Verification: V-PROTOCOL、V-WRITE，配对 T001、T009_
  _Depends: T001, T002_

- [x] **T004** 后端 Domain 测试：新增 `src/backend/test/knowledge/test_mcp_knowledge_query_service.py`、`test_mcp_knowledge_repository.py`。以有界候选和受控权限验证空间可写筛选、目录归属、活动版本、权限后分页、名称/正文搜索及只读无副作用；仓储至少验证真实 SQL 查询结果。
  覆盖 AC: AC-03, AC-04, AC-05, AC-06, AC-17
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-012_
  _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-17_
  _Verification: V-BROWSE、V-SEARCH_
  _Depends: T002_

- [x] **T005** 后端 Domain：新增 `src/backend/bisheng/knowledge/domain/repositories/interfaces/knowledge_mcp_repository.py`、`implementations/knowledge_mcp_repository_impl.py`。继承项目 BaseRepository；空间、目录/文件候选按稳定键分页，过滤活动/主版本与回收状态；范围受限的正文命中以候选批次查询，避免 10000 桶截断；不手写 ORM 租户条件。
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-08_
  _Verification: V-BROWSE、V-SEARCH，配对 T004_
  _Depends: T004_

- [x] **T006** 后端 Domain：新增 `src/backend/bisheng/knowledge/domain/services/knowledge_mcp_query_service.py`。使用现有可见空间与细粒度权限服务，对候选执行上传/读取/目录归属检查后生成轻量 DTO、路径和完整上下文游标；不补建个人库、不修正解析状态。
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-012_
  _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-17_
  _Verification: V-BROWSE、V-SEARCH，配对 T004_
  _Depends: T005_

### B：正文、来源与检索

- [x] **T007** 后端 Domain 测试：新增 `src/backend/test/knowledge/test_mcp_knowledge_content_service.py`。物理/逻辑入口、不同代次、分页变化、未解析、权限拒绝不读正文/不签名、仅预览和水印限制采用受控存储验证。
  覆盖 AC: AC-07, AC-08, AC-09, AC-17
  _Requirements: REQ-006, REQ-007, REQ-012_
  _Acceptance: AC-07, AC-08, AC-09, AC-17_
  _Verification: V-CONTENT_
  _Depends: T006_

- [x] **T008** 后端 Domain：新增 `src/backend/bisheng/knowledge/domain/services/knowledge_mcp_content_service.py`。先对入口授权，再解析 canonical/version/generation，使用有界正文读取与内容游标；来源只签发有权预览，原件严格遵守现有下载/水印/分发限制，不新增匿名下载入口。
  _Requirements: REQ-006, REQ-007_
  _Acceptance: AC-07, AC-08, AC-09_
  _Verification: V-CONTENT，配对 T007_
  _Depends: T007_

### C：新建与上传

- [x] **T009** 后端 Domain 测试：新增 `src/backend/test/knowledge/test_mcp_knowledge_ingestion_service.py`。验证真实字节、目标权限、配额/重复、已有 ID 失败分支、未投递/已投递/投递不确定、断连清理和 50/10 MiB 边界；拒绝不覆盖旧文件。
  覆盖 AC: AC-11, AC-12, AC-13, AC-14, AC-15
  _Requirements: REQ-009, REQ-010, REQ-011_
  _Acceptance: AC-11, AC-12, AC-13, AC-14, AC-15_
  _Verification: V-WRITE_
  _Depends: T003, T006_

- [x] **T010** 后端 Domain：新增 `src/backend/bisheng/knowledge/domain/services/knowledge_mcp_ingestion_service.py`。Base64/UTF-8 转受控暂存，调用知识 Owner 的 add_file、授权、版本和原解析投递，保留原大小/配额/分类规则；识别失败返回与部分副作用，业务清理由 Owner 负责，只自行删除本次暂存对象，不调用 file/sync。
  _Requirements: REQ-009, REQ-010, REQ-011_
  _Acceptance: AC-11, AC-12, AC-13, AC-14, AC-15_
  _Verification: V-WRITE，配对 T009_
  _Depends: T009_

### D：工具注册与装配

- [x] **T011** 后端 API：新增 `src/backend/bisheng/mcp_server/api/endpoints/query_tools.py`、`content_tools.py`。显式注册浏览、搜索、详情和来源工具，签名/返回模型与 schema 一致，实际业务通过 T003 运行边界执行。
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007_
  _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-17_
  _Verification: V-PROTOCOL，配对 T001_
  _Depends: T006, T008_

- [x] **T012** 后端 API：新增 `src/backend/bisheng/mcp_server/api/endpoints/write_tools.py`，修改 `tools.py`。注册两个写工具与新 retrieve_chunks；旧 search_knowledge 范围与行为保持；全部工具参数禁止未知字段，读写注解准确。
  _Requirements: REQ-001, REQ-008, REQ-009, REQ-010, REQ-012_
  _Acceptance: AC-02, AC-10, AC-11, AC-12, AC-17, AC-18_
  _Verification: V-PROTOCOL、V-REGRESSION，配对 T001_
  _Depends: T010, T011_

- [x] **T013** 后端 Domain：修改 `src/backend/bisheng/mcp_server/domain/services/factory.py`，必要时修改 `search_service.py`。每工具请求装配 Repository、知识权限/入口解析及上传服务；新检索先校验所有 ID 均为有权空间再复用原检索核心，保持旧 factory 接口兼容。
  _Requirements: REQ-001, REQ-008, REQ-012_
  _Acceptance: AC-01, AC-02, AC-10, AC-16, AC-18_
  _Verification: V-PROTOCOL，配对 T001、T015_
  _Depends: T012_

- [x] **T014** 后端 API：修改 `src/backend/bisheng/mcp_server/api/router.py`。注入新 factory/runtime，80 MiB 实际请求体计数在 SDK 解析之前，超限返回 413；保留两路径、CORS、鉴权、断连和任务组生命周期。
  _Requirements: REQ-010, REQ-012_
  _Acceptance: AC-13, AC-16, AC-18_
  _Verification: V-PROTOCOL，配对 T001_
  _Depends: T013_

- [x] **T015** 后端 API 测试：扩展 `src/backend/test/mcp_server/test_main_integration.py`、`test_search_factory.py`。更新十名称期望，验证真实主 middleware/lifespan/TCP 与请求专属装配、session 关闭；复用现有 CORS/Token 回归。
  覆盖 AC: AC-01, AC-02, AC-10, AC-13, AC-16, AC-18
  _Requirements: REQ-001, REQ-008, REQ-010, REQ-012_
  _Acceptance: AC-01, AC-02, AC-10, AC-13, AC-16, AC-18_
  _Verification: V-PROTOCOL、V-REGRESSION_
  _Depends: T001_

### E：端到端与交付

- [x] **T016** 后端 API 测试：新增 `src/backend/test/mcp_server/test_mcp_knowledge_flow.py`。通过真实 SDK 执行发现/浏览/搜索/读详情及创建/上传/查询状态流程；使用真实新领域服务与受控外部端口，明确不代表真实基础设施验收。
  覆盖 AC: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-14, AC-15, AC-16, AC-17, AC-18
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012_
  _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-14, AC-15, AC-16, AC-17, AC-18_
  _Verification: V-PROTOCOL；领域行为复用前序证据，不重复同义用例_
  _Depends: T014, T015_

- [x] **T017** 文档：新增本特性 `usage.md`、`verification.md`。说明九工具参数、调用流程与旧工具兼容，记录实际红/绿灯和相关回归命令；真实 DB/FGA/MinIO/Worker/代理/DM8 未验证时列 MANUAL_REQUIRED。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012_
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18_
  _Verification: 关联回归证据与 V0 文档检查_
  _Depends: T016_

- [x] **T018** 审查与状态：本特性 `code-review.md`、`tasks.md`。按任务/特性清单自审权限、来源、并发、错误和分层；实际证据满足后勾选，不把实现测试与线上部署混同。
  _Requirements: REQ-001, REQ-012_
  _Acceptance: AC-01, AC-16, AC-17, AC-18_
  _Verification: 复用最终同一代码状态的测试、Ruff、架构检查和 diff 检查_
  _Depends: T017_

## 任务评审

### 2026-10-16 来源工具缺陷修复

- [x] **T019** 补充来源预览兼容、逻辑入口及拒绝路径回归；观察现有实现失败，再以现有 Owner 预览替代路径拼接，更新 SDK Owner 替身。
  _Requirements: REQ-007, REQ-012_
  _Acceptance: AC-09, AC-09-FIX, AC-17, AC-18_
  _Verification: 领域红/绿灯、SDK 流程、入口解析及现有预览权限回归_
  _Depends: T018_
  _Boundary: 不改变 Owner、权限或下载政策，不部署或写入远程业务数据_

- [x] **T020** 更新使用文档与 verification，记录根因、验证证据及待部署复验范围。
  _Requirements: REQ-007, REQ-012_
  _Acceptance: AC-09-FIX, AC-18_
  _Verification: Ruff、架构守卫、diff 与文档检查；复用 T019 回归_
  _Depends: T019_

LGTM。已对照项目 tasks 清单检查完整 AC 追溯、前置依赖、测试先行、每任务最多两个主要文件、原有 Owner 边界及无新数据迁移。测试文件可先存在失败用例，批次成功后更新最终完成状态。T015 的测试先于 T013/T014 配对实现执行，展示顺序按交付模块分组。

## 实际偏差记录

- 计划中的候选分页采用数据库稳定键扫描，正文只对有界候选批次查询，避免依赖 10000 桶聚合；沿用 design 的预算耗尽显式续页规则。
- 工作分支使用 `codex/078-mcp-knowledge-tools`，避免已有 `feat/2.5.0-sg` 引用与层级分支冲突。
- 查询使用新增的专用 `KnowledgeMcpRepository` 接口/实现，继承现有 BaseRepository；没有向大型旧仓储或 DAO 添加新功能入口。
- 工厂复用已有 `build_knowledge_space_service_for_filelib_sync` 的知识 Owner 装配，未调用 FilelibSyncService、同步规则、身份代理或覆盖流程；未修改 open_endpoints。
- E2E 复用 F070 的 MCP SDK/ASGI/TCP 入口；新业务流程采用真实新服务/SQLite/入口解析器及受控外部端口，不使用 JWT/REST 响应模板，不代表真实基础设施验收。
- 扩大回归发现六项旧上传测试失败，已在未修改 HEAD 快照复现相同原因，未为本功能修复无关代码或装配。最终记录为有基线失败的本地交付。
- 全局测试预置了 KnowledgeUtils/BaseService 替身；内容测试在本用例作用域加载真实纯工具函数，不为适配替身修改生产代码。
- 来源缺陷修复沿用用户指定的现有预览和权限逻辑，纳入已确认 REQ-007；T019 的三个直接关联文件（内容服务、领域测试、SDK Owner 替身）作为同一批次处理，不修改预览 Owner 或其旧测试。

## 完成证据索引

| 任务 | 证据 | L1 结果 |
|---|---|---|
| T001～T003 | E02/E05/E06/E09/E12：协议红/绿灯、严格 schema、运行上下文 | PASS |
| T004～T006 | E04/E09/E12：权限后分页、目录归属、真实 ORM 活动库存查询 | PASS |
| T007～T008 | E04/E08/E09/E12：正文代次、分隔符、逻辑入口、来源限制 | PASS |
| T009～T010 | E09/E12/E13：真实大小/字节、受理状态、取消/不确定交接及安全审计 | PASS |
| T011～T015 | E06/E09/E12：十名称、旧契约、签名、主应用 TCP、session 释放 | PASS |
| T016 | E07/E09/E12：九工具 SDK 连续流程与回查、租户拒绝 | PASS（受控端口） |
| T017～T018 | E10/E11：基线对照、Ruff、架构、文档与特性自审 | PASS_WITH_NOTES |
| T019～T020 | E14～E18：来源红/绿灯、SDK、MCP/入口解析、扩大预览回归及 HEAD 对照；见 verification §7 | PASS_WITH_BASELINE_FAILURES；待部署复验 |
