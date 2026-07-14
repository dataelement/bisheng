from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.schemas.channel_manager_schema import (
    ChannelItemResponse,
    SetPinRequest,
    SortByEnum,
)
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
)


@pytest.mark.asyncio
async def test_channel_pin_still_updates_channel_membership():
    service = ChannelService.__new__(ChannelService)
    membership = SimpleNamespace(id=9, status=MembershipStatusEnum.ACTIVE)
    repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=membership),
        update_pin_status=AsyncMock(),
    )
    service.space_channel_member_repository = repository

    result = await service.set_channel_pin(
        SetPinRequest(channel_id="channel-1", is_pinned=True),
        SimpleNamespace(user_id=7),
    )

    assert result is True
    repository.find_membership.assert_awaited_once_with(
        business_id="channel-1",
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=7,
    )
    repository.update_pin_status.assert_awaited_once_with(member_id=9, is_pinned=True)


def test_channel_list_sorting_still_uses_membership_pin_state():
    now = datetime(2026, 7, 14, 12, 0, 0)
    plain = ChannelItemResponse(
        id="plain",
        name="A",
        source_list=[],
        visibility="public",
        user_role="member",
        is_pinned=False,
        subscribed_at=now,
    )
    pinned = ChannelItemResponse(
        id="pinned",
        name="Z",
        source_list=[],
        visibility="public",
        user_role="member",
        is_pinned=True,
        subscribed_at=now,
    )

    result = ChannelService._sort_channels([plain, pinned], SortByEnum.CHANNEL_NAME)

    assert [item.id for item in result] == ["pinned", "plain"]
    assert "is_pinned" in SpaceChannelMember.model_fields
