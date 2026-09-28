"""分词隔离后仍保持缓存命中位置与回写内容。"""

import asyncio
import importlib
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.common.utils import tfidf_utils
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService


async def test_tokenization_yields_and_preserves_mixed_cache_positions(monkeypatch):
    redis_manager = importlib.import_module("bisheng.core.cache.redis_manager")
    redis = SimpleNamespace(aget=AsyncMock(side_effect=[["缓存"], None]), amset=AsyncMock())
    monkeypatch.setattr(redis_manager, "get_redis_client", AsyncMock(return_value=redis))
    started, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()

    def tokenize(text):
        assert threading.get_ident() != loop_thread
        started.set()
        assert release.wait(2)
        return [text]

    monkeypatch.setattr(tfidf_utils, "tokenize", tokenize)
    service = object.__new__(KnowledgeVersionService)
    items = [(SimpleNamespace(id=1, simhash="a"), "忽略"), (SimpleNamespace(id=2, simhash="b"), "未命中")]
    task = asyncio.create_task(service._tokenize_files_cached(items))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        assert not task.done()
    finally:
        release.set()
    assert await task == [["缓存"], ["未命中"]]
    redis.amset.assert_awaited_once_with(
        {f"{service._TFIDF_TOKEN_CACHE_PREFIX}2:b": ["未命中"]},
        expiration=service._TFIDF_TOKEN_CACHE_TTL,
    )
