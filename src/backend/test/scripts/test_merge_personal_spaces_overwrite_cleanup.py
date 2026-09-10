"""覆盖清理必须区分索引可见性延迟与真实残留, 并在失败处停止。"""

import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from elastic_transport import ConnectionTimeout

from test.scripts.test_merge_personal_knowledge_spaces import file, m, space


@pytest.mark.parametrize(
    "failure, expected_failure",
    [(None, None), ("residual", "indexes"), ("refresh", "indexes"), ("timeout", "indexes"), ("objects", "objects")],
)
async def test_overwrite_refreshes_stale_counts_and_stops_on_failure(monkeypatch, failure, expected_failure):
    visible = {"count": 367}
    mutations = []

    def refresh(**kwargs):
        assert kwargs == {"index": "target-index"}
        if failure == "timeout":
            raise ConnectionTimeout("refresh timed out")
        if failure == "refresh":
            return {"_shards": {"failed": 1}}
        if failure != "residual":
            visible["count"] = 0
        return {"_shards": {"failed": 0}}

    es = SimpleNamespace(
        indices=SimpleNamespace(exists=Mock(return_value=True), refresh=Mock(side_effect=refresh)),
        count=Mock(side_effect=lambda **kwargs: dict(visible)),
    )
    es.options = Mock(return_value=es)
    monkeypatch.setitem(
        sys.modules,
        "bisheng.knowledge.domain.knowledge_rag",
        SimpleNamespace(
            KnowledgeRag=SimpleNamespace(init_knowledge_es_vectorstore_sync=lambda **kwargs: SimpleNamespace(client=es))
        ),
    )
    monkeypatch.setattr(m, "_count_milvus_records", lambda *args: 0)
    monkeypatch.setattr(m, "delete_vector_files", Mock(return_value=True))
    monkeypatch.setattr(m, "_overwrite_object_names", lambda f: (f"original/{f.id}",))

    def remove_object(**kwargs):
        mutations.append("objects")
        if failure == "objects":
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(
        m,
        "get_minio_storage_sync",
        lambda: SimpleNamespace(
            bucket="files",
            remove_object_sync=remove_object,
            object_exists_sync=lambda *args: False,
        ),
    )
    monkeypatch.setattr(m, "_clear_tag_links", AsyncMock(side_effect=lambda *args: mutations.append("tags")))
    monkeypatch.setattr(m, "_tag_snapshot", AsyncMock(return_value=m.TagSnapshot()))
    monkeypatch.setattr(
        m, "_replace_permission_tuples", AsyncMock(side_effect=lambda *args: mutations.append("permissions"))
    )
    monkeypatch.setattr(m, "_read_permission_tuples", AsyncMock(return_value=()))

    @asynccontextmanager
    async def session():
        mutations.append("associations")
        yield SimpleNamespace(exec=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())

    monkeypatch.setattr(m, "get_async_db_session", session)
    monkeypatch.setattr(
        m.KnowledgeFileDao, "adelete_batch", AsyncMock(side_effect=lambda *args: mutations.append("database_record"))
    )
    monkeypatch.setattr(m.KnowledgeFileDao, "query_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(m.KnowledgeDao, "async_update_knowledge_update_time_by_id", AsyncMock())
    target_space = space().model_copy(update={"index_name": "target-index"})
    target = m.TargetContext(1, target_space, None, SimpleNamespace(user_id=7), "", 0)
    operations = m.GuardedOperations(1, {})
    result = await operations.delete_overwrite_target(m.OverwriteTarget("file:126739", (file(126739),)), target)

    es.indices.refresh.assert_called_once_with(index="target-index")
    es.options.assert_called_once_with(request_timeout=60, max_retries=0, retry_on_timeout=False)
    if expected_failure:
        assert result[-1].component == expected_failure
        assert result[-1].status == "failed"
        assert mutations == (["objects"] if failure == "objects" else [])
    else:
        assert all(step.status == "success" for step in result)
        assert result[0].detail["remaining"] == {"milvus_count": 0, "es_count": 0}
        assert mutations == ["objects", "tags", "permissions", "associations", "database_record"]


async def test_version_chain_indexes_checked_before_deleting_any_objects(monkeypatch):
    monkeypatch.setattr(m, "delete_vector_files", Mock(return_value=True))
    monkeypatch.setattr(m, "_index_snapshot", lambda space, fid: m.IndexSnapshot(1 if fid == 102 else 0, 0))
    storage = Mock(side_effect=AssertionError("must not delete objects before all indexes pass"))
    monkeypatch.setattr(m, "get_minio_storage_sync", storage)
    target = m.TargetContext(1, space(), None, SimpleNamespace(user_id=7), "", 0)
    operations = m.GuardedOperations(1, {})
    result = await operations.delete_overwrite_target(
        m.OverwriteTarget("document:35695", (file(101), file(102))), target
    )
    assert [(s.component, s.status, s.target_file_id) for s in result] == [
        ("indexes", "success", 101),
        ("indexes", "failed", 102),
    ]
    storage.assert_not_called()
