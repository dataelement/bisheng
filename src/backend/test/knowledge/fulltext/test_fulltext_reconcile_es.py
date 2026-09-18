from unittest.mock import AsyncMock

from bisheng.knowledge.domain.contracts.fulltext_reconcile import Mutation, Observation
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_es_repository_impl import (
    KnowledgeFulltextReconcileESRepository,
)


async def test_mget_distinguishes_missing_error_and_valid_record():
    client = AsyncMock()
    client.mget.return_value = {
        "docs": [
            {"_id": "1", "found": True, "_source": {"file_id": 1}, "_seq_no": 2, "_primary_term": 1},
            {"_id": "2", "found": False},
            {"_id": "3", "error": {"type": "unavailable_shards_exception"}},
        ]
    }
    result = await KnowledgeFulltextReconcileESRepository(client).read([1, 2, 3, 4])
    assert result[1].source == {"file_id": 1}
    assert result[2].source is None
    assert isinstance(result[3], Exception)
    assert isinstance(result[4], Exception)
    assert client.mget.await_count == 1


async def test_bulk_partial_failure_and_conditional_delete():
    client = AsyncMock()
    client.bulk.return_value = {
        "items": [
            {"create": {"_id": "1", "status": 201}},
            {"delete": {"_id": "2", "status": 409}},
        ]
    }
    repo = KnowledgeFulltextReconcileESRepository(client)
    result = await repo.write(
        [
            Mutation(1, {"file_id": 1, "content": "正文"}, Observation(None)),
            Mutation(2, None, Observation({"file_id": 2}, 7, 2)),
        ]
    )
    assert result[1] is None
    assert isinstance(result[2], Exception)
    operations = client.bulk.call_args.kwargs["operations"]
    assert operations[-1]["delete"]["if_seq_no"] == 7
    assert operations[-1]["delete"]["if_primary_term"] == 2
    assert client.bulk.await_count == 1


async def test_bulk_update_preserves_engagement_and_respects_byte_budget():
    client = AsyncMock()

    async def bulk(**kwargs):
        ops = kwargs["operations"]
        return {"items": [{"update": {"_id": next(iter(ops[0].values()))["_id"], "status": 200}}]}

    client.bulk.side_effect = bulk
    repo = KnowledgeFulltextReconcileESRepository(client, max_bytes=400)
    mutations = [
        Mutation(i, {"file_id": i, "content": "x" * 110, "preview_count": 5}, Observation({"file_id": i}, 1, 1))
        for i in (1, 2)
    ]
    result = await repo.write(mutations)
    assert all(error is None for error in result.values())
    assert client.bulk.await_count == 2
    for call in client.bulk.call_args_list:
        assert "preview_count" not in call.kwargs["operations"][1]["doc"]


async def test_chunk_partial_shard_failure_is_not_missing_content():
    from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunkSource

    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit"}
    client.search.return_value = {"_shards": {"failed": 1}, "hits": {"hits": []}}
    repo = KnowledgeFulltextReconcileESRepository(client)
    result = await repo.chunks([KnowledgeFulltextChunkSource(index_name="rag", file_id=1, knowledge_id=2)])
    assert isinstance(result[1], Exception)
    assert type(result[1]).__name__ == "ReconcileReadError"
    client.close_point_in_time.assert_awaited_once()


async def test_chunk_pages_are_batched_and_missing_file_does_not_truncate_other_file():
    from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunkSource

    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit"}
    client.search.side_effect = [
        {
            "pit_id": "new-pit",
            "hits": {
                "hits": [
                    {
                        "_id": "c1",
                        "sort": [1],
                        "_source": {
                            "text": "正文",
                            "metadata": {"document_id": 1, "knowledge_id": 9, "chunk_index": 0},
                        },
                    }
                ]
            },
        },
        {"hits": {"hits": []}},
    ]
    repo = KnowledgeFulltextReconcileESRepository(client, chunk_page_size=1)
    result = await repo.chunks(
        [KnowledgeFulltextChunkSource(index_name="rag", file_id=i, knowledge_id=9) for i in (1, 2)]
    )
    assert result[1][0].text == "正文"
    assert result[2] == []
    assert client.open_point_in_time.await_count == 1
    assert client.search.await_count == 2
    assert client.search.call_args.kwargs["search_after"] == [1]
    client.close_point_in_time.assert_awaited_once_with(id="new-pit")


async def test_faulty_index_is_not_requeried_for_each_file_and_other_index_continues():
    from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunkSource

    repo = KnowledgeFulltextReconcileESRepository(AsyncMock())

    async def read(index, group):
        if index == "bad":
            raise ConnectionError("unavailable")
        return {s.file_id: [] for s in group}

    repo._chunks_group = AsyncMock(side_effect=read)
    for file_id in (1, 2):
        await repo.chunks([KnowledgeFulltextChunkSource(index_name="bad", file_id=file_id, knowledge_id=9)])
    result = await repo.chunks([KnowledgeFulltextChunkSource(index_name="good", file_id=3, knowledge_id=9)])
    assert result == {3: []}
    assert repo._chunks_group.await_count == 2


async def test_malformed_source_is_split_without_losing_good_files():
    from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunkSource

    repo = KnowledgeFulltextReconcileESRepository(AsyncMock())

    async def read(index, group):
        if any(s.file_id == 1 for s in group):
            raise ValueError("bad chunk")
        return {s.file_id: [] for s in group}

    repo._chunks_group = AsyncMock(side_effect=read)
    result = await repo.chunks(
        [KnowledgeFulltextChunkSource(index_name="rag", file_id=i, knowledge_id=9) for i in (1, 2)]
    )
    assert isinstance(result[1], Exception)
    assert result[2] == []
    assert repo._chunks_group.await_count == 3


async def test_reverse_scan_reports_bad_identity_without_blocking_later_files():
    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit"}
    client.search.side_effect = [
        {"hits": {"total": {"value": 2}}},
        {
            "hits": {
                "hits": [
                    {"_id": "bad-id", "_source": {"file_id": 1}},
                    {"_id": "2", "_source": {"file_id": 2}},
                ]
            }
        },
    ]
    repo = KnowledgeFulltextReconcileESRepository(client)
    assert await repo.reverse_page(0, 200) == [1, 2]
    assert repo.identity_errors == {1: "invalid_es_identity"}
    assert repo.unkeyed_count == 2
