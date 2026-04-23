from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService


@pytest.mark.asyncio
async def test_ensure_knowledge_access_uses_knowledge_library_read_rebac():
    login_user = SimpleNamespace(user_id=7)
    knowledge_model = SimpleNamespace(id=11, user_id=99)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_file_service.PermissionService.check',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check:
        await KnowledgeFileService._ensure_knowledge_access(
            login_user=login_user,
            knowledge_model=knowledge_model,
            access_type=AccessType.KNOWLEDGE,
        )

    mock_check.assert_awaited_once_with(
        user_id=7,
        relation='can_read',
        object_type='knowledge_library',
        object_id='11',
        login_user=login_user,
    )


@pytest.mark.asyncio
async def test_ensure_knowledge_access_uses_knowledge_library_write_rebac():
    login_user = SimpleNamespace(user_id=7)
    knowledge_model = SimpleNamespace(id=18, user_id=99)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_file_service.PermissionService.check',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check:
        await KnowledgeFileService._ensure_knowledge_access(
            login_user=login_user,
            knowledge_model=knowledge_model,
            access_type=AccessType.KNOWLEDGE_WRITE,
        )

    mock_check.assert_awaited_once_with(
        user_id=7,
        relation='can_edit',
        object_type='knowledge_library',
        object_id='18',
        login_user=login_user,
    )


@pytest.mark.asyncio
async def test_ensure_knowledge_access_raises_when_rebac_denies():
    login_user = SimpleNamespace(user_id=7)
    knowledge_model = SimpleNamespace(id=19, user_id=99)

    class _Denied(Exception):
        pass

    with patch(
        'bisheng.knowledge.domain.services.knowledge_file_service.PermissionService.check',
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
