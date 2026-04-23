from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService


@pytest.mark.asyncio
async def test_ensure_knowledge_access_uses_knowledge_permission_service_for_read():
    login_user = SimpleNamespace(user_id=7)
    knowledge_model = SimpleNamespace(id=11, user_id=99)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_file_service.KnowledgePermissionService.check_access_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check_access:
        await KnowledgeFileService._ensure_knowledge_access(
            login_user=login_user,
            knowledge_model=knowledge_model,
            access_type=AccessType.KNOWLEDGE,
        )

    mock_check_access.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=99,
        knowledge_id=11,
        access_type=AccessType.KNOWLEDGE,
    )


@pytest.mark.asyncio
async def test_ensure_knowledge_access_uses_knowledge_permission_service_for_write():
    login_user = SimpleNamespace(user_id=7)
    knowledge_model = SimpleNamespace(id=18, user_id=99)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_file_service.KnowledgePermissionService.check_access_async',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check_access:
        await KnowledgeFileService._ensure_knowledge_access(
            login_user=login_user,
            knowledge_model=knowledge_model,
            access_type=AccessType.KNOWLEDGE_WRITE,
        )

    mock_check_access.assert_awaited_once_with(
        login_user=login_user,
        owner_user_id=99,
        knowledge_id=18,
        access_type=AccessType.KNOWLEDGE_WRITE,
    )


@pytest.mark.asyncio
async def test_ensure_knowledge_access_raises_when_rebac_denies():
    login_user = SimpleNamespace(user_id=7)
    knowledge_model = SimpleNamespace(id=19, user_id=99)

    class _Denied(Exception):
        pass

    with patch(
        'bisheng.knowledge.domain.services.knowledge_file_service.KnowledgePermissionService.check_access_async',
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_file_service.UnAuthorizedError',
        _Denied,
    ):
        with pytest.raises(_Denied):
            await KnowledgeFileService._ensure_knowledge_access(
                login_user=login_user,
                knowledge_model=knowledge_model,
                access_type=AccessType.KNOWLEDGE,
            )
