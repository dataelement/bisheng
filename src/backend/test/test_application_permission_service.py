from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.permission.domain.services.application_permission_service import ApplicationPermissionService


@pytest.mark.asyncio
async def test_get_app_permission_map_async_honors_custom_model_permissions():
    login_user = SimpleNamespace(
        user_id=7,
        get_user_group_ids=AsyncMock(return_value=[]),
    )
    rows = [{'id': 'wf-1', 'flow_type': 10}, {'id': 'asst-1', 'flow_type': 5}]
    fake_fga = SimpleNamespace(
        read_tuples=AsyncMock(side_effect=lambda object: (
            [{'user': 'user:7', 'relation': 'viewer', 'object': 'workflow:wf-1'}]
            if object == 'workflow:wf-1'
            else [{'user': 'user:7', 'relation': 'editor', 'object': 'assistant:asst-1'}]
        )),
    )

    with patch(
        'bisheng.permission.domain.services.application_permission_service._get_relation_models',
        new_callable=AsyncMock,
        return_value=[
            {
                'id': 'custom_view_only',
                'name': '只看不用',
                'relation': 'viewer',
                'grant_tier': 'usage',
                'permissions': ['view_app'],
                'permissions_explicit': True,
                'is_system': False,
            },
            {
                'id': 'custom_editor',
                'name': '可编辑',
                'relation': 'editor',
                'grant_tier': 'usage',
                'permissions': ['view_app', 'use_app', 'edit_app'],
                'permissions_explicit': True,
                'is_system': False,
            },
        ],
    ), patch(
        'bisheng.permission.domain.services.application_permission_service._get_bindings',
        new_callable=AsyncMock,
        return_value=[
            {
                'resource_type': 'workflow',
                'resource_id': 'wf-1',
                'subject_type': 'user',
                'subject_id': 7,
                'relation': 'viewer',
                'include_children': None,
                'model_id': 'custom_view_only',
            },
            {
                'resource_type': 'assistant',
                'resource_id': 'asst-1',
                'subject_type': 'user',
                'subject_id': 7,
                'relation': 'editor',
                'include_children': None,
                'model_id': 'custom_editor',
            },
        ],
    ), patch(
        'bisheng.permission.domain.services.application_permission_service.PermissionService._get_fga',
        return_value=fake_fga,
    ), patch(
        'bisheng.permission.domain.services.application_permission_service.UserDepartmentDao.aget_user_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.permission.domain.services.application_permission_service.DepartmentDao.aget_by_ids',
        new_callable=AsyncMock,
        return_value=[],
    ):
        permission_map = await ApplicationPermissionService.get_app_permission_map_async(
            login_user,
            rows,
            ['use_app', 'edit_app', 'view_app'],
        )

    assert permission_map == {
        'wf-1': {'view_app'},
        'asst-1': {'view_app', 'use_app', 'edit_app'},
    }
