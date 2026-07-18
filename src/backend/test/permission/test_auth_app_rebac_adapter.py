from unittest.mock import AsyncMock, call

import pytest

from bisheng.database.models.role_access import AccessType
from bisheng.user.domain.services import auth as auth_mod


@pytest.fixture
def login_user(monkeypatch):
    monkeypatch.setattr(auth_mod.UserRoleDao, 'get_user_roles', lambda user_id: [])
    return auth_mod.LoginUser(user_id=7, user_name='tester', user_role=[2])


@pytest.mark.asyncio
async def test_async_access_check_uses_assistant_can_read_target(login_user, monkeypatch):
    mock_check = AsyncMock(return_value=True)
    monkeypatch.setattr(auth_mod.LoginUser, 'rebac_check', mock_check)

    allowed = await login_user.async_access_check(
        owner_user_id=99,
        target_id='asst-15',
        access_type=AccessType.ASSISTANT_READ,
    )

    assert allowed is True
    mock_check.assert_awaited_once_with('can_read', 'assistant', 'asst-15')


@pytest.mark.asyncio
async def test_async_accessible_ids_use_assistant_rebac_target(login_user, monkeypatch):
    mock_list = AsyncMock(return_value=['asst-1', 'asst-2'])
    monkeypatch.setattr(auth_mod.LoginUser, 'rebac_list_accessible', mock_list)

    ids = await login_user.aget_user_access_resource_ids([AccessType.ASSISTANT_READ])

    assert set(ids) == {'asst-1', 'asst-2'}
    mock_list.assert_awaited_once_with('can_read', 'assistant')


@pytest.mark.asyncio
async def test_async_merged_app_resource_ids_union_workflow_and_assistant(login_user, monkeypatch):
    mock_list = AsyncMock(
        side_effect=lambda relation, object_type: (
            ['wf-1', 'shared-1']
            if object_type == 'workflow'
            else ['asst-1', 'shared-1']
        ),
    )
    monkeypatch.setattr(auth_mod.LoginUser, 'rebac_list_accessible', mock_list)

    ids = await login_user.aget_merged_rebac_app_resource_ids()

    assert set(ids) == {'wf-1', 'asst-1', 'shared-1'}
    assert mock_list.await_args_list == [
        call('can_read', 'workflow'),
        call('can_read', 'assistant'),
    ]


@pytest.mark.asyncio
async def test_async_access_check_uses_tool_can_edit_target(login_user, monkeypatch):
    mock_check = AsyncMock(return_value=True)
    monkeypatch.setattr(auth_mod.LoginUser, 'rebac_check', mock_check)

    allowed = await login_user.async_access_check(
        owner_user_id=99,
        target_id='tool-15',
        access_type=AccessType.GPTS_TOOL_WRITE,
    )

    assert allowed is True
    mock_check.assert_awaited_once_with('can_edit', 'tool', 'tool-15')


@pytest.mark.asyncio
async def test_async_accessible_ids_use_tool_rebac_target(login_user, monkeypatch):
    mock_list = AsyncMock(return_value=['11', '12'])
    monkeypatch.setattr(auth_mod.LoginUser, 'rebac_list_accessible', mock_list)

    ids = await login_user.aget_user_access_resource_ids([AccessType.GPTS_TOOL_READ])

    assert set(ids) == {'11', '12'}
    mock_list.assert_awaited_once_with('can_read', 'tool')
