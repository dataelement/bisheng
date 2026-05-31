# Feature: F026-knowledge-qa-permission-filter（知识空间 AI 问答 - 检索权限过滤）

**关联 PRD**: [../../../docs/PRD/知识空间优化/知识空间AI问答-权限过滤.md](../../../docs/PRD/%E7%9F%A5%E8%AF%86%E7%A9%BA%E9%97%B4%E4%BC%98%E5%8C%96/%E7%9F%A5%E8%AF%86%E7%A9%BA%E9%97%B4AI%E9%97%AE%E7%AD%94-%E6%9D%83%E9%99%90%E8%BF%87%E6%BB%A4.md)
**优先级**: P0（知识空间 AI 问答存在越权读取风险，必须在 v2.6.0 关闭）
**所属版本**: v2.6.0
**模块编码**: 沿用 180（`knowledge_space`，现有 `common/errcode/knowledge_space.py`），本 spec 复用 `SpacePermissionDeniedError`（18040）作为权限缺失返回，不新增错误码
**依赖**: 现有 ReBAC（`PermissionService.list_accessible_ids` + 10s Redis 缓存 + `invalidate_user`）；现有 Fine-grained 权限解析（`FineGrainedPermissionService.get_effective_permission_ids_async` + `_build_child_permission_context`）；现有知识空间列表过滤路径（`_filter_visible_child_items`）

> **范围边界**
> - **本次纳入**：知识空间 AI 助手的 4 个问答入口（整空间 / 文件夹 / 文件预览 / 首页 & 工作台多 KB 检索）+ 新版角标溯源接口（`POST /api/v1/citations/resolve` 批量、`GET /api/v1/citations/{citation_id}` 单条）。
> - **本次明确排除**：
>   - **工作流 KNOWLEDGE_RETRIEVER 节点**（`workflow/nodes/knowledge_retriever/`）—— 当前不在 PRD 范围，且涉及流程节点执行上下文中的"运行用户身份"问题，留待后续 feature。
>   - **对外 RPC `/api/v2/filelib/retrieve`** —— 当前以"默认 operator"身份运行而非真实终端用户，需要先定义"代用户检索"协议（如 `on_behalf_of_user_id` 字段或新的鉴权方式），不在本 spec 范围。
>   - **OpenFGA 模型变更** —— 不引入新的 `view_file` ReBAC 关系，复用现有 `can_read` 与 `view_file` permission_id。
>   - **chunk 元数据 ACL 索引化（"超大规模"方案）** —— 单空间单用户可见文件 > 10 万时所需的索引层 ACL 字段方案不在本期，本期通过"双层过滤 + 检索次数封顶"在 10 万规模内提供可接受性能。

---

## 1. 概述与用户故事

**故事 A（普通用户 · 整空间 / 文件夹问答）**：
作为 **能进入某个知识空间但只对其中部分文件、文件夹拥有 `view_file` / `view_folder` 权限的用户**，
我希望 **在空间或文件夹页面发起 AI 问答时，检索结果只来自我有权查看的文件，回答引用的文件名、来源、预览链接也不会暴露无权文件**，
以便 **不会通过 AI 问答间接读到管理员不允许我看的内容**。

**故事 B（普通用户 · 文件预览页问答）**：
作为 **正在浏览某个文件预览页的用户**，
我希望 **只能对该文件本身发起问答**，
以便 **对未授权文件的入口在 URL 层就被阻断**（即便我直接构造 URL，也会被拒绝）。

**故事 C（普通用户 · 首页 / 工作台问答）**：
作为 **在首页或工作台选择多个知识空间发起问答的用户**，
我希望 **下拉框只列出我有 `view_space` 的空间；选中的多个空间会分别按可见文件集合过滤；某个空间没有任何可见文件时静默跳过该空间但不打断对话**，
以便 **在多 KB 场景下，仍然能利用我有权限的部分得到回答**。

**故事 D（普通用户 · 角标溯源）**：
作为 **重新打开历史会话查看回答 citation 详情的用户**，
我希望 **如果我现在已经对某些被引用文件失去 `view_file` 权限，那些 citation 不再出现在引用面板里（通过 `/api/v1/citations/resolve` 接口剔除）**，
以便 **历史会话不构成新的越权读取路径**。

**故事 E（研发）**：
作为 **后端研发**，
我希望 **检索过滤逻辑严格对齐"列表 UI 可见性"语义（`view_file` ∈ effective permissions），并在性能上提供索引层粗过滤 + 结果层精过滤的双重保险**，
以便 **不会出现"列表看不到却能通过问答检索到"的越权访问**，同时单次问答的权限解析开销可控、可观测。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> 所有"权限缺失"返回均使用现有错误码 `SpacePermissionDeniedError`（18040），不新增。

### 2.1 整空间问答（`POST /api/v1/knowledge/space/{space_id}/chat/folder`，`folder_id=0`）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 对空间无 `view_space` 的用户 | 调用整空间问答接口 | 返回 `SpacePermissionDeniedError`（18040）；不进入检索；不写 `RecallChunk`；不消耗 LLM 配额 |
| AC-02 | 有 `view_space` 且对部分文件有 `view_file` 的用户 | 同上 | 检索仅命中"用户对其有 `view_file` 的、解析成功的主版本文件"；非主版本文件、解析中/失败文件、无 `view_file` 文件均不进入 LLM 上下文；回答引用 `source_documents` 中的 `file_id` 必须是用户当前 `view_file` 子集 |
| AC-03 | 有 `view_space` 但空间内对该用户**没有**任何 `view_file` 文件 | 同上 | 检索返回空文档集；模型按现有 prompt 设定回答（无文档时由 prompt 决定提示语，例如"未找到相关内容"）；不报错、不抛 403；HTTP 200 |
| AC-04 | 同上调用，本轮问完后管理员**收回**用户对其中某些文件的 `view_file` | 用户立即追问 | 第二轮检索使用最新权限（缓存 TTL ≤ 10s 或 `invalidate_user` 已触发）；被收回的文件不再进入上下文 |

### 2.2 文件夹问答（`POST /api/v1/knowledge/space/{space_id}/chat/folder`，`folder_id>0`）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-05 | 对目标文件夹无 `view_folder` 的用户 | 调用文件夹问答接口 | 返回 `SpacePermissionDeniedError`（18040）；不进入检索 |
| AC-06 | 有 `view_folder` 的用户 | 同上 | 检索范围 = 文件夹子树下用户有 `view_file` 的解析成功主版本文件；子文件夹中无 `view_folder` 的分支被剔除；其下文件即便有"直接对文件授予的 `view_file`"也不进入检索（与列表 UI 对齐：列表中这些文件也因祖先文件夹被隐藏而不可见） |
| AC-07 | 有 `view_folder` 且同时传入 `tags` 过滤的用户 | 同上 | 检索范围 = （文件夹子树可见文件集）∩（带这些 tag 的文件集），交集为空时按 AC-03 行为（空检索 + prompt 提示） |

### 2.3 文件预览页问答（`POST /api/v1/knowledge/space/{space_id}/chat/file/{file_id}`）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-08 | 对该文件无 `view_file` 的用户 | 调用单文件问答接口（URL 直构造） | 返回 `SpacePermissionDeniedError`（18040）；不进入检索 |
| AC-09 | 有 `view_file` 的用户 | 同上 | 检索范围限定 `document_id == file_id`；非主版本会被自动排除（沿用现有 `version_filter` 行为）；行为与原有逻辑等价 |

### 2.4 首页 / 工作台问答（工作台 `search_kb` 工具 → `WorkStationService.queryChunksFromDB`）

> 工作台问答经过 `workstation/domain/services/chat_service.py:_search` 调入 `WorkStationService.queryChunksFromDB`，对每个 KB 调用 `MultiRetriever` + `KnowledgeRetrieverTool`。当前实现以 `kb_id_whitelist`（前端 KB 选择器提供的白名单）+ `check_auth=False` 跳过任何 per-KB 鉴权，是本期重点改造的入口。本期仅覆盖 PRD 所述"知识空间"（`space_bucket`），不修改"组织知识库"（`org_bucket`）路径。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-10 | 用户 | 拉取知识空间下拉列表（前端 KB 选择器数据源：`GET /api/v1/knowledge/space/mine` 我创建的、`/managed` 我管理的、`/joined` 我加入的、`/department` 部门空间） | 上述 4 个端点的服务层（`KnowledgeSpaceService.get_my_*_spaces` / `DepartmentKnowledgeSpaceService.get_user_department_spaces`）当前已经按 `PermissionService.list_accessible_ids(can_read, knowledge_space)` + space membership 过滤；本特性**不修改这 4 个端点的行为**，仅在 E2E 阶段对"无 view_space 的空间不出现在下拉框"做回归验证（覆盖 PRD §场景规则·首页/工作台问答行的"对知识空间没有 view_space 权限，不可见该知识空间"） |
| AC-11 | 用户 | 提交多 KB 检索请求，其中某个 KB 用户**无** `view_space`（构造请求绕过下拉框） | 该 KB 静默跳过、不进入检索；不抛 `SpacePermissionDeniedError`、不阻塞其他 KB；该 KB 不出现在响应的 `kb_succeed` 列表中；INFO 日志记录 `skipped_kb_id=X reason=no_view_space` |
| AC-12 | 用户 | 同上，KB 用户有 `view_space` 但其内对该用户**没有**任何 `view_file` 文件 | 该 KB 经过 Stage 2（索引层 IN/NOT-IN 过滤）或 Stage 3（结果层 `view_file` 精滤）自然产生 0 docs（无显式预检测）；不抛 `SpacePermissionDeniedError`、不阻塞其他 KB；不进入 `kb_succeed` 列表；日志按 AC-27 输出 `accessible_ids_size`、`prefilter_candidate_size`、`post_filter_dropped_count`，以便事后区分"该空间下用户无可见文件" vs "用户有可见文件但与 query 不相关" |
| AC-13 | 用户 | 同上，KB 内有部分可见文件 | 每个 KB 走双层过滤路径，仅返回用户有 `view_file` 的 chunk；跨 KB 结果合并截断行为不变 |
| AC-14 | 用户 | 工作台同时选择"组织知识库"（`org_bucket`，legacy `knowledge_library` 类型）| 本期不修改 `org_bucket` 路径行为；记录在 `release-contract.md` 变更历史中说明该差异 |

### 2.5 历史引用 / 角标溯源（`POST /api/v1/citations/resolve`、`GET /api/v1/citations/{citation_id}`）

> 当前新版引用 UI 通过 `citations/resolve` 接口拿源信息（旧的 `/qa/chunk` / `/qa/keyword` 接口本期不动，待后续合适时机下线，故不纳入 AC）。`CitationResolveService` 当前实现有两处缺陷：① `_has_file_access` 通过 `RoleAccessDao` + `AccessType.KNOWLEDGE` 做**空间级**判定，是 arch-guard RULE-8 VIOLATION；② 无权时仅不填 `downloadUrl`/`previewUrl`/`bbox`，仍然返回 `documentName`/`knowledgeId`/`snippet` 等结构化字段，与 PRD"不得出现在引用、来源、错误提示、日志返回给前端的结构化字段中"冲突。本期改造对齐 `view_file` 文件级精滤 + 整条剔除。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-15 | 登录用户，请求所引用的所有 RAG 文件均满足 `view_file` | `POST /api/v1/citations/resolve` 传 `citationIds: [...]` | 返回 `items` 列表，结构与现有 `ResolveCitationResponse` 保持一致；每个 `RagCitationPayloadSchema.downloadUrl` / `previewUrl` / `items[*].bbox` 字段照常填充 |
| AC-16 | 登录用户，某些 `citationIds` 对应的 RAG 文件用户**已无** `view_file` | 同上 | 响应 `items` 中**整条剔除**这些无权 citation（`documentName` / `knowledgeId` / `snippet` / 任何 chunk 文本均不返回），等价于"该文件不存在于引用注册表中"；不抛错；其他可见 citation 仍正常返回 |
| AC-17 | 登录用户，所有 `citationIds` 对应文件用户均已无权 | 同上 | 响应 `items` 返回空数组 `[]`（HTTP 200）；保持现有 `ResolveCitationResponse` 结构 |
| AC-18 | 登录用户 | `GET /api/v1/citations/{citation_id}` 请求单条 RAG 类型 citation，用户对该文件无 `view_file` | 返回 `NotFoundError`（HTTP 200 body 含 5XX 业务错误码）；不返回任何文件元数据；与"该 citation 不存在"语义一致 |
| AC-19 | 登录用户，目标 citation 类型为 `web`（非 RAG）| 调用 `/resolve` 或 `/{citation_id}` | 本期不修改 web 类型处理（`_enrich_web_item`）行为；web citation 不受 `view_file` 影响 |
| AC-20 | 匿名调用方（无 JWT 或 JWT 失效，`login_user is None`，典型为 share link / 公开场景）| 同上 | 本期**保持现状**——`_has_file_access` 在 `login_user is None` 时短路返回 True；不引入新鉴权要求；本 spec 在「不支持」章节明确，留待后续 share-link 专项处理 |

### 2.6 实时性与缓存

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-21 | 管理员授予 / 收回某用户文件权限 | 调用 `PermissionService.authorize/revoke` | 同步触发 `PermissionCache.invalidate_user(user_id)`（现有行为），用户下一轮问答即用新权限 |
| AC-22 | 权限缓存未及时失效（边缘情况） | 用户连续提问 | TTL 上限 10s（现有 `PermissionCache.TTL`），最迟 10s 内自动收敛 |

### 2.7 性能与可观测

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-23 | 单用户单空间 ≤ 5000 可见文件、热缓存（list_accessible_ids 命中） | 整空间问答 | 权限过滤新增耗时 ≤ 80ms（不含 LLM 生成 / Milvus / ES 时间） |
| AC-24 | 单用户单空间 ≤ 5000 可见文件、冷缓存（OpenFGA list_objects） | 同上 | 权限过滤新增耗时 ≤ 500ms |
| AC-25 | 单用户单空间 ≤ 100000 可见文件、热缓存 | 同上 | 权限过滤新增耗时 ≤ 200ms（走 NOT-IN 或后过滤路径） |
| AC-26 | 任意场景 | 单次问答 | 检索循环次数 ≤ 2（首轮 + 至多 1 次扩展），不存在"凑齐 top_k 的无限扩张" |
| AC-27 | 任意场景 | 单次问答 | 日志结构化输出 `permission_filter` 上下文，至少包含 `strategy=in\|notin\|postfilter`、`accessible_ids_size`、`prefilter_candidate_size`、`retrieval_attempts`、`post_filter_dropped_count` |

---

## 3. 边界情况

- **空间内无任何可见文件**（AC-03、AC-12）：返回空检索集合 + 200 状态码，由 prompt 决定模型回答；不视为错误。
- **文件夹下递归子文件夹深度大**（≤ 现有 8 层限制）：仅按"祖先文件夹 / 文件层链 + 用户绑定"解析权限，不需要展开全部子树即可剔除整段无权子树。
- **同一文件存在多个版本**：检索集合永远只考虑当前主版本（沿用现有 `version_repo.find_non_primary_file_ids_by_knowledge_ids`），权限语义按主版本文件 ID 判断。
- **文件正在解析 / 解析失败**：不参与检索（沿用现有 `file_status` 过滤）；权限过滤在解析状态过滤之后执行。
- **管理员（admin / super_admin）**：`PermissionService.list_accessible_ids` 对 admin 返回 `None`（短路）；本特性据此跳过过滤，与现有所有依赖该原语的路径保持一致。
- **OpenFGA 不可达**：`list_accessible_ids` 现有降级行为是"返回空 / 回退 scope"；本特性沿用，结果为"对该用户无可见文件"，等同于 AC-03 行为；记录 ERROR 日志便于排障。
- **citation registry / `RecallChunk` 引用了已删除的文件**：无权检查发生在文件存在性检查之后；已删除文件本就不在响应中（`KnowledgeFileDao.query_by_id_sync` 返回 None），行为与现状一致。
- **不支持**：
  - 工作流 KNOWLEDGE_RETRIEVER 节点的检索权限过滤（延后到独立 feature）。
  - 对外 RPC `/api/v2/filelib/retrieve` 的检索权限过滤（延后到独立 feature，需要先定义代用户检索协议）。
  - 单用户单空间 > 10 万可见文件场景的低延迟保证（需要 chunk 元数据 ACL group 字段方案，留待后续）。
  - **`/api/v1/qa/chunk` 与 `/api/v1/qa/keyword`**：历史角标溯源接口，新版引用 UI 已切换到 `/api/v1/citations/resolve`；本期不动两个 qa 旧接口，待后续合适时机统一下线。
  - **匿名调用方（`login_user is None`）的 citations 接口**：本期保持现有 `_has_file_access` 在 `login_user is None` 时短路 True 的行为；不引入新鉴权要求；典型场景是 share link 公开访问，需要专项设计后再覆盖（与 RPC `on_behalf_of_user_id` 同类问题）。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 检索权限过滤的语义对齐基线 | A: 仅用 ReBAC `can_read`；B: 仅用 fine-grained `view_file`；C: 双层（`can_read` 索引层粗滤 + `view_file` 结果层精滤） | **选 C** | A 会导致"列表看不到但问答能查到"（越权）；B 在 10 万规模冷启动需要对每个文件单独 OpenFGA tuple 读取，单空间一次性解析耗时不可接受。C 用 `can_read` 在 Milvus/ES 端把候选缩到至少有 ReBAC 读权限的文件（一次 `list_objects` + 缓存），然后在召回结果的 unique file_id（≤ 30 个一般规模）上跑 fine-grained `view_file` 解析，保证最终送进 LLM 的 chunks **必然**满足列表 UI 可见性 |
| AD-02 | 索引层过滤策略选择 | A: 始终 `IN(可见集合)`；B: 自适应 IN / NOT-IN / 不过滤后过滤 | **选 B**，以可见集合大小 `K` 与空间内主版本文件总数 `N` 为决策依据：`K ≤ 5000` → IN；`N − K ≤ 5000` → NOT IN（排除集合 = 非主版本 ∪ 不可见）；二者均 > 5000 → 不下推索引过滤，仅靠"扩大候选 + 结果层精滤" | ES `terms` 默认上限 65536；Milvus 长表达式解析在 ≤ 5000 内表现稳定；自适应让 95% 业务走快路径，极端规模有兜底；阈值 5000 写为可配置常量（`KnowledgeQAFilterConf.index_filter_threshold`），关联 AC-23/22/23 |
| AD-03 | 结果层不够 `top_k` 时的扩展策略 | A: 无限扩张直到凑齐；B: 一次扩张后封顶；C: 不扩张 | **选 B**：首轮按 `top_k × 3` 召回；若过滤后 < `top_k` 且首轮命中文件数 > 0，进行至多 1 次扩张到 `top_k × 10`；仍不足则返回已有结果（可少于 `top_k`） | A 在稀疏访问场景下可能无限循环；C 在边界场景下命中率过低；B 在最坏情况下也只是 2 次 Milvus + 2 次精滤批量调用，单次问答额外延迟 ≤ 400ms 可观测可控；关联 AC-26 |
| AD-04 | 历史引用回显的越权剔除方式 | A: 整条剔除；B: 返回 placeholder + `no_permission=true`；C: 接口层 403 | **选 A**：直接从响应列表中剔除无权文件的 chunks | PRD §异常与边界第 2 行明确"历史消息可保留但再次查看引用详情时按当前权限校验"；剔除不返回 placeholder 简化前端、不暴露文件名/URL/source；接口仍 HTTP 200，符合现有调用方期望 |
| AD-05 | 不引入新的 ReBAC 关系 `view_file` | A: 沿用 `can_read`（ReBAC）+ `view_file`（permission_id）；B: 新增 OpenFGA `view_file` 关系并迁移所有 authorize 调用 | **选 A** | B 涉及 OpenFGA 模型变更、tuple 迁移、所有资源创建路径补写新关系，blast radius 远超本 feature；A 通过双层过滤已实现"严格按 `view_file` 决定可见性" |
| AD-06 | 工作流 KNOWLEDGE_RETRIEVER 节点与对外 RPC 路径 | A: 本期统一改造；B: 延后独立 feature | **选 B** | 两个路径有独立的"运行身份"问题（工作流的 owner vs caller、RPC 的 default operator vs 代用户），需要先定义清楚身份语义再统一改造；本 feature 在 spec §3 边界情况里明确标注"不支持"，避免被误以为已覆盖 |
| AD-07 | 索引层缓存与失效 | A: 复用 `PermissionCache` 现有 10s TTL + `invalidate_user`；B: 引入本特性专属缓存 | **选 A** | `list_accessible_ids` 现有缓存机制已被多个调用方依赖，权限变更走统一失效；新增独立缓存增加状态点且失效路径分裂 |
| AD-08 | 结果层精滤的并发与缓存 | A: 每文件独立调用 `get_effective_permission_ids_async`；B: 复用列表 UI 的 `_build_child_permission_context`（含 `tuple_cache`） + 同 semaphore 8 并发 | **选 B** | 列表 UI 已经验证该模式可行，复用同样的上下文结构、同样的并发限流；空间维度的 `_build_child_permission_context` 在结果集少（≤ 30 个 file_id）时近乎一次性 |

---

## 5. 数据库 & Domain 模型

**本特性不新增数据库表、不修改现有表结构。**

复用现有原语：

| 原语 | 路径 | 用途 |
|------|------|------|
| `PermissionService.list_accessible_ids(user_id, 'can_read', 'knowledge_file', login_user)` | `permission/domain/services/permission_service.py:145` | 索引层粗滤候选集（Redis 10s 缓存，admin 返回 `None`） |
| `FineGrainedPermissionService.get_effective_permission_ids_async` | `permission/domain/services/fine_grained_permission_service.py:350` | 结果层精滤（沿用 lineage 解析） |
| `KnowledgeSpaceService._build_child_permission_context(space_id)` | `knowledge/domain/services/knowledge_space_service.py:1160` | 共享 binding / tuple_cache / membership 上下文 |
| `KnowledgeSpaceService._filter_visible_child_items` 风格的 semaphore=8 并发 | 同上 | 结果层精滤的并发上限（沿用同一常量 `_CHILD_PERMISSION_CHECK_CONCURRENCY`） |
| `KnowledgeVersionRepository.find_non_primary_file_ids_by_knowledge_ids` | `knowledge/domain/repositories/...` | 排除非主版本文件（现有行为） |

**新增配置**（写到 `core/config/settings.py` 既有 settings 类中，不新增 setting class 顶层）：

```python
class KnowledgeQAFilterConf(BaseModel):
    """Knowledge space AI Q&A retrieval permission filter — see F026 spec."""
    index_filter_threshold: int = 5000          # AD-02
    retrieval_initial_multiplier: int = 3       # AD-03 first attempt
    retrieval_expansion_multiplier: int = 10    # AD-03 second attempt
    fine_grained_concurrency: int = 8           # AD-08, 与 _CHILD_PERMISSION_CHECK_CONCURRENCY 默认一致
```

挂在 `Settings` 顶层为可选块（YAML 缺省时按上述默认）。

---

## 6. API 契约

### 端点变更清单

> 所有端点继续走 `UserPayload = Depends(UserPayload.get_login_user)`（QA 端点新增依赖）；响应包装沿用 `UnifiedResponseModel[T]`。

| Method | Path | 描述 | 本特性变更 |
|--------|------|------|-----------|
| POST | `/api/v1/knowledge/space/{space_id}/chat/file/{file_id}` | 单文件问答 | 无外部契约变化；内部新增结果层精滤（应已命中 view_file，作为防御性确认） |
| POST | `/api/v1/knowledge/space/{space_id}/chat/folder` | 整空间 / 文件夹问答（folder_id=0 即整空间） | 无外部契约变化；内部接入双层过滤（AD-01/02/03） |
| POST | （工作台 `search_kb` 工具，路径由 `workstation/chat_service` 内部 LangGraph 注册，无独立 HTTP 端点）| 首页 / 工作台多 KB 检索 | 服务层路径 `WorkStationService.queryChunksFromDB` 内部对每个 KB 按当前用户的 `view_file` 过滤；无 `view_space` 的 KB 静默跳过（AC-11/12）；`org_bucket`（legacy `knowledge_library`）路径不变 |
| POST | `/api/v1/citations/resolve` | 角标溯源批量解析 | 端点签名（`get_optional_login_user`、`ResolveCitationRequest` / `ResolveCitationResponse`）**不变**；Service 内的 `_has_file_access` 改造为文件级 `view_file` 精滤；登录用户无 `view_file` 时**整条剔除** citation（AC-16） |
| GET | `/api/v1/citations/{citation_id}` | 角标溯源单条解析 | 同上；单条无权返回 `NotFoundError`（AC-18） |
| ~~POST `/api/v1/qa/chunk`~~ | （历史接口） | 历史引用 chunk 详情 | **不修改**：本期范围排除（§3 不支持），待后续下线 |
| ~~GET `/api/v1/qa/keyword`~~ | （历史接口） | 历史命中关键词 | **不修改**：同上 |

### 请求 / 响应示例

**`/citations/resolve` 部分 citation 无权（AC-16，整条剔除）**：

请求：
```json
POST /api/v1/citations/resolve
{ "citationIds": ["cit_A_visible", "cit_B_invisible", "cit_C_visible"] }
```

响应（`cit_B_invisible` 对应的文件用户无 `view_file`，整条不返回）：
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "items": [
      {
        "citationId": "cit_A_visible",
        "type": "rag",
        "sourcePayload": {
          "knowledgeId": 5,
          "knowledgeName": "Q1 报告库",
          "documentId": 1234,
          "documentName": "report-Q1.pdf",
          "snippet": "...",
          "previewUrl": "...",
          "downloadUrl": "...",
          "items": [{ "itemId": "...", "bbox": "..." }]
        }
      },
      {
        "citationId": "cit_C_visible",
        "type": "rag",
        "sourcePayload": { "...": "..." }
      }
    ]
  }
}
```

说明：`items` 列表只包含 `view_file ∈ effective_permissions` 的 citation；无权 citation **整条不存在**，不返回 `documentName` / `knowledgeId` / `snippet` / 任何 placeholder。`type=web` 的 citation 不受 `view_file` 过滤影响（AC-19）。

**`chat_folder` 成功流式响应（AC-02，可见集合过滤后）** — 服务端 SSE 流，结尾事件示意：
```json
{
  "type": "end_cover",
  "category": "answer",
  "message": {
    "answer": "...",
    "source_documents": [
      {
        "file_id": 1234,
        "file_name": "report-Q1.pdf",
        "score": 0.91
      }
    ]
  }
}
```
说明：`source_documents[*].file_id` 必为当前用户 `view_file ∈ effective_permissions` 的子集（AD-01 结果层精滤保证）；可能为空数组（AC-03 触发，但模型仍按 prompt 给出回答）。

### 错误码表

| HTTP Status | Code | Error Class | 场景 | 关联 AC |
|-------------|------|-------------|------|---------|
| 200（body） | 18040 | `SpacePermissionDeniedError`（**复用**） | 用户访问无 `view_space` / `view_folder` / `view_file` 的资源 | AC-01, AC-05, AC-08 |
| 200（body） | — | — | 用户有 `view_*` 但当前可见集合为空；citations resolve 时 items 全部被过滤 | AC-03, AC-12, AC-17 |
| 200（body） | 现有 `NotFoundError` 码 | `NotFoundError` | `GET /api/v1/citations/{citation_id}` 用户无 `view_file`：与"citation 不存在"语义一致 | AC-18 |

**不新增错误码**。

---

## 7. Service 层逻辑

> 实现集中在 `knowledge/domain/services/knowledge_space_chat_service.py`（检索流程接入双层过滤）、`workstation/domain/services/workstation_service.py`（首页 / 工作台 KB 循环）与 `citation/domain/services/citation_resolve_service.py`（角标溯源精滤）。`knowledge/api/endpoints/qa.py` 本期不修改。

### 7.1 新增 `KnowledgeFileVisibilityService`

集中"可见文件集合"的解析，避免逻辑散落在 chat service 各处。

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `build_index_prefilter(space_id, candidate_file_ids) -> IndexFilter` | space_id + 候选集合（None=整空间） | `{milvus_expr, es_filter, strategy: in\|notin\|none}` | AD-02：决定索引层过滤策略 |
| `post_filter_visible_files(space_id, file_ids) -> Set[int]` | space_id + 召回 chunk 抽出的 file_id 集合 | 满足 `view_file` 的 file_id 子集 | AD-01/08：结果层精滤；内部一次性 `_build_child_permission_context`、semaphore=8 并发 |
| `is_space_visible(space_id) -> bool` | space_id | 用户是否有 `view_space` | 首页多 KB 跳过逻辑（AC-11） |

### 7.2 `KnowledgeSpaceChatService` 调整

| 方法 | 变更 |
|------|------|
| `chat_single_file` | 已有 `_require_file_view_permission`，无功能变化；增加 DEBUG 日志记录"已通过 view_file 检查"以匹配 AC-27 日志规约 |
| `_build_folder_search_kwargs` → 拆为 `_compute_candidate_file_ids` + `KnowledgeFileVisibilityService.build_index_prefilter` | 索引层过滤策略由独立 service 决定（AD-02） |
| `chat_folder` | 检索流程改为：① 候选集合 = 文件夹子树 ∩ tag 子集（已有）；② 调 `KnowledgeFileVisibilityService.build_index_prefilter` 得索引层过滤；③ 走 `_retrieve_with_post_filter`（新内部方法，含 AD-03 的扩展循环） |
| `space_rag` | 在调用 retriever_tool 之前注入"index prefilter"；retriever_tool 调用后调 `post_filter_visible_files` 然后再喂入 prompt 拼装 |
| ~~`_aretrieve_chunks_for_kb`~~ | **不修改**：仅被对外 RPC `/api/v2/filelib/retrieve` 调用，本 spec 范围排除（AD-06）。若后续 feature 接入，沿用同一 `KnowledgeFileVisibilityService` 即可 |

### 7.2b `WorkStationService.queryChunksFromDB` 调整（首页 / 工作台路径）

| 改造点 | 说明 |
|------|------|
| Stage 1 — KB 白名单二次校验（`view_space`，显式跳过）| 进入循环前对 `space_bucket` 的每个 KB 调 `KnowledgeFileVisibilityService.is_space_visible(kb_id)`；不通过则从循环中静默剔除（AC-11）；记录 INFO 日志 `skipped_kb_id reason=no_view_space` |
| `check_auth=False` 保留 | 该参数原本绕过的是空间订阅检查，本特性不改；新增的可见性检查独立于其外 |
| Stage 2 — 每 KB 索引层过滤（`can_read` 粗滤）| 构造 `MultiRetriever` 的 `search_kwargs` 时注入 `KnowledgeFileVisibilityService.build_index_prefilter(kb_id, None)` 的产物（与 chat_folder 路径一致）。**不显式预检测"用户在该 KB 是否有可见文件"**——若 `accessible_ids` 与该 KB 的 file_id 集合交集为空，Milvus / ES 查询会自然返回 0 chunks |
| Stage 3 — 每 KB 结果层精滤（`view_file` 精滤）| `KnowledgeRetrieverTool.ainvoke` 返回后，对 `kb_docs` 走 `post_filter_visible_files(kb_id, unique_file_ids)` 过滤；survivors 为空时本 KB 不进入 `finally_docs` / 不计入 `kb_succeed`（AC-12 的第二种实现路径） |
| AC-12 "自然跳过"语义 | "用户有 view_space 但无 view_file 文件"不是一个显式检测；它通过 Stage 2 返回 0 chunks **或** Stage 3 砍光 survivors 的方式自然实现。事后排障靠 AC-27 日志字段 `accessible_ids_size`、`prefilter_candidate_size`、`post_filter_dropped_count` 区分原因 |
| 检索循环上限 | 沿用 AD-03：单 KB 内首轮 ×3、扩展上限 ×10，不无限扩张；多 KB 间不互相补量 |
| `org_bucket` 不变 | legacy `knowledge_library` 路径明确不动，避免触碰旧逻辑 |

### 7.3 `CitationResolveService` 改造（角标溯源）

改造 `citation/domain/services/citation_resolve_service.py`，替换现有 `_has_file_access` 的旧 RBAC 路径，对齐 ReBAC + Fine-grained `view_file`。

| 改造点 | 现状 | 目标 |
|------|------|------|
| `_has_file_access(login_user, knowledge_id)` 删除 | 用 `RoleAccessDao.judge_role_access` + `AccessType.KNOWLEDGE` 做**空间级**判定（arch-guard RULE-8 VIOLATION）| 删除该方法；引用方改用下面的批量精滤 |
| 引入 `_filter_visible_rag_items(items, login_user)` | — | 抽出 `items` 中类型为 `RAG` 的 `documentId` 集合（按 `knowledge_id` 分组）→ 调 `KnowledgeFileVisibilityService.post_filter_visible_files(space_id, file_ids)` → 凡 `documentId` 不在精滤结果内的 RAG citation 整条剔除（不进入返回 `items`） |
| `resolve_citations` 流程 | 拿到 items 后并发 `_enrich_item` | 拿到 items 后**先**调 `_filter_visible_rag_items` 过滤再 enrich；`web` 类型直通 |
| `resolve_citation`（单条）| 始终返回 enriched item | RAG 类型且 `login_user is not None` 时先过滤；不通过则抛 `NotFoundError`（AC-18）|
| 匿名调用方（`login_user is None`）| 现有 `has_access = login_user is None or ...` 短路为 True | **保持现状**——本期不引入新鉴权（AC-20）|
| Admin 短路 | `_has_file_access` 间接由 `login_user.is_admin()` 跳过 | 沿用：`KnowledgeFileVisibilityService.post_filter_visible_files` 内部对 admin 短路返回 `None` → 不过滤 |
| 性能 | 每个 citation 一次 `KnowledgeDao.aquery_by_id` + 一次 access_check | 一次 `list_accessible_ids`（缓存命中 ~10ms）+ 一次 `_build_child_permission_context`（按 space 分组，复用 tuple_cache）+ 批量精滤；N 条 citation 平均额外耗时 < 100ms |

### 7.4 检索循环（AD-03 流程）

流程：

1. 调 `build_index_prefilter(space_id, candidate)` 拿到 `{milvus_expr, es_filter, strategy}`；若策略判定为"用户在该空间无任何可读文件"则直接返回空。
2. 首轮按 `top_k × initial_multiplier`（默认 3）召回；用召回 chunks 抽出 unique file_id；调 `post_filter_visible_files(space_id, ids)` 拿到 `view_file` 子集；按子集筛 chunks 截到 `top_k`。
3. 若不足 `top_k` 且首轮命中文件数 > 0：扩张到 `top_k × expansion_multiplier`（默认 10），重复一次步骤 2。
4. 仍不足则返回当前结果，**不再扩张**（AD-03 封顶 = 2 次尝试）。
5. 每次尝试结束写一条结构化日志（字段见 AC-27）。

### 权限检查

> 入口门禁沿用现有 `_require_space_view_permission` / `_require_folder_view_permission` / `_require_file_view_permission`，本特性不修改其签名。
> 资源创建仍由调用方走 `PermissionService.authorize`；本特性不创建资源。

### DAO 调用约定

无新增 DAO 入口。`SpaceFileDao.get_children_by_prefix` 等沿用。

---

## 8. 前端设计

### 8.1 Platform 前端（`src/frontend/platform/`）

后端变更对前端**契约透明**：

- 整空间 / 文件夹 / 单文件问答（4 个入口）：响应 schema 不变，前端无需改动。
- 角标溯源面板：`/api/v1/citations/resolve` 的 `items` 数组在某些场景下变短（无权 citation 被剔除），前端按数组渲染无需特殊处理；单条 `GET /api/v1/citations/{citation_id}` 无权时返回 `NotFoundError`，前端复用现有"该来源已不可访问"提示。

**唯一需要前端联调验证**：

- 整空间 / 文件夹页面在用户对空间内全部文件均无 `view_file` 时（AC-03/AC-12），后端返回空检索 + 模型按 prompt 回答，前端流式渲染应正常（无 chunks 时不应渲染"已引用 0 篇"卡片，或显示合理提示）。i18n 文案（中文 / 英文 / 日文）若现状无对应"未找到相关内容"提示，需要在 `public/locales/{lang}/knowledge.json` 补一条 key（建议 `knowledge.qa.noVisibleContent`）。

### 8.2 Client 前端（`src/frontend/client/`）

首页 / 工作台问答涉及的 KB 下拉框：

- 拉取列表的接口已经按 `view_space` 过滤（沿用现有 `get_my_*_spaces` 路径），本特性仅作回归验证（E2E）。
- KB 选中后提交多 KB 检索：行为同 platform，对前端透明。
- 角标溯源前端 `/workspace/api/v1/citations/resolve` 调用同样对契约透明；返回 `items` 变短时按现有数组渲染。
- i18n key 与文案同 platform，在 `src/locales/{lang}/translation.json` 内补一条对应 key（若现状无对应文案）。

**不涉及**：新增组件、新增路由、新增 store。

---

## 9. 文件清单

> 测试文件与覆盖映射由 tasks.md 在 task 拆分阶段产出；本节只列实现文件。

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/knowledge/domain/services/knowledge_file_visibility_service.py` | 新 service：`build_index_prefilter` / `post_filter_visible_files` / `is_space_visible`（AD-01/02/08） |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py` | `_build_folder_search_kwargs` 拆分 + `chat_folder` 接入双层过滤；`space_rag` 在 retriever_tool 后调用结果层精滤；新增结构化日志 |
| `src/backend/bisheng/workstation/domain/services/workstation_service.py` | `queryChunksFromDB` 加入 `is_space_visible` 二次校验 + 每 KB 索引层粗滤 + 结果层精滤（AC-11 ~ AC-13） |
| `src/backend/bisheng/citation/domain/services/citation_resolve_service.py` | 删除 `_has_file_access`（旧 RBAC `AccessType.KNOWLEDGE` + 空间级，arch-guard RULE-8 VIOLATION）；新增 `_filter_visible_rag_items` 走 `KnowledgeFileVisibilityService.post_filter_visible_files`；`resolve_citations` 先过滤再 enrich；`resolve_citation` 单条无权抛 `NotFoundError`（AC-15 ~ AC-18） |
| `src/backend/bisheng/knowledge/api/dependencies.py` | 注入 `KnowledgeFileVisibilityService` 的 FastAPI 依赖工厂 |
| `src/backend/bisheng/citation/api/dependencies.py` | `CitationResolveService` 构造增加对 `KnowledgeFileVisibilityService` 的依赖 |
| `src/backend/bisheng/core/config/settings.py` | 新增 `KnowledgeQAFilterConf` 配置块（AD-02/03/08 的阈值/并发） |
| `src/frontend/platform/public/locales/{en-US,zh-Hans,ja}/knowledge.json` | 补 `knowledge.qa.noVisibleContent` i18n key（若现状无对应文案） |
| `src/frontend/client/src/locales/{en,zh-Hans,ja}/translation.json` | 补对应 i18n key |
| `features/v2.6.0/release-contract.md` | ① 表 1 追加一行：F026 不引入新领域对象、仅读取 / 调用 F025 之外的现有对象；② 表 2 追加 INV-6（定义见下表）；③ 表 3 追加 F026 行，依赖列为 "—"（无前置 feature）；④ 变更历史登记本次新增 |

### 不修改（明确排除，重申）

| 文件 | 原因 |
|------|------|
| `src/backend/bisheng/knowledge/api/endpoints/qa.py` | `/qa/chunk` / `/qa/keyword` 是历史角标溯源接口，新版引用 UI 已切换到 `/api/v1/citations/resolve`；本期不动，待后续合适时机统一下线 |
| `src/backend/bisheng/workflow/nodes/knowledge_retriever/` | 工作流节点检索路径，本期不动（AD-06） |
| `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py` 与 `citation.py` 的 v2 RPC | 默认 operator 身份运行，与终端用户视角不一致，本期不动（AD-06） |

### INV-6 完整定义（待写入 `release-contract.md` 表 2）

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|-----------|------------|---------|
| INV-6 | 知识空间内容的"AI 问答可检索可见性"必须是"列表 UI 可见性"的子集；即对任意 `(user, space, file)`，若用户在列表 UI 中不可见该 `file`（`view_file ∉ effective_permissions`），则任何 AI 问答入口都不得让该 `file` 的 chunk / 文件名 / 来源出现在模型上下文、回答引用、角标溯源 `/api/v1/citations/resolve` 响应的结构化字段中 | KnowledgeSpace, Folder, KnowledgeFile, MessageCitation | F026 |

### 不修改（明确排除）

- `src/backend/bisheng/workflow/nodes/knowledge_retriever/`
- `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`
- OpenFGA 模型定义文件、`PermissionService.authorize` / `revoke` 路径
- `_filter_visible_child_items` / `_scan_visible_child_items`（列表 UI 路径，沿用）

---

## 10. 非功能要求

### 性能

- 热缓存（list_accessible_ids 命中）下，单次问答新增权限过滤耗时 ≤ 80ms（AC-23）。
- 冷缓存下首轮新增 ≤ 500ms（AC-24）；后续 10s 内追问回到热缓存。
- 10 万规模可见集下走 NOT-IN / 后过滤策略，新增 ≤ 200ms（AC-25）。
- 检索循环次数硬上限 = 2（AC-26），最坏情况下额外延迟 ≤ 400ms。

### 安全

- 双层过滤保证"列表 UI 可见性 = AI 问答可见性"（AD-01）；结果层精滤不可绕过（最终送 LLM 前必经）。
- 角标溯源接口对登录用户严格按 `view_file` 文件级精滤，无权 citation **整条剔除**而非仅隐藏 URL（AC-16/17/18）；匿名调用方维持现状不变（AC-20），不引入回归风险。
- 删除 `CitationResolveService._has_file_access` 对旧 RBAC `RoleAccessDao` + `AccessType.KNOWLEDGE` 的直接依赖，消除一个 arch-guard RULE-8 VIOLATION。
- 不引入新的密钥 / token / 配置敏感项。
- 沿用 PermissionService 五级短路（super_admin → 租户隔离 → 租户 admin → ReBAC → RBAC）。

### 兼容性

- 单文件问答（AC-09）行为与现有逻辑等价，仅多一道防御性精滤（已通过门禁的请求精滤必定命中）。
- 多 KB 检索请求 / 响应 schema 完全不变；前端无需联动改造。
- `/api/v1/citations/resolve` 与 `/api/v1/citations/{citation_id}` 的请求 / 响应 schema 不变（`ResolveCitationRequest` / `ResolveCitationResponse` / 单条 `CitationRegistryItemSchema`），但**登录用户**收到的 `items` 列表可能比改造前更短（无权 citation 被剔除），前端按数组渲染无需改动。
- 匿名调用方（share link / 公开场景，`login_user is None`）行为完全不变，避免破坏现有公开访问流。
- `/api/v1/qa/chunk` 与 `/api/v1/qa/keyword` 本期**完全不动**——保持现有匿名访问 + 旧 RBAC 行为；后续下线时另行单独评估调用方。

### 可观测

- 单条问答日志增 `permission_filter` 结构化字段（AC-27），便于排查"为什么这条问答没拿到我以为能看到的内容"。
- OpenFGA list_objects 失败时 ERROR 日志保留现有 `OpenFGA unreachable during list_objects` 行；本特性额外打点"权限过滤策略退化为空集"以便监控。

---

## 相关文档

- 版本契约: [features/v2.6.0/release-contract.md](../release-contract.md)（写 spec 前必须先阅读；本 spec 要求在该文件追加 INV-6）
- 权限体系 P0 规则（v2.5 之后的现行体系）:
  - `src/backend/AGENTS.md` §3.4 ReBAC + Fine-grained permission_id 统一入口
  - [docs/PRD/2.5 权限管理体系改造 PRD/](../../../docs/PRD/2.5%20%E6%9D%83%E9%99%90%E7%AE%A1%E7%90%86%E4%BD%93%E7%B3%BB%E6%94%B9%E9%80%A0%20PRD/)（v2.5 ReBAC + OpenFGA 改造目标 & 模型）
  - `docs/architecture/10-permission-rbac.md`（**注意**：该文档描述的是 v2.5 之前的旧 RBAC + AccessType + SpaceChannelMember 模型，与本 spec 实际使用的 `PermissionService.list_accessible_ids` / `FineGrainedPermissionService` 体系不一致，仅供历史背景参考）
- PRD: [docs/PRD/知识空间优化/知识空间AI问答-权限过滤.md](../../../docs/PRD/%E7%9F%A5%E8%AF%86%E7%A9%BA%E9%97%B4%E4%BC%98%E5%8C%96/%E7%9F%A5%E8%AF%86%E7%A9%BA%E9%97%B4AI%E9%97%AE%E7%AD%94-%E6%9D%83%E9%99%90%E8%BF%87%E6%BB%A4.md)
- 模块编码登记表: 沿用 180（`knowledge_space`），不新增模块
