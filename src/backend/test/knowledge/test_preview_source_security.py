from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from bisheng.api.v1.schemas import KnowledgeFileProcess
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


async def test_preview_rejects_unbound_path_even_on_cache_hit():
    request = KnowledgeFileProcess(knowledge_id=1, file_list=[{"file_path": "http://127.0.0.1/private"}])
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_service.KnowledgeDao.aquery_by_id",
            AsyncMock(return_value=SimpleNamespace(id=1, user_id=7)),
        ),
        patch.object(KnowledgeService.permission_service, "ensure_knowledge_write_async", AsyncMock()),
        patch.object(
            KnowledgeService,
            "async_get_preview_cache",
            AsyncMock(return_value={"0": {"text": "secret", "metadata": {}}}),
            create=True,
        ),
        patch.object(KnowledgeService, "legacy_preview_cache_key", return_value="legacy", create=True),
        patch("bisheng.knowledge.domain.services.knowledge_service.get_redis_client", AsyncMock()),
    ):
        with pytest.raises(HTTPException):
            await KnowledgeService.get_preview_file_chunk(None, SimpleNamespace(user_id=7), request)
