import asyncio
import time

import pytest
from langchain_core.embeddings import Embeddings

from bisheng.llm.domain.llm.embedding import BishengEmbedding


class _SyncOnlyEmbedding(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        time.sleep(0.05)
        return [[3.0, 4.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        time.sleep(0.05)
        return [3.0, 4.0]


class _NativeAsyncEmbedding(_SyncOnlyEmbedding):
    def embed_query(self, text: str) -> list[float]:
        raise AssertionError("存在原生异步 API 时不应调用同步方法")

    async def aembed_query(self, text: str) -> list[float]:
        await asyncio.sleep(0)
        return [0.0, 1.0]


def _wrapper(provider: Embeddings) -> BishengEmbedding:
    return BishengEmbedding.model_construct(embeddings=provider)


async def test_sync_only_embedding_fallback_does_not_block_event_loop() -> None:
    wrapper = _wrapper(_SyncOnlyEmbedding())
    heartbeat_ticks = 0

    async def heartbeat() -> None:
        nonlocal heartbeat_ticks
        while heartbeat_ticks < 3:
            await asyncio.sleep(0.01)
            heartbeat_ticks += 1

    vector, _ = await asyncio.gather(
        BishengEmbedding.aembed_query.__wrapped__(wrapper, "hello"),
        heartbeat(),
    )

    assert heartbeat_ticks == 3
    assert vector == pytest.approx([0.6, 0.8])


async def test_native_async_embedding_is_used_when_provider_supports_it() -> None:
    wrapper = _wrapper(_NativeAsyncEmbedding())

    vector = await BishengEmbedding.aembed_query.__wrapped__(wrapper, "hello")

    assert vector == [0.0, 1.0]
