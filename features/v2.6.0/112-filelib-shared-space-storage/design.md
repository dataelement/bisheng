# F112 设计说明：Filelib 文件接口统一共享存储

## Metadata

- Feature ID: F112-filelib-shared-space-storage
- Status: IMPLEMENTED_LOCAL
- Created: 2026-10-22
- 基线：`codex/mcp-external-user-identity` @ `938634642`，工作区已有 MCP/身份开发修改。
- Related requirements: [requirements.md](./requirements.md)
- API contract: [spec.md](./spec.md)

## 当前链路与必要改动

| 路径 | 已读取实现 | 发现 |
|---|---|---|
| 详情 | `open_endpoints/api/endpoints/filelib.py` 的内容辅助函数 | 文本对象未命中后调用旧 KnowledgeRag，SPACE 在创建 ES 客户端前失败 |
| 文件列表 | `KnowledgeService.aget_knowledge_files/get_knowledge_files_title` | 摘要仍调用旧 ES，异常后只返回空摘要 |
| 字符串切片 | `api/services/knowledge_imp.py:text_knowledge` | 直接初始化逐库 Milvus/ES，不符合 SPACE 共享写契约 |
| 异步/同步上传 | `aprocess_knowledge_file/sync_process_knowledge_file` | 已能进入现有共享解析路径；须补入口类型前置校验和调用级证据 |
| 删除/清空 | `KnowledgeService.delete_knowledge` | 跳过 drop 共享目标后仍按空间清 MinIO 和 SQL，不能作为共享生命周期的完整替代 |
| 检索 | `KnowledgeSpaceChatService.aretrieve_chunks` | SPACE 已走共享；全非 SPACE 仍可走旧路径，需要 Filelib 边界收口 |
| 原文件地址 | `FilelibFileSourceService` | 已解析规范文档/版本；补 SPACE-only 校验，保留原签名权限契约 |

## 架构与组件

端点只完成校验、身份注入和响应适配；编排服务委托 Knowledge 领域和 Repository，禁止跳层写 SQL。

- `FilelibSpaceQueryService`：SPACE 类型检查、既有列表响应、文件主版本标志及详情元数据编排。
- `FilelibSpaceContentService`：入口权限与物理内容解析、投影就绪检查、文本对象读取、共享分块与摘要读取。
  应复用 `KnowledgeDocumentEntryResolver` 及 Knowledge 仓储查询能力，而不是跨模块调用 MCP 端点。
- `FilelibSpaceCommandService`：默认操作者上下文下的创建、编辑、上传、文件删除、清空、退役编排。
  默认创建操作者拥有的团队库；保持全局 DTO 默认值，Filelib 单独定义入参。
- `FilelibRetrieveService`、`FilelibFileSourceService`：保留既有能力，增加文件资源类型边界；
  不修改外部身份策略或签名授权规则。
- Knowledge 内可新增必要的共享正文仓储和批量摘要方法；优先复用现有 MCP repository 的查询规则，
  抽出公共能力时保持 MCP 对外契约，不侵入工作区未提交的身份改造。

## 共享内容读取

1. 在当前业务用户作用域内查询入口和空间，检查 SPACE 类型与读取能力。
2. 由 resolver 得到有效 canonical document、主版本、实际内容文件、代次和投影状态。
3. 查询租户共享路由；不依赖历史 enabled 开关，缺初始化明确失败。
4. 在实际内容文件上查文本对象；无文本对象时按共享身份、空间归属和内容代次查询分块。
5. 分页完整读取并按 chunk_index 排序；使用稳定的追加游标，不把 MCP 的单页长度上限当全文返回。
6. 返回前校验版本/代次未变化；详情元数据仍使用请求访问的入口身份。

历史非主版本正文读取明确拒绝，不把当前共享主版本内容挂在旧文件元数据下。写冻结不阻断合法读取。

列表摘要按当前页批量取得共享身份和摘要，避免逐文件创建客户端或每个文件单查。
本次不新增列表权限过滤或改变分页协议；正文访问仍必须校验入口读取权限。
空对象沿用既有空内容语义；存储连接失败与不存在分开处理，必要时可尝试另一个共享来源，
但最后仍无法取得成功文件正文时须返回明确错误，不能用空字符串掩盖依赖故障。

## 写入与生命周期

- 普通上传、同步上传沿用解析服务的共享分支，类型/路由/操作资格校验须在下载文件或持久写入前完成。
- 字符串切片使用 `SharedSpaceDirectIngestionService`，沿用 prepare/write/finalize 的版本与归属收敛。
  不直接改通用 `text_knowledge` 的其他业务类型行为；输入 Document.metadata 先复制再整理。
- 删除与清空使用现有 Knowledge 领域生命周期能力，不以 `delete_by_query(knowledge_id)`、drop index、
  直接删空间全部 MinIO 对象替代。保留审计、冻结、管理入口和发布/分享规则。
- 批量文件必须先解析全部目标并检查属于同一空间，再执行领域批量删除；无权/混合空间不能先删一部分。
- 清空需要保留空间和 scope；优先复用领域预检、批量生命周期事务或已有持久任务机制。
  不新增独立任务平台，不做请求内未记录的分批循环；中断和部分执行必须可观察、可恢复。
- 共享内容是否可删除由有效入口和投影聚合决定；仍有效的引用须继续可读。

## File Structure Plan

下列为确认后的实施范围；任务执行与证据见 tasks.md、verification.md。

| Path（相对 src/backend/bisheng） | 操作 | 职责 | 需求 |
|---|---|---|---|
| `open_endpoints/api/endpoints/filelib.py` | modify | 14 个文件接口委托服务；6 QA + 统计函数保持 | REQ-001 至 REQ-008 |
| `open_endpoints/api/dependencies.py` | modify | 新服务与仓储依赖注入，保留现有身份上下文 | REQ-001, REQ-007 |
| `open_endpoints/domain/schemas/filelib.py` | modify | Filelib 专用 SPACE 创建 DTO；保留已有成功 DTO | REQ-001, REQ-008 |
| `open_endpoints/domain/services/filelib_space_query_service.py` | create | 列表、详情响应编排与 SPACE 校验 | REQ-001, REQ-002 |
| `open_endpoints/domain/services/filelib_space_content_service.py` | create | 共享内容与摘要读取、状态校验 | REQ-002, REQ-006 |
| `open_endpoints/domain/services/filelib_space_command_service.py` | create | 创建、上传与生命周期编排 | REQ-001, REQ-003, REQ-004 |
| `open_endpoints/domain/services/filelib_retrieve_service.py` | modify | 检索 SPACE-only 前置边界 | REQ-001, REQ-005 |
| `open_endpoints/domain/services/filelib_file_source_service.py` | modify | 原地址 SPACE-only 边界 | REQ-001, REQ-005 |
| `knowledge/domain/repositories/{interfaces,implementations}/` | modify/create 必要项 | 按页批量读取与 canonical 共享内容查询，禁止新 DAO 入口 | REQ-002, REQ-004 |
| `knowledge/domain/services/` | modify/create 必要项 | 仅补现有共享正文、入库、清空所需领域能力，不改变其他入口契约 | REQ-002 至 REQ-004 |
| `common/errcode/knowledge.py` | modify | 10973/10974 共享可用性与就绪错误 | REQ-006 |

另允许：`src/backend/test/open_endpoints/`、相关 `test/knowledge/`，本 Feature 产物，
`docs/api/filelib-openapi-interfaces.md` 和对应原文件/检索文档，`features/v2.6.0/release-contract.md` 的特性/错误码登记。
如果需要 Schema、全局身份策略、公共共享 schema 或其他业务类型适配，先重新确认范围。

## 状态与兼容性

- 复用 Knowledge、KnowledgeFile、KnowledgeDocument/Version、scope、projection 和既有回收/退役状态；无新 ORM 表。
- 默认类型变化、非 SPACE 拒绝、跨空间批量拒绝、新错误码及创建默认团队库在 API 文档明确列为兼容性变化。
- 只在本次文件接口新增领域检查，不改 default_operator 配置、不把 external_id 扩展到写接口。
- 不改 F069 全局业务用户范围、不新增租户手写 WHERE、不依赖共享 metadata.tenant_id 过滤。
- QA 通用适配器调用保留；旧适配器禁止 SPACE 的保护继续有效，不能通过 allow_legacy_space 绕过。

## Traceability 与验证批次

| Requirements | Acceptance | 主要验证层 / Evidence |
|---|---|---|
| REQ-001, REQ-008 | AC-01, AC-02, AC-11, AC-12 | V2 API 契约，V-01；参数化资源类型，比较排除接口函数与路由 |
| REQ-002, REQ-006 | AC-03, AC-04, AC-09 | V2 内容服务/仓储集成，V-02；真实辅助函数与可控后端，禁止只模拟最终内容函数 |
| REQ-003 | AC-05 | V3 共享直写回归，V-03；主要验证现有 writer/版本提交路径，三入口仅补接线覆盖 |
| REQ-004, REQ-007 | AC-06, AC-07, AC-10 | V3 生命周期/拒绝路径，V-04；两个空间共享同文档及冻结、无权、批量混合空间 |
| REQ-005, REQ-007 | AC-08, AC-10 | V2 既有检索/原链接/外部身份测试，V-05 |
| REQ-002, REQ-003, REQ-004 | AC-03, AC-05, AC-06, AC-07 | V3 受控 API 端到端 V-06；真实 ES/Milvus/MinIO、Worker 和 DM8 单列人工验证 |

使用 `src/backend/.venv/bin/python -m pytest`；复用同一状态的测试证据，
每个行为批次定向一次，阶段结束模块验证一次，最终相关回归一次。保留工作区既有失败并与基线区分。
最低回归范围包含现有 Filelib 检索、列表、原地址、用户上下文，以及共享直写、shared-only、分发和删除模块。
最终执行定向 ruff、语法、架构守卫和 diff 检查；不默认跑无关全量测试。

## 发布、风险与回退

- 本轮不部署、不操作真实数据。确认后仅实现和本地验证，真实服务无证据则记为 MANUAL_REQUIRED。
- 上线前每租户需有有效 route、embedding model、schema fingerprint 及已经迁移/收敛的共享内容。
- 新版仅支持 SPACE 的文件接口会拒绝旧调用方；更新调用文档与接口用例后再发布。
- 删除/清空代码路径改变后，必须以有效引用仍可读取、索引仍存在、原对象未误删为验收证据。
- 回退代码不回滚共享数据；已删除入口使用现有恢复能力，不能依赖旧开关恢复旧库。
- 当前工作区 MCP/身份修改保留；实施前依据确认后的任务决定隔离方式，不擅自切换、提交或清理现有改动。
