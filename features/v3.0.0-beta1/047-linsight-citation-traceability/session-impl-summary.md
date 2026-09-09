# F047 灵思任务模式引用溯源 — 本会话实现总结

**特性**: v3.0.0-beta1 / 047-linsight-citation-traceability  
**目标**: 任务完成后只保存报告**实际引用**的来源，并在结果摘要 / 报告预览里用日常模式同一套 Markdown 画出可点角标（文档名、摘录、知识库、页码）。

---

## 1. 做成了什么

### 1.1 检索时登记来源

- 知识库检索结果带 `<chunk_id>`（如 `knowledgesearch_xxx:10`），写入 Redis 引用登记表。
- 联网检索结果带 `citation_key`（如 `websearch_xxx:0`），同样登记。
- 登记失败不打断检索；模型只看到带出处的检索文本。

### 1.2 模型必须写真实引用标记

- 提示词要求标记是 Unicode 私有区字符 `U+E200 / U+E201 / U+E202`，禁止六字符转义 `\ue200`。
- 写入 `output/*.md` 时，工作区后端会把转义还原成真实 PUA，避免落盘后前端画不出角标。

### 1.3 任务完成时只落「正文里出现过的」来源

- 从口播 `answer` + 本地 `output/*.md` 抽出 citationId。
- 按 id 回 Redis，再按正文过滤；**无标记不落库**（禁止走会「无标记落全部」的旧 helper）。
- 有任务 `ChatMessage.id` 才 `save_message_citations`；失败只打 warning，不打断任务完成。
- 页面 payload `output_result.citations` **去掉 RAG 签名 URL**（`previewUrl` / `downloadUrl` / `sourceUrl`），前端仍走 `/citations/resolve`。

### 1.4 结果摘要也能出角标

日常模式 Markdown **只对正文里的 PUA 标记画角标**，`citations` 数组 alone 不够。灵思收尾口播往往 1～2 句、没有标记，标记在报告文件里。

完成时：

1. 若口播已有标记 → 不动。
2. 否则把报告里**带标记的段落**接到 `output_result.answer` 后面。
3. 把过滤后的 citations 写入 `output_result`，再 `set_session_version_info` + `FINAL_RESULT`。
4. 口播若被改写，再回写任务 `ChatMessage`，与会话版本对齐。

### 1.5 前端复用日常模式 Markdown

结果区、历史轮次、文件预览把 `output_result.citations` + `message_id` 传给同一套 `Markdown`，角标交互与日常问答一致。

### 1.6 会话运行锁（顺带）

同一 session 防止并发跑：Redis `linsight:run_lock:`；`IN_PROGRESS` 守卫；`async_continue` 异常兜住。

---

## 2. 完成路径上修过的两个坑

| 现象 | 根因 | 处理 |
|------|------|------|
| worker 写了带 `\ue200` 的 md，页面仍无角标 | 结果区渲染的是无标记口播 | 曾用 `answer_with_visible_citations` 把报告带标记段落接到 answer；2026-09-09 按产品决定移除（结果区只显示模型原话，角标在报告预览中呈现） |
| worker 打 `saved=1 answer_has_markers=True`，页面仍是纯口播 | `output_result` 是 JSON 字段，原地改不脏；`set_session_version_info` 的 `commit+refresh` 冲掉内存改动；`FINAL_RESULT` / 前端 reconcile 读到旧值 | 拷贝成新 dict 再赋回 `session_model.output_result`，再落库 / 推事件 |

页面上的 `` `knowledgesearch_xxx:10` `` 若出现在口播反引号里，那是模型**用文字提到** id，不是角标。角标只来自 PUA 标记。

---

## 3. 运行时数据流

```
search_knowledge_base / web_search
        ↓ 登记 Redis（citationId + 文档名/摘录/页码）
模型 write_file → output/*.md（真实 U+E200…）
        ↓ 任务完成（success / direct-answer / partial）
persist_task_turn_message
        ↓
_persist_report_citations
  · 读 answer + output/*.md
  · persist_linsight_report_citations（只保存正文引用到的）
  · 新 dict 赋回 output_result（citations）
  · （2026-09-09 移除：不再把报告带标记段落拼进 answer，也不再二次回写 ChatMessage）
  · set_session_version_info
        ↓
FINAL_RESULT（整包 session，含 output_result）
        ↓
前端 ResultSection / PreviewBody → Markdown（角标 + /citations/resolve）
```

---

## 4. 修改位置

### 4.1 后端 — 引用核心

| 文件 | 改动 |
|------|------|
| `src/backend/bisheng/citation/domain/services/citation_prompt_helper.py` | `unescape_citation_markers`；`persist_linsight_report_citations`（只按正文 citationId 落库，返回 items）；`serialize_citation_items_for_page`（去 RAG 签名 URL）；`strip_citation_markers`（导出/下载去标记与来源 ID，2026-09-09） |
| `src/backend/bisheng/core/prompts/yaml/citation.yaml` | 强制真实 PUA；禁止 `\ue200` 转义；File Output 条款 |
| `src/backend/bisheng/tool/domain/langchain/linsight_knowledge.py` | `base_search`：annotate + cache + `format_retrieved_chunk`（`<chunk_id>`） |

### 4.2 后端 — 灵思执行

| 文件 | 改动 |
|------|------|
| `src/backend/bisheng/linsight/domain/task_exec.py` | `_persist_report_citations`（success / direct-answer / partial）；口播补段落；新 dict 赋回 JSON 字段；Redis 运行锁 |
| `src/backend/bisheng/linsight/domain/services/agent_factory.py` | 包装 `web_search` 写 `citation_key`；主/子代理注入 citation 规则 |
| `src/backend/bisheng/linsight/domain/services/workspace_backend.py` | 写 `.md` 时 unescape 转义标记 |
| `src/backend/bisheng/linsight/domain/utils.py` | 会话状态 / 任务消息等配套（含运行锁相关） |

### 4.3 前端 — 把 citations 接到 Markdown

| 文件 | 改动 |
|------|------|
| `src/frontend/client/src/components/Linsight/Artifacts/ResultSection.tsx` | `citations` + `messageId` → `Markdown` |
| `src/frontend/client/src/components/Linsight/Artifacts/PreviewBody.tsx` | 预览 md 同样传 citations |
| `src/frontend/client/src/components/Linsight/Artifacts/FilePreviewPanel.tsx` | 向下传 |
| `src/frontend/client/src/components/Linsight/Artifacts/WorkspacePanel.tsx` | 向下传 |
| `src/frontend/client/src/components/Linsight/Execution/ExecutionFlow.tsx` | 结果区 + 预览：`output_result.citations`、`message_id` |
| `src/frontend/client/src/components/Linsight/Execution/TaskTurnPanel.tsx` | 同上 |
| `src/frontend/client/src/components/Linsight/Execution/ConversationRound.tsx` | 历史轮次结果区带 `citations` |
| `src/frontend/client/src/components/Chat/ChatView.tsx` | 日常会话里的任务预览用 `taskLinsight?.output_result?.citations` |
| `src/frontend/client/src/api/linsight.ts` | 类型补 `citations` |
| `src/frontend/client/src/hooks/Websocket/index.tsx` | `FINAL_RESULT` 整包写入 `output_result`（含 citations / 改写后的 answer） |

未改日常模式 `Markdown` 本身，只接线。

### 4.4 测试

| 文件 | 覆盖 |
|------|------|
| `src/backend/test/citation/test_persist_linsight_report_citations.py` | 有/无标记落库、unescape、serialize 去 URL、口播补段落 |
| `src/backend/test/linsight/test_task_exec_report_citations.py` | 三处完成路径调用 persist；读 md；吞异常；citations 上屏；新 dict 赋回；改写 answer 后回写消息 |
| `src/backend/test/linsight/test_linsight_knowledge_citations.py` | KB 检索登记 |
| `src/backend/test/linsight/test_linsight_citation_agent.py` | web 包装 + prompt 注入 |
| `src/backend/test/linsight/test_session_run_lock.py` | 运行锁 |

相关回归：`test_final_result_selection.py`、`test_workspace_backend.py`、`test_skill_prompt_priority.py` 等。

### 4.5 文档

| 文件 | 说明 |
|------|------|
| `features/v3.0.0-beta1/047-linsight-citation-traceability/tasks.md` | 任务拆解（T001–T009） |
| `features/v3.0.0-beta1/047-linsight-citation-traceability/e2e-checklist.md` | 手工验收清单 |

---

## 5. 关键函数

| 函数 | 位置 | 作用 |
|------|------|------|
| `persist_linsight_report_citations` | `citation_prompt_helper.py` | 只保存正文引用到的来源 |
| `serialize_citation_items_for_page` | 同上 | 页面 JSON，去掉 RAG 签名 URL |
| `strip_citation_markers` | 同上 | 导出 Word/PDF、批量下载 zip 时去掉引用标记与来源 ID（2026-09-09；`answer_with_visible_citations` 已移除） |
| `unescape_citation_markers` | 同上 | `\ue200` → 真实 U+E200 |
| `_persist_report_citations` | `task_exec.py` | 完成路径：落库 + 改 `output_result` + 打日志 |
| `_wrap_linsight_web_citation_tools` | `agent_factory.py` | web_search 结果加 citation_key 并登记 |

完成日志：

```text
linsight citations session=<id> saved=<N> answer_has_markers=True
```

`saved` / `answer_has_markers` 在**赋回新 dict 之后**仍表示本地计算结果；要以页面 `output_result.answer` 是否含 `\ue200`、是否带 `citations` 为准。改 JSON 字段赋值后，`FINAL_RESULT` 与版本列表应一致。

---

## 6. 验证

```bash
cd src/backend
uv run pytest \
  test/citation/test_persist_linsight_report_citations.py \
  test/linsight/test_task_exec_report_citations.py \
  test/linsight/test_linsight_knowledge_citations.py \
  test/linsight/test_linsight_citation_agent.py \
  test/linsight/test_session_run_lock.py -q
```

真环境：改 `task_exec.py` 后必须**重启** `start_task_worker.sh`。成功时结果摘要末尾出现报告里带角标的段落；点角标能看到文档名 / 摘录 / 知识库 / 页码。打开 `output/*.md` 预览同样有角标。

---

## 7. 仍未收口

- 模型「重新生成」时可能只 `read_file` 旧稿、不 `write_file`，标记会停留在上一轮 citationId。
- 模型可能编造未检索到的下标（如本轮只有 `:10` 却写 `:12` / `:18`）。persist 按 **citationId（冒号前）** 匹配，同一检索仍能挂上；角标详情可能对不齐虚假 item。
- 口播里用反引号写出的 `knowledgesearch_xxx:10` 不会变成角标。
- 历史轮次 `ConversationRound` 目前只传了 `citations`，未传 `messageId`；角标可画，详情 resolve 可能不如当前轮完整。
