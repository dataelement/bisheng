from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.permission.domain.services.tool_permission_service import ToolPermissionService


@pytest.mark.asyncio
async def test_has_any_permission_async_honors_custom_tool_permissions():
    login_user = SimpleNamespace(
        user_id=7,
        get_user_group_ids=AsyncMock(return_value=[]),
    )
    fake_fga = SimpleNamespace(
        read_tuples=AsyncMock(return_value=[
            {'user': 'user:7', 'relation': 'viewer', 'object': 'tool:12'},
        ]),
    )

    with patch(
        'bisheng.permission.domain.services.tool_permission_service._get_relation_models',
        new_callable=AsyncMock,
        return_value=[{
            'id': 'custom_view_only',
            'name': '只看不用',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['view_tool'],
            'permissions_explicit': True,
            'is_system': False,
        }],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service._get_bindings',
        new_callable=AsyncMock,
        return_value=[{
            'resource_type': 'tool',
            'resource_id': '12',
            'subject_type': 'user',
            'subject_id': 7,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_view_only',
        }],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.PermissionService._get_fga',
        return_value=fake_fga,
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[],
    ):
        assert await ToolPermissionService.has_any_permission_async(login_user, '12', ['use_tool']) is False
        assert await ToolPermissionService.has_any_permission_async(login_user, '12', ['view_tool']) is True


def test_filter_tool_ids_by_permission_sync_uses_system_relation_defaults():
    login_user = SimpleNamespace(
        user_id=7,
        get_user_group_ids=AsyncMock(return_value=[]),
    )
    fake_fga = SimpleNamespace(
        read_tuples=AsyncMock(side_effect=lambda object: (
            [{'user': 'user:7', 'relation': 'viewer', 'object': 'tool:12'}]
            if object == 'tool:12'
            else [{'user': 'user:7', 'relation': 'editor', 'object': 'tool:13'}]
        )),
    )

    with patch(
        'bisheng.permission.domain.services.tool_permission_service._get_relation_models',
        new_callable=AsyncMock,
        return_value=[
            {
                'id': 'viewer',
                'name': '可查看',
                'relation': 'viewer',
                'grant_tier': 'usage',
                'permissions': [],
                'permissions_explicit': False,
                'is_system': True,
            },
            {
                'id': 'custom_edit',
                'name': '可编辑',
                'relation': 'editor',
                'grant_tier': 'usage',
                'permissions': ['view_tool', 'use_tool', 'edit_tool'],
                'permissions_explicit': True,
                'is_system': False,
            },
        ],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service._get_bindings',
        new_callable=AsyncMock,
        return_value=[
            {
                'resource_type': 'tool',
                'resource_id': '12',
                'subject_type': 'user',
                'subject_id': 7,
                'relation': 'viewer',
                'include_children': None,
                'model_id': 'viewer',
            },
            {
                'resource_type': 'tool',
                'resource_id': '13',
                'subject_type': 'user',
                'subject_id': 7,
                'relation': 'editor',
                'include_children': None,
                'model_id': 'custom_edit',
            },
        ],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.PermissionService._get_fga',
        return_value=fake_fga,
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[],
    ):
        filtered_use = ToolPermissionService.filter_tool_ids_by_permission_sync(
            login_user,
            ['12', '13'],
            'use_tool',
        )
        filtered_edit = ToolPermissionService.filter_tool_ids_by_permission_sync(
            login_user,
            ['12', '13'],
            'edit_tool',
        )

    assert filtered_use == ['12', '13']
    assert filtered_edit == ['13']


@pytest.mark.asyncio
async def test_has_any_permission_async_matches_user_group_admin_as_member():
    login_user = SimpleNamespace(
        user_id=7,
        get_user_group_ids=AsyncMock(return_value=[]),
    )
    fake_fga = SimpleNamespace(
        read_tuples=AsyncMock(return_value=[
            {'user': 'user_group:3#member', 'relation': 'viewer', 'object': 'tool:12'},
        ]),
    )

    with patch(
        'bisheng.permission.domain.services.tool_permission_service._get_relation_models',
        new_callable=AsyncMock,
        return_value=[{
            'id': 'custom_use',
            'name': '可用工具',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['use_tool'],
            'permissions_explicit': True,
            'is_system': False,
        }],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service._get_bindings',
        new_callable=AsyncMock,
        return_value=[{
            'resource_type': 'tool',
            'resource_id': '12',
            'subject_type': 'user_group',
            'subject_id': 3,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_use',
        }],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.PermissionService._get_fga',
        return_value=fake_fga,
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service.UserGroupDao.aget_user_admin_group',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(group_id=3)],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[],
    ):
        assert await ToolPermissionService.has_any_permission_async(login_user, '12', ['use_tool']) is True


@pytest.mark.asyncio
async def test_has_any_permission_async_unions_implicit_scope_permissions():
    login_user = SimpleNamespace(
        user_id=7,
        get_user_group_ids=AsyncMock(return_value=[]),
    )
    fake_fga = SimpleNamespace(
        read_tuples=AsyncMock(return_value=[
            {'user': 'user:7', 'relation': 'viewer', 'object': 'tool:12'},
        ]),
    )

    with patch(
        'bisheng.permission.domain.services.tool_permission_service._get_relation_models',
        new_callable=AsyncMock,
        return_value=[{
            'id': 'custom_view_only',
            'name': '只看不用',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['view_tool'],
            'permissions_explicit': True,
            'is_system': False,
        }],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service._get_bindings',
        new_callable=AsyncMock,
        return_value=[{
            'resource_type': 'tool',
            'resource_id': '12',
            'subject_type': 'user',
            'subject_id': 7,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_view_only',
        }],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.PermissionService._get_fga',
        return_value=fake_fga,
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.PermissionService.get_implicit_permission_level',
        new_callable=AsyncMock,
        return_value='can_manage',
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.permission.domain.services.tool_permission_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[],
    ):
        assert await ToolPermissionService.has_any_permission_async(
            login_user, '12', ['manage_tool_owner'],
        ) is True
