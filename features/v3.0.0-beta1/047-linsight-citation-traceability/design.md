# Design: 灵思任务模式引用溯源（角标溯源）

> **本文档定位 — 现状快照（Why this How）**。spec 回答做什么；本文回答为什么这么实现 + 反直觉事实 + 对外契约。

**关联**: [spec.md](./spec.md)
**版本**: v3.0.0-beta1（原 v2.6.0 F040，改编为 F047，见 spec 抬头）
**最后更新**: 2026-07-27（迁入 v3.0.0-beta1 版本线；设计内容未变，仍为实现前初版）

---

## 1. 目标与非目标

- **目标**：把灵思**任务模式**的报告产出接入 BiSheng **既有的 citation 溯源子系统**（`bisheng/citation/`，日常对话模式已在用），让报告正文出现可点击的内联角标，回看知识库原文件（bbox 定位）或原网页。**最大化复用、最小化改动、零新增前端（Phase 1）**。
- **非目标**：
  - 不自研任务模式专属的溯源机制；不新增溯源相关的领域对象/表/事件类型/迁移。
  - Phase 1 不改下载的 Word/PDF（Phase 2）；不做「参考资料」汇总面板；不做引用修复 pass。
  - 不改灵思底层检索的**文件级可见性**（F029/F035 范畴）；本 feature 只在角标呈现面复用其过滤。
  - 不动日常模式。

---

## 2. 关键约束

- 全局铁律遵循 `docs/constitution.md` C1–C7（分层 / 双 DB / 多租户 / 权限 / 错误码），本节只列本功能特有：
- **INV-7（硬约束，release-contract 表 2）**：知识库内容的「AI 问答可检索可见性」⊆「列表 UI 可见性」。对无 `view_file` 的 `(user, file)`，其 chunk / 文件名 / 来源**不得**出现在 `/api/v1/citations/resolve` 响应的结构化字段中。→ 本 feature 通过复用 `CitationResolveService` 的 `_filter_visible_rag_items` 满足；这是**安全红线**，不是可选项。
- **`MessageEventType` 10 枚举冻结**（F035 契约）：溯源不得新增流式事件类型。
- **DM8 写放大红线**：`LinsightExecuteTask.history` 大 JSON 频繁全量重写曾撑爆达梦 undo（见 `project_linsight_dm8_history_write_amplification`）。→ 溯源数据**不**逐步写 history，只进 Redis（每次工具调用）+ 完成时一次 `message_citation` 批量插入。
- **灵思工具「绝不 raise」契约**：工具内异常会穿透 deepagents tool node 杀掉整个任务（见 `linsight_knowledge.py` / `linsight_export.py` 注释）。→ 引用注解全部包窄 try/except，失败回退裸结果。
- **无 alembic 迁移**：复用现成 `message_citation` 表；`output_result` 若需附加字段也是 schema-less JSON，无 DDL。

---

## 3. 方案对比与选定

### 决策 1：整体路线 —— 复用 citation 子系统，而非自研或 Skill/提示词

- **备选**：
  - A. **复用 `bisheng/citation/`**：让任务模式的检索工具走与日常模式相同的 annotate→collect→cache→resolve 链路，模型发相同的 Unicode 私用区标记，前端复用相同渲染器。
  - B. **自研任务模式专属溯源**：新建 sources 数据结构 + 新前端组件 + 新 resolve。
  - C. **Skill / 提示词让模型自己在文末写「参考资料」列表**：零代码，纯 prompt/Skill。
- **选定**：A。
- **原因**：
  - **C 从根上走不通**——今天 `search_knowledge_base` 只把 `page_content` 交给模型（`linsight_knowledge.py:92` 丢弃 `Document.metadata`），模型**根本看不到 chunk 来自哪个文件/页**。让模型自己写文献表 = 让它**凭空编造文件名**，与「可信溯源」正相反。这恰好证明：无论用不用 Skill，都必须先在**工具边界**把来源身份暴露出来。
  - 一旦来源身份已流出，B 相比 A 没有任何收益却要重造 registry / resolve / 前端渲染 / **INV-7 权限过滤**（安全红线，A 现成、B 得重写且易错）。
  - A 的前端成本为 **0**：任务模式报告预览已复用日常模式同一个 citation-capable 渲染器（`PreviewBody.tsx:261` → `Chat/Messages/Content/Markdown`）。
  - 对标 ChatGPT / Gemini Deep Research：其溯源本质就是「检索时给来源分配稳定 ID → 模型按 ID 内联引用 → 渲染层解析成可点击卡」。BiSheng 的 citation 子系统就是这套架构，任务模式只是没接线。
- **关于「Skill 减小改动量」（用户特别问）**：Skill 无法减小改动——(1) 元数据缺口是工具边界的代码级问题，Skill 救不了；(2) 溯源须**常开**（用了 KB/Web 就生效），而 Skill 是用户按会话勾选的，skill-gating 会让溯源时有时无；(3) 来源身份流出后复用现成模块 ≈ 手写文献表的成本，却白拿可点击/过滤/bbox。结论：Skill 只会分散逻辑、增加复杂度。
- **何时该重新考虑**：若未来 citation 子系统被大改或下线；或任务模式产物彻底脱离 Markdown 预览（如纯二进制），则 A 的「前端零改动」前提失效，需重估。

### 决策 2：KB 元数据在工具边界保留并接入 registry（改 `base_search`），不换用日常模式 KB 工具

- **备选**：
  - A. 改 `SearchKnowledgeBase.base_search`：保留 `Document`，补 `knowledge_id`/`knowledge_name`，调 `annotate_rag_documents_with_citations`→`collect_rag_citation_registry_items`→`cache_citation_registry_items`。
  - B. 把灵思 KB 工具整体换成日常模式的 `search_knowledge_bases`（已内建注解链路）。
- **选定**：A。
- **原因**：B 的日常工具签名/`CitationRegistryCollector` 注入/白名单语义与灵思不同（灵思有 `allowed_knowledge_ids` 逐 id C4 白名单 + `knowledge_id` 入参 + 「绝不 raise」软错误契约），整体替换比 ~15 行的 A 更大更险。A 里两工具最终调用的是同一批 `citation_prompt_helper` 函数，天然 DRY。
- **何时该重新考虑**：若两条 KB 检索路径要统一为一个 Service，再评估合并。

### 决策 3：收集机制 = 写 Redis 运行时缓存（无内存 collector）

- **备选**：
  - A. 每个检索工具把 registry item 写进**进程级 Redis 运行时缓存**（`cache_citation_registry_items`，按 citationId 存），完成时按报告里出现的 citationId 反查。
  - B. 复刻日常模式的 `CitationRegistryCollector` 内存对象，跨主图/子代理线程化传递。
- **选定**：A。
- **原因**：任务模式的 registry 收集要跨 **researcher 子代理**（deepagents 子图独立的工具调用流）。B 需要把 collector 穿透进子图，触及线程化风险（历史上 `active_skills` 未线程化就踩过坑）。A 用 Redis 全局天然跨子图，且**前端本就从报告文本里的标记惰性解析 citationId**（不依赖任何推送的 registry），所以根本不需要 collector 这个「把 registry 推给前端」的对象。
- **何时该重新考虑**：若 Redis 不可用的部署形态出现（目前灵思强依赖 Redis queue，不成立）。

### 决策 4：持久化复用 `message_citation`（message_id = 任务轮 `ChatMessage.id`），不塞 `output_result`

- **备选**：
  - A. 完成时 `save_message_citations(message_id=task_msg.id, items, chat_id=session_id)`，写既有 `message_citation` 表。
  - B. 把 sources 塞进 `LinsightSessionVersion.output_result["sources"]`。
- **选定**：A。
- **原因**：A 直接复用 `CitationResolveService`——它是 **INV-7 的执行点**（`_filter_visible_rag_items` 按查看者逐文件跑 `view_file`）+ bbox 解析 + 新签名 URL。B 得自己重造过滤/签名/bbox，且绕开安全红线，风险高。`persist_task_turn_message(session_model) -> ChatMessage`（`utils.py:340`，`category="task"`）已存在且在 3 个完成处理器被调用（返回值当前被丢弃，捕获即可）；resume 时它 update 同一行 → 同一 int id；`message_citation.citation_id` 唯一 → 重复持久化幂等（满足 AC-06）。
- **何时该重新考虑**：若任务产物需要脱离 ChatMessage 独立分享（跨用户下载件的权限模型），再设计独立 sources 通道。

### 决策 5：预览面保留裸标记 / 下载面（Phase 2）烘焙可见编号

- **选定**：磁盘 `output/*.md` 永远保留**裸私用区标记**（预览渲染用）；Phase 2 只在 `export_docx`/`export_pdf` 转换前对 md 文本做**烘焙**（标记→可见 `[1]` + 文末「参考资料」段），仅作用于导出字节，不改磁盘 md。
- **原因**：私用区标记是不可见控制字符，进 Word/PDF 会丢失或乱码；而预览器要靠它渲染角标。一份真相（裸 md）+ 一份派生（烘焙导出）职责最清。
- **何时该重新考虑**：若前端预览也改成消费烘焙后的编号（不再解析私用区标记），再统一。

### 决策 6：分期 —— Phase 1 预览先行、只做行内角标；Phase 2 下载随后

- 用户已确认：先做应用内预览行内角标（高价值、低成本、零前端），下载件烘焙随后；先不做「参考资料」汇总面板。见 spec 范围边界。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（Phase 1）

```
[检索侧] researcher/主图 调工具
  search_knowledge_base ─► base_search: milvus 命中 Document(带 metadata)
        → 补 metadata.knowledge_id/knowledge_name（单 KB 路径 metadata 无 knowledge_id）
        → annotate_rag_documents_with_citations(docs)  # page_content 追加 "citation_key: knowledgesearch_x:1"
        → collect_rag_citation_registry_items(docs) → cache_citation_registry_items(items)  # Redis, 按 citationId
        → 返回 {"状态":"成功","结果":[已注解 page_content...]}   # 模型据此内联引用
  web_search(包装) ─► annotate_web_results_with_citations → collect_web_citation_registry_items → cache
[撰写] 模型写 output/report.md，内联发 ⟨START citationId:itemId END⟩ 私用区标记（裸）
[完成] task_exec 完成处理器：
  msg = persist_task_turn_message(session_model)                       # 既有，捕获返回
  ids = extract_citation_ids_from_text(report_md)                      # 只取报告实际出现的
  items = CitationRuntimeCacheService().get_citations_by_ids(ids)      # 从 Redis 回取
  save_message_citations(message_id=msg.id, items, chat_id=session_id) # 写 message_citation（幂等）
[预览] PreviewBody 取 report.md(带标记) → Markdown.transformPrivateCitations → 上标角标
  → useEffect resolveCitationDetails(ids) → POST /api/v1/citations/resolve
  → CitationResolveService（缓存→DB, view_file 过滤[INV-7], 新签名 URL, bbox）
  → 悬浮卡 + 点击 → CitationDocumentPreviewDrawer → PdfViewer(bbox 高亮) / Web 开新页
```

### 4.2 关键数据结构 / 字段约定（均为**复用**，非新增）

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁消费 |
|---|---|---|---|
| 私用区标记 | ` citationId:itemId [ …] ` | 模型内联发；规则 `core/prompts/yaml/citation.yaml` | 前端 `transformPrivateCitations` / Phase 2 烘焙 |
| `CitationRegistryItemSchema` | `{key, citationId, type, itemId, sourcePayload}` | registry / 缓存 / resolve 的线上对象 | 缓存、`/resolve` |
| `RagCitationPayloadSchema` | `{knowledgeId, knowledgeName, documentId, documentName, snippet, previewUrl, downloadUrl, sourceUrl, items[{chunkId,chunkIndex,content,bbox,page}]}` | KB 来源载荷 | 前端角标/预览 |
| `WebCitationPayloadSchema` | `{url,title,snippet,source,siteIcon,datePublished,items}` | Web 来源载荷；与 `web_search` 的 `normalize_result_item` 1:1 | 前端角标 |
| `message_citation` 行 | `citation_id`(uniq), `message_id`(=任务轮 ChatMessage.id), `chat_id`(=session_id), `citation_type`, `source_payload`(JSON) | 完成时持久化 | `/resolve` 回退 DB |

### 4.3 关键模块职责（改动点）

| 模块 / 文件 | 本 feature 的职责 | 不做什么 |
|---|---|---|
| `tool/domain/langchain/linsight_knowledge.py` | `base_search` 保留 metadata + 注解/收集/缓存（决策 2） | 不做权限过滤（在 resolve 侧）；不 raise |
| `linsight/domain/services/agent_factory.py` | 系统/子代理提示词追加引用规则；包装 web_search 使其登记 registry | 不改工具白名单语义 |
| `linsight/domain/task_exec.py` | 3 个完成处理器捕获 `persist_task_turn_message` 返回 + 调持久化 helper | 不写 history；不新增事件 |
| `citation/domain/services/citation_prompt_helper.py` | 新增 `persist_linsight_report_citations(...)`（读报告→抽 id→取缓存→save）；Phase 2 新增 `bake_citations_for_export(md)` | — |
| `tool/domain/langchain/linsight_export.py` | **Phase 2**：`_arun` 转换前对 md 烘焙可见引用 | — |
| 前端（Phase 1） | **零改动**——`PreviewBody→Markdown` 已具备全套角标渲染 + 惰性 resolve + bbox 预览 | — |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `search_knowledge_base` 当前只返回 `page_content`，**丢弃 `Document.metadata`**（`linsight_knowledge.py:92`）。模型根本不知道 chunk 出处 | 任何「让模型写文献表」的方案都会编造文件名；溯源无从谈起 | 决策 2：`base_search` 保留 Document |
| 2 | **单知识库 milvus 检索路径的 metadata 不含 `knowledge_id`**（只有 chunk_index/bbox/page/pk）；但工具入参有 `knowledge_id` | 不补则 RAG 载荷缺 knowledgeId，分组/展示不全 | `base_search` 从入参 `setdefault('knowledge_id', ...)` |
| 3 | deepagents 子代理**只回末条消息**，子图内部工具调用的中间态不回主图 | researcher 检索到的引用标记若不在其**末条消息**里，主图撰写时拿不到 → 无角标 | 决策 3（Redis 收集不受影响）+ researcher 提示词要求末条带标记；主图丢了则按 AC-14 优雅降级 |
| 4 | 灵思工具内 `raise` 会穿透 deepagents tool node **杀掉整个任务** | 引用注解一处异常 = 整个任务失败 | 所有注解包窄 try/except，回退裸结果（AC-13） |
| 5 | `LinsightExecuteTask.history` 频繁全量重写曾**撑爆达梦 undo** 致 -7120 | 若把 sources 逐步写 history，长任务在 DM8 上卡死白屏 | 只进 Redis + 完成时一次批量插 message_citation（§2 约束） |
| 6 | 前端**不依赖任何推送**的 registry：`Markdown` 从报告文本里的私用区标记**惰性**解析 citationId 再 `/resolve` | 误以为要像日常模式那样在 SSE end 事件推 citations → 白做 | Phase 1 前端零改动即生效 |
| 7 | 运行时缓存有 TTL（约 30 天）；老报告预览时缓存可能已过期 | 不在完成时落 DB，则老报告 resolve 空 → 角标全灰 | AC-05 完成时持久化，`/resolve` 缓存未命中回退 DB |
| 8 | milvus 集合的文件 id 字段名可能是 `file_id` 而非 `document_id`（registry 服务已 `document_id or file_id` 兼容） | 若集合版本字段名不同，documentId 解析空 | 实现时按集合实际字段核对；registry 已有兜底 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `message_citation` 的**灵思写入路径**（message_id=任务轮 ChatMessage.id） | DB 写行为（复用 `save_message_citations`） | `/api/v1/citations/resolve` 读；未来 Phase 2 烘焙读 |
| 任务模式报告 `output/*.md` 内**保留私用区标记**的约定 | 隐式数据契约 | 前端预览渲染；Phase 2 导出烘焙 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `citation_prompt_helper` 的 `annotate_*/collect_*/cache_*/extract_citation_ids_from_text/save_message_citations` | 内部 Python API | citation 模块若改签名，本 feature 静默坏 |
| `CitationResolveService._filter_visible_rag_items`（F029 `view_file` 过滤） | 内部 Service | **INV-7 执行点**；F029 若回归，溯源可能越权（必须回归测试守住） |
| `web_search` 的 `normalize_result_item` 输出 shape | 隐式数据契约 | 与 `WebCitationPayloadSchema` 1:1；provider 若改字段会漏登记 |
| milvus `asimilarity_search` 返回 Document 的 metadata 字段（chunk_index/bbox/page/pk/file_id） | 隐式数据契约 | 集合版本差异（见坑 8） |
| `persist_task_turn_message() -> ChatMessage`（int id，幂等 upsert） | 内部 API | 若改为不返回/非 int id，持久化路径失效 |
| 灵思检索的**文件级可见性**（F029/F035） | 上游行为 | 本 feature 只在角标面复用过滤；检索级若有 INV-7 缺口属上游，见 §8 |

---

## 7. 测试与可观测

- **后端单测**（`test/citation/` 或 `test/linsight/`，`asyncio_mode=auto`）：
  - `base_search`：mock milvus Document → 断言保留 metadata、补 knowledge_id、page_content 含 `citation_key:`、调用了 cache。
  - web 包装：mock `web_search` JSON → 断言 annotate+collect+cache。
  - `persist_linsight_report_citations`：给样例含标记的报告 → 断言只抽出现的 id、以任务 ChatMessage id 调 `save_message_citations`；无标记时不写。
  - 幂等：重复调用不新增行。
  - **Phase 2** `bake_citations_for_export`：RAG/WEB 各一，标记→`[n]` + 「参考资料」段；无标记 no-op。
- **集成**（连 test 环境中间件，不改 test 部署）：选 KB 跑一个任务 → 断言 `output/report.md` 含私用区标记、`message_citation` 有以任务 ChatMessage id 落的行、`/resolve` 返回富 RAG（签名 URL+bbox）；**INV-7 回归**：无 `view_file` 的用户调 `/resolve` 拿不到该文件来源。
- **手动验证一遍**（本地起前后端 + 连 test 环境中间件 ES/Milvus/MinIO，不改 test 部署代码）：
  1. 后端 `export config=config.yaml; uv run uvicorn bisheng.main:app --port 7860`；灵思 worker `uv run python bisheng/linsight/worker.py`；client `npm run dev`（:4001，base `/workspace`）。
  2. 在任务模式选一个含 PDF 的知识库，提交一个会检索该库的任务；等产出报告。
  3. 预览报告（`PreviewBody` 走 `Chat/Messages/Content/Markdown`）→ 断言：正文出现 [1][2] 上标角标、悬浮卡有文档名+页码、点击 KB 角标开 `PdfViewer` 且黄框高亮定位、点击 Web 角标开原网页。
  4. 换一个对该 PDF 无 `view_file` 权限的用户预览同一报告 → 角标灰化为「无权限」，`/resolve` 不返回该文件字段（INV-7）。
- **可观测**：来源注解 try/except 分支 `logger.warning` 打点（确认降级发生率）；完成持久化条数 log。

---

## 8. 后续改进 / 不打算做的事

- **Phase 2 —— 下载 Word/PDF 烘焙可见引用**：新增 `bake_citations_for_export(md)`（标记→顺序 `[n]` + `## 参考资料`：RAG=文档名+页码 / Web=title+URL），插入 `ExportDocxTool/ExportPdfTool._arun` 转换前。局限：下载件内 KB 文件只能显示名称+页码（无法点击预览/bbox）；跨用户分享下载件的权限过滤属更后续项（下载者即任务所有者，已具 C4 检索权限）。
- **上传附件的溯源（PRD FR-2.13 提及「附件」，候选 Phase 1.5）**：本期只覆盖检索类来源（KB/Web）。上传附件经 `read_file` 按需翻阅、不走检索工具，模型看不到「文件级来源标识」。要溯源需在 workspace 文件读取路径上加「读文件即登记来源」（把 `uploads/` 文件登记成一条 RAG-like citation，previewUrl 指向该 workspace 文件），并让模型引用工作区文件时也发标记——机制与检索侧不同、复杂度更高，故延后。
- **「参考资料」汇总面板**：复用日常模式 `CitationReferencesDrawer`，在结果区聚合本次全部来源（用户本期选择不做）。
- **引用修复 pass**：对漏发标记做补救性二次校验（本期优雅降级，不做）。
- **检索级文件可见性对齐 INV-7（上游）**：灵思 KB 检索白名单是**知识库级**（`allowed_knowledge_ids`），知识空间（type=3）文件夹/文件级 `view_file` 过滤属 F029/F030/F035 范畴。本 feature 通过 resolve 过滤守住**角标呈现面**的 INV-7；若发现检索级仍把无权文件的 chunk 喂进模型上下文，应在上游 feature 收敛，不在本 feature 扩范围。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-07-23 | 初版设计（实现前）；Phase 1 预览角标 + Phase 2 下载烘焙分期 | 承接 F035 FR-2.13 / §4.3.3，用户确认「先文档后代码」 |
