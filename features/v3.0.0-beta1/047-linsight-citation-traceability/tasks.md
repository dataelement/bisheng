# Tasks: F047 灵思任务模式引用溯源

**关联规格**: [spec.md](./spec.md)
**设计入口**: [design.md](./design.md)
**版本**: v3.0.0-beta1 / F047

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户确认范围（Phase 1 预览角标，KB+Web） |
| design.md | ✅ 已评审 | 2026-09-07 用户确认；接手第一入口 |
| tasks.md | ✅ 已拆解 | 9 任务 / 4 wave；无实现偏差 |
| 实现 | ✅ 9 / 9 | 单测 62 passed。T009 清单已写，真环境手工勾选见 `e2e-checklist.md` |

---

## 开发模式

- 无新增 ORM / Alembic / 错误码 / HTTP API / 前端。不改日常模式。不写 `LinsightExecuteTask.history`。
- 后端 Test-First：每个实现任务前有配对测试。`asyncio_mode=auto`。新测试放 `test/citation/` 或 `test/linsight/`。
- 前端 AC-08～AC-12 复用既有 `PreviewBody → Markdown`，Phase 1 零改动；手工清单见 T009。
- INV-7 过滤复用既有 `CitationResolveService`（`test/citation/test_citation_resolve_visibility.py` 已覆盖 resolve 面）；本 feature 只保证写入路径让 resolve 能过滤。
- 自包含：文件 / 逻辑 / AC 写在任务里。**为什么**只指向 design §X，不抄决策。

---

## Tasks

### Wave 1：persist helper 与 KB 检索接线（可并行）

- [x] **T001**: persist helper 单元测试
  **文件**: `src/backend/test/citation/test_persist_linsight_report_citations.py`
  **逻辑**: mock `CitationRuntimeCacheService.get_citations_by_ids` 与 `save_message_citations`。断言：正文含 `\ue200knowledgesearch_x:1\ue202` 时只按该 citationId 回取并调用 save（`message_id`=任务 ChatMessage id，`chat_id`=session_id）；无标记 / 空文本不调用 save；缓存未命中的 id 被跳过；重复调用仍只按正文中的 id save（幂等交给既有 `ensure_citations`）。禁止使用 `select_registry_items_for_persistence`（无标记会落全部）。
  **覆盖 AC**: AC-05, AC-06, AC-14
  **验证**: `cd src/backend && uv run pytest test/citation/test_persist_linsight_report_citations.py`
  **依赖**: 无

- [x] **T002**: 实现 persist_linsight_report_citations
  **文件**: `src/backend/bisheng/citation/domain/services/citation_prompt_helper.py`
  **逻辑**: 新增 `persist_linsight_report_citations(message_id, chat_id, report_texts)`：拼接文本 → `extract_citation_ids_from_text` → Redis `get_citations_by_ids` → `filter_registry_items_by_text` → `save_message_citations`。无标记 / 无 message_id / 无 items 直接 return。异常由调用方吞（本函数可让异常冒泡给 task_exec 的窄 try）。论证见 design 决策 4 / 坑 10。
  **测试**: T001 全部通过。
  **覆盖 AC**: AC-05, AC-06, AC-14
  **依赖**: T001

- [x] **T003**: base_search 溯源单元测试
  **文件**: `src/backend/test/linsight/test_linsight_knowledge_citations.py`
  **逻辑**: mock milvus `asimilarity_search` 返回带 metadata 的 Document（有 file_id/page/bbox，**无** knowledge_id）；mock `cache_citation_registry_items` 与 `KnowledgeDao.get_list_by_ids`。断言：返回 JSON `状态=成功`；结果字符串含 `<chunk_id>`（`format_retrieved_chunk`）；调用了 cache；入参 knowledge_id 被 setdefault 进 metadata。注解函数 raise 时仍返回裸 `page_content` 且不向外 raise。无命中仍返回既有「无结果」JSON。
  **覆盖 AC**: AC-01, AC-13
  **验证**: `cd src/backend && uv run pytest test/linsight/test_linsight_knowledge_citations.py`
  **依赖**: 无

- [x] **T004**: 改 SearchKnowledgeBase.base_search
  **文件**: `src/backend/bisheng/tool/domain/langchain/linsight_knowledge.py`
  **逻辑**: 保留 Document；`setdefault knowledge_id/knowledge_name/access_scope=per_user`；`annotate_rag_documents_with_citations` → `collect_rag_citation_registry_items` → `cache_citation_registry_items`；输出 `KnowledgeUtils.format_retrieved_chunk`。注解包窄 try/except，失败回退裸结果。不改白名单 / `_arun` 软错误契约。论证见 design 决策 2 / 坑 1、2、9、12。
  **测试**: T003 全部通过；既有 `test_linsight_knowledge.py` 保持通过。
  **覆盖 AC**: AC-01, AC-13
  **依赖**: T003

### Wave 2：web_search 包装与提示词

- [x] **T005**: web 包装 + 引用规则提示词单元测试
  **文件**: `src/backend/test/linsight/test_linsight_citation_agent.py`
  **逻辑**: 不拉起 `create_linsight_agent` 全图。测：① `_wrap_linsight_web_citation_tools`：假 web_search 返回 JSON list 时输出含 `citation_key` 且调用 cache；非 list / 非法 JSON 原样返回且不 raise；非 web_search 工具不包装。② `_with_citation_rules` / `_build_researcher_prompt`：有 KB 或有 web 时 prompt 含 `\ue200`；两者都没有时不含；researcher 在有检索时要求末条带回 chunk_id/citation_key。③ `_build_researcher_subagent` 对含 web_search 的工具列表也会注入规则。
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-13
  **验证**: `cd src/backend && uv run pytest test/linsight/test_linsight_citation_agent.py`
  **依赖**: 无

- [x] **T006**: agent_factory 包装 web_search 并注入 citation.yaml
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: `create_linsight_agent` 入口 `_wrap_linsight_web_citation_tools`（name/`tool_name`==`web_search`）。主 prompt / researcher prompt 在 has_kb 或 has_web 时追加 `CITATION_PROMPT_RULES`；researcher 另加末条带回标记。不改 `init_linsight_config_tools`。论证见 design 决策 3、7 / 坑 3、4。
  **测试**: T005 全部通过；既有 `test_subagent_reintroduction.py` / `test_skill_prompt_priority.py` 保持通过。
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-13
  **依赖**: T005

### Wave 3：任务完成落库

- [x] **T007**: 完成路径接线单元测试
  **文件**: `src/backend/test/linsight/test_task_exec_report_citations.py`
  **逻辑**: mock `persist_task_turn_message` 返回带 int id 的 ChatMessage；patch `_persist_report_citations`。断言 `_handle_task_success` / `_handle_direct_answer_completion` / `_handle_task_partial` 在 persist 消息之后调用 `_persist_report_citations`；`_handle_task_failure` 不调用。另测 `_persist_report_citations`：拼接 answer + 真实存在的 `output/*.md` 后调用 `persist_linsight_report_citations`；读文件失败 / helper raise 不向外抛。不新增 `MessageEventType`。
  **覆盖 AC**: AC-05, AC-15
  **验证**: `cd src/backend && uv run pytest test/linsight/test_task_exec_report_citations.py`
  **依赖**: T002

- [x] **T008**: task_exec 三处完成路径落引用
  **文件**: `src/backend/bisheng/linsight/domain/task_exec.py`
  **逻辑**: 新增 `_persist_report_citations`；在 `_handle_task_success` / `_handle_direct_answer_completion` / `_handle_task_partial` 捕获 `persist_task_turn_message` 返回值后调用。启动占位与 `_handle_task_failure` 不调用。窄 try/except，失败只打 warning。不写 history、不 push 新事件。论证见 design 决策 4 / 坑 5、11。
  **测试**: T007 全部通过；既有 `test_unified_task_turn_write.py` 保持通过。
  **覆盖 AC**: AC-05, AC-15
  **依赖**: T002, T007

### Wave 4：手工验收

- [x] **T009**: Phase 1 手工 E2E 清单
  **文件**: `features/v3.0.0-beta1/047-linsight-citation-traceability/e2e-checklist.md`
  **逻辑**: 把 design §7 写成可勾选清单（KB 角标 + bbox、Web 开新页、无权限灰态 /resolve 不泄漏、无引用不落库、漏标不报错）。不改业务代码。
  **覆盖 AC**: AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-14
  **测试降级**: 依赖本地前后端 + 测试环境 ES/Milvus/MinIO + 真模型；INV-7 需第二个无 `view_file` 账号。前端零改动，不进 PR 单测门禁。resolve 过滤回归继续由既有 `test/citation/test_citation_resolve_visibility.py` 守住。
  **依赖**: T004, T006, T008

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。
