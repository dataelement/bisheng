from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceAuthorizeScopeDeniedError
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.permission.api.endpoints import resource_permission
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRequest


def _login_user(user_id: int = 7, is_admin: bool = False):
    return SimpleNamespace(user_id=user_id, is_admin=lambda: is_admin)


@pytest.mark.asyncio
async def test_team_space_allows_department_grant_from_full_tenant_tree():
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(
                subject_type='department',
                subject_id=99,
                relation='viewer',
            )
        ]
    )

    with patch(
        'bisheng.permission.api.endpoints.resource_permission._get_knowledge_space_level',
        new_callable=AsyncMock,
        return_value=KnowledgeSpaceLevelEnum.TEAM,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._can_view_all_grant_subject_departments',
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._resolve_grant_subject_tenant_id',
        new_callable=AsyncMock,
        return_value=1,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._list_knowledge_space_grant_departments',
        new_callable=AsyncMock,
        return_value=[{'id': 10, 'children': []}, {'id': 99, 'children': []}],
    ):
        result = await resource_permission._validate_knowledge_space_authorize_scope(
            resource_type='knowledge_space',
            resource_id='100',
            request=request,
            login_user=_login_user(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_team_space_rejects_department_grant_outside_tenant_tree():
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(
                subject_type='department',
                subject_id=88,
                relation='viewer',
            )
        ]
    )

    with patch(
        'bisheng.permission.api.endpoints.resource_permission._get_knowledge_space_level',
        new_callable=AsyncMock,
        return_value=KnowledgeSpaceLevelEnum.TEAM,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._can_view_all_grant_subject_departments',
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._resolve_grant_subject_tenant_id',
        new_callable=AsyncMock,
        return_value=1,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._list_knowledge_space_grant_departments',
        new_callable=AsyncMock,
        return_value=[{'id': 10, 'children': []}, {'id': 99, 'children': []}],
    ):
        result = await resource_permission._validate_knowledge_space_authorize_scope(
            resource_type='knowledge_space',
            resource_id='100',
            request=request,
            login_user=_login_user(),
        )

    assert result is SpaceAuthorizeScopeDeniedError


@pytest.mark.asyncio
async def test_team_space_department_candidates_return_full_tenant_tree_for_non_admin():
    full_tree = [
        {'id': 10, 'name': '当前部门', 'children': []},
        {'id': 99, 'name': '其它部门', 'children': []},
    ]

    with patch(
        'bisheng.permission.api.endpoints.resource_permission._has_resource_permission_management_access',
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._resolve_grant_subject_tenant_id',
        new_callable=AsyncMock,
        return_value=1,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._get_knowledge_space_level',
        new_callable=AsyncMock,
        return_value=KnowledgeSpaceLevelEnum.TEAM,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._list_knowledge_space_grant_departments',
        new_callable=AsyncMock,
        return_value=full_tree,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._can_view_all_grant_subject_departments',
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._knowledge_space_grant_department_ids',
        new_callable=AsyncMock,
        return_value={10},
    ):
        result = await resource_permission.get_knowledge_space_grant_subject_departments(
            space_id='100',
            login_user=_login_user(),
        )

    assert result.status_code == 200
    assert result.data == full_tree


@pytest.mark.asyncio
async def test_team_space_child_resource_department_candidates_return_full_tenant_tree_for_non_admin():
    full_tree = [
        {'id': 10, 'name': '当前部门', 'children': []},
        {'id': 99, 'name': '其它部门', 'children': []},
    ]

    with patch(
        'bisheng.permission.api.endpoints.resource_permission._has_resource_permission_management_access',
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._resolve_grant_subject_tenant_id',
        new_callable=AsyncMock,
        return_value=1,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._resolve_child_resource_space_id_for_grant_scope',
        new_callable=AsyncMock,
        return_value='100',
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._get_knowledge_space_level',
        new_callable=AsyncMock,
        return_value=KnowledgeSpaceLevelEnum.TEAM,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._list_knowledge_space_grant_departments',
        new_callable=AsyncMock,
        return_value=full_tree,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._can_view_all_grant_subject_departments',
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._knowledge_space_grant_department_ids',
        new_callable=AsyncMock,
        return_value={10},
    ):
        result = await resource_permission.get_grant_subject_departments(
            resource_type='knowledge_file',
            resource_id='200',
            login_user=_login_user(),
        )

    assert result.status_code == 200
    assert result.data == full_tree
