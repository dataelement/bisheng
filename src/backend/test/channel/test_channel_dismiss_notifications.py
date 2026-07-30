from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelPermissionDeniedError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    UserRoleEnum,
)


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


def _permission_adapter():
    record = SimpleNamespace(tenant_id=1)
    return (
        SimpleNamespace(
            load_permission_record=AsyncMock(return_value=record),
            project_delete=AsyncMock(),
        ),
        record,
    )


@pytest.mark.asyncio
async def test_dismiss_channel_notifies_active_members():
    channel = SimpleNamespace(
        id="channel-1",
        name="test-channel",
        source_list=[],
    )
    member_repo = _MemberRepo(
        [
            _member(1, 693, UserRoleEnum.CREATOR),
        ]
    )
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
    adapter, _ = _permission_adapter()

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.get_f048_resource_adapter",
            return_value=adapter,
        ),
    ):
        await service.dismiss_channel("channel-1", _User())

    message_service.send_generic_notify.assert_awaited_once()
    notify_kwargs = message_service.send_generic_notify.await_args.kwargs
    assert notify_kwargs["action_code"] == "channel_dismissed"
    assert notify_kwargs["receiver_user_ids"] == [693]
    assert member_repo.deleted_ids == [1]


@pytest.mark.asyncio
async def test_dismiss_allowed_for_non_creator_with_delete_channel_permission():
    channel = SimpleNamespace(id="channel-1", name="test-channel", source_list=[])
    member_repo = _MemberRepo(
        [
            _member(1, 693, UserRoleEnum.ADMIN),
        ]
    )
    channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(return_value=[channel]),
        delete=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repo,
        channel_info_source_repository=SimpleNamespace(),
    )
    adapter, record = _permission_adapter()
    require_action = AsyncMock()

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            new=require_action,
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.get_f048_resource_adapter",
            return_value=adapter,
        ),
    ):
        await service.dismiss_channel("channel-1", _User())

    require_action.assert_awaited_once()
    channel_repository.delete.assert_awaited_once_with("channel-1")
    adapter.project_delete.assert_awaited_once()
    assert adapter.project_delete.await_args.kwargs["record"] is record
    assert member_repo.deleted_ids == [1]


class _SuperAdmin(_User):
    def is_admin(self):
        return True


@pytest.mark.asyncio
async def test_dismiss_allowed_for_super_admin_without_delete_channel_permission():
    """A super admin may dismiss any channel even when they are neither the creator
    nor hold the fine-grained ``delete_channel`` permission."""
    channel = SimpleNamespace(id="channel-1", name="test-channel", source_list=[])
    member_repo = _MemberRepo(
        [
            _member(1, 693, UserRoleEnum.ADMIN),
        ]
    )
    channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(return_value=[channel]),
        delete=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repo,
        channel_info_source_repository=SimpleNamespace(),
    )
    adapter, _ = _permission_adapter()
    require_action = AsyncMock()

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            new=require_action,
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.get_f048_resource_adapter",
            return_value=adapter,
        ),
    ):
        await service.dismiss_channel("channel-1", _SuperAdmin())

    require_action.assert_awaited_once()
    channel_repository.delete.assert_awaited_once_with("channel-1")
    adapter.project_delete.assert_awaited_once()
    assert member_repo.deleted_ids == [1]


@pytest.mark.asyncio
async def test_dismiss_denied_for_non_creator_without_delete_channel_permission():
    channel = SimpleNamespace(id="channel-1", name="test-channel", source_list=[])
    member_repo = _MemberRepo(
        [
            _member(1, 693, UserRoleEnum.ADMIN),
        ]
    )
    channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(return_value=[channel]),
        delete=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repo,
        channel_info_source_repository=SimpleNamespace(),
    )
    adapter, _ = _permission_adapter()

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.require_business_action",
            new=AsyncMock(side_effect=ChannelPermissionDeniedError()),
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.get_f048_resource_adapter",
            return_value=adapter,
        ),
    ):
        with pytest.raises(ChannelPermissionDeniedError):
            await service.dismiss_channel("channel-1", _User())

    channel_repository.delete.assert_not_awaited()
    adapter.load_permission_record.assert_not_awaited()
    adapter.project_delete.assert_not_awaited()
    assert member_repo.deleted_ids == []
