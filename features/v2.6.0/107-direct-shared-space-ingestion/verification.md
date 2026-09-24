# Verification: F107 共享知识空间直接解析入库

**Feature ID**: `107-direct-shared-space-ingestion`  
**Verified**: 2026-09-03  
**Result**: 本地实现验证通过；待部署后执行真实 SPACE 文件重试

## 自动化证据

### V1 契约与静态验证

- 真实故障回归先验证旧实现出现 `2 failed`：共享 schema 找不到 `tenant_id`，writer row 读取该键时
  触发 `KeyError`；补写后同一用例 `2 passed`。
- `uv run --python=.venv/bin/python ruff check --select E9,F63,F7,F82` 针对本次三个 Python 改动文件。
  - 结果：通过。
- `uv run ruff check bisheng/knowledge/domain/services/shared_space_direct_ingestion_service.py test/knowledge/test_shared_space_direct_ingestion.py`
  - 结果：通过。
- `uv run ruff format --check` 针对上述两个新增文件。
  - 结果：通过。
- `git diff --check`
  - 结果：通过。
- `uv run python -m compileall -q` 针对本次主要 Python 实现文件。
  - 结果：通过。
- 数据面契约审计：共享 schema 保留非空 `tenant_id`，writer row 与 ES metadata 固定补写 `1`；
  Milvus 表达式与 ES filter 不使用 tenant filter。

### V2 模块与集成回归

执行：

```text
uv run pytest \
  test/knowledge/test_shared_space_contracts.py \
  test/knowledge/test_shared_space_storage_adapter.py \
  test/knowledge/test_shared_space_direct_ingestion.py \
  test/knowledge/test_knowledge_retrieval_scope_resolver.py \
  test/knowledge/test_shared_space_projection.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/knowledge/fulltext/test_fulltext_worker.py -q
```

结果：`167 passed`。

补充执行：

```text
uv run pytest \
  test/knowledge/test_knowledge_file_parse_lifecycle.py \
  test/knowledge/test_file_title_worker.py \
  test/test_knowledge_space_content_telemetry.py::test_add_embedding_enqueues_file_stat_after_success -q
```

结果：`11 passed`。

## 验收覆盖

| AC | 证据 | 结果 |
|---|---|---|
| AC-001 | routed parse 测试断言旧 Milvus/ES 初始化均未调用 | 通过 |
| AC-002 | schema 保留非空 `tenant_id`，writer row/ES metadata 固定为 `1`，查询无 tenant filter | 通过 |
| AC-003 | shared writer 失败无 fallback；pending generation 重试复用 | 通过 |
| AC-004 | writer generation 幂等测试与 direct ingestion 写入顺序 | 通过 |
| AC-005 | 正常 projection service 不注入 legacy chunk loader | 通过 |
| AC-006 | 未路由 SPACE、非 SPACE 参数化 legacy 兼容测试 | 通过 |
| AC-007 | 既有 metadata schema 与 writer row 兼容契约测试 | 通过 |

## 人工门禁

本次修复不要求迁移生产 Milvus/ES。部署后重新解析故障文件 `9992228`，确认 Milvus insert、ES
metadata、文件 SUCCESS 与 projection READY 同时收敛。若未来删除物理 `tenant_id` 字段，则必须
另建 collection/index 并迁移，不能复用当前 schema。
