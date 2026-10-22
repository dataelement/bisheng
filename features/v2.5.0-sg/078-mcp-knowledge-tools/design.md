# MCP 知识空间工具：实现设计与分批计划

> 2026-10-22 身份契约更新：[F081](../081-mcp-external-user-identity/spec.md) 已获用户确认。十工具顶层必填 `external_id`，以目标用户及其当前有效租户执行；Token 保留接入、绑定有效性、IP/路由/限流校验。本文首期的绑定用户、禁止身份参数或原样兼容描述如与 F081 冲突，以 F081 为准；历史验证记录不代表新身份契约验收。


- Feature ID: `078-mcp-knowledge-tools`
- Status: `IMPLEMENTED_LOCAL`
- Created: `2026-10-16`
- Related requirements: [requirements.md](requirements.md)

## 1. 设计结论

2026-10-16 缺陷修复：`get_file_source` 在现有 MCP 空间/文件/入口权限校验后，调用已装配的知识 Owner `get_file_preview(entry_file_id)`，不再自行预测对象路径。优先采用其 PDF、HTML、普通预览；只有原生可预览的文本、PDF、图片可使用 Owner 返回的原生文件地址作为 `preview_url`。Office 缺少预览时不回退原件。仅输出现有来源 DTO 字段，`original_url` 保持为空，显式 original 仍拒绝。Owner 的相对签名 URL 补回现有对象存储分享域名，绝对地址及签名保持原样。复用已生成的产物，不新增生成/上传/转换流程。

落点为 `knowledge_mcp_content_service.py`、其领域回归和受控 Owner 的 SDK 流程替身。备选的逐格式补拼对象路径会继续复制预览分支，因此不采用。回退可还原本次局部提交，无数据迁移。

继续扩展已有 `mcp_server`。MCP 层负责 schema、协议、目标身份、超时和安全结果；知识模块负责查询、内容和写入；现有共享检索服务负责 RAG。服务之间直接调用领域接口，不在后端通过 HTTP 回调自身 REST，也不让 MCP endpoint 导入其他模块 endpoint。

```mermaid
flowchart TD
    A[外部 MCP 客户端] --> B[/mcp Token 与统一路由鉴权]
    B --> C[实际工具任务：目标用户与当前租户]
    C --> D[浏览与文件搜索]
    C --> E[正文与来源]
    C --> F[文本或 Base64 上传]
    C --> G[共享 FilelibRetrieveService]
    D --> H[知识领域服务与 Repository]
    E --> H
    F --> H
    H --> I[既有权限和入口解析]
    H --> J[DB / MinIO / ES]
    F --> K[既有版本、授权与解析投递]
```

## 2. 边界承诺

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| MCP | 注册九工具、统一执行上下文、实际请求体上限、严格 schema | 改默认开关/跨域、允许匿名、绕过 F081 指定账号规则、删除旧工具 | 协议、SDK、生命周期或鉴权改动 |
| knowledge | 新增范围明确的领域服务；为其补必要 Repository 方法 | 在新 Service 写 ORM/SQL、新 DAO 入口、改变既有下载/覆盖政策 | 文件权限、canonical、上传或派生存储改动 |
| open_endpoints | 调用已有 `FilelibRetrieveService` 等领域能力 | 跨模块 API 导入、自身 HTTP 调用、改变原 Filelib 契约 | 共享服务变更时复跑受影响 REST 回归 |
| permission / tenant | 使用统一权限服务和已有细粒度权限；上下文自动注入 | 将业务 permission ID 当 FGA relation、手写 ORM tenant 条件、扩大发现权限 | 授权或数据范围变化需重新确认 |
| schema / runtime | 复用现有表、会话及基础设施 | 新迁移、新依赖、必填服务配置、生产数据处理 | 出现此类需求先更新规格并确认 |

Allowed dependencies: 现有依赖；不新增第三方包。

## 3. 组件设计

### 3.1 协议与执行上下文

将 `tools.py` 的注册按浏览、内容、写入三组拆分，保留原检索注册。所有新工具使用一致的 principal 获取、`McpAuthService.use_identity`、安全异常与审计。实际服务通过 factory 在身份作用域内创建，持有请求专属 session，不能在 FastMCP 静态实例上共享可变 `KnowledgeSpaceService`。

继续继承每请求 SDK task group 的取消行为。增加鉴权后、SDK JSON 解析前的接收体积上限，覆盖分块或无长度头请求。超限终止接收并返回 413，不把完整大字符串交给模型参数校验后才限制。

请求体上限为 80 MiB，对应 50 MiB 文件约 66.7 MiB 的 Base64，以及 10 MiB 文本可能产生的 JSON 字符转义膨胀。SDK 仍需解析完整 JSON，不能宣称仅通过分块落盘即可实现全链路流式上传；实施时应验证上限附近的请求、解码和并发资源释放，避免同时保留不必要的完整字节副本。线上代理是否允许该体积属于部署验收，本次不修改代理配置。

### 3.2 空间、目录、文件与搜索

2026-10-22 目录 ID 兼容：在 browse schema 新增独立 `FolderId`，以严格正整数或受格式约束的数字字符串作为输入，验证后归一化为 int。列表、嵌套搜索范围及写工具的请求模型和注册签名统一使用该别名；不修改通用 `ResourceId`，避免放宽空间/文件/标签 ID。响应仍为整数；不把空字符串视为根目录。实现落点为 browse/ingestion schema、query/write 工具及 SDK 回归，回退局部代码即可，无数据或配置变更。

知识模块增加 `KnowledgeMcpQueryService`，复用现有可见空间与权限能力。新增 `KnowledgeMcpRepository` 接口和实现，继承项目 BaseRepository，将查询封装在知识模块内。空间查询不调用会补建默认个人库的入口。

`writable_only` 需要完整的可写候选过滤，再分页；不能只对当前页算上传权。参考 F066 的批量 `PermissionReadContext`、并发上限与最近一级目录绑定规则，但不继承同步场景候选类型限制。可写子目录必须在当前用户可访问范围内；仅有上传权但无法定位的隐藏目录不能造成路径泄漏。

`list_folders/list_files` 使用独立文件类型查询、当前版本与活动入口约束、目录归属验证，再做有界权限扫描填充页面。不能沿用后台对 invalid 入口直接展示的例外，也不能对一页混合结果删掉目录后假称一页完整。

`search_files` 的 name/content/all 使用仓储的有界、稳定排序候选，在权限检查后执行名称匹配和范围限定正文命中；始终保留目标空间、目录子树、canonical generation 约束。按入口合并名称/正文命中，生成稳定游标。不新建全文索引或重算历史投影；正文搜索下游不可用时 content/all 明确失败，不静默降级成不完整结果。

现有 `search_shared_space_file_ids` 的聚合最多返回 10000 个文档，不能当作完整分页数据源。实现采用数据库稳定键续读，每批最多 100 个候选；正文只对已授权候选作严格 canonical 范围的 ES filters 聚合，不使用 PIT 或全量 ID 桶。每请求扫描最多 1000 个文件候选，权限/目录过滤后继续补页；预算耗尽时返回可继续游标，不伪称已经穷尽。ES 命中仅为派生查询结果，不成为权限事实源。

所有分页游标绑定完整查询上下文。不要依赖既有 children 游标只含排序的上下文直接满足新契约。查询服务返回轻量 DTO，不把完整 ORM 模型或门户富化字段直接给 MCP。

### 3.3 正文与来源

增加 `KnowledgeMcpContentService`，先通过统一权限能力检查空间/入口，再用 `KnowledgeDocumentEntryResolver` 解析物理内容和当前版本。必要时将现有正文读取中的纯领域能力提取到该服务；不导入 Filelib API 私有函数。

优先使用当前物理文件已解析的文本对象，缺失时读取 scoped ES chunk。查询包含 canonical document/version/generation 与请求空间；参考现有门户 chunks 方法的过滤原则，不复用其发现范围和专家问答身份旁路。正文续页绑定内容身份，变化时拒绝旧游标。

来源工具复用有权预览能力。原件需额外验证 download_file、分发入口限制及 Owner 的来源策略；当前下载路由提供水印 PDF 时，不能把旧 `source_url` 当作允许绕过的依据。本次不新增水印下载文件托管/票据 endpoint；只能合法提供预览时明确返回该结果。原工具和 REST 既有来源字段不在本次顺手调整。

### 3.4 文本创建与 Base64 写入

增加 `KnowledgeMcpIngestionService`：目标与上传权预校验 → 输入字节/文件名/扩展名/配额校验 → 受控暂存 → 调用知识 Owner 的 add_file/授权/版本/dispatch 链路 → 返回真实受理状态。

上传权限、分类、业务域、标签和租户配额沿用 Owner；不使用 `default_operator`，不使用带替换/责任人代理/个人库兜底的 `FilelibSyncService.sync`。目标不存在时拒绝，不转存到其他空间。不传 `skip_approval`、跳过业务域校验或放开重复的参数来绕过 Owner。

暂存命名由服务端生成，展示文件名保留映射；只允许服务本次创建的对象/路径传给 add_file。Base64 在编码长度预检查后严格解码，解码后再次检查真实大小。采用异步存储或既有线程执行边界，避免大解码/同步文件操作阻塞事件循环。

字节上限采用文件 50 MiB、文本 10 MiB UTF-8，并在调用 Owner 前继续执行现有文件大小校验。现有 `upload_file_size.py` 的普通文档源码默认值为 50 MiB，但 DB 的 `env.uploaded_files_maximum_size` 可以覆盖它；该默认值不代表当前运行环境的实际设置。MCP 不提高原设置或配额。

重复检测仍以 Owner 当前库内规则为准；并发冲突不得覆盖旧内容。新适配必须识别旧处理函数的“返回失败状态的已有文件对象”分支，不能只判断有 ID 就写 accepted=true。清理只通过 Owner 方法，不直接删除数据库/权限数据。

取消按阶段处理：未创建资源可直接清理；已创建未投递通过 Owner 补偿；已确认投递不删除；投递结果不明保留可定位审计并要求查询确认，不自动重放。实现前须用失败注入验证 Owner 实际阶段边界，不能假设连接取消等于业务回滚。

## 4. 文件结构计划

所有代码路径相对 `src/backend/`；以下均为计划，当前未创建生产文件。

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `bisheng/mcp_server/api/endpoints/tools.py` | modify | 集中注册，保留旧检索并注册新名称 | REQ-001、REQ-008 |
| `bisheng/mcp_server/api/endpoints/{query_tools,content_tools,write_tools}.py` | create | 显式工具签名、注解与 DTO 转换 | REQ-002～010 |
| `bisheng/mcp_server/domain/schemas/{browse,content,ingestion}.py` | create | 严格参数、输出白名单、上限与游标契约 | REQ-002～012 |
| `bisheng/mcp_server/domain/services/{factory,search_service}.py` | modify | 身份内装配、检索复用及新工具适配 | REQ-001、REQ-008、REQ-012 |
| `bisheng/mcp_server/domain/services/tool_runtime.py` | create | 所有新工具的身份、安全结果、审计和资源边界 | REQ-001、REQ-011、REQ-012 |
| `bisheng/mcp_server/api/router.py` | modify | 注入新装配与实际请求体限制，保持原协议策略 | REQ-010、REQ-012 |
| `bisheng/knowledge/domain/services/knowledge_mcp_query_service.py` | create | 权限后空间/目录/文件查询、搜索与游标 | REQ-002～005 |
| `bisheng/knowledge/domain/services/knowledge_mcp_content_service.py` | create | 入口授权、canonical 正文、有权来源 | REQ-006、REQ-007 |
| `bisheng/knowledge/domain/services/knowledge_mcp_ingestion_service.py` | create | 暂存、Owner 写入和阶段失败处理 | REQ-009～011 |
| `bisheng/knowledge/domain/repositories/{interfaces,implementations}/knowledge*_repository*.py` | modify as needed | 新查询封装、候选分页和当前入口过滤；具体方法在 tasks 中限定 | REQ-002～007、REQ-011 |
| `bisheng/knowledge/domain/services/knowledge_space_service.py` | minimal modify if needed | 仅提取已有权限/查询的可复用领域入口，禁止无关整理大文件 | REQ-002～007、REQ-011 |
| `test/mcp_server/{test_mcp_server,test_main_integration}.py` | modify | 十名称、schema、真实 SDK、鉴权、体积、隔离及断连 | REQ-001、REQ-008、REQ-010、REQ-012 |
| `test/knowledge/test_mcp_knowledge_{query,content,ingestion}_service.py` | create | 三个领域批次的可执行行为证据 | REQ-002～011 |
| 本特性 `usage.md`、`verification.md` | create during implementation | 工具调用流程和实际验证边界 | REQ-001～012 |

不计划修改前端、配置、依赖锁、迁移或现有 Token 模型。若任务拆分发现必须改变这些边界，先更新规格重新确认。

## 5. 分批实施顺序

用户已确认该实施计划；具体执行与状态以 `tasks.md` 为准。

| 批次 | 交付行为 | 依赖 | 可观察完成条件 | 需求 |
|---|---|---|---|---|
| A | 共用工具运行边界 + list_knowledge / list_folders / list_files | 规格确认与任务评审 | SDK 可发现目标并逐层浏览，细粒度可写状态正确，拒绝路径不泄漏 | REQ-001～004、REQ-012 |
| B | search_files / get_file_detail / get_file_source / retrieve_chunks | A 的身份、DTO 和权限边界 | 找文件、分段读当前正文、取有权来源、新旧检索共存 | REQ-005～008 |
| C | create_document / upload_file | A 的目标权限，B 的详情查询 | 文本和 Base64 文件成功写到指定目录，能查询解析状态，冲突/配额/断连失败结果真实 | REQ-009～011 |
| D | 相关回归、实际 SDK 端到端、接入说明和发布前验收记录 | A～C | 十名称齐全，两条用户流程有证据，原 REST/Token/CORS 不回归 | REQ-001～012 |

典型流程：列空间 → 列目录 → 浏览/搜索 → 读详情/片段/来源；生成 Markdown 或读取本地文件 → 写入 → 查询状态 → 检索确认。

## 6. 测试与证据策略

| 验收 | 风险 / 层级 | 主要层 | 证据组 | 完成条件 |
|---|---|---|---|---|
| AC-03～06 | 权限后分页与范围 / V3 | 领域服务 + 必要仓储集成 | V-BROWSE、V-SEARCH | 读/写能力独立、目录越界、版本/状态、空结果和页边界有证据 |
| AC-07～09 | 正文与签名来源 / V3 | 内容服务 | V-CONTENT | 逻辑入口、受限原件、长正文、版本变化、拒绝不签发有证据 |
| AC-11～15 | 字节、权限、配额、并发和跨存储副作用 / V3 | 入库服务集成与失败注入 | V-WRITE | 50 MiB 文件/10 MiB 文本的合法边界和超限、旧文件未覆盖、不同副作用阶段恢复有证据 |
| AC-01、02、10、13、16、17 | SDK schema、HTTP 流与任务隔离 / V3 | 真实 SDK 经 HTTP/必要 TCP 边界 | V-PROTOCOL | 十名称、未知字段、80 MiB 实际请求体边界、文本 JSON 转义、并发租户、真实断连、脱敏成立 |
| AC-18 | 共享服务与原系统兼容 / V2～V3 | 当前受影响回归集 | V-REGRESSION | Filelib、Token、检索、上传投递、细粒度权限与 CORS 相关测试通过 |

本地只为独立行为选择一个主要层；协议和业务间有独立风险时增加边界测试。批次完成验证一次，同一代码状态的有效证据复用，不机械重复全套。

实际基础设施验收单独记录：真实 Token + OpenFGA 权限（公共/部门/团队/科室/个人）、MinIO 上传及链接、ES/Milvus 检索、Worker 排队到成功、代理请求体限制、MySQL 和 Linux/CI DM8。尚无环境证据时均为 `MANUAL_REQUIRED`，不能用本地替身标成通过。

## 7. 数据归属、风险及回退

不新增数据模型。Knowledge/KnowledgeFile/KnowledgeDocument/Version、元组、MinIO 对象和解析任务仍由原 Owner 创建/维护，租户自动注入。调用现有 Owner 不意味着复制其 API 层默认身份或业务同步例外。

新建文件与原 MCP 读能力的差别是实际业务写入：已有 `/mcp` Token 会得到其绑定用户现有权限范围内的写入入口；规格确认后才实施。回退代码移除新工具，已创建文件保留；需要清理时是单独业务操作，不随代码回退删除。

其他重点风险：Base64 的 JSON/内存放大、目录细粒度授权、活动入口与物理正文错配、原件绕过水印、断连后写入结果不确定。通过明确上限、Owner 授权、canonical 范围和阶段失败验证控制；不新增全局安全策略。

## 8. 需求设计追溯

| Requirement | Acceptance | Design Element | Verification |
|---|---|---|---|
| REQ-001 | AC-01、AC-02 | §3.1 协议/身份，显式工具注册 | V-PROTOCOL |
| REQ-002 | AC-03 | §3.2 可见空间与可写候选 | V-BROWSE |
| REQ-003 | AC-04 | §3.2 目录归属与细粒度上传权 | V-BROWSE |
| REQ-004 | AC-05 | §3.2 只读列表与权限后游标 | V-BROWSE |
| REQ-005 | AC-06 | §3.2 有界候选搜索、子树与入口过滤 | V-SEARCH |
| REQ-006 | AC-07、AC-08 | §3.3 canonical 正文与代次续页 | V-CONTENT |
| REQ-007 | AC-09 | §3.3 预览/下载/水印策略 | V-CONTENT |
| REQ-008 | AC-02、AC-10 | §3.1 保留旧工具、复用现有检索 | V-PROTOCOL |
| REQ-009 | AC-11 | §3.4 UTF-8 新文档与 Owner 写入 | V-WRITE |
| REQ-010 | AC-12、AC-13 | §3.1 请求体上限，§3.4 Base64/暂存 | V-WRITE、V-PROTOCOL |
| REQ-011 | AC-14、AC-15 | §3.4 权限/配额/冲突及阶段恢复 | V-WRITE |
| REQ-012 | AC-16、AC-17、AC-18 | §2 边界，§3.1 身份/脱敏，§6 回归 | V-PROTOCOL、V-REGRESSION |
