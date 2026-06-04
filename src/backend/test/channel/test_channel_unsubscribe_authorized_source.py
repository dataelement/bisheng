from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelOrganizationGrantUnsubscribeDeniedError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    UserRoleEnum,
)


class _User:
    user_id = 7
    tenant_id = 1


def _member(
    *,
    member_id: int,
    subject_type: str | None,
    subject_id: int | None,
    binding_key: str | None,
    relation: ChannelRelationEnum = ChannelRelationEnum.VIEWER,
):
    return SimpleNamespace(
        id=member_id,
        business_id='channel-1',
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=7,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.ACTIVE,
        relation=relation,
        grant_subject_type=subject_type,
        grant_subject_id=subject_id,
        grant_relation=relation,
        grant_include_children=False,
        grant_model_id=relation.value,
        grant_binding_key=binding_key,
    )


class _Repo:
    def __init__(self, sources):
        self.sources = sources
        self.deleted_ids = []
        self.deleted_binding_keys = []

    async def find_membership(self, **kwargs):
        return self.sources[0] if self.sources else None

    async def find_channel_membership_sources(self, channel_id: str, user_id: int):
        return self.sources

    async def delete_channel_membership_source(self, channel_id: str, grant_binding_key: str):
        self.deleted_binding_keys.append(grant_binding_key)
        return 1

    async def delete(self, member_id: int):
        self.deleted_ids.append(member_id)


def _service(repo: _Repo) -> ChannelService:
    return ChannelService(
        channel_repository=SimpleNamespace(),
        space_channel_member_repository=repo,
        channel_info_source_repository=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_unsubscribe_direct_user_source_removes_source_and_revokes_fga():
    repo = _Repo([
        _member(member_id=1, subject_type='user', subject_id=7, binding_key='channel:channel-1:user:7:viewer:-')
    ])
    service = _service(repo)

    existing_bindings = [{
        'key': 'channel:channel-1:user:7:viewer:-',
        'resource_type': 'channel',
        'resource_id': 'channel-1',
        'subject_type': 'user',
        'subject_id': 7,
        'relation': 'viewer',
        'include_children': None,
        'model_id': 'viewer',
    }]
    save_mock = AsyncMock()

    with patch(
        'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
        new=AsyncMock(),
    ) as mock_authorize, patch(
        'bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
        new=AsyncMock(return_value=[]),
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._get_bindings',
        new=AsyncMock(return_value=existing_bindings),
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._save_bindings',
        new=save_mock,
    ):
        result = await service.unsubscribe_channel('channel-1', _User())

    assert result is True
    assert repo.deleted_binding_keys == ['channel:channel-1:user:7:viewer:-']
    # ReBAC relations for the user must be revoked so unsubscribe drops access.
    mock_authorize.assert_awaited_once()
    revokes = mock_authorize.await_args.kwargs['revokes']
    assert revokes and all(item.subject_id == 7 for item in revokes)
    # The direct user binding must be removed so the user no longer surfaces in
    # the channel authorization list after unsubscribe.
    save_mock.assert_awaited_once()
    saved_bindings = save_mock.await_args.args[0]
    assert all(
        not (b['subject_type'] == 'user' and b['subject_id'] == 7)
        for b in saved_bindings
    )


@pytest.mark.asyncio
async def test_unsubscribe_self_subscribe_source_revokes_fga_and_binding():
    # Self-subscribe (own application) rows carry no grant_subject_type; subscribe
    # still mirrors a ReBAC viewer grant + UI binding, so unsubscribe must revoke
    # both, otherwise the user keeps access and stays in the authorization list.
    repo = _Repo([
        _member(member_id=1, subject_type=None, subject_id=None, binding_key=None)
    ])
    service = _service(repo)

    save_mock = AsyncMock()

    with patch(
        'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
        new=AsyncMock(),
    ) as mock_authorize, patch(
        'bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
        new=AsyncMock(return_value=[]),
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._get_bindings',
        new=AsyncMock(return_value=[]),
    ), patch(
        'bisheng.permission.api.endpoints.resource_permission._save_bindings',
        new=save_mock,
    ):
        result = await service.unsubscribe_channel('channel-1', _User())

    assert result is True
    # No grant_binding_key -> the membership row itself is deleted.
    assert repo.deleted_ids == [1]
    mock_authorize.assert_awaited_once()
    revokes = mock_authorize.await_args.kwargs['revokes']
    assert revokes and all(item.subject_id == 7 for item in revokes)
    save_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_unsubscribe_department_source_is_blocked():
    repo = _Repo([
        _member(member_id=1, subject_type='department', subject_id=100, binding_key='dept-viewer')
    ])
    service = _service(repo)

    with pytest.raises(ChannelOrganizationGrantUnsubscribeDeniedError) as exc_info:
        await service.unsubscribe_channel('channel-1', _User())

    assert exc_info.value.kwargs['blocked_by'] == ['department']
    assert repo.deleted_binding_keys == []


@pytest.mark.asyncio
async def test_unsubscribe_user_group_source_is_blocked():
    repo = _Repo([
        _member(member_id=1, subject_type='user_group', subject_id=200, binding_key='group-viewer')
    ])
    service = _service(repo)

    with pytest.raises(ChannelOrganizationGrantUnsubscribeDeniedError) as exc_info:
        await service.unsubscribe_channel('channel-1', _User())

    assert exc_info.value.kwargs['blocked_by'] == ['user_group']
    assert repo.deleted_binding_keys == []


@pytest.mark.asyncio
async def test_unsubscribe_permission_model_department_without_membership_is_blocked():
    repo = _Repo([])
    service = _service(repo)

    with patch(
        'bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
        new=AsyncMock(return_value=[{
            'resource_type': 'channel',
            'resource_id': 'channel-1',
            'subject_type': 'department',
            'subject_id': 100,
            'relation': 'viewer',
            'include_children': False,
            'model_id': 'viewer',
        }]),
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_current_user_subject_strings',
        new=AsyncMock(return_value={'user:7', 'department:100#member'}),
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_binding_department_paths',
        new=AsyncMock(return_value={}),
    ):
        with pytest.raises(ChannelOrganizationGrantUnsubscribeDeniedError) as exc_info:
            await service.unsubscribe_channel('channel-1', _User())

    assert exc_info.value.kwargs['blocked_by'] == ['department']
    assert repo.deleted_binding_keys == []


@pytest.mark.asyncio
async def test_unsubscribe_permission_model_user_group_without_membership_is_blocked():
    repo = _Repo([])
    service = _service(repo)

    with patch(
        'bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
        new=AsyncMock(return_value=[{
            'resource_type': 'channel',
            'resource_id': 'channel-1',
            'subject_type': 'user_group',
            'subject_id': 200,
            'relation': 'editor',
            'include_children': None,
            'model_id': 'editor',
        }]),
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_current_user_subject_strings',
        new=AsyncMock(return_value={'user:7', 'user_group:200#member'}),
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_binding_department_paths',
        new=AsyncMock(return_value={}),
    ):
        with pytest.raises(ChannelOrganizationGrantUnsubscribeDeniedError) as exc_info:
            await service.unsubscribe_channel('channel-1', _User())

    assert exc_info.value.kwargs['blocked_by'] == ['user_group']
    assert repo.deleted_binding_keys == []


@pytest.mark.asyncio
async def test_unsubscribe_mixed_sources_is_blocked_when_organization_source_exists():
    repo = _Repo([
        _member(member_id=1, subject_type='user', subject_id=7, binding_key='user-viewer'),
        _member(member_id=2, subject_type='department', subject_id=100, binding_key='dept-viewer'),
    ])
    service = _service(repo)

    with pytest.raises(ChannelOrganizationGrantUnsubscribeDeniedError) as exc_info:
        await service.unsubscribe_channel('channel-1', _User())

    assert exc_info.value.kwargs['blocked_by'] == ['department']
    assert repo.deleted_binding_keys == []
