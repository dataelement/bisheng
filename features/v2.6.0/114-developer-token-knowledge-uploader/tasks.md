# F114 实施任务：Developer Token 知识上传人

| 文档 | 状态 |
|---|---|
| requirements.html | v0.2 需求已闭环 |
| design.html | v0.2 设计已确认（2026-11-06） |
| test-cases.html | v0.1 已定义 |
| release-contract.md | 已登记表 1 / INV-19 / 表 3 |

路径相对仓库根目录 `bisheng/`。

## 任务列表

- [x] **T001 · Alembic 迁移（MySQL + DM8）**  
  - 文件：`src/backend/bisheng/core/database/alembic/versions/`（新建 revision）、`bisheng/developer_token/domain/models/developer_token.py`  
  - 内容：`developer_token` 新增 `knowledge_uploader_user_id`（INT，nullable 兼容存量；列 **中文 COMMENT**）；应用层新建/更新必填。  
  - _REQ: REQ-002_ _AC: —_ _验证: `uv run alembic upgrade head`（本地 MySQL）；DM8 手检方言_  

- [x] **T002 · Domain Schema + Repository**  
  - 文件：`bisheng/developer_token/domain/schemas/developer_token.py`、`developer_token/domain/services/developer_token_service.py`、`repository` 实现  
  - 内容：`DeveloperTokenCreate`/`Update`/`Read`/`Detail` 增加字段；创建/更新校验上传人存在、租户一致、未删除；列表/详情返回展示字段。  
  - _REQ: REQ-001 REQ-002_ _AC: AC-02_  

- [x] **T003 · `DeveloperTokenPrincipal` 与认证**  
  - 文件：`bisheng/developer_token/domain/schemas/developer_token.py`、`developer_token_service.authenticate_principal`  
  - 内容：Principal 增加 `knowledge_uploader_user_id`；认证时从 ORM 填充。  
  - _REQ: REQ-003_ _AC: —_  

- [x] **T004 · Admin HTTP**  
  - 文件：`bisheng/developer_token/api/endpoints/developer_token.py`（若需）、路由已注册处  
  - 内容：OpenAPI 契约与错误码（198 模块新增码位与 `common/errcode/developer_token.py` 对齐，避免冲突）。  
  - _REQ: REQ-002_ _AC: AC-02_  

- [x] **T005 · Filelib 依赖：双用户上下文**  
  - 文件：`bisheng/open_endpoints/api/dependencies.py`  
  - 内容：新增写路径用依赖（如 `get_filelib_write_context`）：组合 `get_developer_token_principal`、`FilelibUserContextService`、`external_id` Query；产出 `permission_user` + `record_user`；无 Token 时保持 `default_operator` 合一语义（设计 §5.4）。  
  - _REQ: REQ-003 REQ-004_ _AC: AC-01 AC-04 AC-05_  

- [x] **T006 · `FilelibSpaceCommandService` + filelib 写端点**  
  - 文件：`bisheng/open_endpoints/domain/services/filelib_space_command_service.py`、`bisheng/open_endpoints/api/endpoints/filelib.py`  
  - 内容：写操作（create/update/upload/delete/clear/chunks/ingest 等）改用新依赖；`permission_user` 进 `prepare_upload`/quota，`record_user` 下传到 upload。  
  - _REQ: REQ-003 REQ-004_ _AC: AC-01~AC-03_  

- [x] **T007 · `KnowledgeService` 上传行字段**  
  - 文件：`bisheng/knowledge/domain/services/knowledge_service.py`（`upload_original_file`、`aprocess_knowledge_file`、`sync_process_knowledge_file`）  
  - 内容：可选 `record_user`；缺省保持现网；行字段与 `KnowledgeFileOrganizationService.uploader_organization` 入参用 `record_user.user_id`。  
  - _REQ: REQ-003 REQ-005_ _AC: AC-01 AC-04_  

- [x] **T008 · `FilelibSyncService`**  
  - 文件：`bisheng/open_endpoints/domain/services/filelib_sync_service.py`  
  - 内容：实现 design §5.2（责任人优先；无责任人回落用配置上传人）。  
  - _设计 §5.2_ _TC: TC-F114-SYNC-01/02_  

- [x] **T009 · 后端测试**  
  - 文件：`src/backend/test/developer_token/`、`src/backend/test/open_endpoints/`（新建或增量）  
  - 内容：覆盖 TC-F114-ADM-01、TC-F114-API-01～04；sync 视 fixture 可得性。  
  - _验证: `uv run pytest test/...`_  

- [x] **T010 · Platform 前端**  
  - 文件：`src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx`、`src/frontend/platform/src/controllers/API/developerToken.ts`  
  - 内容：表单必选知识上传人；列表/详情展示；类型对齐。  
  - _REQ: REQ-001_ _AC: AC-02_  

- [x] **T011 · 文档**  
  - 文件：`docs/api/filelib-openapi-interfaces.md`（若存在）  
  - 内容：说明未传 external_id 时上传人来源。  

- [x] **T012 · 静态检查**  
  - `uv run ruff format` / `ruff check` 于改动文件；`bash scripts/arch-guard.sh` 于改动文件。  

## 实际偏差记录

- **T001**：迁移 revision 已在仓库；各环境 **`uv run alembic upgrade head`** 仍由运维/本地执行人按需跑。
- **T005**：`get_filelib_write_space_context` 改为 **async generator**（`yield`），使带 `external_id` 的写请求在整个 endpoint 执行期间保持 `FilelibUserContextService.use_user` 的租户可见性上下文；并将 `get_filelib_user_repository` 提前定义，避免模块导入时 `Depends` 前向引用失败。Query 参数 `external_id` 的默认值放在函数参数 `= None`，**不在** `Query(...)` 内写 `default=None`（FastAPI 约束）。
- **T009**：补了 **`test_filelib_write_space_context_external_id.py`**（写路径 + `external_id` 时 `build_filelib_space_query_service` 须在全局可见性下执行）；`test-cases.html` 中 TC-F114-API/SYNC 全量用例仍以文档为准，未在本轮逐条自动化。

## 依赖顺序

T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009；T010 可与 T004 后并行；T011/T012 收尾。
