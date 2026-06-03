from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelPermissionDeniedError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    UserRoleEnum,
)
from bisheng.permission.domain.schemas.permission_schema import ResourcePermissionItem


class _User:
    user_id = 693
    user_name = "yangxin"
    tenant_id = 1

    def is_admin(self):
        return False


class _MemberRepo:
    def __init__(self, members):
        self.members = members
        self.deleted_ids = []

    async def find_membership(self, **kwargs):
        return self.members[0]

    async def find_all(self, **kwargs):
        return self.members

    async def delete(self, member_id: int):
        self.deleted_ids.append(member_id)


def _member(member_id: int, user_id: int, role: UserRoleEnum):
    return SimpleNamespace(
        id=member_id,
        business_id="channel-1",
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=user_id,
        status=MembershipStatusEnum.ACTIVE,
        user_role=role,
    )


@pytest.mark.asyncio
async def test_dismiss_channel_notifies_authorized_users_not_only_member_rows():
    channel = SimpleNamespace(
        id="channel-1",
        name="test-channel",
        source_list=[],
    )
    member_repo = _MemberRepo([
        _member(1, 693, UserRoleEnum.CREATOR),
    ])
    message_service = SimpleNamespace(send_generic_notify=AsyncMock())
    service = ChannelService(
        channel_repository=SimpleNamespace(
            find_channels_by_ids=AsyncMock(return_value=[channel]),
            delete=AsyncMock(),
        ),
        space_channel_member_repository=member_repo,
        channel_info_source_repository=SimpleNamespace(),
        message_service=message_service,
    )

    with patch(
        "bisheng.channel.domain.services.channel_service.PermissionService.get_resource_permissions",
        new=AsyncMock(return_value=[
            ResourcePermissionItem(subject_type="user", subject_id=740, relation="viewer"),
        ]),
    ), patch(
        "bisheng.channel.domain.services.channel_service.PermissionService._affected_user_ids_for_subject",
        new=AsyncMock(return_value={740}),
    ), patch(
        "bisheng.channel.domain.services.channel_service.OwnerService.delete_resource_tuples",
        new=AsyncMock(),
    ):
        await service.dismiss_channel("channel-1", _User())

    message_service.send_generic_notify.assert_awaited_once()
    notify_kwargs = message_service.send_generic_notify.await_args.kwargs
    assert notify_kwargs["action_code"] == "channel_dismissed"
    assert notify_kwargs["receiver_user_ids"] == [693, 740]
    assert member_repo.deleted_ids == [1]


def _authorized_member(member_id: int, user_id: int, role: UserRoleEnum):
    member = _member(member_id, user_id, role)
    member.grant_subject_type = "user"
    member.relation = ChannelRelationEnum.MANAGER
    return member


@pytest.mark.asyncio
async def test_dismiss_allowed_for_non_creator_with_delete_channel_permission():
    channel = SimpleNamespace(id="channel-1", name="test-channel", source_list=[])
    member_repo = _MemberRepo([
        _authorized_member(1, 693, UserRoleEnum.ADMIN),
    ])
    channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(return_value=[channel]),
        delete=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repo,
        channel_info_source_repository=SimpleNamespace(),
    )

    with patch(
        "bisheng.channel.domain.services.channel_service.FineGrainedPermissionService"
        ".get_effective_permission_ids_async",
        new=AsyncMock(return_value={"view_channel", "edit_channel", "delete_channel"}),
    ), patch(
        "bisheng.channel.domain.services.channel_service.OwnerService.delete_resource_tuples",
        new=AsyncMock(),
    ) as mock_delete_tuples:
        await service.dismiss_channel("channel-1", _User())

    channel_repository.delete.assert_awaited_once_with("channel-1")
    mock_delete_tuples.assert_awaited_once()
    assert member_repo.deleted_ids == [1]


@pytest.mark.asyncio
async def test_dismiss_denied_for_non_creator_without_delete_channel_permission():
    channel = SimpleNamespace(id="channel-1", name="test-channel", source_list=[])
    member_repo = _MemberRepo([
        _authorized_member(1, 693, UserRoleEnum.ADMIN),
    ])
    channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(return_value=[channel]),
        delete=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repo,
        channel_info_source_repository=SimpleNamespace(),
    )

    with patch(
        "bisheng.channel.domain.services.channel_service.FineGrainedPermissionService"
        ".get_effective_permission_ids_async",
        new=AsyncMock(return_value={"view_channel", "edit_channel"}),
    ), patch(
        "bisheng.channel.domain.services.channel_service.OwnerService.delete_resource_tuples",
        new=AsyncMock(),
    ) as mock_delete_tuples:
        with pytest.raises(ChannelPermissionDeniedError):
            await service.dismiss_channel("channel-1", _User())

    channel_repository.delete.assert_not_awaited()
    mock_delete_tuples.assert_not_awaited()
    assert member_repo.deleted_ids == []
