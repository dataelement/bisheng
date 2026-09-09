# F047 Phase 1 手工验收清单

> 前端零改动。预览走 `PreviewBody` → `Chat/Messages/Content/Markdown`。
> 单测不覆盖真模型 / 权限账号；resolve 过滤回归由 `test/citation/test_citation_resolve_visibility.py` 守住。

**启动**（连测试环境 ES / Milvus / MinIO，不改测试部署）：

1. 后端：`export config=config.yaml; uv run uvicorn bisheng.main:app --port 7860`
2. 灵思 worker：`uv run python bisheng/linsight/worker.py`
3. client：`pnpm --filter bishengchat start`（:4001，base `/workspace`）

---

## 主路径

- [ ] **KB 角标**：任务模式选含 PDF 的知识库，提交会检索该库的任务。报告预览正文出现 `[1][2]` 上标；悬浮卡有文档名 + 页码；点击打开原文件预览；PDF 高亮并定位到被引页/段。
- [ ] **Web 角标**：同一任务打开联网检索。网页来源角标悬浮显示标题/站点；点击在新标签打开原 URL。
- [ ] **磁盘 md 保留裸标记**：`output/*.md` 含 `\ue200…\ue202`，不是可见 `[1]`。
- [ ] **只落已引用**：任务完成后，`message_citation` 仅有报告里出现过的 citationId（未引用的检索命中不落库）。`message_id` = 该轮 `category=task` 的 ChatMessage id。

## 权限（INV-7 / AC-07, AC-12）

- [ ] 换一个对该 PDF **无查看权限**的用户打开同一报告：该 KB 角标为「无权限」灰态，点击打不开。
- [ ] 该用户调用 `POST /api/v1/citations/resolve` 的响应**不含**该文件的文件名 / URL / chunk 等结构化字段。
- [ ] Web 角标不受此过滤，仍可打开。

## 降级

- [ ] 模型漏打部分标记：已标记的角标正常，未标记处无角标、无报错（AC-14）。
- [ ] 检索命中但报告零引用：无角标，不写 `message_citation`。
- [ ] 子代理检索、主流程写报告：主报告仍能出现子代理带回的标记（AC-04）；主流程转述丢失则少角标，任务不失败。

## 非侵入（AC-15）

- [ ] 执行过程无新的流式事件类型；任务步骤 history 结构不变。
- [ ] 日常对话模式角标行为与改前一致。
