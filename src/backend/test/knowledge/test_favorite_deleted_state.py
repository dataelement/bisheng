from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


async def test_favorite_list_marks_soft_deleted_source_with_reason():
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=11, tenant_id=1)
    service._find_favorite_space = AsyncMock(
        return_value=SimpleNamespace(id=101)
    )
    service._resolve_favorite_durable_target = AsyncMock(return_value=(20, None))
    reference = SimpleNamespace(
        id=301,
        file_name="制度.pdf",
        update_time=datetime(2026, 7, 30, 10, 0, 0),
        user_metadata={
            "favorite_reference": {
                "source_space_id": 10,
                "source_file_id": 20,
            }
        },
    )
    deleted_source = SimpleNamespace(
        id=20,
        knowledge_id=10,
        file_name="制度.pdf",
        deleted_at=datetime(2026, 7, 30, 11, 0, 0),
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeFileDao.aget_references_by_knowledge_id",
            new=AsyncMock(return_value=([reference], 1)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeFileDao.query_by_id",
            new=AsyncMock(return_value=deleted_source),
        ),
    ):
        response = await service.list_shougang_portal_favorites()

    assert response.data[0].status == "invalid"
    assert response.data[0].invalid_reason == "source_deleted"
    assert response.data[0].source_file_id == 20
