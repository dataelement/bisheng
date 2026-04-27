from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_subscribe_channel_uses_role_quota_service():
    from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
    from bisheng.channel.domain.schemas.channel_manager_schema import (
        SubscribeChannelRequest,
        SubscriptionStatusEnum,
    )
    from bisheng.channel.domain.services.channel_service import ChannelService
    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        UserRoleEnum,
    )
    from bisheng.role.domain.services.quota_service import QuotaResourceType

    channel = SimpleNamespace(id='channel-1', visibility=ChannelVisibilityEnum.PUBLIC)
    channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(return_value=[channel]),
    )
    member_repository = SimpleNamespace(
        find_membership=AsyncMock(return_value=None),
        add_member=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repository,
        channel_info_source_repository=SimpleNamespace(),
    )
    login_user = SimpleNamespace(user_id=42, tenant_id=7, is_admin=lambda: False)

    with patch(
        'bisheng.channel.domain.services.channel_service.QuotaService.check_quota',
        new=AsyncMock(return_value=True),
    ) as mock_check:
        status = await service.subscribe_channel(
            SubscribeChannelRequest(channel_id='channel-1'),
            login_user,
        )

    assert status == SubscriptionStatusEnum.SUBSCRIBED
    mock_check.assert_awaited_once_with(
        user_id=42,
        resource_type=QuotaResourceType.CHANNEL_SUBSCRIBE,
        tenant_id=7,
        login_user=login_user,
    )
    member_repository.add_member.assert_awaited_once_with(
        business_id='channel-1',
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=42,
        role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.ACTIVE,
    )
