# HANDOFF.md — 知识空间统一存储与文件发布引用化 重构

**接手 agent 请先阅读 `bisheng_2/CLAUDE.md` 建立全局约束，然后按本文档逐项推进。**

---

## 状态概览

| 里程碑 | 状态 | 提交 |
|--------|------|------|
| T0.6 契约冻结 | ✅ 完成 | `b8c009ff4` |
| F1 共享存储适配层 | ✅ 完成 | `ea0b87172` |
| F2 双 Projection | ✅ 完成 | `c060e34ca` |
| **F3 Scope Resolver** | 🔴 **阻塞** | 未提交 |
| F4 迁移/可观测 | ⬜ 未开始 | — |
| B1-B8 业务模块 | ⬜ 未开始 | — |

**F3 阻塞原因**：resolver 代码和测试文件已落盘，但**仓库层缺少三个方法**——resolver 导入的是仓库模块名，编译能过，但 `find_active_entries_for_documents`、`find_distribution_entries_by_document_id`、`mark_document_entries_content_generation` 从未在接口/实现中定义。前一个 agent 用 mock 跑通了 36 个测试，但其真实实现从未落盘。

---

## 操作模式

**串行、逐任务、单 agent**。不要并行启动多个 agent（API 配额有限）。

分支：`feat/unified-space-storage`（在 `bisheng_2/` 内，该目录本身是 git 仓库）

---

## 前置命令

```bash
# 所有命令从 bisheng_2/src/backend 执行
cd /Users/zhangguoqing/works/shougang/bisheng_2/src/backend

# 运行测试
.venv/bin/python -m pytest test/knowledge/test_shared_space_storage_adapter.py test/knowledge/test_shared_space_projection.py test/knowledge/test_knowledge_retrieval_scope_resolver.py -q -p no:cacheprovider

# 格式化
uv run ruff format <file>
uv run ruff check --fix <file>
```

---

## 第一步：确认仓库文件真实状态

```bash
git log --oneline -6
git status --short
grep -n "find_active_entries_for_documents\|find_distribution_entries\|mark_document_entries" bisheng/knowledge/domain/repositories/interfaces/knowledge_file_repository.py
```

若上述 grep 没有输出，说明三个方法**确实不在接口中**，需要补全。

---

## 第二步：补齐 KnowledgeFileRepository 接口

**文件**：`bisheng/knowledge/domain/repositories/interfaces/knowledge_file_repository.py`

需要新增三个方法签名：

```python
@abstractmethod
async def find_active_entries_for_documents(
    self,
    *,
    tenant_id: int,
    document_ids: list[int],
    knowledge_ids: list[int],
) -> list[KnowledgeFile]:
    """F3: batch query active entries for given documents within requested spaces.

    Filters: tenant_id match, reference_document_id IN document_ids,
    knowledge_id IN knowledge_ids, entry_status=ACTIVE,
    entry_type IN (manager, publish, share).
    """
    ...

@abstractmethod
async def find_distribution_entries_by_document_id(
    self, document_id: int, *, for_update: bool = False,
) -> list[KnowledgeFile]:
    """F2: all distribution entries (manager/publish/share) for a document.

    Used by shared projection to re-aggregate knowledge_ids after
    entry create/delete/primary-switch.
    """
    ...

@abstractmethod
async def mark_document_entries_content_generation(
    self, document_id: int, new_generation: int,
) -> None:
    """F2: bulk update applied_content_generation for all entries of a document.

    Called after primary version switch to bump content generation
    on all distribution entries.
    """
    ...
```

---

## 第三步：补齐 KnowledgeFileRepository 实现

**文件**：`bisheng/knowledge/domain/repositories/implementations/knowledge_file_repository_impl.py`

### 3.1 `find_active_entries_for_documents`

```python
async def find_active_entries_for_documents(
    self,
    *,
    tenant_id: int,
    document_ids: list[int],
    knowledge_ids: list[int],
) -> list[KnowledgeFile]:
    if not document_ids or not knowledge_ids:
        return []
    stmt = (
        select(KnowledgeFile)
        .where(
            KnowledgeFile.tenant_id == tenant_id,
            KnowledgeFile.reference_document_id.in_(document_ids),
            KnowledgeFile.knowledge_id.in_(knowledge_ids),
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
            KnowledgeFile.entry_type.in_([
                KnowledgeFileEntryType.MANAGER.value,
                KnowledgeFileEntryType.PUBLISH.value,
                KnowledgeFileEntryType.SHARE.value,
            ]),
        )
    )
    result = await self._session.execute(stmt)
    return list(result.scalars().all())
```

### 3.2 `find_distribution_entries_by_document_id`

在现有实现中查找是否已有类似查询（如 `find_by_reference_document_id`），若已有则复用/调整；若无则新增：

```python
async def find_distribution_entries_by_document_id(
    self, document_id: int, *, for_update: bool = False,
) -> list[KnowledgeFile]:
    stmt = (
        select(KnowledgeFile)
        .where(
            KnowledgeFile.reference_document_id == document_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.entry_type.in_([
                KnowledgeFileEntryType.MANAGER.value,
                KnowledgeFileEntryType.PUBLISH.value,
                KnowledgeFileEntryType.SHARE.value,
            ]),
        )
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await self._session.execute(stmt)
    return list(result.scalars().all())
```

**⚠️ DM8 兼容性**：
- 不使用 `JSON_EXTRACT`、`JSON_CONTAINS`
- 不使用 `LONGTEXT`（用 `LargeText`）
- 不使用 `ON UPDATE CURRENT_TIMESTAMP`（用 `UPDATE_TIME_SERVER_DEFAULT`）
- `with_for_update()` 在 DM8 上可能需要适配——检查 `dialect_helpers` 中是否有包装

### 3.3 `mark_document_entries_content_generation`

```python
async def mark_document_entries_content_generation(
    self, document_id: int, new_generation: int,
) -> None:
    stmt = (
        update(KnowledgeFile)
        .where(
            KnowledgeFile.reference_document_id == document_id,
            KnowledgeFile.file_type == FileType.FILE.value,
        )
        .values(applied_content_generation=new_generation)
    )
    await self._session.execute(stmt)
    await self._session.commit()
```

---

## 第四步：验证 F3 resolver 代码完整性

**文件**：`bisheng/knowledge/domain/services/knowledge_retrieval_scope_resolver.py`（765 行，已落盘）

需确认以下要点：
1. `from ...knowledge_file_repository import KnowledgeFileRepository` 导入是否成功（应已存在）
2. `self.file_repository.find_active_entries_for_documents(...)` 调用是否与接口签名匹配
3. `_require_projection_ready` 在 `_select_and_authorize_entry` 的候选循环中用的是 `raise` 而非 `continue`——若候选 entry 投影未就绪会直接报错。这是 fail-closed 语义，需确认是否符合契约预期

**文件**：`test/knowledge/test_knowledge_retrieval_scope_resolver.py`（932 行，36 个测试，但可能用了 mock 绕过真实仓库）

---

## 第五步：运行回归测试

```bash
cd /Users/zhangguoqing/works/shougang/bisheng_2/src/backend
.venv/bin/python -m pytest test/knowledge/ -q -p no:cacheprovider 2>&1 | tail -40
```

**已知预存失败**（约 140 个，非本次引入）：
- `test_tag_library_append_file_tags.py`
- `test_backfill_file_subcategories_script.py`
- `test_knowledge_space_content_projection_events.py`（×2）
- `test_knowledge_parse_queue_redis.py`（需要真实 Redis）

**目标**：F1/F2/F3 相关测试（约 56 个）全部通过，不引入新失败。

---

## 第六步：提交 F3

```bash
git add -A
git commit -m "feat(space-shared-storage): F3 retrieval scope resolver

- SqlKnowledgeRetrievalScopeResolver implementing KnowledgeRetrievalScopeResolver
- F3.1: resolve_request with OpenFGA space visibility check (fail-closed)
- F3.2: build_backend_filter with tenant boundary + routing version assertion
- F3.3: map_and_authorize_hits with O(Top-K) batch entry query + F059 checks
- F3.4: overfetch top-up loop (default Kx2, max 4 rounds) for dirty members
- F3.5: dedup per canonical chunk with explicit > space-order > type priority
- F3.6: MappedEntryHit no raw metadata leakage
- F3.7: fail-closed on all error paths
- repository: find_active_entries_for_documents batch query
- repository: find_distribution_entries_by_document_id for F2 runtime
- repository: mark_document_entries_content_generation for primary switch
- render_milvus_expr / render_es_membership_query pre-filter renders"
```

---

## 关键文件清单

| 文件 | 用途 |
|------|------|
| `bisheng/knowledge/domain/contracts/retrieval_scope.py` | 冻结契约（只读参考） |
| `bisheng/knowledge/domain/contracts/errors.py` | 错误码枚举 |
| `bisheng/knowledge/domain/services/knowledge_retrieval_scope_resolver.py` | F3 核心实现（已落盘） |
| `bisheng/knowledge/domain/repositories/interfaces/knowledge_file_repository.py` | **需补接口** |
| `bisheng/knowledge/domain/repositories/implementations/knowledge_file_repository_impl.py` | **需补实现** |
| `bisheng/knowledge/rag/shared_space_storage.py` | F1 共享存储适配器 |
| `bisheng/knowledge/domain/services/knowledge_document_projection_service.py` | F2 双投影 |
| `bisheng/knowledge/domain/services/shared_space_projection_support.py` | F2 辅助函数 |
| `bisheng/worker/knowledge/document_projection.py` | F2 worker 钩子 |
| `test/knowledge/test_knowledge_retrieval_scope_resolver.py` | F3 测试（36 个） |
| `test/knowledge/test_shared_space_projection.py` | F2 测试（20 个） |
| `test/knowledge/test_shared_space_storage_adapter.py` | F1 测试（20 个） |

---

## 注意事项

1. **多租户**：不要手写 `WHERE tenant_id = X`，SQLAlchemy 事件自动注入。
2. **DM8 兼容**：不用 `JSON_EXTRACT`/`JSON_CONTAINS`/`JSON_SEARCH`/`LONGTEXT`/`ON UPDATE CURRENT_TIMESTAMP`。
3. **所有新逻辑有开关**：`knowledge_space_shared_storage.enabled` + 路由行 `shared_enabled`，开关关闭 = 零行为变化。
4. **契约不可改**：`domain/contracts/` 下的文件是冻结的，只能读不能改。
5. **测试无需 asyncio 标记**：`pyproject.toml` 中 `asyncio_mode=auto`。
