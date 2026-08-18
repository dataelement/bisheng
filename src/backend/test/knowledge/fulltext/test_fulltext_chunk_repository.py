from unittest.mock import AsyncMock

from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_chunk_repository_impl import (
    KnowledgeFulltextChunkRepositoryImpl,
)


async def test_chunk_repository_reads_all_pages_with_stable_search_after():
    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit-1"}
    client.search.side_effect = [
        {
            "pit_id": "pit-2",
            "hits": {
                "hits": [
                    {
                        "_id": "a",
                        "sort": [0, "a"],
                        "_source": {
                            "text": "first",
                            "metadata": {"document_id": 7, "knowledge_id": 9, "chunk_index": 0},
                        },
                    }
                ]
            }
        },
        {
            "pit_id": "pit-3",
            "hits": {
                "hits": [
                    {
                        "_id": "b",
                        "sort": [1, "b"],
                        "_source": {
                            "text": "second",
                            "metadata": {"document_id": 7, "knowledge_id": 9, "chunk_index": 1},
                        },
                    }
                ]
            }
        },
        {"pit_id": "pit-4", "hits": {"hits": []}},
    ]
    repository = KnowledgeFulltextChunkRepositoryImpl(client, page_size=1)

    chunks = await repository.list_all(
        index_name="knowledge_9",
        file_id=7,
        knowledge_id=9,
    )

    assert [item.chunk_index for item in chunks] == [0, 1]
    assert client.search.await_count == 3
    client.open_point_in_time.assert_awaited_once_with(index="knowledge_9", keep_alive="1m")
    assert "search_after" not in client.search.await_args_list[0].kwargs
    assert client.search.await_args_list[1].kwargs["search_after"] == [0, "a"]
    assert "index" not in client.search.await_args_list[0].kwargs
    assert client.search.await_args_list[0].kwargs["pit"] == {"id": "pit-1", "keep_alive": "1m"}
    assert client.search.await_args_list[1].kwargs["pit"] == {"id": "pit-2", "keep_alive": "1m"}
    assert client.search.await_args_list[0].kwargs["sort"] == [
        {"metadata.chunk_index": "asc"},
        {"_shard_doc": "asc"},
    ]
    client.close_point_in_time.assert_awaited_once_with(id="pit-4")


async def test_chunk_repository_closes_pit_when_search_fails():
    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit-error"}
    client.search.side_effect = RuntimeError("search failed")
    repository = KnowledgeFulltextChunkRepositoryImpl(client)

    try:
        await repository.list_all(index_name="knowledge_9", file_id=7, knowledge_id=9)
    except RuntimeError as exc:
        assert str(exc) == "search failed"
    else:
        raise AssertionError("search failure must propagate")

    client.close_point_in_time.assert_awaited_once_with(id="pit-error")
