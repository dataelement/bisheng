# F083：文件夹范围检索设计

- Feature ID: `083-mcp-folder-retrieval`
- Status: `IMPLEMENTED_LOCAL`
- Created: `2026-10-26`
- Related: [spec.md](spec.md)、[requirements.md](requirements.md)。

## 1. 上下文和边界承诺

沿用 MCP FastMCP → McpToolRuntime → 请求专属 factory → knowledge 领域 Service/Repository 和 FilelibRetrieveService → KnowledgeSpaceChatService → 共享范围 resolver/reader。

已读取相关工具 schema/注册、runtime、factory、知识 MCP query/repository、共享检索/范围解析/来源服务及相关测试；版本/模块约束以双版本 release-contract 和当前 AGENTS 为准。旧架构说明中的 DAO、新响应包装或 JWT 注入不用于替换当前 MCP 运行机制。

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| MCP 对外 | 增加一个工具及其 DTO | 修改旧十工具参数、原 Token/账号/CORS 语义 | 修改已注册旧 schema/身份装配时补相关回归 |
| knowledge 领域 | 只读范围服务，复用现有仓储与权限 | 新 DAO、Service SQL、直接读 role_access、授予权限或隐式写入 | 新查询必须归 Repository，并验证双数据库兼容 |
| 共享检索 | 仅内部文件范围透传和新请求启用严格映射 | REST schema 新字段、手工 Milvus/ES 条件、旧调用默认行为改变 | 新内部参数必须验证省略/空集/非空三态 |
| 存储和投影 | 现有 canonical/current generation 解析 | 新字段/索引/迁移、旧索引回退、放松最终授权 | 实际发现无法沿用时先回到规格 |

无新增依赖、配置、数据表或领域对象；不需要修改版本契约的 Owner 或全局不变量。

## D-01：工具参数与注册（REQ-001/005）

在 `mcp_server/domain/schemas/content.py` 新增 `FolderRetrieveRequest(McpIdentityRequest)`，使用既有 ExternalAccount、FolderId、ResourceId、SearchQuery、TopK、MaxContent 以及 McpRetrieveFilters；recursive 使用 strict boolean。DTO 与工具函数签名使用相同类型。

after validator 校验 filters 的空间只等于 knowledge_id，最多一项，不重复；只支持 ANY。未知字段禁止，包括嵌套 file_ids、canonical ID 和 external_id。过滤错误必须在运行时开启业务 session 前被 SDK/DTO 拒绝；即使空目录也不能绕过参数校验。

`register_content_tools` 新增同名函数，沿用 readOnlyHint=true、destructiveHint=false、openWorldHint=false；返回 RetrieveResp，调用 runtime.invoke(ctx, "retrieve_folder_chunks", params)。保留 `StrictRequest` 和已有响应/嵌套 schema 的身份边界。

## D-02：目录范围服务与完整枚举（REQ-002/003/004/007/009）

新增 `knowledge/domain/services/knowledge_mcp_folder_retrieval_service.py` 的 `KnowledgeMcpFolderRetrievalService`，依赖现有 KnowledgeMcpQueryService；职责是解析并授权目录文件集合，不访问检索索引，不持有全局用户状态。

建议接口 `resolve_file_ids(*, knowledge_id: int, folder_id: int, recursive: bool) -> list[int]`：

1. `query.require_space(knowledge_id)` 后调用 `query.folder_path(knowledge_id, folder_id)`，先完成空间/目录归属及权限校验。
2. Repository `scan_files` 传入 `[knowledge_id]`、file_type=1、parent_path、recursive、statuses=[2]，分批上限 100；沿用现有 file_name + id 的升序游标键，使用 query.file_key 生成后续键。同一 AsyncSession 串行读取和权限查询，不用 gather 并发复用 session。
3. 本服务常量 `MAX_FOLDER_RETRIEVAL_FILES=1000`，计数所有返回的成功候选（在权限及标签过滤前）。恰好 1000 继续查询探测；发现第 1001 个即抛新增 `McpFolderRetrievalScopeLimitError`（18007）；不调用检索、不返回候选数/列表。
4. 不复用面向列表响应的 SCAN_BUDGET/has_more 截断逻辑；循环直到无下一批、明确超限、30 秒外层总超时或取消。重复游标/无进展异常不得陷入循环或返回部分成功。
5. 候选逐个通过 query.visible；无权返回 false 则不加入范围，异常直接传播。只保留去重的有效入口 ID，拒绝项不进入返回、来源或日志。子目录权限不在此另造“祖先一票否决”策略，后代文件依既有最近授权规则检查。
6. 返回 [] 是合法已授权空范围。范围数据仅在调用内持有，不跨账号、租户或调用缓存；不自动补建任何资源。

scan_files 已有带斜杠的 startswith 子树条件，避免目录 ID 前缀误匹配。现有排序键和 SQLModel 查询继续适配 MySQL/DM8；不新增手写 tenant_id WHERE。候选读取/权限变化遵循调用内枚举语义，无跨系统事务承诺。

## D-03：内部限域、空集与严格映射（REQ-003/005/006/008）

### 内部服务接口

给 `FilelibRetrieveService.retrieve` 增加 keyword-only 内部参数 `file_ids_by_knowledge: Mapping[int, Sequence[int]] | None = None`。不将该参数加入 RetrieveReq/REST/MCP 对外 filters。由 factory 将经过目录解析的 `{knowledge_id: file_ids}` 传入。

该映射用于严格目录场景，key 集合必须与请求知识空间集合一致；不接受缺 key、额外空间或非法 ID 的半限域请求。None 继续原调用路径，不新增 strict 选项或改变旧调用的实参；映射存在时逐空间复制标签配置并合入 file_ids，不覆写标签、不修改原请求对象。

- 本功能只有一个空间，列表为空则在参数与空间/目录校验之后直接返回 RetrieveResp(chunks=[],total=0)，不执行 embedding、Milvus/ES 或来源签发。
- 列表非空则转入 aretrieve_chunks，原 tag_file_ids 与 file_ids 的交集逻辑继续使用；交集为空也在共享检索内短路，禁止 truthiness 导致空列表变 None。
- 不把 external_id 传入内部 RetrieveReq；运行时已消费身份。不得设置 preauthorized_file_ids 以跳过空间校验。

### 严格回映射

给 `KnowledgeSpaceChatService.aretrieve_chunks` 及 `_aretrieve_chunks_shared` 增加内部选项 `strict_file_scope: bool = False`，仅在显式内部范围存在时置 true；共享 resolver 的 map_and_authorize_hits 调用在该模式传 `strict_explicit=True`。已有调用省略该选项，保留默认策略。严格模式若丢失预期 file_ids 或进入不支持路径则抛错，不能变成整库检索。

范围 resolver 已支持 strict_explicit，实施无需修改其授权算法或自建 canonical 过滤器。非空目标文件先成为 EntryRef，解析当前 canonical document/version 与 generation，再通过 resolver.build_backend_filter 在召回前限制；命中回映射仅在显式 EntryRef 内选入口，目录内入口无权则丢弃，不回退其他入口。

最终外部结果沿用 RetrieveChunk 及来源服务；可在共享服务范围边界断言返回 kb/entry 属于显式范围，违约时在来源签发前失败，作为防错检查，不能替代召回前限域。保留原结果排序/去重、top_k 和 max_content，不引入自建重排、补齐或索引查询协议。

### 版本与准备状态

候选仅成功文件；resolver 继续验证 active 入口、当前主版本和内容/成员代次。范围解析后某入口失效、缺失 canonical 关系或出现版本竞态，按现有共享检索的失败/最终丢弃语义处理，不拼装历史正文或跳过异常。当前 resolver 对投影就绪的处理保持，不为此工具额外强制所有投影就绪或授予豁免。

## D-04：装配、错误与生命周期（REQ-001/004/007/008/009）

`build_tool_services` 在已有目标用户 query 上装配范围服务。新增闭包 `retrieve_folder_chunks`：先解析完整 file_ids，再在现有 search_factory(request,user) 中构造单空间 RetrieveReq，传内部文件范围并返回共享结果。可在空集时避免打开检索服务，前提是输入和空间/目录校验均已完成；不能绕过公共 schema 校验。

工具纳入普通只读 runtime，外层 anyio.fail_after(30) 覆盖身份至返回；身份读取/业务 session、ContextVar、审计清理沿用 F081。在 common/errcode/knowledge_space.py 新增继承 BaseErrorCode 的 `McpFolderRetrievalScopeLimitError`（18007）；runtime 仅在新工具匹配该错误类时映射为固定的目录范围过大提示，其他错误和旧工具映射不变，不直接回显 exc.message。

仅在既有 180 模块新增范围预算错误，不创建新模块；账号、资源、异常和超时继续使用安全错误映射。范围解析和检索主链路异常不能被 catch 后返回 []。仅来源签发超时使用现有空链接策略。新工具审计走已有双身份日志/SDK 拒绝审计；不记录输入问题、账号、候选、正文、路径和签名。

调用内目录范围以枚举时为准，最终授权照常执行；进行中移动/改权没有跨存储原子性承诺。下一调用重新加载目录和权限，不使用全局范围缓存。

## D-05：文件计划、测试及发布（REQ-008/010）

以下路径均相对项目根目录。仅列允许落点，不要求为已足够的同一行为额外修改测试文件。

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/mcp_server/domain/schemas/content.py` | modify | 新请求与过滤校验 | REQ-001、REQ-005 |
| `src/backend/bisheng/mcp_server/api/endpoints/content_tools.py` | modify | 新工具注册及类型 | REQ-001 |
| `src/backend/bisheng/mcp_server/domain/services/factory.py` | modify | 目标身份下的范围/检索装配 | REQ-004、REQ-008 |
| `src/backend/bisheng/mcp_server/domain/services/tool_runtime.py` | modify | 新工具容量拒绝安全提示 | REQ-007、REQ-009 |
| `src/backend/bisheng/common/errcode/knowledge_space.py` | modify | 18007 范围预算业务错误 | REQ-007 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_mcp_folder_retrieval_service.py` | create | 目录验证、完整枚举、权限与容量 | REQ-002、REQ-003、REQ-004、REQ-007、REQ-009 |
| `src/backend/bisheng/open_endpoints/domain/services/filelib_retrieve_service.py` | modify | 内部范围三态、标签透传、结果守卫和来源复用 | REQ-003、REQ-005、REQ-006、REQ-008 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py` | modify | 内部严格范围选项，复用 resolver | REQ-005、REQ-006、REQ-008 |
| `src/backend/test/knowledge/test_mcp_folder_retrieval_service.py` | create | 领域范围/权限/预算行为 | REQ-002、REQ-003、REQ-004、REQ-007、REQ-009 |
| `src/backend/test/knowledge/test_mcp_knowledge_repository.py` | modify if needed | 真实路径与续扫边界 | REQ-002、REQ-003 |
| `src/backend/test/mcp_server/test_mcp_tools.py` | modify | SDK schema/参数/十一工具覆盖 | REQ-001、REQ-008 |
| `src/backend/test/mcp_server/test_mcp_server.py` | modify | 既有工具集合断言扩展为十一 | REQ-001、REQ-008 |
| `src/backend/test/mcp_server/test_mcp_knowledge_flow.py` | modify | 真实 SDK、范围仓储和装配端到端 | REQ-004、REQ-007、REQ-009 |
| `src/backend/test/open_endpoints/test_filelib_retrieve_service.py` | modify | 内部范围透传/空集/旧默认/来源守卫 | REQ-003、REQ-005、REQ-006、REQ-008 |
| `src/backend/test/knowledge/test_knowledge_space_chat_service_retrieve.py` | modify | strict 选项接入与标签交集 | REQ-005、REQ-006、REQ-008 |
| `src/backend/test/knowledge/test_knowledge_retrieval_scope_resolver.py` | modify if needed | 严格入口拒绝目录外回退 | REQ-005 |
| `docs/api/mcp-usage.md` | modify | 工具总数、新参数、示例、预算和错误 | REQ-010 |
| `features/v2.5.0-sg/083-mcp-folder-retrieval/` | create/update | 规格；确认后 tasks/verification/review 证据 | REQ-001～010 |

现有 query/repository 接口预计无需扩展，复用 scan_files、folder_path、visible。若真实实现发现此假设不成立，新增只读查询须先更新本设计并遵守 Repository 边界，不借机修改旧列表语义。

### 测试策略与证据组

采用 requirements 的 V-PROTOCOL/SCOPE/PERMISSION/RETRIEVAL/FLOW/REGRESSION/DOC。权限、空范围扩大和 strict 回映射风险先写失败用例；领域路径与分页用实际仓储数据，SDK 参数和调用用真实 FastMCP。范围到召回及回映射的边界有独立风险，分别验证；不按每条 AC 复制多层同义测试。

计划最终定向回归涵盖 `test/mcp_server/`、`test/knowledge/test_mcp_knowledge_*.py`、新增目录范围服务测试、共享检索/范围 resolver、Filelib 共享服务及相关 Developer Token/身份用例；实际命令和基线以实施时环境为准。相关目录/文件尚未改动的测试可作为基线，但不能充当新功能行为证据。

受控端到端使用真实 SDK、目标身份装配、SQLite、实际目录扫描和共享服务；FGA/MinIO/Milvus/ES 端口可控，外部权限/搜索后端边界必须明确，不声称真实环境通过。MySQL/DM8 及真实检索存储需后续条件性验证；macOS DM8 不可用时记录 MANUAL_REQUIRED，而非豁免。

### 发布、回退与风险

- 无迁移及配置；实施代码回退即可撤回工具，使用方刷新工具清单，不删除数据。
- 新内部参数默认关闭，旧检索保持不变；真实测试中比较默认 kwargs/响应，不能只依赖代码阅读。
- 1000 成功候选预算控制范围展开规模，代价是大目录明确拒绝；用户若希望提高预算，需重新评估 SQL/权限/索引参数与总时限，不能仅放大常量宣称稳定。
- 最终 Top-K 仍可能因权限、失效或现有召回策略不足而少于 top_k；本次不重写召回补齐算法。
- 完整规格已获确认并完成实施；本地测试、端到端、静态检查及尚未执行的真实设施验证见 verification.md。

## 需求追踪

| Requirement | Acceptance | Design Element | Verification |
|---|---|---|---|
| REQ-001 | AC-01 | D-01、D-04 | V-PROTOCOL |
| REQ-002 | AC-02 | D-02 | V-SCOPE |
| REQ-003 | AC-03、AC-06 | D-02、D-03 | V-SCOPE、V-RETRIEVAL |
| REQ-004 | AC-04 | D-02、D-04 | V-PERMISSION、V-FLOW |
| REQ-005 | AC-05 | D-01、D-03 | V-RETRIEVAL |
| REQ-006 | AC-05、AC-06 | D-03 | V-RETRIEVAL |
| REQ-007 | AC-03、AC-06 | D-02、D-04 | V-SCOPE、V-FLOW |
| REQ-008 | AC-01、AC-07 | D-03、D-04、D-05 | V-REGRESSION |
| REQ-009 | AC-04、AC-06、AC-07 | D-02、D-04 | V-PERMISSION、V-FLOW |
| REQ-010 | AC-07 | D-05 | V-DOC |
