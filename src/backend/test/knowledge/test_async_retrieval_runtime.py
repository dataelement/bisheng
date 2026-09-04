import asyncio

from bisheng.core.config.settings import KnowledgeRetrievalRuntimeConf
from bisheng.knowledge.rag.async_retrieval_runtime import AsyncRetrievalRuntime


class _SlowAsyncMilvusClient:
    def __init__(self) -> None:
        self.loaded: list[str] = []

    async def load_collection(self, collection_name: str, **kwargs) -> None:
        self.loaded.append(collection_name)
        await asyncio.sleep(0.01)

    async def search(self, collection_name: str, **kwargs):
        await asyncio.sleep(0.05)
        return [[{"distance": 0.1, "entity": {"text": "hit", "document_id": 7}}]]

    async def close(self) -> None:
        return None


def test_connection_args_use_async_specific_alias_and_uri() -> None:
    runtime = AsyncRetrievalRuntime(
        config=KnowledgeRetrievalRuntimeConf(),
        connection_args={"host": "milvus", "port": "19530", "alias": "primary"},
        milvus_client=_SlowAsyncMilvusClient(),
    )

    assert runtime.connection_args == {
        "uri": "http://milvus:19530",
        "alias": "primary-async-retrieval",
    }


async def test_slow_milvus_search_does_not_block_event_loop() -> None:
    runtime = AsyncRetrievalRuntime(
        config=KnowledgeRetrievalRuntimeConf(),
        connection_args={},
        milvus_client=_SlowAsyncMilvusClient(),
    )
    heartbeat_ticks = 0

    async def heartbeat() -> None:
        nonlocal heartbeat_ticks
        while heartbeat_ticks < 3:
            await asyncio.sleep(0.01)
            heartbeat_ticks += 1

    rows, _ = await asyncio.gather(
        runtime.search_milvus(
            collection_name="col_test",
            vector=[0.1, 0.2],
            limit=5,
        ),
        heartbeat(),
    )

    assert heartbeat_ticks == 3
    assert rows[0][0]["entity"]["document_id"] == 7
    assert runtime.milvus_client.loaded == ["col_test"]


async def test_collection_is_loaded_only_once_per_worker() -> None:
    client = _SlowAsyncMilvusClient()
    runtime = AsyncRetrievalRuntime(
        config=KnowledgeRetrievalRuntimeConf(),
        connection_args={},
        milvus_client=client,
    )

    await asyncio.gather(
        runtime.search_milvus(collection_name="col_test", vector=[0.1], limit=1),
        runtime.search_milvus(collection_name="col_test", vector=[0.1], limit=1),
    )

    assert client.loaded == ["col_test"]
