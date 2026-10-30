# 门户问答引用并入被系统化调用知识数

验证规则生效后，门户智能问答和写作模板回答正文里的引用，会让对应非个人库知识计入看板「被系统化调用知识数」。同一份知识仍只计 1。没打开过、只被正文引用的知识也计 1。

```bash
cd src/backend
BISHENG_E2E=1 .venv/bin/python -m pytest ../../e2e/qa-citation-called-count/test_qa_citation_called_flow.py -q --tb=short
```

测试直接写配置里的 MySQL、Redis 和看板 Elasticsearch，结束时删除本次插入的行和日统计。不启动门户，也不调用大模型。

## 要起的服务

- 同一版毕昇 API 和内容统计 Celery worker。工人需能识别 `portal_qa_citation`。
- 门户 BFF，问答走毕昇 `shougang-portal/chat/completions`。
- MySQL、Redis、看板 Elasticsearch。

## 数据前提

- 一份仍在当前库存中的非个人库知识，之前没有预览和下载。
- 一个能打开知识空间内容统计看板的账号。
- 用门户智能问答或写作模板提问，并得到回答正文里带引用标记、指向这份知识的成功回答。

## 核对

1. 回答成功后，Elasticsearch `mid_knowledge_space_content_stat` 出现该文件的 `record_type=qa_citation_daily`，且 `qa_citation_count > 0`，`space_level` 不是 `personal`。
2. 看板指标 `called_document_count` 把这份知识计 1。再预览一次，数字仍是 1。
3. `export_portal_category_usage.py` 对同一租户、同一库存的「被系统化调用数量」包含这份知识。
4. 正文没有引用标记的成功回答，不新增 `qa_citation_daily`。
5. 个人库文件即使出现在正文引用里，也不进入该指标。
6. `portal_qa` 的智能问答次数不因引用文件数增加。

不回补本版发布前的历史回答。
