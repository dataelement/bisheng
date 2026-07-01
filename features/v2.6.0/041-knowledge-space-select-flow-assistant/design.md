# Design: F041-knowledge-space-select-flow-assistant（工作流 / 助手应用支持选择知识空间）

> **本文档定位 — 现状快照（Why this How）**
> - [spec.md](./spec.md) 回答做什么；本文回答**为什么这么实现** + 今天代码长什么样 + 坑 + 对外契约。
> - 全局铁律不重抄，遵循 [`docs/constitution.md`](../../../docs/constitution.md) C1–C7。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（待编写）
**版本**: v2.6.0
**最后更新**: 2026-07-01（初版，随实现同步覆盖更新）

---

## 1. 目标与非目标

- **目标**：让 4 个入口（助手应用、工作流助手节点 `agent`、知识库问答节点 `rag`、知识库检索节点 `knowledge_retriever`）能选「知识空间」并检索；检索按开关分档过滤 `view_file`（开=运行使用者、关=配置者）；结果与文档知识库**同构**、复用统一角标溯源。**本质是在既有检索链路上叠一层「空间 id 识别 + F029 双层 view_file 过滤 + 按身份切换」，不是新建检索。**
- **非目标**：不改 QA 检索节点（`qa_retriever`）；不给知识空间加自定义元数据；不改 OpenFGA 模型；不动对外 RPC `/api/v2/filelib/retrieve`（F030 已覆盖）；不支持"单个工作流节点内混选文档库+空间"（助手应用支持混选，工作流节点为模式互斥，见决策 4）。

---

## 2. 关键约束

- 遵循 `constitution.md` C1（分层，不新增 DAO 入口）/ C3（多租户：`resolve_operator` 内已 `set_current_tenant_id`）/ C4（权限统一入口，复用 `PermissionService` / F029，禁直查 `role_access`）。
- **不新增领域对象 / 表 / 对外 API / 错误码**；唯一的持久化 schema 改动是给 F029 拥有的 citation 链路加一个 `accessScope` 字段（已在 `release-contract.md` 作为 INV-7 例外的协同改动登记）。
- **INV-7 例外**（见 `release-contract.md` 表 2）：本 feature 让"空间 AI 可见性 ⊆ 列表 UI 可见性"在工作流/助手入口变为开关可选，且**两档都不越过配置者本人的 `view_file` 边界**。
- **运行形态约束**：工作流节点在 Celery worker（`workflow_celery`，线程池）里**同步**执行（`RagUtils.retrieve_question` 是 sync），而 F029 过滤是 **async** → 见坑 §5.2。
- 性能沿用 F029：热缓存单次过滤开销可控（`list_accessible_ids` 10s Redis 缓存 + `post_filter` semaphore 并发）。

---

## 3. 方案对比与选定

### 决策 1：空间检索怎么落 —— 扩 `RagUtils` 注入 F029 过滤，而非走 `aretrieve_chunks`

- **备选**：
  - A. **扩现有节点检索**：在 `RagUtils`（rag / knowledge_retriever）与助手工具里，识别 `type=3` 空间 id → 解析空间 file_ids → 注入 F029 索引层 prefilter（`build_index_prefilter` 产的 milvus_expr/es_filter）到 `KnowledgeRetrieverTool` 的 search_kwargs → 结果层 `post_filter_visible_files` → 复用既有 `annotate_rag_documents_with_citations` + `collect_rag_citation_registry_items`。
  - B. **走 `KnowledgeSpaceChatService.aretrieve_chunks`**（F030 多态检索）。
- **选定**：A。
- **原因**：① 结果格式与 citation **自动一致**（走的是同一个 `KnowledgeRetrieverTool` → `List[Document]` → 同一套 annotate/collect），6.3 天然满足，无需另写一份 citation 组装；② `aretrieve_chunks` 的空间路径 `_aretrieve_chunks_for_kb` **只校 `view_space`、不做 F029 双层 `view_file` 过滤**，且不产节点风格 citation，用它反而要补更多；③ blast radius 更小——只在 `RagUtils` / 助手工具加空间分支，不动 F030 对外 RPC 语义。
- **何时重新考虑**：若未来 `aretrieve_chunks` 的空间路径补齐了 view_file 双层过滤 + 统一 citation，则可收敛为单一入口。
- **arch-guard 注**：`RagUtils` 在 `workflow/common/knowledge.py`，新增 import `knowledge/domain` 的 `KnowledgeFileVisibilityService` 属 common→domain；`RagUtils` 已 import `KnowledgeRag`（同属 knowledge/domain），是既有模式，预期不触发 arch-guard RULE-1（RULE-1 针对顶层 `bisheng/common`，非 `workflow/common`）——实现期以 hook 输出为准确认。

### 决策 2：过滤身份按开关切换（本 feature 的核心）

- **备选**：A. 永远运行使用者；B. 永远配置者；C. **开=运行使用者、关=配置者**。
- **选定**：C（详见 spec 第一性分析）。
- **原因**：文档库"关档=借整库"能自洽是因为配置者对整库有权；知识空间是协作的，配置者未必对全部文件有 `view_file`，若关档"纯不过滤"会检索到**连配置者都无权看**的文件（整个空间 collection 都可召回）——越权且抹掉空间存在的意义。C 让关档=借用配置者可见范围，**永不越配置者边界**，与文档库"借库"语义对称。
- **实现**：`KnowledgeFileVisibilityService(request, login_user)` 的所有过滤都取构造入参 `self.login_user` → 换身份=换构造：
  - 开档：用运行使用者 `UserPayload`（workflow `self.user_id` / assistant `self.invoke_user_id`）。
  - 关档：造配置者 `UserPayload`（`UserPayload.init_login_user(user_id=配置者id, tenant_id=当前 flow 租户)`）——**不切换当前租户上下文**。**不要**直接用 `resolve_operator`（它内部 `set_current_tenant_id` 会切走当前租户、污染同节点后续 tenant-scoped 查询，见坑 §5.10）；配置者与 flow 同租户，直接用当前 flow 租户构造即可。
- **何时重新考虑**：若产品要求"关档也按人隔离"或"关档纯共享全空间"（放弃边界），需回 spec 改 AC-14 并重登记 INV-7 例外。

### 决策 3：workflow 配置者 id 怎么拿到 —— 构造期透传，而非节点内查库

- **备选**：A. 像 `tenant_id` 一样把 `flow_user_id`（创建者）从 `Workflow → GraphEngine → BaseNode` 透传；B. 节点内 `FlowDao.get_flow_by_id(self.workflow_id).user_id` 现查。
- **选定**：A。
- **原因**：任务入口 `tasks.py` 已 `FlowDao.get_flow_by_id(workflow_id)` 拿到 `workflow_info.user_id`（当前只透传了 `tenant_id`，没透传创建者）；透传避免每个节点一次 DB 查询（B 会 N 次）。
- **何时重新考虑**：若 workflow 引入"代运行/多所有者"语义，配置者定义变复杂时重议。
- **assistant 侧无此问题**：`AssistantAgent.assistant.user_id`（创建者）与 `self.invoke_user_id`（运行者）在实例上都直接可用。

### 决策 4：前端选择器 —— 工作流节点用「模式」、助手应用用「每项类型标记」

- **备选**：A. 统一每项带 `resourceType` 标记；B. 统一"空间作为独立模式"；C. **按各入口现有 shape 分别处理**。
- **选定**：C。
- **原因**：两套选择器现有 shape 不同，各自最小改动：
  - **工作流三节点**（`KnowledgeSelectItem`，现 `{type:'knowledge'|'tmp', value:[{key,label}]}`，`type` 是**模式**）：新增 `'space'` 模式（与 knowledge/tmp 互斥，和现在"切 tab=切模式"一致）。回显读 `type` 即知归属。**单节点内不混选**文档库+空间（AC-04 已声明不强制）。
  - **助手应用**（`KnowledgeSelect`，现 `knowledge_list:[{name,id}]`，`type='file'` 时不出 tab）：改为出 tab（文档知识库 + 知识空间），每条选择加**类型标记**（沿用 client 日常模式 `type:'space'` 范式），并入同一 `knowledge_list`，可混选。回显读每项 type。
- **回显区分**（对应 spec AC-03）：工作流节点靠模式字段、助手应用靠每项标记；**存量未标记项默认按文档知识库兜底**。
- **何时重新考虑**：若产品要求工作流节点也混选文档库+空间，则工作流节点也切到每项标记（A）。

### 决策 5：角标溯源 `accessScope` 分级（方案 B）

- **备选**：A. 溯源恒按 F029 严格 view_file（关档会断裂）；B. **citation 标 `accessScope`，`shared` 分级暴露**；C. 溯源用配置者身份判定。
- **选定**：B（详见 spec §2.5 / §3 交互）。
- **原因**：关档内容已收敛到配置者可见范围，但运行使用者未必有 `view_file`；若溯源仍整条剔除则"用了内容却点不开来源"。B 让 `shared` citation 保留、展示来源元数据与 snippet，但**完整文件预览/下载 URL 仍按运行使用者 `view_file` 判定**——既不断裂、又不泄露整份文件、也不越配置者边界。
- **实现**：`CitationRegistryItemSchema` + 持久化的 `MessageCitation` 加 `accessScope: 'per_user'|'shared'`（默认 `per_user`，存量从严）；4 个 citation 生成点按开关赋值；`CitationResolveService` 分支（见 §4.3）。
- **何时重新考虑**：若产品要"关档也不给无权用户看来源元数据"，退回 A 语义即可（`shared` 也按 view_file 剔除）。

### 决策 6：节点改名 = 仅 i18n 显示名

- 改 `flow.json` 的 `node.rag.name`（文档知识库问答→知识库问答）、`node.knowledge_retriever.name`（文档知识库检索→知识库检索），中/英/日三语。**节点 type 标识 `rag` / `knowledge_retriever` 不变** → 存量流程零迁移（决策依据：type 是数据主键语义，改名只动展示层）。
- **何时重新考虑**：基本终态；仅当需要改节点内部 `type` 标识或合并/拆分节点时才回看（那时才涉及存量流程数据迁移）。

### 决策 7：空间列表口径 = client 日常模式并集

- 知识空间 tab 的数据源 = `/api/v1/knowledge/space/mine` + `/joined` + `/department` 三端点**去重并集**，前端一次性加载 + 前端名称搜索；**不含广场**（`/square`），**不套**文档库 tab 的游标分页（与 client `ChatKnowledge` 完全一致）。原因：需求方要求与 client 日常模式口径一致；这三端点是 INV-6 例外（F040）全返回，天然适合一次性加载。
- **何时重新考虑**：若 client 日常模式口径变化，或产品要求配置场景纳入广场（公共/已发布空间）/ 更宽的 `view_space` 口径时重议（呼应 §8 的 open question）。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（关档为例，开档把"配置者身份"换成"运行使用者身份"）

**工作流 rag / knowledge_retriever 节点**：
`节点执行 → RagUtils 读 knowledge 参数(type=space) → 解析空间 file_ids(SpaceFileDao.get_children_by_prefix) → 按开关取身份(开=self.user_id / 关=resolve_operator(flow_user_id)) → KnowledgeFileVisibilityService.build_index_prefilter 注入 milvus_expr/es_filter → KnowledgeRetrieverTool 检索 → post_filter_visible_files 结果层精滤 → annotate_rag_documents_with_citations + collect_rag_citation_registry_items(accessScope 按开关) → graph_state`

**工作流 agent 节点 / 助手应用**：
`_init_knowledge_tools / init_knowledge_tool 构造知识工具 → 工具内检索时同上(空间分支 + F029 过滤 + 身份切换) → AssistantCitationToolWrapper/WorkflowCitationToolWrapper 产 citation(accessScope 按开关)`

**溯源解析**（历史/实时都走）：
`citations/resolve → CitationResolveService: per_user 项按运行使用者 view_file 整条剔除(F029 现状) / shared 项保留 → enrich 时 shared 项按运行使用者 view_file 决定是否填 previewUrl/downloadUrl`

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 形状 | 说明 | 谁消费 |
|---|---|---|---|
| 工作流节点 `knowledge`/`knowledge_id` 参数 | `{type:'knowledge'\|'tmp'\|'space', value:[{key,label}]}` | `type` 新增 `'space'` 模式（互斥） | RagUtils / agent 节点 / 回显 |
| 助手 `knowledge_list` 项 | `{name, id, type:'knowledge'\|'space'}` | 每项新增类型标记（沿用 client） | 助手检索 / 回显 |
| `search_switch`(用户知识库权限校验) | node 参数 `user_auth: bool`（默认 `false`） | 4 入口统一；助手应用/agent 节点**新增** | RagUtils `_knowledge_auth` / 助手 |
| `CitationRegistryItemSchema.accessScope` | `'per_user'\|'shared'`（默认 `per_user`） | 溯源门禁分级；持久化到 `MessageCitation` | CitationResolveService |
| citation `sourcePayload`（RAG） | `{knowledgeId, documentId, documentName, snippet, previewUrl?, downloadUrl?, items[]}` | 空间与文档库**同构**（不变） | 前端溯源面板 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `knowledge/domain/services/space_flow_retrieval.py`（**F041 新增，共享**） | `abuild_scoped_login_user`(无副作用配置者身份) + `aretrieve_space_documents`(空间 file_ids 解析 + F029 双层过滤 + 元数据/身份组合 + 2 次尝试循环)；供 rag/knowledge_retriever/agent/assistant 共用 | 放**知识域**而非 workflow/common，避免 assistant→workflow 跨模块依赖（T003/T004 偏差） |
| `workflow/common/knowledge.py` `RagUtils` | rag/knowledge_retriever 检索 + citation；空间分支经 `run_async_safe` 调 `aretrieve_space_documents`、身份=开档 `self.user_id`/关档 `self.flow_user_id` | 不直查 role_access |
| `workflow/nodes/rag/rag.py` `RagNode` / `.../knowledge_retriever/*` | 节点编排（复用 RagUtils） | — |
| `workflow/nodes/agent/agent.py` `AgentNode` | 助手节点；`_init_knowledge_tools` 加空间分支 + 新增 user_auth 开关 | — |
| `api/services/assistant_agent.py` `AssistantAgent` | 助手应用；`init_knowledge_tool` 加空间分支 + 新增 user_auth 开关；身份 `self.assistant.user_id`(配置者)/`self.invoke_user_id`(运行) | — |
| `knowledge/domain/services/knowledge_file_visibility_service.py`（F029） | 双层 view_file 过滤；**按构造入参 login_user 决定身份** | 复用，不改其算法 |
| `open_endpoints/domain/utils.py` `resolve_operator` | 从裸 user_id 造 UserPayload（关档取配置者身份） | — |
| `citation/domain/services/citation_resolve_service.py` | 溯源解析；新增 `accessScope` 分支（per_user 剔除 / shared 保留 + enrich 按 view_file 决定 URL） | — |
| `citation/domain/schemas/citation_schema.py` / `MessageCitation` | 加 `accessScope` 字段（F029 协同改动） | — |
| 前端 `selectComponent/knowledge.tsx` `KnowledgeSelect` | 助手应用选择器；出 tab + 每项类型标记 + 空间三端点数据源 | — |
| 前端 `FlowNode/component/KnowledgeSelectItem.tsx` | 工作流节点选择器；加 `'space'` 模式 tab + 空间数据源 | — |
| 前端 `flow.json` / `bs.json` locales | 节点改名 + tab 文案 + 开关 tips 文案（中/英/日） | — |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 5.1 | **workflow 节点当前只透传运行使用者 `self.user_id`，配置者 id 没穿到节点**（`tasks.py` 拿到 `workflow_info.user_id` 却只透传了 tenant_id） | 关档取不到配置者身份，过滤身份错 | `Workflow→GraphEngine→BaseNode` 新增 `flow_user_id` 透传（决策 3） |
| 5.2 | **workflow 节点是 Celery 线程池里的 sync 执行，F029 过滤是 async** | 直接 `asyncio.run` 每次新建 loop → OpenFGA/aiomysql 单例报 "Event loop is closed"，节点挂 | 用项目既有单一持久后台 loop（`run_async_safe` / `file_encoding._AsyncRunner` 范式）跑 async 过滤 |
| 5.3 | **空间检索必须先解析 file_ids**（Milvus collection 是按 knowledge_id 建的，不先 `document_id in [file_ids]` 就会搜整个空间全部文件） | 越权 + 检索范围失控 | 走 `SpaceFileDao.get_children_by_prefix` 拿空间 file_ids 再喂 prefilter |
| 5.4 | **空间 id 与知识库 id 同表全局唯一**（type=3 vs 0/1），选择器 value 里可能混着 | 若默认当 KB 处理，空间会走错检索/权限路径 | 前端带类型标记（决策 4）；后端按标记/`row.type` 分派 |
| 5.5 | **`accessScope` 必须持久化到 `MessageCitation`，不能只进 Redis 缓存**（缓存 100s TTL，历史会话重开时缓存已失效走 DB） | 历史溯源丢 accessScope → 默认 per_user → 关档来源被误剔除，断裂复现 | schema + 持久层都加字段；存量无值默认 `per_user`（从严） |
| 5.6 | **溯源 `shared` 分级要改两个地方**：`_filter_visible_rag_items`（shared 不剔除）+ `_enrich_rag_item`（当前 `del login_user`，shared 要重新按运行使用者 view_file 决定是否填 URL） | 只改 filter 会把无权用户的完整文件 URL 也发出去（越权下载） | 两处都改，见 §4.3 |
| 5.7 | **`qa_retriever` 节点用 `check_auth=False` + 独立 `qa_select_multi`，不在本期范围** | 误改会动 QA 检索语义 | 不碰 |
| 5.8 | **知识空间无自定义 metadata_fields**（`getKnowledgeDetailApi` 对空间返回空） | 元数据过滤 UI 拉自定义字段时对空间会空/报错 | 空间 tab 只提供内置字段，前端不拉自定义字段 |
| 5.9 | **助手应用 `KnowledgeSelect` 现 `type='file'` 时根本不渲染 tab**（`tabs={type==='all'?...:null}`） | 以为改文案就行，实际要让它出 tab 结构 | 组件改造出 tab（决策 4） |
| 5.10 | **`resolve_operator` 自带 `set_current_tenant_id` 副作用**（为 F030 对外 RPC 设计）——关档取配置者身份**不能**直接用它 | 会在节点执行中途把当前租户切成配置者租户，污染同节点后续 tenant-scoped 查询（配置者与 flow 不同租户时更明显） | 无副作用地构造配置者 `UserPayload`（沿用当前 flow 租户，`UserPayload.init_login_user(...)`，**不切租户**），见决策 2 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 | 变更性质 |
|---|---|---|---|
| 节点 `knowledge`/`knowledge_id` 参数新增 `type:'space'` / 每项类型标记 | 节点配置数据 | 前端选择器 / 回显 / 后端检索 | **加法**，存量无标记默认 knowledge |
| `search_switch`(user_auth) 出现在助手应用 / agent 节点 | 节点/助手配置 | 前端 | **加法**，默认 false |
| `CitationRegistryItemSchema.accessScope` | citation resolve 响应 + 持久化 | 前端溯源面板 / 历史回放 | **加法**，默认 per_user |
| 节点显示名（知识库问答 / 知识库检索） | i18n | 前端渲染 | 仅显示名，存量流程零影响 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F029 `KnowledgeFileVisibilityService`（双层 view_file 过滤） | 内部 async API | 其算法/签名变则本 feature 过滤失效；按构造 login_user 决定身份是硬约束 |
| F030 `resolve_operator(user_id)` | 内部 async API | 关档配置者身份构造依赖；改签名要同步 |
| `MessageCitation`（F029 owns） | 持久化模型 | 加 `accessScope` 是 F029 协同改动（已登记契约） |
| `KnowledgeRetrieverTool` / `annotate_/collect_rag_citation_*` | 内部 API | 结果格式与 citation 同构靠它；改则 6.3 失效 |
| `SpaceFileDao.get_children_by_prefix` | 内部 DAO（只读） | 解析空间 file_ids |
| `/api/v1/knowledge/space/{mine,joined,department}` | HTTP | 空间列表口径；与 client 共用 |
| `Flow.user_id` / `Assistant.user_id` | 模型字段 | 配置者身份来源 |
| workflow 单一持久后台 loop（`run_async_safe`） | 运行时 | sync 节点跑 async 过滤的唯一安全姿势（坑 5.2） |

---

## 7. 测试与可观测

- **单元**：过滤身份切换（开=运行使用者 / 关=配置者）；`accessScope` 赋值（4 生成点 × 开关）；`resolve_operator(配置者id)` 造 UserPayload。
- **集成**：空间检索在开/关两档下的 `view_file` 命中集合（越权文件不进结果）；`shared` citation 的 enrich URL 门禁（无权→无 URL、有权→有 URL）；历史 citation（缓存失效走 DB）accessScope 正确。
- **e2e（`/e2e-test`）**：4 入口各选空间 → 开/关开关 → 校验检索结果与角标；节点改名三语；回显区分。
- **手动**：起 workflow worker `uv run celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h`（cwd `src/backend/`），在 platform（:3001）建一个含知识库检索节点+选知识空间的工作流，用**非配置者**账号触发运行，观察 worker 日志无 "Event loop is closed"、检索结果符合开/关两档预期（坑 5.2 回归 + 决策 2 身份切换）。溯源在 client（`/workspace`）用不同权限账号打开会话验证 `shared`/`per_user` 分级。
- **可观测**：沿用 F029 `permission_filter` 结构化日志（strategy / accessible_ids_size / post_filter_dropped_count），本 feature 额外打点 `identity=runtime|author` 与 `accessScope`。

---

## 8. 后续改进 / 不打算做的事

- **工作流节点内混选文档库+空间**：本期工作流节点为模式互斥（决策 4），助手应用已支持混选；若需要再切每项标记。
- **知识空间自定义元数据过滤**：F030 已确认空间无此能力，暂不做。
- **`qa_retriever` 节点支持空间**：需求未点名，不做。
- **配置选择器是否含广场空间**：本期与 client 日常模式一致（不含 `/square`）；若配置场景确需挂公共空间，另议（spec §一 first-principles 已标注该 open question）。
- **`aretrieve_chunks` 空间路径补齐 view_file + 统一 citation**：若补齐，可把决策 1 的检索入口收敛为单一多态入口。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-07-01 | 初版（8 决策 + 现状 + 9 坑 + 契约） | spec 定稿后落 How |
