from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_chunk_repository_impl import (
    KnowledgeFulltextChunkRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_repository_impl import (
    KnowledgeFulltextOutboxRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunkSource
from test.knowledge.fulltext.test_fulltext_outbox_repository import make_session
from test.knowledge.fulltext.test_fulltext_sync_service import outbox, service, snapshot


async def test_batch_isolates_bad_file_preserves_delete_and_rejects_stale_lease():
    sync, repo, source, chunks, index = service()
    rows = [outbox(id=i, aggregate_id=i) for i in range(1, 5)]
    source.get_current_snapshots.return_value = {1: snapshot(file_id=1), 2: snapshot(file_id=2), 4: snapshot(file_id=4)}
    source.get_chunk_sources.return_value = {
        i: KnowledgeFulltextChunkSource(index_name="rag", file_id=i, knowledge_id=9) for i in (1, 2, 4)
    }
    chunks.list_many.return_value = {1: [object()], 2: ValueError("bad chunks"), 4: [object()]}
    repo.lock_current_many.return_value = rows[:3]
    index.apply_batch.return_value = {1: None, 3: None}
    result = await sync.sync_files_batch(rows, lease_owner="a")
    assert result == {1: None, 2: "ValueError", 3: None}
    writes = index.apply_batch.await_args.args[0]
    assert set(writes) == {1, 3}
    assert writes[3] is None
    source.get_current_snapshots.assert_awaited_once()
    chunks.list_many.assert_awaited_once()
    repo.settle_many.assert_awaited_once()


async def test_bulk_preserves_engagement_and_reports_partial_failure():
    client = AsyncMock()
    client.bulk.return_value = {
        "items": [{"update": {"status": 200}}, {"delete": {"status": 404}}, {"delete": {"status": 503}}]
    }
    document = SimpleNamespace(
        model_dump=lambda **kw: {"file_id": 1, "content": "正文", "preview_count": 9, "download_count": 3}
    )
    result = await KnowledgeFulltextIndexRepositoryImpl(client).apply_batch({1: document, 2: None, 3: None})
    assert result == {1: None, 2: None, 3: "FulltextBulkWriteError"}
    body = client.bulk.await_args.kwargs["operations"][1]
    assert "preview_count" not in body["doc"]
    assert body["upsert"]["preview_count"] == 9


async def test_chunks_batch_reads_all_pages_and_keeps_documents_separate():
    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit"}

    def hit(file_id, index):
        return {
            "_id": str(index),
            "sort": [index],
            "_source": {
                "text": str(index),
                "metadata": {"document_id": file_id, "knowledge_id": 9, "chunk_index": index},
            },
        }

    client.search.side_effect = [
        {"hits": {"hits": [hit(1, 0), hit(2, 1)]}},
        {"hits": {"hits": [hit(1, 2)]}},
        {"hits": {"hits": []}},
    ]
    sources = [KnowledgeFulltextChunkSource(index_name="rag", file_id=i, knowledge_id=9) for i in (1, 2)]
    result = await KnowledgeFulltextChunkRepositoryImpl(client, page_size=2).list_many(sources)
    assert [chunk.chunk_index for chunk in result[1]] == [0, 2]
    assert [chunk.chunk_index for chunk in result[2]] == [1]
    client.open_point_in_time.assert_awaited_once()
    assert client.search.await_count == 3
    client.close_point_in_time.assert_awaited_once()


async def test_batch_claim_charges_crash_and_settlement_excludes_changed_revision():
    engine, session = await make_session()
    try:
        row = outbox(id=1, aggregate_id=1, status="pending", lease_owner=None, retry_count=7)
        session.add(row)
        await session.commit()
        repo = KnowledgeFulltextOutboxRepositoryImpl(session)
        now = datetime.now()
        claimed = await repo.claim_many({1: 2}, lease_owner="a", now=now)
        assert claimed[0].retry_count == 8
        await session.commit()
        assert await repo.claim_many({1: 2}, lease_owner="b", now=now + timedelta(hours=1)) == []
        row.desired_revision = 3
        await session.flush()
        assert await repo.lock_current_many(claimed, "a", now) == []
    finally:
        await session.close()
        await engine.dispose()
