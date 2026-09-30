# Design: 工作台日常模式引用改用短句柄

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（目标、AC、边界）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**
>
> 调整原则：实现变化 → 覆盖更新本文档；推翻已 ★ 确认的决策 → 停下与用户重新确认。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（待拆解） · 前序 [F069 design](../069-linsight-citation-handles/design.md)
**版本**: v3.0.0-beta1（发版线 `feat/3.0.0-beta2`）
**最后更新**: 2026-09-30（初版；行号核对到 beta2 `2c4e17ad2`）

---

## 1. 目标与非目标

- **目标**：日常模式的模型不再逐字抄写 `knowledgesearch_xxxxxxxx:0` 这类内部键，改写 `[S3]` 短编号；后端在流式下发前把编号确定性地转回既有私有区标记，前端渲染、`message_citation` 持久化、resolve、分享与历史回看全部沿用现状。做法照搬 F069 已在任务模式验证过的契约（A/B uncited 44% → 0%），编号表与任务模式共用。
- **非目标**：不改知识空间、频道、工作流、助手四个入口（它们继续走 `citation.yaml` + `ensure_citation_rules` + `strip_unregistered_citation_markers`）；不改 `KnowledgeUtils.format_retrieved_chunk`、`citation.yaml`、`select_registry_items_for_persistence`、`strip_unregistered_citation_markers` 这些共享件；不做开关与过渡期；不做会话导出烘焙。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md`，本节只列本功能特有：

- **共享件冻结**：`format_retrieved_chunk` 被日常模式、工作流 agent 知识工具、RAG / 助手文档填充四处共用；`ensure_citation_rules` / `citation.yaml` 被知识空间、频道、工作流、助手共用；`select_registry_items_for_persistence` 被工作流 `redis_callback.py`、助手 `common/chat/client.py`、知识空间共用，其"无标记全存"由 F054 AC-18 非回归用例钉住。所有改动只能发生在**日常模式调用点之后**，不改这些函数本身。
- **INV-7 不放松**：角标解析仍走 `CitationResolveService` 的 `view_file` 过滤；编号表里的标题与定位只喂给模型，不进任何面向查看者的响应（与 F069 §2 同一口径）。
- **前端零改动的前提**：流式 `agent_answer/stream` 的 `msg` 增量、`agent_answer/end` 的 `{msg, events}` 快照、历史接口返回的消息体，里面的引用必须一直是私有区标记。气泡正文渲染的是 `events` 里最后一个文本段（`AiMessageBubble.tsx:555-566`），end 事件会用 `events` 快照覆盖前端状态（`useAiChatSSE.ts:324`），所以 `events` 里的文本与 `msg` 必须同一份转换结果。
- **中断路径是同步的**：`persist_interrupted_turn` 跑在 `CancelledError / GeneratorExit` 上，里面不能 `await`（`chat_service.py:1705-1746` 的注释）。凡是中断路径要用的数据，必须在进程内镜像里提前备好。
- **C8 无本地共享状态**：编号表的真相在 Redis（`linsight:cite_handles:<session_id>`，TTL 30 天）；进程内只是一轮对话生命期内的镜像，每轮开头从 Redis 水化。
- **i18n**：默认提示词模板在 platform 的三语 locale（`chatConfig.systemPrompt2`），三语同 PR 改；`chatConfig.aiPrompt` 是知识空间 / 频道的默认模板，不动。

---

## 3. 方案对比与选定

### 决策 1：编号表 —— 与任务模式共用会话级 HASH，但日常模式不钉契约

- **备选**：
  - A. 日常模式单独一张表（如 `daily:cite_handles:<chat_id>`）— 与任务模式互不影响；但同一会话里先跑任务模式再回到日常，同一来源会有两个编号，历史回放给模型时两套编号混在一起。
  - B. 共用 `linsight:cite_handles:<session_id>`（日常模式的 `conversationId` 就是任务模式的 `session_id`，`chat_service.py:2611`），复用 `assign_handles` / `load_handle_table` / `convert_handles_to_markers`。
- **选定**：B。日常模式新建一个轻量 scope（鸭子类型满足 `assign_handles` 需要的 `enabled`、`session_id`、`key_to_handle`、`register_handle`），每轮开头 `load` 一次水化镜像。
- **一处必须改的共享行为**：`assign_handles` 在表刚创建（`next == 1`）时写 `meta:enabled`，把任务模式的契约钉在会话上（F069 决策 6）。如果日常模式先创建了表，就会把 `meta:enabled=1` 钉上，之后同一会话的任务轮即使运维关了 `linsight.citation_handles_enabled` 也仍按句柄契约跑，任务模式的回退开关对这类会话失效。所以 scope 增加 `pins_contract` 属性（任务模式 True、日常模式 False），`assign_handles` 只在它为真时写 `meta:enabled`。日常模式自己不读 `meta:enabled`（没有开关，永远是句柄契约）。
- **何时该重新考虑**：任务模式删掉开关与 `meta:enabled`（F069 决策 6 写的"稳定两个版本后"）时，`pins_contract` 一并删除。

### 决策 2：流式转换 —— 增量转换器，下发前就转成标记

- **备选**：
  - A. 照任务模式：流式阶段原样下发 `[S12]`，完成时再转换并用 end 事件覆盖 — 实现最简单；但日常模式今天的角标是边写边出现的，改成"先看到 `[S12]` 字面、结束后才变角标"是体验倒退，也违反 spec AC-05。
  - B. 每来一块就对累计全文跑一次 `convert_handles_to_markers`，把新增部分下发 — 前面已下发的文本可能被后来的上下文改变（如后来才闭合的代码块），无法撤回。
  - C. 增量转换器 `HandleStreamConverter`：`feed(text)` 返回可以安全下发的前缀，`flush()` 在工具调用开始、流结束、中断时吐出剩余部分。只扣住"可能还没写完"的尾巴：未闭合的 `[`（后面可能是 `S12]` 或 `, S7]`）、紧跟一组编号后可能还有下一组的位置、未闭合的私有区标记 `…`。
- **选定**：C。
- **规则**：
  - 转换文法与 `convert_handles_to_markers` 完全一致（`[S3]`、`[S3][S7]`、`[S3, S7]`，排除链接标签、代码、定义行）；转换器内部跟踪围栏代码块（```、~~~ 按行切换）与行内反引号状态，代码里不转换。
  - 扣住的尾巴设长度上限（64 字符）；超过上限仍未闭合就按字面下发，避免模型写了个无关的 `[` 导致正文卡住。
  - 模型自己写出的私有区标记（逐字复制内部键的旧写法，含 `\\ue200` 六字符转义形态）整段丢弃，只计数（spec AC-10）。
  - **不变量（测试钉住）**：同一段模型输出，无论按什么粒度切块喂给转换器，拼接后的结果都等于对全文调用一次 `convert_handles_to_markers`（再去掉旧写法标记）。
- **下游一致**：转换后的文本同时进 `final_msg`、`events` 最后一个文本段、SSE `msg` 增量、内容安全扫描器 `scanner.feed`。完成与中断时不再对 `final_msg` 做第二次转换，只做 `flush`。
- **何时该重新考虑**：模型开始大量在代码块里写编号、或需要支持新的编号形态时，先改 `citation_handle_service` 的文法，再让转换器复用同一组正则。

### 决策 3：完成时落库 —— 只认转换产生的标记，严格过滤，不做重映射

- **备选**：
  - A. 沿用今天的 `select_registry_items_for_persistence` + `strip_unregistered_citation_markers` — 前者无标记时全存（与 spec AC-14 相反），后者在"一个已登记 id 都没引用"时按文本重叠把标记改指到真实来源，是 F069 PRD 定性的"掩盖模型缺陷"。
  - B. 日常模式自己的完成步骤：从转换后的正文取出全部被引 key → 本轮 collector 里有的直接用；没有的（引用了之前轮次的来源，spec AC-12）按 id 从 citation 运行时缓存补查（异步路径 `get_citations_by_ids`，中断路径 `get_citations_by_ids_sync`）→ 用 `filter_registry_items_by_text` 严格过滤 → `save_message_citations`。
- **选定**：B。不再调用 `strip_unregistered_citation_markers`：正文里的标记全部由转换器根据编号表生成，编号表里的 key 都真实存在；模型自己写的旧标记已在流式阶段丢弃。
- **补查不到的 key**（运行时缓存 30 天过期）：标记保留、不绑定；resolve 会先查缓存再查 `message_citation`，之前那轮落过库的来源仍能解析，查不到的按 F054 显示"已失效"（spec AC-12）。
- **何时该重新考虑**：若产品要求"引用过期来源的角标直接不显示"，在转换器里对编号表 entry 的时间戳做判断，而不是在落库时删标记。

### 决策 4：引用规则 —— 日常模式专用规则，运行时替换旧段落

- **备选**：
  - A. 复用任务模式的 `linsight_handle_rules` — 文案写的是"写 output/ 下的 markdown 交付物和最终回复"、"本轮来源表"，日常模式没有交付文件也不注入来源表，照搬会误导模型。
  - B. 在 `citation_handles.yaml` 新增 `daily_handle_rules`，与任务模式同一标题 `# 来源编号`（`prompt_has_handle_rules` 靠标题判重，天然幂等）；正文只讲"依据检索结果写出的内容在句末写编号、多来源写法、没有依据不标"，并有一句"本提示词其它位置若有不同的引用写法，以本段为准"。
- **选定**：B。
- **旧段落替换**（spec AC-03）：只在日常模式调用点处理，替换函数放 `citation_handle_service`：
  1. 找 `# 引用规则` / `# Citation Rules` / `# 引用ルール` 这一行（整行匹配，前后可有空白）。
  2. 段落结束位置 = 之后第一个"不属于旧规则的小节"或下一个一级标题。旧规则的小节标题是已知集合（zh `来源 ID / 标记格式 / 使用要求`，en `Source ID / Format / Requirements`，ja `ソースID / フォーマット / 要件`）；`## 其他信息 / ## Other / ## その他` 不在集合里，因为它装着 `当前时间：{cur_date}`，必须保留（见 §5 #2）。
  3. 用 `daily_handle_rules` 替换这一段；没找到标题但正文里有 `<chunk_id>` 或私有区字符时（管理员改写过），不动原文、直接在末尾追加新规则，靠"以本段为准"覆盖；两者都没有则追加。
- **默认模板**（spec AC-04）：三语 `chatConfig.systemPrompt2` 的 `# 引用规则` 段改为新规则文本（与 yaml 同义，按语言翻译），`## 其他信息` 保留。已保存旧模板的存量租户靠运行时替换生效，不做数据迁移。
- **何时该重新考虑**：出现第四种语言的默认模板，或管理员普遍改写引用段导致替换命中率低时，改为"去掉提示词中所有引用相关段落再追加"。

### 决策 5：历史回放 —— 标记反向映射成编号，映射不到就去掉

- **备选**：
  - A. 历史原样回放 — 模型同时看到私有区标记 + 长 key 和 `[S3]` 两种写法，而且会模仿历史里的旧写法。
  - B. 回放前把每个私有区标记拆出 key，按镜像里的 `key → handle` 写回 `[Sn]`；表里没有的 key（迁移前的老消息、编号表已过期）连同标记一起去掉，保留正文。
- **选定**：B，作用于 `AGENT_ANSWER` 与 `TASK` 两类行（`workstation_service.py:1541-1560`）。反向映射需要镜像已水化，所以日常模式 scope 的 `load` 必须在构造历史之前完成。
- **何时该重新考虑**：若要让模型能继续引用迁移前老消息里的来源，给老 key 懒分配编号（按 key 从运行时缓存取 item 再 `assign_handles`）。

### 决策 6：编号分配失败 —— 本轮不给编号，不回退旧写法

- **备选**：A. 回退为呈现内部 key（F069 AC-17 的做法）；B. 本轮检索结果不带任何来源标识，回答照常。
- **选定**：B（用户决定不保留旧契约，spec AC-17）。`assign_handles` 返回空映射时，知识库结果去掉 `<chunk_id>…</chunk_id>`、联网结果去掉 `citation_key` / `itemId` 字段，记 ERROR 日志 `[daily-citation] handle allocation failed chat=…`。模型手里没有编号，自然不产生角标。
- **同步工具路径**：`DailyChatCitationToolWrapper._run`（同步）无法 await 分配，按 B 处理。日常模式的 agent 走 `astream_events`，实际只调 `_arun`；同步路径保留只是为了不让意外调用崩掉。
- **何时该重新考虑**：`[daily-citation] handle allocation failed` 日志在生产上频繁出现（Redis 不稳定）时，评估给编号表加进程内降级分配（仅本轮有效、不落 Redis），而不是恢复旧写法。

### 决策 7：复制与导出剥未识别编号 —— 只作用于日常模式

- **选定**：
  - 前端复制：`AiMessageBubble` 的复制按钮对日常模式消息在 `stripCitationMarkers` 之后再调既有的 `stripCitationHandles`（`citationUtils.ts:118`）。知识空间、频道共用同一气泡组件，而且日常模式（`ChatView.tsx:812`）、分享页（`ShareView.tsx:63`）与知识空间、频道都传 `knowledgeChatLayout`，这个 prop 区分不了入口；因此经 `AiChatMessages` 向气泡新增一个显式 prop（如 `stripCitationHandlesOnCopy`），只由 `ChatView` 与日常模式的分享页传 true，知识空间与频道不传，行为不变（spec AC-20）。
  - 会话导出：`ConversationExportService._strip_citations`（`conversation_export_service.py:486`）在剥私有区标记后追加 `strip_citation_handles`。该服务只服务日常模式会话导出。
- **原因**：已识别编号在正文里已经是标记，复制时本就会被剥；只剩未识别编号需要处理（spec AC-15）。
- **何时该重新考虑**：知识空间或频道也迁移到短句柄时，去掉这个 prop，复制路径对所有入口统一剥编号。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（目标态）

```
POST /api/v1/workstation/chat/completions → stream_chat_completion → _agent_stream_chat_completion
  ├─ 每轮开头：DailyCitationScope(session_id=conversationId).load()   ← 水化编号表镜像
  ├─ 构造历史：AGENT_ANSWER / TASK 行里的私有区标记 → [Sn]（映射不到则去掉）
  ├─ 系统提示词：ws_config.systemPrompt（替换 {cur_date}）→ replace_legacy_citation_rules → ensure 日常规则
  ├─ 工具：
  │   知识库 search_knowledge_base（chat_service.py:~981）
  │     annotate → collect → cache registry → collector.extend
  │     → assign_handles(scope, items) → format_retrieved_chunk → <chunk_id>key</chunk_id> 换成 <ref>S3</ref>
  │   联网 DailyChatCitationToolWrapper._aappend_web_citation
  │     annotate → collect → cache → collector.extend → assign_handles → 结果加 "ref"、去 citation_key / itemId
  ├─ 流式：模型文本 → HandleStreamConverter.feed → 转换后文本进 final_msg / events / SSE msg / scanner
  │         on_tool_start、流结束、中断 → converter.flush()
  ├─ 完成：cited keys（正文）→ collector ∪ 运行时缓存补查 → filter_registry_items_by_text
  │         → ChatMessage {msg, events} → save_message_citations → agent_answer/end
  │         → 日志 [daily-citation-audit]
  └─ 中断：flush → 同上（同步 DAO、同步缓存补查）
前端：不改（角标渲染 / resolve / 历史 / 分享）；复制按钮对日常模式多剥一次未识别编号
```

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| Redis `linsight:cite_handles:<session_id>` | 沿用 F069：`h:<n>` → `{key,type,title,loc}`，`id:<identity>` → n，`next`，`meta:enabled`（仅任务模式写） | 日常与任务两模式共用；identity 规则不变（rag `rag:{documentId}:{itemId}`，web `web:{normalize_url}`） | 两种模式的工具输出、转换、历史回放 |
| 模型可见来源标识 | 知识库 `<ref>S3</ref>`（替换 `<chunk_id>`），联网 `"ref": "S7"` | 与任务模式同一形态 | 模型 |
| `citation_handles.yaml` → `daily_handle_rules` | prompt | 标题 `# 来源编号` | 日常模式系统提示词 |
| 日志 `[daily-citation-audit] chat= model= sources_seen= cited= unknown_handles= legacy_markers=` | 每轮一行；`sources_seen>0 且 cited==0` 为 WARNING，其余 INFO | spec AC-13 | 运维统计 |
| 日志 `[daily-citation] handle allocation failed chat=` | ERROR | spec AC-17 | 告警 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `citation/domain/services/citation_handle_service.py` | 新增 `HandleStreamConverter`、`replace_legacy_citation_rules`、`ensure_daily_handle_rules`、`markers_to_handles`（历史反向映射）、`swap_chunk_id_for_handle` / `rewrite_web_results_with_handles`（从 `linsight_knowledge.py`、`agent_factory.py` 上移，两模式共用）；`assign_handles` 读 `scope.pins_contract` | 不查权限；不改 `citation_registry_service` |
| `citation/domain/services/daily_citation_scope.py`（新） | 日常模式一轮的编号表镜像 + 本轮统计（seen / unknown / legacy） | 不写 `meta:enabled`，不写 `cite_seen` |
| `workstation/domain/services/chat_service.py` | 构造 scope、工具换编号、流式转换、完成与中断落库、审计日志、规则替换 | 不再调 `ensure_citation_rules`、`select_registry_items_for_persistence`、`strip_unregistered_citation_markers` |
| `workstation/domain/services/workstation_service.py` | 历史回放时标记 → 编号 | 不改其它类别的回放 |
| `workstation/domain/services/conversation_export_service.py` | 导出时追加剥未识别编号 | 不烘焙 |
| `common/image_view/react_loop.py` | 识图答案剥引用时一并剥 `[Sn]` | — |
| `linsight/…`（`linsight_knowledge.py`、`agent_factory.py`、`linsight_citation_scope.py`） | 改为调用上移后的共用函数；scope 加 `pins_contract=True` | 行为不变 |
| platform `public/locales/{zh-Hans,en-US,ja}/bs.json` | `chatConfig.systemPrompt2` 引用段改写 | `chatConfig.aiPrompt` 不动 |
| client `AiMessageBubble.tsx` / `AiChatMessages.tsx` / `ChatView.tsx` / `ShareView.tsx` | 新增显式 prop，日常模式复制多剥一次未识别编号 | 知识空间、频道不传该 prop |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `assign_handles` 在表刚创建时写 `meta:enabled`，任务模式据此钉契约 | 日常模式先建表会把任务模式的回退开关对该会话废掉 | 决策 1：`pins_contract` |
| 2 | 默认模板里 `## 其他信息 当前时间：{cur_date}` 挂在 `# 引用规则` 之下 | 按"到下一个一级标题为止"整段删，会把当前时间一起删掉，模型失去日期 | 决策 4：按已知小节集合裁剪 |
| 3 | 气泡正文渲染的是 `events` 最后一个文本段，不是 `msg`；end 事件用 `events` 快照覆盖前端状态 | 只转换 `msg` 时，气泡里出现字面 `[S3]` 并被 end 事件固定下来；今天 `events` 文本也从未经过 `strip_unregistered_citation_markers` | 决策 2：转换发生在写入 `final_msg` / `events` 之前 |
| 4 | 中断持久化跑在取消路径上，不能 await | 中断时补查跨轮来源、读 Redis 会被取消，整轮回答丢失 | 中断路径用 `get_citations_by_ids_sync` 与进程内镜像 |
| 5 | 流式分片会把 `[S1` 和 `2]` 切开，模型也可能先写 `[S3]` 再紧跟 `[S7]` | 提前下发半截或把一组拆成两组 | 转换器扣住尾巴，上限 64 字符 |
| 6 | `format_retrieved_chunk` 的 `<chunk_id>` 同时被工作流、助手使用 | 直接改它会让其它入口丢掉来源标识 | 只在日常模式调用点之后替换标签 |
| 7 | `chatConfig.aiPrompt` 也含旧引用规则，但它是知识空间 / 频道的默认模板 | 顺手改掉会破坏 spec AC-20 | 只改 `systemPrompt2` |
| 8 | 识图问题的答案在 `react_loop._strip_picture_citations` 里剥私有区标记 | 若 `[Sn]` 先到了这里没被剥、后被转换，图片答案会出现角标 | 同处追加 `strip_citation_handles`；实现时核对该函数与日常流式转换的先后顺序 |
| 9 | 同一会话多标签页并发提问会并发分配编号 | 按进程锁分配会撞号 | 沿用 F069 `HINCRBY + HSETNX` 原子分配，允许空洞 |
| 10 | 迁移前的老消息里是长 key，编号表里没有它们 | 历史回放若保留原样会诱导模型写旧格式 | 决策 5：映射不到就去掉 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 日常模式消息体里的引用仍是私有区标记 | 隐式数据契约（F047 / F054） | client 渲染、resolve、分享页、会话导出 |
| `[daily-citation-audit]` 日志行 | 日志格式 | 迁移效果统计 |
| `citation_handle_service` 新增的共用函数 | 内部 Python API | 日常模式、任务模式 |
| F054 AC-18 对日常模式的修订、F069 编号表改为两模式共写 | spec 契约修订 | release-contract 表 1 / 表 4 需登记 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F069 编号表结构与 identity 规则 | Redis 数据契约 | 任务模式改表结构会同时影响日常模式 |
| `format_retrieved_chunk` 输出里的 `<chunk_id>` 标签 | 内部格式 | 标签改名则替换失配，模型会看到长 key；单测钉住 |
| 联网结果 JSON 里的 `citation_key` 字段 | 内部格式 | 同上 |
| citation 运行时缓存按 id 查询 | 内部 API | 跨轮补查依赖，过期即退化为"已失效" |
| platform 默认模板的标题文字 | 文案 | 标题改动会让运行时替换失配（退化为追加） |

**会破的既有测试**（改为新契约断言）：`test/workstation/test_daily_chat_citation_backstop.py`（断言日常模式调 `ensure_citation_rules`）、`test_stream_interrupt_persist.py`（中断路径落库）、`test_daily_chat_image_view.py`、`test_unified_chat_entry.py`、`test_conversation_export_service.py` 中与引用相关的用例；逐个核对后在 tasks.md 记录。`test/citation/test_f054_non_regression.py` 不应变化（共享函数没改），它是 spec AC-20 的回归基线。

---

## 7. 测试与可观测

- **单测**：
  - 转换器：文法表（多组、逗号 / 顿号、链接、代码、定义行、未知编号、旧写法标记与转义形态）；任意切块与整段转换结果一致的性质测试；尾巴上限。
  - 规则替换：三语默认模板替换后保留 `{cur_date}`；管理员改写过的变体走追加；幂等。
  - 编号：日常模式建表不写 `meta:enabled`；与任务模式同会话同来源同编号。
  - 完成与中断：零引用不落库；跨轮引用补查并绑定；未识别编号保留在 `msg` 与 `events`；中断路径不 await。
  - 历史回放：映射与去除。
  - 前端：日常模式复制剥未识别编号，知识空间复制不剥。
- **116 对比**：沿用 F069 的两题（Q1 知识库 + 联网，Q2 仅知识库），在日常模式里对 flash / pro / qwen3.5 各跑 3 次，迁移前（release 现状）与迁移后各 18 次，指标取 `[daily-citation-audit]`；迁移前没有这行日志，基线从 `message_citation` 行数与消息正文里的标记数统计。
- **手动验证**：120:3002 日常模式开知识库 + 联网问答 → 角标边写边出现、蓝紫两色；刷新后一致；追问"上一条第二点的出处"→ 角标仍可点；复制无 `[Sn]` 残留。

---

## 8. 后续改进 / 不打算做的事

- **不做**：开关与过渡期、会话导出烘焙、每轮来源表注入、零引用前端提示、自动补引用、给迁移前老 key 懒分配编号。
- **已知短板**：跨轮引用的来源运行时缓存过期后，本轮不再绑定该来源，只能靠之前那轮已落库的记录解析。
- **重写触发**：任务模式删除开关后，`pins_contract` 与 `meta:enabled` 一起删。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-30 | 初版 | spec 确认（直接迁移、无开关无过渡期） |
