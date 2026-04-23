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
async def test_check_access_async_uses_knowledge_library_rebac():
    service = KnowledgePermissionService()
    login_user = SimpleNamespace(user_id=7)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.PermissionService.check',
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check:
        allowed = await service.check_access_async(
            login_user=login_user,
            owner_user_id=99,
            knowledge_id=16,
            access_type=AccessType.KNOWLEDGE,
        )

    assert allowed is True
    mock_check.assert_awaited_once_with(
        user_id=7,
        relation='can_read',
        object_type='knowledge_library',
        object_id='16',
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


def test_check_access_sync_uses_knowledge_library_rebac():
    service = KnowledgePermissionService()
    login_user = SimpleNamespace(user_id=7)

    def _close_and_allow(coro):
        coro.close()
        return True

    with patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service._run_async_safe',
        side_effect=_close_and_allow,
    ) as mock_run_async:
        allowed = service.check_access_sync(
            login_user=login_user,
            owner_user_id=99,
            knowledge_id=23,
            access_type=AccessType.KNOWLEDGE,
        )

    assert allowed is True
    assert mock_run_async.call_args.args[0].cr_code.co_name == 'check'


def test_ensure_access_sync_raises_when_rebac_denies():
    service = KnowledgePermissionService()
    login_user = SimpleNamespace(user_id=7)

    class _Denied(Exception):
        pass

    def _close_and_deny(coro):
        coro.close()
        return False

    with patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service._run_async_safe',
        side_effect=_close_and_deny,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.UnAuthorizedError',
        _Denied,
    ):
        with pytest.raises(_Denied):
            service.ensure_access_sync(
                login_user=login_user,
                owner_user_id=99,
                knowledge_id=24,
                access_type=AccessType.KNOWLEDGE_WRITE,
            )


@pytest.mark.asyncio
async def test_filter_knowledge_ids_by_permission_async_honors_custom_model_permissions():
    service = KnowledgePermissionService()
    login_user = SimpleNamespace(
        user_id=7,
        get_user_group_ids=AsyncMock(return_value=[]),
    )
    fake_fga = SimpleNamespace(
        read_tuples=AsyncMock(return_value=[
            {'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_library:12'},
        ]),
    )

    with patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service._get_relation_models',
        new_callable=AsyncMock,
        return_value=[{
            'id': 'custom_view_only',
            'name': '只看不用',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['view_kb'],
            'permissions_explicit': True,
            'is_system': False,
        }],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service._get_bindings',
        new_callable=AsyncMock,
        return_value=[{
            'resource_type': 'knowledge_library',
            'resource_id': '12',
            'subject_type': 'user',
            'subject_id': 7,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_view_only',
        }],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.PermissionService._get_fga',
        return_value=fake_fga,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_permission_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[],
    ):
        assert await service.filter_knowledge_ids_by_permission_async(login_user, [12], 'use_kb') == []
        assert await service.filter_knowledge_ids_by_permission_async(login_user, [12], 'view_kb') == [12]
