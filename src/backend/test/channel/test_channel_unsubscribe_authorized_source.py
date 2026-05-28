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

    with patch(
        'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
        new=AsyncMock(),
    ) as mock_authorize:
        result = await service.unsubscribe_channel('channel-1', _User())

    assert result is True
    assert repo.deleted_binding_keys == ['channel:channel-1:user:7:viewer:-']
    mock_authorize.assert_awaited_once()
    assert mock_authorize.await_args.kwargs['revokes'][0].subject_id == 7


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
async def test_unsubscribe_mixed_sources_only_removes_direct_source():
    repo = _Repo([
        _member(member_id=1, subject_type='user', subject_id=7, binding_key='user-viewer'),
        _member(member_id=2, subject_type='department', subject_id=100, binding_key='dept-viewer'),
    ])
    service = _service(repo)

    with patch(
        'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
        new=AsyncMock(),
    ):
        result = await service.unsubscribe_channel('channel-1', _User())

    assert result is True
    assert repo.deleted_binding_keys == ['user-viewer']
