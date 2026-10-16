# MCP 知识空间工具：现状分析与需求确认

- Feature ID: `078-mcp-knowledge-tools`
- Created: `2026-10-16`
- Status: `DISCOVERY_CONFIRMED_IMPLEMENTED_LOCAL`
- 分析基线：分支 `feat/2.5.0-sg-main`，提交 `06bc21e27`；开始分析时工作区干净。
- 需求来源：用户提供的九工具截图，以及本次会话的范围确认；没有独立 PRD。

## 1. 结论

分析基线的 `/mcp` 可承载此次扩展，当时仅注册 `search_knowledge`。九项需求中，检索已有可共享的领域服务；库、目录、文件列表已有相关能力，需要补齐 MCP 契约和严格的文件级权限；正文、来源和上传不能直接照搬旧开放接口。以下现状表保留分析基线，最终实现和验证见 [verification.md](verification.md)。

本次只规划知识空间，覆盖公共、部门、团队、科室、个人空间；文件通过 Base64 传入。保留旧 `search_knowledge`，新增截图中的九个工具，因此最终共十个注册名称。旧检索与新 `retrieve_chunks` 共用检索核心，旧工具原有输入范围不因本次收敛而缩小。

规格整体确认后，已完成九工具的本地实现与验证，调用方式见 [usage.md](usage.md)。未修改运行配置或真实业务数据，未部署或验证生产环境。

## 2. 确认记录

### 用户已确认

| 日期 | 问题 | 回答 |
|---|---|---|
| 2026-10-16 | 现有文件如何交给 MCP | 客户端读取本地文件后，以 Base64 传入 |
| 2026-10-16 | 是否覆盖传统知识库 | 只覆盖知识空间 |
| 2026-10-16 | 大小限制建议 | 用户要求增大；采用文件 50 MiB、文本 10 MiB、请求体 80 MiB |
| 2026-10-16 | 整体规格及实施 | “确认，按调整后的限制开始实施图片中的九个 MCP 工具。” |

延续 F070 已确认的默认开启、MCP 任意来源跨域和 `X-Developer-Token`，不新增必填服务配置。2026-10-16 后续确认取消 MCP 专用非空白名单要求：空白名单不限制路由，非空时必须匹配 `/mcp`；执行及验证记录见 F070 T008～T009。

### 随整体规格确认的行为

- 保留旧工具，新增九个指定名称；不删除或重命名 `search_knowledge`。
- 目录按层分页浏览；文件搜索同时支持文件名和正文关键词，不调用模型生成答案。
- 新建和上传只新增文件，遇到现有去重规则命中时返回冲突，不自动覆盖、替换版本或建目录。
- 按用户要求增大限制：Base64 解码后上限 50 MiB，文本创建上限 10 MiB UTF-8，请求体上限 80 MiB；仍受现有上传大小规则、租户/角色配额和扩展名规则约束。
- 已授权 `/mcp` 的 Token 在绑定用户具备上传权限时可调用两个写工具。这扩大原 MCP 入口的业务能力，已在整体规格确认中接受；本次不另造逐工具 Token 权限配置。
- 原文件链接不能从预览权限推导。发布、分享、水印下载限制继续有效，无法合法签发原件时明确说明原因并提供有权预览入口。

## 3. 当前项目有哪些相关接口

这里区分“对外 Filelib 接口”和“前端知识空间接口”；下表列出的是已注册源码路径，不代表线上已部署可访问。

| 现有入口 | 当前能力 | 与目标的差距 | 证据 |
|---|---|---|---|
| `POST /mcp` | Streamable HTTP、Token 鉴权，当前一个 `search_knowledge` | 增加九工具及统一调度，保持取消和租户隔离 | S01、S02 |
| `GET /api/v2/filelib/?type=3` | 按门户侧栏可见范围列空间，名称筛选、游标分页，不补建个人库 | 缺少可靠的根目录/子目录可写标志及可写筛选；转换时传了空权限映射，不能用其 `permission_ids` 推断上传权 | S03、S04 |
| `GET /api/v2/filelib/file/list` | 库内文件、关键词、状态、页码分页，返回库级 `writeable` | 无目录/排序参数；其共享列表方法有超过 24 小时后更新解析状态的副作用，不宜作为只读 MCP 的直接调用链 | S03、S05 |
| `GET /api/v2/filelib/file/detail` | 按 `file_encoding` 查唯一文件，返回元数据和已解析正文 | 不是按文件 ID；入口只显式检查库级读取；正文读取辅助函数放在 API 层，且不能直接用逻辑入口 ID 读 canonical 正文 | S03 |
| `GET /api/v2/filelib/file/source_url` | 文件 ID → 原件签名链接，检查库级读取和 `view_file`，解析当前内容入口 | 不等价于 `download_file` 与当前水印下载政策；不能当新工具的下载授权入口 | S06 |
| `POST /api/v2/filelib/retrieve` | 多库片段检索和来源，复用权限过滤与检索运行时 | 可共享 `FilelibRetrieveService`；新工具额外限定输入为空间，MCP 不接收 REST 的 `external_id` | S03、S07 |
| `POST /api/v2/filelib/file/{knowledge_id}` | multipart 或 URL 上传，走传统处理入口 | 无目标目录参数，业务用户来自 `default_operator`，不能继承到新 MCP | S03 |
| `POST /api/v2/filelib/file/sync` | Token 同步规则选库/目录、责任人归属、同名清理覆盖，再入队 | 目标与身份语义不同，且会先清旧文件；不得包装为截图中的通用上传 | S08 |
| `GET /api/v1/knowledge/space/{space_id}/children` | 当前目录浏览，游标、排序、状态、文件/目录类型筛选 | 补目录展示路径、上传权限、MCP 安全字段；不复制后台对失效条目的管理展示例外 | S09、S10 |
| `GET /api/v1/knowledge/space/{space_id}/search` | 库/目录子树关键词搜索、状态和排序，当前含文件与目录 | 需要只返回文件、先过滤后分页；分页后删目录会导致页大小和总数失真 | S09、S10 |
| `GET /api/v1/knowledge/space/global-search` | 可见空间中的成功文件名搜索、路径 | 不是统一正文搜索；方法内未调用逐文件可见性过滤，不能作为 MCP 最终权限结果直接返回 | S10 |
| `POST /api/v1/knowledge/upload` + `POST /api/v1/knowledge/space/{space_id}/files` | 暂存后调用 `KnowledgeSpaceService.add_file`，目标目录、细粒度上传权、配额、元组、版本和解析入队 | Base64/文本需在服务端安全暂存并转换，不能让 MCP 参数直接指定任意服务端路径 | S09、S10、S11 |
| `GET .../{space_id}/files/{file_id}/preview` / `download` | 预览走知识领域服务；当前下载路由走 PDF 准备/水印流程 | 新来源工具必须区分预览和原件，不能跳过下载策略 | S09、S13 |
| `GET /api/v1/knowledge/shougang-portal/files/{space_id}/{file_id}/chunks` | canonical 当前版本/内容代次和空间范围内读取正文分块 | 查询原则可复用；门户发现/专家问答上下文不能自动带入 MCP 的一般资源授权 | S10、S12 |

## 4. 九个目标工具的复用判断

| 工具 | 实现策略 | 核心新增工作 | 批次 |
|---|---|---|---|
| `list_knowledge` | 复用已有可见空间集合，复用细粒度权限计算原则 | 可写筛选、根/子目录上传能力、权限后分页 | A |
| `list_folders` | 复用当前目录查询与 folder 权限 | 逐层分页、路径、目录上传权；跨空间目录拒绝 | A |
| `list_files` | 复用知识空间当前目录查询 | 仅文件、排序/状态、游标、活动入口和版本过滤 | A |
| `search_files` | 复用知识空间搜索及共享正文查询能力 | 指定空间/子树范围、文件名/正文模式、权限后分页和字段裁剪 | B |
| `get_file_detail` | 抽取知识领域正文读取能力，复用入口解析 | 按入口 ID 授权、canonical 当前内容、分段读取、明确解析状态 | B |
| `get_file_source` | 复用知识领域预览和下载授权 | 区分 `preview` / `original`，遵守入口与水印策略 | B |
| `retrieve_chunks` | 共享 `FilelibRetrieveService` | 新名称、仅空间参数检查；旧 `search_knowledge` 保持兼容 | B |
| `create_document` | UTF-8 文本/Markdown → 暂存 → 知识领域写入 | 文件名/大小校验、目标上传权、冲突、异步状态 | C |
| `upload_file` | Base64 → 校验/暂存 → 同一写入服务 | 编码与大小限制、文件格式、配额、清理和入队失败处理 | C |

F066 的 `list_file_sync_target_spaces/folders` 已有批量细粒度上传权限判定，可以复用其原则和底层能力；但候选空间用于同步场景，不能原样替代覆盖团队、科室和个人的 MCP 空间发现。

## 5. 必须保持的边界

1. 所有新工具只接收资源参数，不接收身份切换字段。身份来自 Token，实际工具任务中建立租户上下文。
2. 可见空间不等于可读文件，门户发现开关不授予正文/下载权限；无权 ID、文件名、摘要、路径和原件地址不得泄漏。
3. 细粒度上传权限是业务权限 ID `upload_file_to_space` / `upload_file_to_folder`，不是 OpenFGA 的关系名；目录采用最近一级授权规则。
4. 只读列表不修正解析状态、不创建个人库、不清理旧文件；新 MCP 查询使用无这些副作用的领域/仓储入口。
5. 内容按调用者入口授权，再解析当前 canonical 文件、版本及 generation；不能删除空间范围来“解决”查询不到内容。
6. 权限、版本、投影、对象存储和任务的 Owner 不变。MCP 不直接写数据库、OpenFGA、ES 或 Milvus。
7. 本次不自动修复、重构或改变旧 Filelib 的身份、覆盖、来源链接和响应行为。

## 6. 代码证据索引

行号对应分析基线，实施时应重新核对。

| 证据 | 文件与位置 | 已读取的关键实现 |
|---|---|---|
| S01 | [MCP router](../../../src/backend/bisheng/mcp_server/api/router.py)，第 45～121 行 | 生命周期、每请求鉴权、SDK 任务组与断开取消 |
| S02 | [tools.py](../../../src/backend/bisheng/mcp_server/api/endpoints/tools.py)，第 20 行起 | 仅注册 `search_knowledge`、严格参数及审计 |
| S03 | [filelib.py](../../../src/backend/bisheng/open_endpoints/api/endpoints/filelib.py)，第 331、384、460、486、543、744 行 | Filelib 查询、详情、上传、来源、检索 |
| S04 | [filelib_knowledge_list_service.py](../../../src/backend/bisheng/open_endpoints/domain/services/filelib_knowledge_list_service.py)，第 15 行起 | 可见空间与游标，空 permission_map |
| S05 | [knowledge_service.py](../../../src/backend/bisheng/knowledge/domain/services/knowledge_service.py)，第 1840～1936 行 | 文件列表库级权限及超时状态写入 |
| S06 | [filelib_file_source_service.py](../../../src/backend/bisheng/open_endpoints/domain/services/filelib_file_source_service.py)，第 60 行起 | `view_file` 与原件链接签发 |
| S07 | [MCP search_service.py](../../../src/backend/bisheng/mcp_server/domain/services/search_service.py)，第 15 行起；[FilelibRetrieveService](../../../src/backend/bisheng/open_endpoints/domain/services/filelib_retrieve_service.py) | 共享检索、绑定身份与超时 |
| S08 | [filelib_sync_service.py](../../../src/backend/bisheng/open_endpoints/domain/services/filelib_sync_service.py)，第 142～283 行 | 规则选库、身份切换、同名清理、add_file 参数 |
| S09 | [knowledge_space.py](../../../src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py)，第 546、636、647、828、954、964 行 | 空间文件查询、添加和预览/下载路由 |
| S10 | [knowledge_space_service.py](../../../src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py)，第 1435、1540、8160、13224、13466、15549、15711、15966、17234 行 | 上传权、正文、空间范围、文件可见性、目录查询、写入 |
| S11 | [upload_extensions.py](../../../src/backend/bisheng/knowledge/domain/upload_extensions.py)；[knowledge_service.py](../../../src/backend/bisheng/knowledge/domain/services/knowledge_service.py)，第 1468、1644 行 | 扩展名、异步入队、同名/同内容冲突 |
| S12 | [shared_space_file_queries.py](../../../src/backend/bisheng/knowledge/domain/services/shared_space_file_queries.py)；[knowledge_document_entry_resolver.py](../../../src/backend/bisheng/knowledge/domain/services/knowledge_document_entry_resolver.py)，第 101 行起 | 共享正文范围、代次与入口能力 |
| S13 | [portal_pdf_download_service.py](../../../src/backend/bisheng/knowledge/domain/services/portal_pdf_download_service.py)，第 222 行起 | 当前下载授权、配额及水印准备 |
| S14 | [knowledge_fulltext_search_service.py](../../../src/backend/bisheng/knowledge/domain/services/knowledge_fulltext_search_service.py)；[查询端口](../../../src/backend/bisheng/knowledge/domain/repositories/interfaces/knowledge_fulltext_search_repository.py) | 已有 PIT/search_after 和查询会话生命周期，作为有界候选分页参考 |

## 7. 交付和后续门禁

完整工具契约见 [spec.md](spec.md)，可验证需求见 [requirements.md](requirements.md)，实现设计见 [design.md](design.md)，任务及完成状态见 [tasks.md](tasks.md)。

项目规格评审和用户整体确认点已通过，随后拆解任务、连续实施和验证。真实环境验收边界仍以 verification 为准，本次不自动提交或部署。
