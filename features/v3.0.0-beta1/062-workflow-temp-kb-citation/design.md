# Design: 工作流临时知识库溯源（F062）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（目标、AC、边界）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
>
> **关联**: [spec.md](./spec.md) · [F054 discovery](../054-unified-citation-entries/discovery.md) · [F054 spec §2.5](../054-unified-citation-entries/spec.md) · [F054 design 决策 6](../054-unified-citation-entries/design.md)
> **版本**: v3.0.0-beta1
> **最后更新**: 2026-09-09（按 design 审查回写：现状、每文件 id、提升复用、cache 时序）

---

## 0. 术语

产品说的「临时知识库」和 citation / F054 里写的「临时文件」不是两个功能，是同一条链路的两层：

| 词 | 指什么 | 在系统里的位置 |
|---|---|---|
| **临时文件** | 用户上传的原件（PDF / Word 等） | MinIO 临时桶，TTL 3 天；输入节点输出变量 `file_path`；问题消息 `files` 在发送时会按 F043 提升到主桶 |
| **临时知识库** | 原件切块、向量化后，给后续检索节点用的 scratch 集合 | Milvus collection（按 embedding 模型命名）+ ES `tmp_workflow_data_new`；`document_id` = UUID，`knowledge_id` = 工作流 ID；**没有** `knowledge` / `knowledge_file` 行 |

工作流输入节点三种策略把两层拆开：

| 策略 | `file_parse_mode` | 临时文件（原件） | 临时知识库（可检索切片） |
|---|---|---|---|
| 解析（不入库） | 表单别名 `parse_only` → 后端 `extract_text` | 有 | 没有，文本塞进 `file_content` |
| **解析并存入临时知识库** | 表单别名 `parse_ingest` → 后端 `ingest_to_temp_kb`（常与 `extract_text` 成对） | 有 | **有** |
| 不解析（原始文件） | 表单别名 `no_parse` → 后端 `keep_raw` | 有 | 没有 |

**本期只做第二种。** 溯源要同时用两层：片段来自临时知识库召回；打开原文来自临时文件对象。

技术类型名仍用 `citation_type=temp`（不是知识库资源，不能复用 `rag`）。用户可见文案用「临时知识库」，不要写内部对象名。

---

## 1. 目标与非目标

- **目标**：工作流输入节点「解析并存入临时知识库」后，RAG / 知识检索 / Agent 召回的内容可以真正溯源：角标可点、悬停看到文件名与引用片段、点击用现有文件预览抽屉打开原文、引用段能展示。PDF 高亮仅在解析管线已产出 `bbox` 时可用。
- **非目标**：见 [spec.md](./spec.md) 范围边界。实现上额外钉死：
  - 不把临时知识库做成正式 `knowledge` / `knowledge_file`，不加 Alembic，不新错误码段。
  - 不改 INV-7 的 `per_user` / `shared`，不把临时来源纳入知识空间 OpenFGA。
  - 不新增角标颜色（设计师未批第三色，复用 `document`）。

F054 AC-16 / AC-17（「工作流 Agent 检索临时文件不得登记溯源」）被本 Feature **取代**：Agent 路径恢复包装，但登记为 `temp` 而不是 `rag`。正式知识库 / 知识空间行为不变。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md` C1–C7。本功能特有：

- **不能走现有 `rag` 解析**。`rag` 假定整数 `documentId`、`knowledge_file` 行、`view_file`。临时知识库三条都不成立；硬塞会继续 404 / 「暂无权限」。
- **`citation_type` 已是 `varchar(32)`**，新增取值 + schema-less `source_payload` → **无 DDL、无 Alembic**（与 F054 文章来源同一套路）。
- **临时桶 3 天 TTL**。历史消息要打开被引用原文（AC-08），必须让引用原件落到主桶；未引用的不必（AC-09）。
- **已有临时 collection 不能改向量 schema**。`InputFileMetadata` 是白名单，未知字段会被删掉；给 Milvus/ES 加 `source_url` 会碰到存量 collection。
- **不得新增对外 API 路径**。复用既有 `/api/v1/citations/{id}` 与 `/citations/resolve`；响应只做向后兼容字段。
- **i18n**：用户可见文案三语齐发，不得硬编码中文。platform 现有 `getCitationSourceLabel` 仍硬编码「网页」「文档」，本 Feature 改到它时必须抽成 i18n。
- **组件视觉归设计师**。角标颜色继续用 `document`。
- **会话删除只从消息 `files` 收集 object_name**（`chat_attachment.py` 注释）。citation 用的永久对象必须能被这条清理链找到，禁止另起一个删会话扫不到的前缀。

---

## 3. 方案对比与选定

### 决策 1：第四种来源类型 `temp`，不把临时知识库当 `rag`

- **备选**：
  - A. 新增 `CitationType.TEMP` + 前缀 `tempsearch_` + 专属 payload（UUID + MinIO object）。
  - B. 入库时写 `knowledge_file`、改用整数 `document_id`，继续走 `rag` + `view_file`。
  - C. 按 F054 把 RAG 路径也关掉，不出角标（方向 A）。
- **选定**：A。
- **原因**：B 把会话上传物伪装成知识库资源，会撞上 OpenFGA `view_file`、INV-7、知识库列表与清理语义，改动面远超溯源。C 已实现过并按用户要求整段撤销；产品要的是能点开。频道文章已经证明新类型无需新表。
- **代价**：前端 `normalizeCitationType` 今天是「web / article，其余一律 rag」（platform 甚至还没有 article 分支）。不显式识别 `temp`，点击会进知识库预览再去 `/knowledge/file_share`（F054 坑 2 的同一类失败）。client 与 platform 都必须加分支。
- **何时该重新考虑**：若产品要把临时知识库升级为可在知识空间里管理的正式库。

### 决策 2：每文件唯一 UUID，不改向量 schema；召回后回填路径

- **备选**：
  - A. 每个上传文件单独 `generate_uuid()` 作为 `document_id`；`init_file_retriever` 收集该变量 metadata **列表里的全部** `document_id`（不是只取 `[0]`）；召回后用图状态 `document_id → file_path` 把原件定位打到 `Document.metadata`。
  - B. 维持今天「`file_id = generate_uuid()` 放在 for 循环外」，同一输入变量下多文件共用一个 id。
  - C. 给 `InputFileMetadata` / Milvus / ES 增加 `source_url` 字段。
  - D. 改成整数 document id 并写 `knowledge_file`。
- **选定**：A。
- **原因**：今天共用一个 id，是 retriever 只取 `file_metadata[0]["document_id"]` 仍能召回该变量全部文件的唯一原因。B 让 `document_id → file_path` 变成一对多，多文件角标会打开错文件，直接违反 AC-10。若只改成每文件唯一 id、却不改 retriever，其余文件会从召回里消失。C 要改已有 tmp collection schema。D 即决策 1 的 B。原文 URL 已经在输入节点输出变量 `file_path` 里，与 metadata **按文件下标**对齐，只是没进向量。
- **何时该重新考虑**：若临时知识库生命周期超过单次工作流运行、需要跨会话检索同一份文件。

### 决策 3：授权对齐文章来源，不走 OpenFGA；会话可读落在既有判定

- **备选**：
  - A. 已登录且能读该会话 → 放行；匿名 → `forbidden`；记录或对象没了 → `expired`。
  - B. 给临时文件造 OpenFGA 资源类型，走 `view_file`。
  - C. 只要有 citation_id 就返回（含分享页匿名）。
- **选定**：A。
- **原因**：临时知识库不是知识空间资源，B 是假 C4。C 会把会话上传物泄漏到分享链接（F054 已收紧匿名解析）。口径与文章来源同构：可见性在作答时由「谁能跑这条工作流 / 谁能读这条会话」决定，解析时不再做知识库级鉴权。
- **会话可读的落点**（不要在 citation 层发明第二套）：
  - 有 `chat_id`：`MessageSessionDao.async_get_one(chat_id)`，`session.user_id == login_user.user_id`。与会话历史 / `chat_message_service`（`chat_message.user_id != login_user.user_id` → 未授权）同一条归属判定。
  - 无 `chat_id` 的调试运行：不落库；本轮 cache 解析仅放行当前登录的执行用户。不存在「匿名调试」。
  - 超管不单开后门：跟现有会话历史接口一致。
- **判定顺序**（沿用 F054 决策 5 的安全序，并插入会话可读）：
  1. 无已登录用户 → `forbidden`（不泄漏存在性）。**已裁定**：免登录独立工作流上传者点自己刚传的文件走这一条，不可点（spec AC-15）。
  2. 记录在缓存和库里都没有 → 已登录则 `expired`，匿名仍 `forbidden`。
  3. 记录存在但当前用户读不到该会话 → `forbidden`。
  4. 记录存在、会话可读，但 MinIO 对象没了 → `expired`。
- **不要把 share-token / 默认操作人当成登录用户来放行 temp**。访客页的执行主体是发布者，所有访客共用；当成已登录会让整条发布链接上的人都能打开别人的上传件。F053 落地后 citation 解析仍以「自然人已登录」为准，share-token 只证明「允许连这条发布应用」，不打开 temp。
- **何时该重新考虑**：产品要「当场能点开」时，另做按 `chat_id` 绑定的访客票（sessionStorage + Redis），不复用 share-token；或会话协作者模型变化。

### 决策 4：复用 F043 已提升的 `object_name`，不另起对象前缀

- **备选**：
  - A. 优先从**同一会话问题消息**的 `files[].object_name` 取已提升对象（`promote_chat_attachments` 在 `redis_callback.save_chat_message`、`category=question` 时已经跑过，键为 `chat/{user_id}/{uuid}.ext`）。对不上再对那一个被引用文件调用现有提升；把 `objectName` 写入 citation payload，并确保该键仍挂在某条消息的 `files` 上，以便删会话能清掉。
  - B. 输入节点入库时就把所有上传文件提升到主桶。
  - C. 不提升，解析时继续签临时桶 URL。
  - D. 答案落库时按新前缀 `chat_attachments/{user_id}/workflow_temp/...` 再拷一份。
- **选定**：A。
- **原因**：C 三天后历史消息全部「来源已失效」（违反 AC-08）。B 会把未引用的大文件也永久留下（违反 AC-09）。D 二次拷贝，且会话删除只扫消息 `files`，新前缀会变成孤儿对象（C8）。问题消息发送时原件往往**已经**在主桶；citation 缺的是「引用载荷指向那个 `object_name`」，不是再搬一次。
- **载荷与 cache 时序**（必须写死，否则 3–30 天窗口会假 `expired`）：
  1. 登记时 payload **只存稳定定位**：`documentId`（UUID 字符串）+ 原件 URL / 已有 `objectName`；**不持久化预签名 URL**。
  2. 答案落库前：解析出被引用文件 → 填上主桶 `objectName` → `save_message_citations` → **同步更新运行时 cache**（resolve 是 cache 优先，TTL 30 天；不刷新就会继续签临时桶，TTL 过后对象没了）。
  3. resolve 现签主桶；对象不存在 → `expired`。流式期间若提升尚未完成，可对仍在的临时对象现签，不得把过期签名写进 cache。
- **何时该重新考虑**：若临时桶 TTL 调整，或产品要求「上传即永久保留」。

### 决策 5：打开 F054 的两个关断点，但分流到 `temp` 而不是放行 `rag`

- **备选**：
  - A. `ephemeral_source=True` 继续标识「这是临时来源」；Agent `_wrap_citation_tool` **恢复包装**，wrapper 走 `build_temp_registry`。`_is_citable_rag_document` **继续拒绝 UUID**，另增 `_is_temp_file_document` 只给 temp 登记用。RAG / 知识检索 `type=tmp` 走 temp collect。
  - B. 放开 `_is_citable_rag_document`，让 UUID 进 `rag` 登记。
  - C. 维持 F054：Agent 不包装，RAG 也不登记。
- **选定**：A。
- **原因**：F054 决策 6 写明「下一版打开时这两处就是接入点」。B 会把临时 chunk 写进要求整数 id 的 RAG payload，解析仍然失败。C 是方向 A，已否。今天 RAG 路径**已经不会出半残角标**：`annotate_rag_documents_with_citations` 因 UUID 护栏不发 `citation_key`，`collect_rag` 直接跳过；用户看到的是无角标 + 空 `<chunk_id>` 幻觉风险，不是点开 404。本 Feature 要做的是**打开 temp 登记**，不是去修一条已经不存在的半残路径。
- **混用**：Agent 同时绑正式库和临时库时按文档分流——整数 id → `rag`，否则 → `temp`。知识检索 `type=knowledge/space` 行为不变。RAG 节点一次只选 knowledge / space / tmp 之一，混用发生在多节点或 Agent 多工具。
- **何时该重新考虑**：无。这是本 Feature 的开关语义。

### 决策 6：保留解析管线 bbox；文件级 metadata 不得回写覆盖

- **备选**：
  - A. 文件级 dict **不要带** `bbox` / `page` / `chunk_index`。`one.update(all_metadata[-1])` 只合并身份字段（`document_id` / `document_name` / `knowledge_id` / 时间戳）。保留 `TempFilePipeline` 产出的 bbox / page。没有则片段仍可展示，PDF 不定位。
  - B. 只删掉 `"bbox": ""` 这一行，其余不动。
  - C. 本期不做 bbox，一律只展示片段。
- **选定**：A。
- **原因**：覆盖注释写的是「临时文件无法溯源因为原件不持久化」。原件可打开后这条理由不成立。B 不够：真正盖掉 parser 产出的是 `one.update(...)` 整表覆盖，文件级只要带 `bbox` 键就会把管线结果打成空串。不保证所有格式都有 bbox，避免把「PDF 高亮」做成假承诺。
- **何时该重新考虑**：若要为非 PDF 做页内定位，需要独立解析能力，不在本期。

### 决策 7：用户可见类型名用「临时知识库」，技术枚举用 `temp`

- **备选**：
  - A. payload / API 枚举 `temp` + 前缀 `tempsearch_`；界面文案「临时知识库」。
  - B. 枚举也叫 `temp_kb` / `temporary_knowledge`，与产品词对齐。
  - C. 复用 `rag`，只改前端文案。
- **选定**：A。
- **原因**：用户纠正 F054「临时文件」口径；内部对象名不能出现在 UI。`temp` 表示「非知识库文件的会话内来源」，避免和正式 `rag` 知识库混淆。B 加长枚举没有收益，前缀风格已与 `websearch_` / `articlesearch_` 对齐。C 即决策 1 的反面。
- **何时该重新考虑**：若后续日常附件 / 灵思上传也接入同一类型，再评估是否拆类型或只改文案。

---

## 4. 系统现状（接手必读）

### 4.1 今天的代码行为（F054 落地后）

用户投诉的「角标暂无权限 / 右侧加载失败 / 原文打不开」是 **F054 之前**把临时 chunk 登记成 `rag` 的半残态。当前仓库已经不是那个状态：

```
输入节点 ingest_to_temp_kb
  → 临时向量库（同一变量下多文件目前共用一个 UUID document_id）
  → RAG / 知识检索 type=tmp：仍调用 annotate_rag_documents_with_citations
       → _is_citable_rag_document 拒绝 UUID → 不发 citation_key
       → collect_rag 跳过 → 不落库、不出角标
       → format_retrieved_chunk 的 <chunk_id> 为空 → 模型可能幻觉 knowledgesearch_*
  → Agent tmp 工具：ephemeral_source=True → _wrap_citation_tool 直接跳过 → 同样无角标
```

| 用户现在可能看到的 | 实际判定点 |
|---|---|
| 临时知识库问答**没有**对应角标 | F054 双层关断（Agent skip + UUID 护栏） |
| 偶发未注册角标闪一下 | 空 `<chunk_id>` + 默认 RAG 提示词仍含引用规则；流式结束会 scrub |
| 历史消息里**旧的**半残 rag 角标 | F054 之前已落库的 `citation_type=rag`；点开仍 404 / 「暂无权限」——本 Feature 不回填、不修复（AC-24） |
| client 角标悬停「暂无权限」 | `chatApi.ts` `getCitationDetail` 对所有 404 设 `citationForbidden`，不读 body `reason` |
| platform 详情失败形态不同 | platform `getCitationDetail` **没有** `citationForbidden` 分支，走 axios；`getCitationSourceLabel` 硬编码中文 |

方向 A（把 RAG 也关停、完全不出角标）曾落地后又整段撤销；当前代码 = F054 基线（关 Agent + UUID 护栏，RAG 调用 annotate 但是空转）。本 Feature 的目标数据流见 §4.2，不是去恢复半残 rag 角标。

### 4.2 目标数据流

```
输入节点 parse_upload_file（ingest_to_temp_kb）
  → 每文件唯一 UUID；文件级 metadata 不带 bbox/page；保留管线 bbox/page
  → file_path 与 metadata 按下标对齐进图状态
  → RAG init_file_retriever 收集该变量全部 document_id
  → 召回后按 document_id 回填原件定位
  → 登记 citation_type=temp（前缀 tempsearch_），cache 只存稳定定位
  → 答案落库：复用/补齐主桶 object_name → 刷新 cache → save_message_citations
  → GET/POST /citations：登录且会话归属匹配 → 按 objectName 现签
  → 前端按 temp 打开 FilePreview 抽屉，展示 snippet；无 bbox 则不定位
```

### 4.3 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| `citation_type` | `"temp"` | 第四种来源；列已是 varchar(32) | registry / resolve / 两端前端 |
| 前缀 | `tempsearch_` | 模型可见标记，对齐 `knowledgesearch_` / `websearch_` / `articlesearch_` | prompt helper / strip 未注册标记 |
| `document_id`（向量 metadata） | UUID hex 字符串，**每文件一个** | 输入节点循环内 `generate_uuid()`，**不是** int | temp 登记 / 与 `file_path` 映射 |
| `knowledge_id`（向量 metadata） | 工作流 ID 字符串 | 不是知识库主键 | `_is_temp_file_document` 护栏 |
| `source_payload.objectName` | 主桶对象键 `chat/{user_id}/{uuid}.ext` | 与 F043 会话附件同一套；resolve 现签 | resolve / 会话删除 |
| `source_payload.documentName` | 文件名 | 角标 / 来源列表 | 前端 |
| `source_payload.snippet` | 召回片段 | 悬停 / 右侧面板 | 前端 |
| `source_payload.items[]` | `{ itemId, content, bbox, page, chunkIndex }` | 引用段；bbox 可空 | 预览定位 |
| `source_payload.previewUrl` / `downloadUrl` | 现签 URL | **只在 resolve 时生成**，不写入 cache / 库 | 预览抽屉 |

登记载荷不含整数 `documentId` / `knowledgeId`。temp 的 `documentId` 若出现在 JSON 里也是 UUID 字符串，不要塞进 `RagCitationPayloadSchema` 的 `int` 字段。

### 4.4 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `workflow/nodes/input/input.py` `parse_upload_file` | 每文件唯一 UUID；身份字段与管线 bbox 分离；输出 `file_path` | 不写 `knowledge_file`；文件级 dict 不带 `bbox`/`page` |
| `workflow/common/knowledge.py` `init_file_retriever` | 收集该变量 **全部** `document_id`；召回后回填原件定位 | 不改 knowledge/space 路径；不只取 `[0]` |
| `workflow/nodes/rag/rag.py` / `knowledge_retriever.py` | `type=tmp` 走 temp annotate + collect | 正式库仍走 rag |
| `tool/domain/services/executor.py` `init_tmp_knowledge_tool_sync` | 继续打 `ephemeral_source=True` | 不负责登记 |
| `workflow/nodes/agent/agent.py` `_wrap_citation_tool` | 对 ephemeral 工具恢复包装，走 temp registry | 不把 UUID 登记为 rag |
| `citation_prompt_helper.py` | `_is_citable_rag_document` 继续拒 UUID；新增 `_is_temp_file_document`；临时 chunk 写入真实 `citation_key` | 不发空 `<chunk_id>` |
| `citation_registry_service.py` | `CitationType.TEMP`、`TEMP_PREFIX`、`build_temp_registry`；`_load_source_payload` **必须**加 temp 分支 | 不 invent 整数 documentId；未知类型不得再落到 Web schema |
| `core/storage/chat_attachment.py` `promote_chat_attachments` | 被引用且尚未提升的原件走现有提升 | 不新前缀 |
| `worker/workflow/redis_callback.py` | 落库前补齐 `objectName`、刷新 cache、再 `save_message_citations` | 不提升未引用文件 |
| `citation_resolve_service.py` | temp 分支：会话归属 + 现签；跳过 `KnowledgeFileDao` / `view_file` | 不把 temp 加入 `_is_anonymous_readable`；不走 INV-7 两档 |
| client / platform `citationUtils.ts` | `normalizeCitationType` 识别 `temp` / `tempsearch` | 不走 `/knowledge/file_share` |
| client `chatApi.ts` `getCitationDetail` | 404 读 `reason`：`expired` ≠ `forbidden` | 不把所有 404 当无权限 |
| platform `controllers/API` `getCitationDetail` | 同样区分 `reason`；文案走 i18n | 不能只改 client；现有实现与 client 不是同一套 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `_is_citable_rag_document` 只拒绝**出现了且不可解析为 int** 的 `document_id`；缺 id 时仍按文件名分组登记为 rag | 召回丢掉 id 后，临时文件会再次混进 rag，点开空白 | temp 分流必须同时看 `knowledge_id` 非整数；rag 护栏保持拒绝 UUID |
| 2 | 前端 `normalizeCitationType`：非 web / article 一律当 rag（platform 连 article 都还没有） | 新类型不登记就会进知识库预览抽屉，预览空白（F054 坑 2） | client + platform 两边加 `temp` |
| 3 | client `getCitationDetail` 把所有 404 标成 `citationForbidden`；platform 走 axios，**没有**该分支 | 只改 client，平台调试会话仍分不清失效 / 无权限 | 两端都解析 body `reason` |
| 4 | `input.py` 用 `"bbox": ""` **加上** `one.update(all_metadata[-1])` 覆盖 parser bbox | 只删空串赋值不够，PDF 仍然无法定位 | 文件级 metadata 不带 bbox/page/chunk_index（决策 6） |
| 5 | `InputFileMetadata` 白名单会删掉未知字段，原文 URL 进不了向量 | 只改 metadata 字典不够，召回时没有原件定位 | 召回后从图状态回填 |
| 6 | Agent 已按 F054 跳过 ephemeral 包装；RAG 仍调用 annotate，但 UUID 护栏让它空转 | 只改 Agent 会以为主问答「已经关掉了」；只看「仍在 annotate」会误以为还有半残角标 | RAG / 知识检索 `type=tmp` 必须走 **temp** 登记；不要把「半残 rag 角标」当现状 |
| 7 | 默认 RAG 提示词仍有引用规则；空 `<chunk_id>` 会诱使模型幻觉 `knowledgesearch_*` | 关掉登记后仍可能闪未注册角标 | 临时 chunk 发真实 `tempsearch_` key |
| 8 | 方向 A 曾落地（关 RAG 角标）后又整段撤销 | 不要把 `test_temp_file_no_citation.py` 或「tmp 不 annotate」当成当前目标 | 本 Feature 要的是能点开；该测试改为「登记为 temp」 |
| 9 | 预览抽屉吃的是 `fileUrl`，不是知识库 file id | 只要 resolve 返回了 URL，不必新做预览组件 | 关键是 `objectName` + 现签，不是新 UI |
| 10 | `parse_upload_file` 今天把 `generate_uuid()` 放在循环外；`init_file_retriever` 只取 `file_metadata[0]` | 每文件唯一 id 而不改 retriever → 只召回第一份；不改 id → 多文件串源 | 决策 2 两条必须一起做 |
| 11 | `_load_source_payload` 未知类型走 `WebCitationPayloadSchema` | 加了 `CitationType.TEMP` 却漏 load 分支 → 校验失败或字段被吃掉 | registry load / resolve `_enrich_item` 与枚举同一波次落地 |
| 12 | resolve **cache 优先**（TTL 30 天），提升发生在落库前 | cache 里若仍是临时桶 URL，3 天后主桶有副本也会 `expired` | 落库时写入 `objectName` 并刷新 cache（决策 4） |
| 13 | 会话删除只收集消息 `files` 里的 `object_name` | citation 若用独立对象键，删会话留下孤儿对象 | 复用 F043 的 `chat/{user_id}/...` 键（决策 4） |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `citation_type=temp` + `tempsearch_` 前缀 | `message_citation.citation_type` / 答案内联标记 | client、platform、strip 未注册标记 |
| `CitationRegistryService.build_temp_registry` / `_load_source_payload` temp 分支 | 内部 Python | RAG / 知识检索 / Agent wrapper、历史回放 |
| 既有 `GET /api/v1/citations/{id}`、`POST /api/v1/citations/resolve` 对 temp 的解析语义 | HTTP；404 `reason` = `forbidden` \| `expired` | 两端角标 / 参考来源抽屉 |
| temp payload（无整数 documentId，含 `objectName` / snippet / items；URL 仅 resolve 时出现） | JSON `source_payload` | 预览抽屉、悬停 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F054 文章类型扩展点（枚举 + payload load + resolve 分支 + 前端 normalize） | 既有 citation 子系统 | 漏改前端会重复坑 2；漏改 `_load_source_payload` 会重复坑 11 |
| F054 匿名拒绝知识库 / 文章详情 | resolve 安全序 | temp 必须同样拒绝匿名，且不得加入 `_is_anonymous_readable` |
| F043 `promote_chat_attachments` + 问题消息 `files` | MinIO 临时桶 → `chat/{user_id}/{uuid}` | 提升失败则历史消息只能 `expired`；对象键必须能被会话删除收集 |
| `MessageSessionDao.async_get_one` / 消息 `user_id` 归属 | 既有会话访问判断 | 协作者模型若变，temp 授权要跟着变 |
| 输入节点 `file_path` 与 metadata 按**文件**下标对齐 | 图状态 | 错位会签错文件；循环外 uuid 会让映射坍缩 |
| INV-7 / `view_file` | 不调用 | 误走 rag Enrich 会再次 404 |

### 6.3 对 F054 的关系

- **取代** F054 AC-16 / AC-17 中「临时文件不出角标」——仅针对工作流 `ingest_to_temp_kb` 召回。
- **保留** `_is_citable_rag_document` 对 UUID 的拒绝（防止混进 rag）。
- **保留** `ephemeral_source` 标记位，语义从「跳过」改为「走 temp 登记」。
- 日常附件、灵思上传仍按 F054 discovery §4.5 排除。

落地前更新 [release-contract.md](../release-contract.md) 表 1：无新表，Owner = F062，说明扩展第四种 `citation_type`。F054 行改为「不再拥有临时来源是否出角标」的写语义。表 3 增加 F062 依赖 F054。

---

## 7. 测试与可观测

- **单元 / 集成**（`src/backend/test/citation/` 或 `test/workflow/`）：
  - 每文件唯一 `document_id`；retriever 收集全部 id；两文件引用互不串源。
  - temp 登记前缀为 `tempsearch_`，payload 无整数 `documentId`，`_load_source_payload` 能 round-trip。
  - 正式库 + 临时库混用：整数 id → rag，UUID → temp。
  - 匿名 resolve → `forbidden`；会话非归属人 → `forbidden`；对象删除 → `expired`。
  - 落库后 cache 中的 payload 带主桶 `objectName`，不再是临时桶 URL。
  - 未引用文件不要求提升；`_is_citable_rag_document` 仍拒绝 UUID。
  - 正式知识库 / 知识空间 / 文章 / 网页回归。
- **前端**（client **和** platform）：
  - `normalizeCitationType` 识别 `temp`；点击走 FilePreview 而不是 `/knowledge/file_share`。
  - 404 `reason=expired` 显示「来源已失效」，不再显示「暂无权限」。
  - 三语文案「临时知识库」；platform 去掉硬编码「网页」「文档」时不得只改一处。
- **手动**（本地起前后端 + 连 test 环境中间件）：
  1. 后端：`cd src/backend && export config=config.yaml && uv run uvicorn bisheng.main:app --port 7860`
  2. 工作台：`cd src/frontend && pnpm dev:client`（`:4001`，base `/workspace`）
  3. 平台：`cd src/frontend/platform && pnpm start -- --host 0.0.0.0`（`:3001`）
  4. 工作流输入节点选「解析并存入临时知识库」，RAG 只绑该临时库，上传一份 PDF 提问 → 角标可点、右侧有引用段、能打开原文。
  5. 同一输入再传第二份文件，问能分别命中的问题 → 两条来源、打开的是各自原件。
  6. 同工作流再绑正式库 → 两类角标并存、跳转各走各的。
  7. 未登录打开该会话分享页 → 临时来源不可点，文案为无权限，页面不崩。免登录独立工作流当场上传再点角标：同样不可点（AC-15），不要当成缺陷。
  8. 无 bbox 的格式（如纯文本）→ 能打开、能看片段、不假装高亮。
- **日志**：提升失败、resolve 时对象不存在，打 warning，不要让问答失败（spec AC-23）。

---

## 8. 落地顺序

spec.md 已写。任务拆解见 [tasks.md](./tasks.md)（24 项 / 6 Wave）。实现波次：

1. Schema：`CitationType.TEMP` + payload + `TEMP_PREFIX` + registry load/enrich（先堵住坑 11）。
2. 输入节点：每文件唯一 id；文件级 metadata 不覆盖 bbox；retriever 收集全部 id；召回回填原件定位。
3. RAG / 知识检索 / Agent：按类型分流登记；临时 chunk 发真实 key。
4. 持久化：复用 F043 `object_name` + 刷新 cache + `save_message_citations`。
5. Resolve：跳过 `view_file`，按会话归属 + 现签 URL。
6. Client + platform：`normalizeCitationType`、预览分派、404 `reason`、三语文案。
7. 改写 `test_temp_file_no_citation.py` + 正式库回归。

---

## 9. 后续改进 / 不打算做的事

- 日常模式附件要溯源，必须先改成检索而不是整段拼提示词，机制变更，单独立项。
- 灵思工作区翻阅文件接入溯源，见 F047 候选 Phase 1.5。
- 非 PDF 的页内定位、临时知识库跨会话复用、把 tmp collection 收进知识空间权限模型：均不在本期。
- 来源类型继续膨胀时，把「类型 → 载荷 → 图标 → 点击」抽成注册表（F054 决策 2 已记），本期仍加分支。
- 免登录独立工作流「当场打开自己刚传的文件」：已裁定本期不做。若要做，须另立项发按会话绑定的访客票，不能无登录放行 temp，也不能拿 share-token / 默认操作人当上传者。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-09 | 初版实现方案 | 工作流临时知识库问答要能溯源；产品选定方向 B，并纠正「临时文件 / 临时知识库」口径 |
| 2026-09-09 | 审查回写：重写现状；每文件唯一 id + retriever 收集全部 id；提升复用 F043 键并刷新 cache；bbox 用「文件级不带键」而不是只删空串；会话鉴权落到 `MessageSessionDao`；补坑 10–13 | `/sdd-review design`：半残角标现状过时、循环外 uuid、新对象前缀与会话删除冲突、cache 时序 |
| 2026-09-09 | 免登录独立工作流：上传者点自己刚传的文件按无登录不可点（取消待澄清） | 用户裁定；share-token 不得冒充登录用户放行 temp |
