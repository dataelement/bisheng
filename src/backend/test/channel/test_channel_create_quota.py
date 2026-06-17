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


def _membership(channel_id: str):
    """A creator membership row — only business_id matters for the quota count."""
    return SimpleNamespace(business_id=channel_id)


def _channel_repo(existing_ids, saved=None):
    """channel_repository whose find_channels_by_ids returns only ids that still exist.

    Mirrors the real ``WHERE id IN (...)`` query: orphan business_ids (memberships whose
    channel was already deleted) are dropped, so they never inflate the create-quota count.
    """

    async def _find_channels_by_ids(ids):
        return [SimpleNamespace(id=cid) for cid in ids if cid in existing_ids]

    return SimpleNamespace(
        find_channels_by_ids=AsyncMock(side_effect=_find_channels_by_ids),
        save=AsyncMock(return_value=saved),
    )


@pytest.mark.asyncio
async def test_create_channel_blocks_at_configured_quota_with_real_number():
    """At/over the role quota → ChannelCreateLimitExceededError carrying the real limit."""
    member_repository = SimpleNamespace(
        # 2 creator memberships, both pointing to channels that still exist → 2 real channels
        find_channel_memberships=AsyncMock(return_value=[_membership("c1"), _membership("c2")]),
        add_member=AsyncMock(),
    )
    # quota is 2 and 2 channels still exist → blocked
    service = _service(member_repository, _channel_repo(existing_ids={"c1", "c2"}))

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
        find_channel_memberships=AsyncMock(
            return_value=[_membership("c1"), _membership("c2"), _membership("c3")]
        ),  # 3 existing
        add_member=AsyncMock(),
    )
    service = _service(member_repository, _channel_repo(existing_ids={"c1", "c2", "c3"}))

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


@pytest.mark.asyncio
async def test_create_channel_ignores_orphan_membership():
    """Regression: an orphan creator membership (its channel was already deleted) must NOT
    count toward the quota.

    1 real channel + 1 orphan membership, quota 2 → still creatable. Before the fix the check
    used ``len(find_channel_memberships)`` (== 2) which hit ``2 >= 2`` and blocked one slot
    early — the "configured 14, only 13 usable" bug. Now the count intersects with channels
    that still exist, so the orphan is ignored and the 2nd channel can be created.
    """
    saved = SimpleNamespace(id="channel-new", name="资讯频道", source_list=[])
    member_repository = SimpleNamespace(
        find_channel_memberships=AsyncMock(return_value=[_membership("real-1"), _membership("orphan-1")]),
        add_member=AsyncMock(),
    )
    # Only "real-1" still has a channel row; "orphan-1" is dropped by the WHERE id IN filter.
    channel_repository = _channel_repo(existing_ids={"real-1"}, saved=saved)
    service = _service(member_repository, channel_repository)

    with (
        patch(_QUOTA_PATCH, new=AsyncMock(return_value=2)),
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
    assert result.id == "channel-new"
