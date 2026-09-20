# Design: 灵思任务模式引用溯源可靠性（短句柄 + 审计）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（目标、AC、边界）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档；推翻已 ★ 确认的决策 → 停下与用户重新确认。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（待拆解） · PRD `docs/PRD/3.0 灵思任务模式引用溯源优化方案/灵思任务模式引用溯源优化方案.md`
**版本**: v3.0.0-beta1（发版线 `feat/3.0.0-beta2`）
**最后更新**: 2026-09-20（初版，行号核对到 `a0770eb67` / beta2 `3b8b83965`，两线该部分代码相同）

---

## 1. 目标与非目标

- **目标**：让第三方模型（DeepSeek、Qwen 等）在任务模式长上下文里稳定产出可解析的引用；模型不产出时系统能度量并如实告诉用户。做法是换掉 F047 的上游契约（模型逐字抄私有区标记加 hash id），保留其全部下游契约。
- **非目标**：不自动补引用、不做事后归因写回、不改日常模式与其它入口、不改 `citation.yaml` 与检索结果模板、不改 resolve 接口与 `message_citation` 表、不新增前端组件。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md` C1–C8，本节只列本功能特有：

- **INV-7 不放松**：角标解析仍走 `CitationResolveService` 的 `view_file` 过滤，本 Feature 不新开任何取来源的口子。编号表里存的标题、定位只喂给模型，不进任何对用户的响应。P2 导出烘焙是新的呈现面：参考资料列表必须按**导出者本人**（含分享页查看者）经同一 `CitationResolveService` 过滤后的结果生成，被过滤的来源退回剥离、不分配可见编号（spec AC-21）；不得直接读编号表或登记簿生成列表。
- **下游契约冻结**：私有区标记字法 `U+E200 key (U+E201 key)* U+E202`、key 形态 `prefix_hex8:item`、Redis 登记簿 `citation:runtime:<citationId>`、`message_citation` 表、`POST /api/v1/citations/resolve`、`strip_citation_markers` 的全部调用点、client 与 platform 两套解析器，均不改。22 个既有测试钉住这些契约，是本 Feature 的回归基线。
- **灵思工具「绝不 raise」**（F047 §2）：编号分配、来源记录、写盘转换全部包窄 try/except，异常回退原文。
- **DM8 写放大红线**（F047 §2）：审计结果只放计数与有上限的列表，不把编号表塞进 `output_result`，不逐步写 `history`。
- **C8 无本地共享状态**：编号表与本 run 见过的来源都在 Redis；进程内只是镜像，恢复与追问从 Redis 水化。
- **不动 `wrap_tool_call`**（仓库记忆：卸载结果不动点循环）：所有软提示走 `awrap_model_call` 的临时 HumanMessage。
- **不进 L3 连续失败计数**（`resilience_middleware.py` 的 `_trailing_tool_failure_run`）：写文件缺引用绝不返回 `status=error`。
- **config.yaml 新键**：shipped `config.yaml` 只加注释掉的键，避免老镜像因新顶级键拒启（仓库 §Config & Packaging Contracts）。
- **前端文案**：零引用提示三语 i18n，不在源码硬编码中文；只加一行文字，不加组件，不需设计师签字。

---

## 3. 方案对比与选定

### 决策 1：模型侧契约 —— 后端短句柄 `[Sn]`，而不是继续加固逐字复制

- **备选**：
  - A. 保留逐字复制私有区标记 + hash id，只加固提示词位置、加写盘校验与拒写重试 — 改动最小；但 run A 证明 flash 手里有 15 个可复制的短标记仍改写成脚注，run B 的 pro 直接用自然语言，业界没有任何产品让第三方模型抄不透明 id，五家 tokenizer 里一个标记 20 到 21 个 token。
  - B. 后端按检索顺序分配 `S1、S2…`，模型只写 `[S3]`，写盘边界转回私有区标记 — 与 OpenAI citation formatting 原方案（`turn0search1`）和 open_deep_research、Perplexity、Manus 的做法同构；`[3]` 3 个 token；下游零改动。
  - C. 结构化引用（子代理返回 `{claim, source_ids}`、`cite` 工具）— 覆盖率高但多耗轮次，且 DeepSeek/Qwen 经 OpenAI 兼容口的 `response_format` 成功率未知。
- **选定**：B，C 留 P3 按 P1 数据再议。
- **原因**：见 PRD §2、§3；三位独立核验者对「换句柄就能命中」持保留意见，因此 P1 的效果定为待 A/B 证明的假设（§7）。
- **何时该重新考虑**：A/B 显示 `[Sn]` 相对基线 uncited 率无显著下降，或 unknown_handles 率高于 5%，则关开关回到 P0 的诚实呈现，转向 C。

### 决策 2：模型不引用时 —— 度量、告警、如实提示、一次提醒；不补、不拒

- **备选**：
  - A. 写盘时按文本重叠给句子挂来源（日常模式 `strip_unregistered_citation_markers` 有此逻辑）/ 把 `[^n]` 映射到编号表 / 二次模型调用事后归因写回。
  - B. 写文件缺引用返回工具错误强迫重写。
  - C. 完成时审计落 `output_result.citation_audit` + WARNING；前端一行 i18n 提示；写后每文件一次临时提醒，让模型用 `edit_file` 补编号。
- **选定**：C（PRD D2、D3、D4）。
- **原因**：A 把「模型没标」伪装成「已溯源」，违反仓库「不用兜底掩盖模型缺陷」；B 的 `status=error` 进 L3 计数被误诊为「内容过长」，且软着陆阶段可能零交付；C 是文献里的「写作后校验」环节，且不掩盖。
- **何时该重新考虑**：产品接受「自动归因」标识为独立一档（UI 区分模型引用与自动归因）时，可做离线诊断先行。

### 决策 3：来源计数在工具层按 svid 记录，不从主图 values 快照取

- **备选**：
  - A. 扩展 `task_exec._capture_values_snapshot` 正则 ToolMessage 里的 id — 改动小；但三处调用都门控 `mode == "values" and not namespace`（`task_exec.py:577 / 684 / 1408`），researcher 子图的检索看不到。run A 子代理见 45 个 id，主图只收到 4 个。
  - B. `SearchKnowledgeBase.base_search` 与 `_LinsightWebCitationWrapper._arun` 各记一笔到按 svid 键的 Redis HASH `linsight:cite_seen:{svid}`，主图与子图共用同一批工具实例。
- **选定**：B。
- **原因**：当检索全部委派给子代理且子代理用自然语言回传时，A 会把「有来源未引用」判成「无来源」，恰在最需要提示的场景下静默。
- **何时该重新考虑**：deepagents 子图事件透传方式改变时复核。

### 决策 4：编号表 —— 会话级 Redis HASH，identity 去重，进程内锁，不写 Lua

- **备选**：
  - A. 每次检索沿用 registry 的随机 citationId 编号 — 同一 chunk 在 10 次检索里得到 10 个编号，run B 会有 470 个。
  - B. `linsight:cite_handles:{session_id}`（hash tag = session_id），字段 `h:<n>` 存 `{key, type, title, loc}`、`id:<identity>` 存编号、`next` 存下一个编号；identity：rag/temp 为 `rag:{documentId}:{itemId}`，web 为 `web:{normalize_url(url)}`；分配用进程内 `asyncio.Lock` 读改写。
  - C. Lua 原子分配 — 多进程安全，但运行锁 `linsight:run_lock:*` 已保证同一会话同一时刻只有一个 worker 在跑。
- **选定**：B。
- **原因**：追问轮共享同一表（AC-16），编号稳定；TTL 30 天与登记簿一致；Redis 异常回退原始 key（AC-17）。
- **何时该重新考虑**：若运行锁被移除或允许同会话并行执行，改 C。

### 决策 5：每轮来源表与一次提醒放 `awrap_model_call`，不放 `wrap_tool_call`，不加 `list_sources` 工具

- **备选**：`wrap_tool_call` 注入 / 新工具 / `awrap_model_call` 临时 HumanMessage。
- **选定**：`awrap_model_call`，样板 `resilience_middleware.py` `_with_wrap_up_nudge`、`tool_loop_middleware.py` `_repeat_nudge`。
- **原因**：deepagents Filesystem 中间件的大结果卸载会整体替换 ToolMessage，`wrap_tool_call` 里的软提示历史上造成过 79 轮不动点；新工具增加 schema 长度并多耗轮次。表不超过 150 行，约 2.5k token/轮，占 2% 到 3%。
- **何时该重新考虑**：上下文压缩触发频繁、150 行不够用时，再评估只读 `list_sources`。

### 决策 6：kill switch 三处联动

- **选定**：`LinsightConf.citation_handles_enabled`（默认 on），唯一读取点在 `task_exec._create_agent` 构造 scope；工具输出、规则文本与尾巴、写盘转换、每轮来源表都只看 `scope.enabled`。
- **原因**：任一处单独回退都会造成契约错配（模型看到编号但写盘不转换，或看到 key 但规则讲编号）。
- **何时该重新考虑**：契约稳定两个版本后可删开关。

### 决策 7：审计位置在兜底报告之后，前端渲染提示，后端不改 answer

- **备选**：复用 `_with_soft_landing_note` 的位置把注记拼进 answer。
- **选定**：三条完成路径在 `get_final_result_file` / `build_fallback_report_file` 之后、组 `output_result` 之前计算审计；answer 不动；前端按 `citation_audit.status` 渲染一行 i18n（PRD D6）。
- **原因**：软着陆注记位置在兜底报告生成之前，注记会被烘进 `报告.md`，且此时读不到最终 md 无法判定；后端拼中文与「UI 文案不硬编码中文」相悖。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（P1 目标态；P0 只含审计与提示词两支）

```
检索工具（KB base_search / web wrapper；主图与 researcher 共用实例）
  → 生成 registry item、写 Redis 登记簿            （现有）
  → scope.record_seen(items) → linsight:cite_seen:{svid}   （P0 新）
  → handles = scope.assign(items) → linsight:cite_handles:{session_id}  （P1 新）
  → 工具输出：<ref>S3</ref> / "ref": "S7"（长 key 移除；失败回退原样）
系统提示词：内核 → citation_handles 短规则 → deepagents 样板 → _CitationTailMiddleware → _LanguageTailMiddleware
每轮：LinsightCitationSourceMiddleware 追加临时 HumanMessage（来源表；必要时一次补编号提醒）
模型写 output/*.md、edit_file、最终回复：[S3] / [S3][S7]
  → WorkspaceBackend write/edit/awrite：unescape → convert_handles_to_markers  （P1 新）
  → answer 在软着陆注记之后、兜底报告之前同样转换
完成：_audit_report_citations（读最终 md + answer）→ output_result.citation_audit + WARNING
  → _persist_report_citations（现有，零改动）→ message_citation + output_result.citations
前端：ResultSection 读 citation_audit → 一行 i18n 提示；预览/解析/分享/历史沿用现有链路
导出：strip_citation_markers（现有）+ strip_citation_handles（P1）→ P2 改为烘焙
```

关键位置（行号见 PRD 附录 A）：`agent_factory.py` 3a 行、`_build_linsight_system_prompt`、`_with_citation_rules`、web wrapper、`create_linsight_agent`、中间件栈；`task_exec.py` `_create_agent`、三条完成路径、`_persist_report_citations`；`workspace_backend.py` 写边界；`linsight_knowledge.py` `base_search`；`citation_prompt_helper.py` 常量与 `persist_linsight_report_citations`。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| `output_result.citation_audit` | `{sources_seen:int, cited:int, unknown_handles:[str]≤50, footnotes_without_defs:int, bracket_numbers:int, converted:int, persisted:int, status:"no_sources"\|"cited"\|"uncited", scanned_files:[str]≤20, html_only:bool}` | 完成时写入，随 FINAL_RESULT / 历史 / 分享同一通道 | client `ResultSection`；运维统计 |
| Redis `linsight:cite_seen:{svid}` | HASH，field = item key，value = type；TTL 30d | 本 run 见过的来源 | 审计 |
| Redis `linsight:cite_handles:{session_id}` | HASH：`h:<n>` → JSON `{key,type,title,loc}`；`id:<identity>` → n；`next` → int；TTL 30d | 会话级编号表 | 工具输出、来源表、写盘转换、P2 烘焙 |
| 模型可见来源标识 | KB `<ref>S3</ref>`（替换 `<chunk_id>` 内容）；web `"ref": "S7"` | 开关关闭时恢复 `<chunk_id>key</chunk_id>` / `citation_key` | 模型 |
| 写盘转换文法 | 只认 `[S\d{1,4}]`、连续多组、`[S3, S7]`（逗号 / 全角逗号 / 顿号）；排除 `(` 紧随、代码块、行首 `[Sn]:` 定义行 | 未知编号字面保留 | `WorkspaceBackend`、answer 路径 |
| `LinsightConf.citation_handles_enabled` | bool，默认 true | kill switch | `_create_agent` |
| i18n key `com_linsight_citation_uncited` | `{{0}}` = sources_seen | 零引用提示 | client |
| 日志 `[linsight-citation-audit] session= model= status= sources_seen= cited= unknown_handles= footnotes_without_defs= bracket_numbers= html_only=` | 一行，`uncited` 为 WARNING 其余 INFO | 统计与告警 | 运维 |
| 日志 `[linsight-citation-nudge] session= file=` | INFO | 提醒触发计数 | A/B |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `citation/domain/services/linsight_citation_scope.py`（新） | 每 run 的来源记账与编号表镜像；Redis 读写；`enabled`、`handles`、`unknown_handles` | 不生成 registry item，不查权限 |
| `citation/domain/services/citation_handle_service.py`（新） | 编号分配、`convert_handles_to_markers`、`strip_citation_handles`、P2 `render_citations_for_export`（输入为已按导出者权限 resolve 过的来源列表） | 不动 `citation_registry_service.py`；不自行查权限 |
| `linsight/domain/services/citation_source_middleware.py`（新） | 每轮来源表、一次补编号提醒 | 不改 state，不返回 error |
| `agent_factory.py` | 3a 占位符、短规则分支、`_CitationTailMiddleware`、web wrapper 接 scope、把 scope 绑到工具 | 不动语言指令文本 |
| `task_exec.py` | 构造 scope、`_audit_report_citations`、answer 转换 | `_persist_report_citations` 逻辑不变 |
| `workspace_backend.py` | 写边界转换（含 edit 的 old_string） | `.html` 不转换（PRD D5） |
| `linsight_knowledge.py` | 记录来源、替换 `<chunk_id>` 为 `<ref>` | `format_retrieved_chunk` 不改 |
| `core/prompts/yaml/citation_handles.yaml`（新） | 灵思专用短规则 | `citation.yaml` 不改 |
| client `ResultSection.tsx` | 读 `citation_audit` 渲染一行提示 | 不加 Badge，不改 Markdown 解析器 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 主图 values 快照门控 `not namespace`，子代理检索的 ToolMessage 只在子图 state 里，主图只收到子代理末条 AIMessage 文本 | 来源计数系统性少计；检索全交子代理时审计判 `no_sources`，提示不出现 | 决策 3：工具层记录 |
| 2 | `_with_soft_landing_note` 在 `get_final_result_file` 之前执行，`build_fallback_report_file(answer=)` 会把 answer 烘进 `报告.md` | 若在此处拼注记，注记进入交付物文件 | 决策 7：审计在兜底之后，后端不改 answer |
| 3 | `_build_linsight_system_prompt` 没有 `has_web` 参数，3a 文本无条件；`_with_citation_rules` 只在 `has_kb or has_web` 时追加规则 | 无检索能力的任务会引用一段不存在的规则 | 3a 用占位符，增 `has_web_search` 入参，与规则同门控 |
| 4 | `_LanguageTailMiddleware` 在 `has_kb/has_web` 计算之前构造，且其文本自述「仅约束输出语言」 | 把引用段塞进语言尾巴与其措辞冲突，且拿不到门控值 | 独立 `_CitationTailMiddleware`，`has_kb/has_web` 计算上移 |
| 5 | 磁盘 md 写入后已是私有区标记，模型记忆里仍是 `[S3]`；`edit_file` 的 `old_string` 原样匹配 | 编辑定位失败「old_string not found」 | 写边界对 `old_string` 先转换（AC-14） |
| 6 | run A 的 `[^n]` 指向模型自编的附录表，粒度是文档不是 chunk | 若兼收 `[^n]` 映射，会把错误来源挂到句子上 | AC-11 只计数不转换 |
| 7 | 写文件返回 `status=error` 进 L3 连续失败计数（`resilience_middleware.py` `_trailing_tool_failure_run`），会被误诊为「内容过长」 | 拒写方案让软着陆阶段零交付 | 决策 2：不拒写，提醒走临时 HumanMessage |
| 8 | deepagents summarization 会把旧消息里超 2000 字的工具参数截断 | 「读回旧稿再补标记」不能依赖上下文 | 每轮来源表 + 提醒用 `edit_file` 定点补 |
| 9 | 每次检索 registry 重发 uuid，同一 chunk 多次检索多个 key | 若按 key 编号，run B 会出现 470 个编号 | 决策 4：identity 去重 |
| 10 | `_persist_report_citations` 只扫 `.md`；html 交付物既不扫也不剥 | 只有 html 交付物时审计误判「无来源」 | AC-05：seen>0 且无 md 引用判 `uncited`；html 保留字面编号（D5） |
| 11 | 终止接口用陈旧模型写回 `output_result`（`linsight.py` terminate 路径） | 完成与终止竞态时审计字段可能被盖 | 完成-终止竞态已由 `_check_user_termination` 重读处理；实施时核 terminate 写回是否合并现有字段 |
| 12 | 流式阶段 answer 会短暂显示 `[S12]` | 误以为转换失败 | FINAL_RESULT 后被持久化版本替换，接受 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `output_result.citation_audit` | JSON 字段（§4.2） | client `ResultSection`；运维统计 |
| `[linsight-citation-audit]` 日志行 | 日志格式 | A/B 统计、告警 |
| `strip_citation_handles` / P2 `render_citations_for_export` | 内部 Python API | 导出工具、convert 端点、zip、前端另存 md（P2） |
| 磁盘 `output/*.md` 仍保留私有区标记 | 隐式数据契约（承接 F047 §6.1） | 前端预览、P2 烘焙 |
| F054 AC-07、AC-12 在 P2 改为烘焙措辞 | spec 契约修订 | F054 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F047 全部下游契约（标记字法、key 形态、登记簿、`persist_linsight_report_citations`、resolve） | 内部 API 与数据契约 | 改 key 形态会让编号表反查失效 |
| `CitationRegistryService.normalize_url`、item id 规则（chunk_index） | 内部 API | identity 去重依赖 |
| deepagents `awrap_model_call` 的 `request.state` / `request.override` | 框架 API | 升级 deepagents 需复核 |
| `LinsightRunLock`（`linsight:run_lock:*`） | 运行期互斥 | 若允许同会话并行，编号分配需改 Lua |
| `KnowledgeUtils.format_retrieved_chunk` 的 `<chunk_id>` 标签 | 内部 API | 标签改名则 `<ref>` 替换正则失配，回退原样 |
| `_LanguageTailMiddleware` 在栈尾的位置 | 内部约定 | 引用尾巴必须在它之前 |

**P1 下会破的既有测试**（改为按 `handles` 分支断言）：`test/linsight/test_linsight_citation_agent.py` 的 `test_citation_rules_only_when_kb_or_web`、`test_citation_rules_require_real_pua_and_cover_written_files`、`test_with_citation_rules_delegates_to_the_shared_backstop`、`test_researcher_prompt_requires_last_message_handoff_when_citable`、`test_researcher_subagent_injects_rules_for_web_search`；`test_task_exec_report_citations.py` 的 fixture 需给 `_citation_scope`。其余 18 个钉下游契约的测试不受影响。

---

## 7. 测试与可观测

- **单测**（`test/citation/`、`test/linsight/`，`asyncio_mode=auto`）：编号分配幂等与 identity 去重；转换文法表（含 `[3]`、`[^3]`、链接、代码块、定义行、未知编号、幂等）；写边界三入口与 `old_string`；来源表 ephemeral 与 150 上限；提醒每文件一次、软着陆跳过、子代理不提醒；审计三条路径与 `uncited` 判定（含 html-only）；尾巴中间件位置与门控；开关关闭时行为与今天一致。前端 `ResultSection` 三种 status。
- **离线回放**：用 116 上两次 run 的 `write_file` 内容跑 `convert_handles_to_markers`，应 0 转换、`[^n]` 只计数。
- **116 A/B 协议**（PRD §7）：固定两题；P0 上线后 flash / pro / qwen3.5 各 3 次取 uncited 率基线；P1 上线后同样 18 次；判定 uncited 率显著下降且 unknown_handles 率低于 5% 保留默认 on，否则关开关。pro 若仍 100% uncited 如实记录。指标全部从 `[linsight-citation-audit]` 日志与 `linsight_session_version.output_result` 取。
- **关键日志**：`[linsight-citation-audit]`（WARNING 即需关注）、`[linsight-citation-nudge]`。

---

## 8. 后续改进 / 不打算做的事

- **P3 条件触发**：子代理 `response_format` 结构化 findings、离线归因诊断（只度量不写回），在 P1 数据后议。
- **不做**：文本重叠硬贴 key、无标记全量落库、脚注自动映射、事后归因写回、`write_file` 拒写、`wrap_tool_call` 提示、`list_sources` 工具、接 Anthropic Citations / OpenAI annotations、登记上传附件、前端复制加剥编号、部分引用与归因错误的检测。
- **已知短板**：技能或代码解释器读含标记的 md 再生成产物会带私有区字符；上传件同时在知识库时可能误报 `uncited`。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-20 | 初版 | PRD 评审通过（D1～D8） |
