from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService


@pytest.mark.asyncio
async def test_ensure_knowledge_read_async_uses_knowledge_library_rebac():
    service = KnowledgePermissionService()
    login_user = SimpleNamespace(user_id=7)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.PermissionService.check',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check:
        await service.ensure_knowledge_read_async(
            login_user=login_user,
            owner_user_id=99,
            knowledge_id=12,
        )

    mock_check.assert_awaited_once_with(
        user_id=7,
        relation='can_read',
        object_type='knowledge_library',
        object_id='12',
        login_user=login_user,
    )


@pytest.mark.asyncio
async def test_ensure_knowledge_write_async_uses_knowledge_library_rebac():
    service = KnowledgePermissionService()
    login_user = SimpleNamespace(user_id=7)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.PermissionService.check',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check:
        await service.ensure_knowledge_write_async(
            login_user=login_user,
            owner_user_id=99,
            knowledge_id=18,
        )

    mock_check.assert_awaited_once_with(
        user_id=7,
        relation='can_edit',
        object_type='knowledge_library',
        object_id='18',
        login_user=login_user,
    )


@pytest.mark.asyncio
async def test_ensure_access_async_raises_when_rebac_denies():
    service = KnowledgePermissionService()
    login_user = SimpleNamespace(user_id=7)

    class _Denied(Exception):
        pass

    with patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.PermissionService.check',
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.UnAuthorizedError',
        _Denied,
    ):
        with pytest.raises(_Denied):
            await service.ensure_access_async(
                login_user=login_user,
                owner_user_id=99,
                knowledge_id=20,
                access_type=AccessType.KNOWLEDGE,
            )
