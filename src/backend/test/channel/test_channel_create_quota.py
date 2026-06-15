"""Unit tests for the role-configurable channel-creation quota.

After F005 consolidation, channel creation no longer uses a hardcoded
``MAX_USER_CHANNEL_COUNT = 10``; ``ChannelService.create_channel`` reads
``QuotaService.get_effective_quota(CHANNEL)`` (default 10, admins/-1 = unlimited,
tenant-chain cap folded in) and raises ``ChannelCreateLimitExceededError(quota=...)``
carrying the real configured limit.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelCreateLimitExceededError

_QUOTA_PATCH = "bisheng.channel.domain.services.channel_service.QuotaService.get_effective_quota"


class _LoginUser:
    user_id = 7
    user_name = "operator"
    tenant_id = 1

    def is_admin(self):
        return False


def _service(member_repository, channel_repository=None):
    return ChannelService(
        channel_repository=channel_repository or SimpleNamespace(),
        space_channel_member_repository=member_repository,
        channel_info_source_repository=SimpleNamespace(find_by_ids=AsyncMock(return_value=[])),
        article_es_service=SimpleNamespace(count_articles=AsyncMock(return_value=0)),
    )


def _create_request():
    return CreateChannelRequest(
        name="资讯频道",
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        is_released=True,
    )


@pytest.mark.asyncio
async def test_create_channel_blocks_at_configured_quota_with_real_number():
    """At/over the role quota → ChannelCreateLimitExceededError carrying the real limit."""
    member_repository = SimpleNamespace(
        # 2 channels already created, quota is 2 → blocked
        find_channel_memberships=AsyncMock(return_value=[object(), object()]),
        add_member=AsyncMock(),
    )
    service = _service(member_repository)

    with patch(_QUOTA_PATCH, new=AsyncMock(return_value=2)):
        with pytest.raises(ChannelCreateLimitExceededError) as exc_info:
            await service.create_channel(_create_request(), _LoginUser())

    # The error carries the configured limit so the i18n template can render it.
    assert exc_info.value.kwargs.get("quota") == 2
    member_repository.add_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_channel_quota_is_authoritative_not_hardcoded_ten():
    """Limit is the configured value (3), not the legacy hardcoded 10."""
    member_repository = SimpleNamespace(
        find_channel_memberships=AsyncMock(return_value=[object(), object(), object()]),  # 3 existing
        add_member=AsyncMock(),
    )
    service = _service(member_repository)

    with patch(_QUOTA_PATCH, new=AsyncMock(return_value=3)):
        with pytest.raises(ChannelCreateLimitExceededError) as exc_info:
            await service.create_channel(_create_request(), _LoginUser())

    # Under the old hardcoded MAX_USER_CHANNEL_COUNT=10, 3 existing would have passed.
    assert exc_info.value.kwargs.get("quota") == 3


@pytest.mark.asyncio
async def test_create_channel_unlimited_allows_beyond_legacy_ten():
    """effective == -1 (unlimited) creates successfully even with >10 existing channels."""
    channel = SimpleNamespace(id="channel-1", name="资讯频道", source_list=[])
    channel_repository = SimpleNamespace(save=AsyncMock(return_value=channel))
    member_repository = SimpleNamespace(
        # 15 existing — old hardcoded cap of 10 would have blocked this
        find_channel_memberships=AsyncMock(return_value=[object()] * 15),
        add_member=AsyncMock(),
    )
    service = _service(member_repository, channel_repository)

    with (
        patch(_QUOTA_PATCH, new=AsyncMock(return_value=-1)),
        patch(
            "bisheng.channel.domain.services.channel_service.OwnerService.write_owner_tuple",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
            new=AsyncMock(return_value=SimpleNamespace(subscribe_information_source=AsyncMock())),
        ),
    ):
        result = await service.create_channel(_create_request(), _LoginUser())

    member_repository.add_member.assert_awaited_once()
    assert result.id == "channel-1"
