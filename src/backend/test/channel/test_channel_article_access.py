from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.services.channel_service import ChannelService


async def test_article_search_uses_f048_visible_action_without_legacy_permission_lookup():
    channel_repository = SimpleNamespace(
        find_channels_by_ids=AsyncMock(
            return_value=[
                # Not public: a public channel skips the `visible` gate on purpose,
                # which is what this test is asserting still happens otherwise.
                SimpleNamespace(
                    id="channel-1",
                    source_list=[],
                    visibility=ChannelVisibilityEnum.PRIVATE,
                )
            ]
        )
    )
    member_repository = SimpleNamespace(find_membership=AsyncMock(return_value=None))
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=member_repository,
        channel_info_source_repository=SimpleNamespace(),
    )
    login_user = SimpleNamespace(user_id=7, tenant_id=1)

    with patch(
        "bisheng.channel.domain.services.channel_service.require_business_action",
        new=AsyncMock(),
    ) as require_action:
        result = await service.search_channel_articles(
            channel_id="channel-1",
            login_user=login_user,
        )

    require_action.assert_awaited_once_with(
        login_user,
        resource_type="channel",
        resource_id="channel-1",
        action="visible",
    )
    member_repository.find_membership.assert_not_awaited()
    assert result.data == []
    assert result.total == 0
