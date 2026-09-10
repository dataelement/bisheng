# Tasks: 工作流临时知识库溯源（F062）

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)
**版本**: v3.0.0-beta1
**分支**: `feat/v3.0.0-beta1/062-workflow-temp-kb-citation`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户 2026-09-09 确认开工 |
| design.md | ✅ 已评审 | 用户 2026-09-09 确认开工；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 24 个任务 / 6 个 Wave；AC-01～AC-25 全部有测试或手动验证覆盖 |
| 实现 | 🔲 进行中 | 23 / 24 完成。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

- **后端 Test-First**：测试任务在实现任务之前；实现任务的「测试」字段写明要转绿的测试。
- **前端手动验证**：Client 与 Platform **分任务**，各附可操作步骤（完整清单见 design §7）。
- **中间件 / DM8 / e2e 在 CI 跑**，不依赖本地。
- **无 DDL、无新错误码、无新对外 API**。复用 `GET /api/v1/citations/{id}` 与 `POST /citations/resolve`。
- **自包含**：任务内联文件与逻辑；**为什么这么做指向 design §3 的决策编号，不复制论证**。
- **取代关系**：F054 的 `test_temp_file_no_citation.py` 在 T013 **改写预期**（登记为 `temp`，不是关掉角标）。日常附件 / 灵思上传仍排除。

---

## Tasks

### Wave 1 — 无依赖，可并行（基础设施 + 基线 + i18n）

- [x] **T001**: 新增 `temp` 来源类型与载荷 schema
  **文件**: `src/backend/bisheng/citation/domain/schemas/citation_schema.py`
  **逻辑**: `CitationType` 增加 `TEMP = "temp"`；新增 `TempCitationItemSchema` 与 `TempCitationPayloadSchema`（字段形状见 design §4.3：`documentId` 为 UUID **字符串**、`objectName`、`documentName`、`snippet`、`items[]` 含可空 `bbox`/`page`/`chunkIndex`；**不含**整数 `knowledgeId`）。`CitationSourcePayload` 联合类型扩为四种。**不改** `message_citation` 表（`citation_type` 已是 `varchar(32)`）——**无 DDL、无 Alembic，因而无需回滚方案**。
  **设计依据**: design §3 决策 1 / 决策 7
  **依赖**: 无

- [x] **T002**: 登记 release-contract 第四种来源
  **文件**: `features/v3.0.0-beta1/release-contract.md`
  **逻辑**: 表 1 新增 F062 行：无新表，Owner = F062，说明在 F029 拥有的 citation 链路上扩展第四种 `citation_type=temp`。F054 行改为「不再拥有临时来源是否出角标」的写语义（文章类型 / 匿名收紧 / 失效态仍归 F054）。表 3 增加 F062 依赖 F054。**不改 INV-7**。
  **跨 Feature 影响**: 只改契约登记，不改代码。
  **依赖**: 无

- [x] **T003**: 非侵入回归**基线**测试（先写、先绿）
  **文件**: `src/backend/test/citation/test_f062_non_regression.py`
  **逻辑**: 在**改造前**的代码上写并跑绿，锁死本 Feature 不得破坏的不变量：①`_is_citable_rag_document` 仍拒绝 UUID、仍接受整数 `document_id`；②`_is_anonymous_readable` **只**对 `web` 为真（后续 temp 分支不得加入该函数）；③未注册标记仍被 strip，用户可见文本不含 `knowledgesearch_` / `tempsearch_` / 协议字符。**不要**把「临时来源不出角标」写进本文件——那是 F054 旧预期，由 T013 改写。实现全部完成后 T024 必须重跑本文件，并重跑 `test_f054_non_regression.py`、`test_access_scope_tiering.py` 的已登录两档。
  **覆盖 AC**: AC-12, AC-21, AC-24
  **依赖**: 无

- [x] **T004**: Client 溯源文案 i18n（临时知识库）
  **文件**: `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**: 在既有 `com_citation.*` 下新增 `source_temp_kb`。三语文案必须是产品词「临时知识库」及其对译（en: Temporary knowledge base / ja: 一時ナレッジベース，实现时以自然口语为准），**禁止**写「临时文件」。`no_permission` / `source_expired` 已存在，不重复造 key。组件接线在 T020 / T021。
  **覆盖 AC**: AC-20
  **依赖**: 无

- [x] **T005**: Platform 溯源文案 i18n
  **文件**: `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 在既有 `citation` 命名空间下新增 `tempKb`（「临时知识库」三语）、`noPermission`（「暂无权限查看该来源」）、`sourceExpired`（「来源已失效」）。T023 把 `getCitationSourceLabel` 的硬编码「网页」「文档」一并改走 `citation.web` / `citation.document`（这两 key 已在 `citation` 下），本任务只补 key、不改 TS。
  **覆盖 AC**: AC-20
  **依赖**: 无

### Wave 2 — 注册表 + 每文件身份

- [x] **T006**: 临时来源注册表单测
  **文件**: `src/backend/test/citation/test_temp_registry.py`
  **逻辑**: mock 召回文档（UUID `document_id` + 工作流 id 作为 `knowledge_id` + 原件路径）→ 断言：`build_temp_registry` 产出 `citation_type=temp`、前缀 `tempsearch_`；payload **没有**整数 `documentId` / `knowledgeId`；`documentId` 是 UUID 字符串；`_load_source_payload("temp", ...)` round-trip 成功。护栏：把同一文档喂给 `build_rag_registry` / `_is_citable_rag_document` 仍被跳过。分组：未知类型不得落到 Web schema（给 `_load_source_payload` 喂 `temp` 不得走 `WebCitationPayloadSchema`）。
  **覆盖 AC**: AC-02
  **依赖**: T001

- [x] **T007**: 注册服务支持 temp 来源 + load/group 分支
  **文件**: `src/backend/bisheng/citation/domain/services/citation_registry_service.py`
  **逻辑**: 新增 `TEMP_PREFIX = "tempsearch_"`、`generate_temp_citation_id`、`build_temp_registry`（按 `document_id` 分组，一项一文件）。`_load_source_payload` **必须**加 `CitationType.TEMP` 分支（design 坑 11：未知类型今天走 Web schema）。`_group_registry_items` 同样加 temp 分支，禁止掉进 `else` 的 web 分组。`dump_source_payload` 类型并入 `TempCitationPayloadSchema`。不 invent 整数 documentId。
  **跨 Feature 影响**: 该文件是 F029 / F054 的 citation 注册入口；只增量第四种类型，既有 rag / web / article 构建逻辑一字不改。
  **设计依据**: design §3 决策 1 · §5 坑 11
  **测试**: T006 全绿，且 T003 仍全绿
  **覆盖 AC**: AC-02
  **依赖**: T001, T006

- [x] **T008**: 每文件唯一 id + retriever 收集 + bbox 不覆盖 单测
  **文件**: `src/backend/test/workflow/test_temp_kb_identity.py`
  **逻辑**: ①身份 dict 工厂（T009 落地为循环内 `generate_uuid()` 或抽取的静态方法）：两次调用 `document_id` 不同；keys **不含** `bbox` / `page` / `chunk_index`。②给定同一变量下两份 metadata，收集到 **两个** `document_id`，不是只取 `[0]`。③模拟 `one.update(file_metadata)`：文件级 dict 不含 bbox 时，管线产出的 bbox/page 仍在。④`parse_only` / `keep_raw` 不走 ingest 时，不产生 temp 登记所需的 metadata 列表（沿用 `test_input_parse_mode.py` 的模式暴露规则：无 `ingest_to_temp_kb` 则无 key 变量）。
  **覆盖 AC**: AC-06, AC-10, AC-13
  **依赖**: 无

- [x] **T009**: 输入节点每文件唯一 UUID，文件级 metadata 不带 bbox
  **文件**: `src/backend/bisheng/workflow/nodes/input/input.py`
  **逻辑**: `parse_upload_file` 把 `generate_uuid()` **移入** `for one_file_url in value` 循环；文件级 dict 只留身份字段（`document_id` / `document_name` / `knowledge_id` / 时间戳），**删除** `"bbox": ""` 以及任何 `page` / `chunk_index` 键，避免 `one.update(...)` 盖掉管线产出。不写 `knowledge_file`，不改向量 schema。**不得单独合入**：每文件唯一 id 而不改 T010 的 retriever，其余文件会从召回里消失。
  **跨 Feature 影响**: 输入节点是工作流共用入口——只改 ingest 路径的 identity 生成，`extract_text` / `keep_raw` 的输出变量规则不变。
  **设计依据**: design §3 决策 2 / 决策 6 · §5 坑 4、坑 10
  **测试**: T008 与身份 / bbox 相关用例全绿
  **覆盖 AC**: AC-06, AC-10
  **依赖**: T008

- [x] **T010**: `init_file_retriever` 收集全部 id，召回后回填原件定位
  **文件**: `src/backend/bisheng/workflow/common/knowledge.py`
  **逻辑**: `init_file_retriever` 遍历该变量 metadata **列表全部** `document_id`（禁止 `file_metadata[0]`）。召回后按图状态里 `document_id → file_path`（与 `file_path` 输出按下标对齐）回填到 `Document.metadata`，供 T007 登记使用。不改 `knowledge` / `space` 路径。
  **跨 Feature 影响**: `RagUtils` 为 RAG 节点与知识检索节点共用；正式库 `init_knowledge_retriever` 一行不改。
  **设计依据**: design §3 决策 2 · §5 坑 5、坑 10
  **测试**: T008 的收集 / 回填用例全绿
  **覆盖 AC**: AC-10
  **依赖**: T008, T009

### Wave 3 — 按类型分流登记（打开 F054 关断点，走 temp）

- [x] **T011**: 临时 chunk 标注 / 混用分流 / 失败回退 单测
  **文件**: `src/backend/test/citation/test_temp_annotate.py`
  **逻辑**: ①临时文档经 `annotate_temp_documents_with_citations` 后 `citation_key` 以 `tempsearch_` 开头，且 `<chunk_id>` 非空。②同一批文档混有整数 id 与 UUID：整数走 rag 收集，UUID 走 temp 收集，互不串型。③`_is_citable_rag_document` 对 UUID 仍 False。④标注抛异常时返回原文档、不中断（AC-23）。⑤未使用来源时不要求本任务断言持久化（那是 T016）。
  **覆盖 AC**: AC-01, AC-03, AC-11, AC-23
  **依赖**: T007

- [x] **T012**: prompt helper：temp 标注 + 收集；rag 护栏保持拒绝 UUID
  **文件**: `src/backend/bisheng/citation/domain/services/citation_prompt_helper.py`
  **逻辑**: 新增 `_is_temp_file_document`（`knowledge_id` 非整数 + `document_id` 为 UUID 字符串，见 design 坑 1）。新增 `annotate_temp_documents_with_citations` / `collect_temp_citation_registry_items`，形态对齐 rag / article。`_is_citable_rag_document` **继续拒绝 UUID**，不要为了出角标而放开。标注 / 收集包一层 try/except，失败记 warning、回退为不带该条 key。
  **跨 Feature 影响**: 所有调用 annotate_rag 的入口（工作流 / 日常 / 助手）不受影响，除非它们开始改调新函数。
  **设计依据**: design §3 决策 5 · §5 坑 1、坑 7
  **测试**: T011 全绿，T003 仍全绿
  **覆盖 AC**: AC-01, AC-03, AC-23
  **依赖**: T007, T011

- [x] **T013**: 改写 F054 临时来源关断单测 → 登记为 temp
  **文件**: `src/backend/test/workflow/test_temp_file_no_citation.py`
  **逻辑**: **只改测试、不改实现**。原「ephemeral 工具不被包装 / 不产生来源」改为：ephemeral 工具**被**包装；召回临时文档后 registry 项 `type=temp`、前缀 `tempsearch_`；同一轮正式知识库工具仍走 rag。保留「UUID 不得被当成 rag 可引用」护栏。文件头注释改为 F062 取代 F054 AC-16 / AC-17。本任务提交后会红，直到 T015 转绿。
  **覆盖 AC**: AC-01, AC-11
  **依赖**: T007

- [x] **T014**: RAG / 知识检索 `type=tmp` 走 temp 标注
  **文件**: `src/backend/bisheng/workflow/nodes/rag/rag.py`, `src/backend/bisheng/workflow/nodes/knowledge_retriever/knowledge_retriever.py`
  **逻辑**: `_knowledge_type` 为 knowledge / space 时仍 `annotate_rag` + `collect_rag`。`tmp`（`init_file_retriever` 那条）改调 `annotate_temp` + `collect_temp`。不要继续对 UUID 文档空转 rag annotate（会留下空 `<chunk_id>`，诱使模型幻觉 `knowledgesearch_*`）。
  **跨 Feature 影响**: 两文件是工作流检索入口；正式库 / 知识空间分支零行为变化。
  **设计依据**: design §3 决策 5 · §5 坑 6、坑 7
  **测试**: T011 全绿；用 tmp 文档走节点调用路径时 `citation_key` 为 `tempsearch_`
  **覆盖 AC**: AC-01, AC-11
  **依赖**: T010, T012

- [x] **T015**: Agent 恢复包装 ephemeral 工具，wrapper 走 temp
  **文件**: `src/backend/bisheng/workflow/nodes/agent/agent.py`
  **逻辑**: `_wrap_citation_tool` **删除**「`ephemeral_source=True` 则原样返回」的 skip；ephemeral 工具同样包进 `WorkflowCitationToolWrapper`。`_format_knowledge_results` / `_aformat_knowledge_results`：若 `self.tool.ephemeral_source`，走 `annotate_temp` + `collect_temp`，否则仍走 rag。只恢复包装不够——wrapper 今天无条件 `annotate_rag`，UUID 仍会被护栏跳过。保留 `ephemeral_source` 标记位（语义从「跳过」改为「走 temp」）。
  **跨 Feature 影响**: `executor.py` 继续给 tmp 工具打 `ephemeral_source=True`，本任务不改 executor。正式知识库工具包装路径不变。
  **设计依据**: design §3 决策 5 · §5 坑 6、坑 8
  **测试**: T013 全绿；T011 混用断言仍绿
  **覆盖 AC**: AC-01, AC-11
  **依赖**: T012, T013

### Wave 4 — 持久化（F043 键）+ 解析授权

- [x] **T016**: 引用原件提升 + cache 刷新 单测
  **文件**: `src/backend/test/citation/test_temp_persist_object_name.py`
  **逻辑**: mock `promote_chat_attachments`：①答案实际引用的 temp 项，落库 payload 带主桶 `objectName`（`chat/{user_id}/{uuid}.ext`），且运行时 cache 同步被刷新为同一 `objectName`（不是临时桶 URL）。②未引用文件不调用提升。③重复处理同一条回答不插入重复 `message_citation`。④提升 / 写 cache 抛错时问答仍成功、该条溯源被丢掉（AC-23）。⑤对象键必须是消息 `files` 能收集到的那种，禁止断言任何 `workflow_temp/` 前缀。
  **覆盖 AC**: AC-07, AC-08, AC-09, AC-23
  **依赖**: T007

- [x] **T017**: temp 解析授权单测（会话归属 + 安全序）
  **文件**: `src/backend/test/citation/test_temp_resolve.py`
  **逻辑**: 按 design 决策 3 的顺序各一例：①已登录且 `MessageSession.user_id == login_user.user_id` → 返回 payload，含现签 URL，**不**查 `KnowledgeFileDao` / `view_file`。②`login_user is None`（分享页 / 免登录独立工作流，含上传者点自己刚传的文件）→ `forbidden`。③已登录但会话归属不匹配 → `forbidden`。④会话可读但 MinIO 对象不存在 → `expired`。⑤无权限与对象缺失同时成立 → 仍 `forbidden`（不泄漏存在性）。⑥temp **不得**让 `_is_anonymous_readable` 变 True。⑦citation 端点继续只认 JWT：测试保持 `login_user=None` 即拒绝，不要为「方便点开」给 citation 路由加 share-token Depends。
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18
  **依赖**: T007

- [x] **T018**: 答案落库前补齐 `objectName` 并刷新 cache
  **文件**: `src/backend/bisheng/worker/workflow/redis_callback.py`；如提升/刷新 cache 不宜内联，第二文件放 `src/backend/bisheng/citation/domain/services/citation_prompt_helper.py`（例如 `attach_temp_object_names`），**禁止**再开第三文件或新前缀模块。
  **类别**: Worker（既有回调，**不新开** Celery 任务）
  **tenant_id**: 不新增传递。`RedisCallback.__init__` 已从 `worker/workflow/tasks.py` `_execute_workflow` 的 `Flow.tenant_id` 注入（F022 INV-T18）；本任务只在 `save_chat_message` 里、`save_message_citations_sync` 之前，对**实际引用**的 temp 项复用 `promote_chat_attachments_sync` 已写出的 `chat/{user_id}/{uuid}.ext`，对不上再对那一个文件调用现有提升，写入 payload `objectName` 后调用既有 `save_citations_sync` / cache 刷新。未引用文件不提升。提升失败记 warning，不让问答失败。
  **跨 Feature 影响**: 该回调是全部工作流消息落库入口——只处理 `citation_type=temp` 的引用项；问题消息的 F043 提升原逻辑不动。
  **设计依据**: design §3 决策 4 · §5 坑 12、坑 13
  **测试**: T016 全绿
  **覆盖 AC**: AC-07, AC-08, AC-09, AC-23
  **依赖**: T016

- [x] **T019**: resolve 服务 temp 分支：会话归属 + 现签，跳过 `view_file`
  **文件**: `src/backend/bisheng/citation/domain/services/citation_resolve_service.py`
  **逻辑**: `_enrich_item` 增加 `CitationType.TEMP` 分支：校验 payload、按 `objectName` 现签 `previewUrl`/`downloadUrl`（不把预签名写入 cache/库）。闸门：无登录 → `forbidden`；有登录则 `MessageSessionDao.async_get_one(chat_id)` 且 `session.user_id == login_user.user_id`，否则 `forbidden`；对象没了 → `expired`。无 `chat_id` 的调试运行：仅放行当前登录执行用户。temp **不要**加入 `_is_anonymous_readable`。**不要**走 `_permitted_file_ids` / INV-7。超管不单开后门。
  **跨 Feature 影响**: 该文件是 F029/F054 解析入口；rag / article / web 分支与匿名安全序（除插入 temp 会话检查外）不改。已登录用户的 INV-7 两档一字不改。
  **设计依据**: design §3 决策 3 · §5 坑 3
  **测试**: T017 全绿，T003 仍全绿（`_is_anonymous_readable` 仍只对 web）
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18
  **依赖**: T017

### Wave 5 — 前端 Client 与 Platform（分开，禁止混目录）

- [x] **T020**: Client 识别 `temp` 并走文件预览（不是知识库预览）
  **文件**: `src/frontend/client/src/components/Chat/Messages/Content/citationUtils.ts`, `CitationSourceIcon.tsx`
  **逻辑**: `normalizeCitationType` 增加 `temp` / `tempsearch` 分支（**不扩展就会被当成 rag**）。新增 `isTempCitation`。来源类型文案对 temp 返回 `com_citation.source_temp_kb`。悬停展示类型名、文件名、snippet。角标颜色继续用 `document`，不新增来源色。**点击跳转在 T021**（`Markdown.tsx`），本任务不改 Markdown。
  **设计依据**: design §3 决策 1 · §5 坑 2 · §2 组件所有权约束
  **覆盖 AC**: AC-04, AC-20, AC-22
  **手动验证**:
  - 打开 http://192.168.106.114:4001/workspace ，工作流输入选「解析并存入临时知识库」，RAG 只绑该临时库，上传 PDF 提问
  - 角标出现；悬浮看到「临时知识库」+ 文件名 + 片段（点击在 T021 验）
  **依赖**: T004, T014, T015, T019

- [x] **T021**: Client 单条详情 404 读取 `reason`；分享页不崩
  **文件**: `src/frontend/client/src/api/chatApi.ts`, `src/frontend/client/src/components/Chat/Messages/Content/Markdown.tsx`
  **逻辑**: `getCitationDetail` 解析 404 body 的 `reason`：`expired` 与 `forbidden` 分态（今天所有 404 都打成 `citationForbidden`）。`Markdown.tsx` 点击：`isTempCitation` 走既有 FilePreview（吃 resolve 返回的 `previewUrl`），**禁止**请求 `/knowledge/file_share`；`notPermitted` / `expired` 保持不可点。文案用 T004 已有 key。历史消息缺结构化溯源时原样保留答案、不补造角标。分享页 / 免登录独立工作流解析失败 → 不可点，**不 throw 到错误边界、不让页面白屏**。`CitationReferencesDrawer` 若仍把单条 404 全当无权限，只改它消费 `getCitationUnresolvedReason` 的那几行（必要时作为本任务第 3 个文件）。
  **覆盖 AC**: AC-05, AC-06, AC-11, AC-17, AC-18, AC-19, AC-24
  **手动验证**:
  - 同一条临时知识库答案：点击角标用文件预览打开原文，不是知识空间页面；无 bbox 的 txt 能打开、能看片段、不假装高亮
  - 无痕窗口打开含临时知识库角标的分享页 → 角标「暂无权限查看该来源」、正文仍在、控制台无渲染崩溃
  - 免登录独立工作流当场上传再点角标：同样不可点（AC-15），不要当成缺陷
  **依赖**: T004, T019, T020

- [x] **T022**: Platform 识别 `temp` 并走文件预览
  **文件**: `src/frontend/platform/src/components/bs-comp/chatComponent/citationUtils.ts`, `CitationSourceIcon.tsx`
  **逻辑**: 与 T020 对等，但 **platform 今天连 article 分支都没有**——本任务加 `temp` / `tempsearch`。若改 `normalizeCitationType` 时 fall-through 仍会把 `article` 当成 rag，**只**补 `article`/`articlesearch` 映射，不改文章点击行为。`getCitationSourceLabel` 在本任务内改走 T005 的 i18n（`citation.tempKb` / `citation.web` / `citation.document`），去掉硬编码「网页」「文档」「临时知识库」。悬停展示类型名、文件名、snippet。**点击跳转在 T023**。
  **设计依据**: design §5 坑 2 · AC-22 两端一致
  **覆盖 AC**: AC-04, AC-20, AC-22
  **手动验证**:
  - 打开 http://192.168.106.114:3001 平台调试会话，同一工作流跑一遍 T020 的上传提问
  - 角标类型名、悬停与工作台一致（点击在 T023 验）
  **依赖**: T005, T014, T015, T019

- [x] **T023**: Platform 详情 404 `reason` + 去掉硬编码中文标签
  **文件**: `src/frontend/platform/src/controllers/API/index.ts`, `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/MessageMarkDown.tsx`
  **逻辑**: `getCitationDetail` 今天走 axios 且**没有** `citationForbidden` 分支——对齐 Client：404 读 `reason`，`expired` ≠ `forbidden`。`MessageMarkDown`：temp 点击走既有 `CitationDocumentPreviewDrawer`（吃 `previewUrl`），禁止 `/knowledge/file_share`；无权限 / 已失效不可点，文案用 T005 的 `citation.noPermission` / `citation.sourceExpired`。`getCitationSourceLabel` 已在 T022 改完，本任务不回改 citationUtils。`CitationReferencesDrawer` 若直接 catch 详情失败，同步接 reason（第 3 个文件上限内）。
  **覆盖 AC**: AC-05, AC-11, AC-17, AC-19, AC-22
  **手动验证**:
  - 平台调试会话：点击临时角标打开文件预览抽屉，不是 `/knowledge/file_share`
  - 平台调试会话分享页 / 无登录打开 → 临时角标不可点、页面不崩
  - 人为删掉 MinIO 对象后，有权限用户看到「来源已失效」而不是「暂无权限」
  **依赖**: T005, T019, T022

### Wave 6 — 验收与落档

- [ ] **T024**: 回归重跑 + 端到端手动验证 + 落档
  **文件**: 本文件「实际偏差记录」段
  **逻辑**: ①重跑 T003，必须仍全绿。②重跑 `test_f054_non_regression.py`、`test_access_scope_tiering.py`（已登录两档）、T006 / T008 / T011 / T013 / T016 / T017。③按 design §7 八步清单走工作台 **和** 平台（含多文件不串源、正式库混用、分享页不可点、免登录当场不可点、无 bbox 格式）。④实现期改变系统认知的偏差回写 design（决策或坑），此处只留一行指针。
  **覆盖 AC**: AC-12, AC-21, AC-22, AC-25
  **依赖**: T020, T021, T022, T023, T018

---

## AC 覆盖对照

| AC | 覆盖任务 |
|----|----------|
| AC-01 | T011, T013, T014, T015 |
| AC-02 | T006, T007 |
| AC-03 | T011, T012 |
| AC-04 | T020, T022 |
| AC-05 | T021, T023 |
| AC-06 | T008, T009, T021 |
| AC-07 | T016, T018 |
| AC-08 | T016, T018 |
| AC-09 | T016, T018 |
| AC-10 | T008, T009, T010 |
| AC-11 | T011, T013, T014, T015, T021, T023 |
| AC-12 | T003, T024 |
| AC-13 | T008 |
| AC-14 | T017, T019 |
| AC-15 | T017, T019, T021 |
| AC-16 | T017, T019 |
| AC-17 | T017, T019, T021, T023 |
| AC-18 | T017, T019, T021 |
| AC-19 | T021, T023 |
| AC-20 | T004, T005, T020, T022 |
| AC-21 | T003, T024 |
| AC-22 | T020, T021, T022, T023, T024 |
| AC-23 | T011, T012, T016, T018 |
| AC-24 | T003, T021 |
| AC-25 | T024 |

---

## 实际偏差记录

> **只留一行指针**，论证写进 design.md（决策 / 坑），这里不重复。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认，再记录。

- 无设计决策偏差。T024 自动化回归 59 绿；design §7 八步工作台/平台手动清单待联调环境验证。
