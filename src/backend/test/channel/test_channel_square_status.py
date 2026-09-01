"""F051 — the channel square derives subscription status from F048 ``visible``
(consistent with the "我加入的" rule): a channel the user can see is SUBSCRIBED;
otherwise it falls back to the membership row for PENDING / REJECTED / NOT_SUBSCRIBED.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import bisheng.channel.domain.services.channel_service as mod
from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import SubscriptionStatusEnum
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.models.space_channel_member import MembershipStatusEnum


def _async(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


class _FakeEs:
    def __init__(self, counts):
        self.counts = counts

    async def count_articles_batch(self, requests):
        return list(self.counts)[: len(requests)]


def _channel(cid: str):
    return SimpleNamespace(
        id=cid,
        name=f"name-{cid}",
        description="",
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],
        source_list=[],
        latest_article_update_time=None,
        create_time=datetime(2024, 1, 1),
        update_time=datetime(2024, 1, 1),
    )


def _service(rows, counts) -> ChannelService:
    return ChannelService(
        channel_repository=SimpleNamespace(
            find_square_channels=_async(rows),
            count_square_channels=_async(len(rows)),
        ),
        space_channel_member_repository=SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(find_by_ids=_async([])),
        article_es_service=_FakeEs(counts),
    )


async def test_square_status_visible_is_subscribed_else_membership_fallback(monkeypatch):
    now = datetime.now()
    # rows: (Channel, membership_status, membership_update_time, subscriber_count)
    rows = [
        (_channel("v1"), None, None, 0),  # visible -> SUBSCRIBED regardless of membership
        (_channel("v2"), MembershipStatusEnum.PENDING, now, 0),  # not visible -> PENDING
        (_channel("v3"), MembershipStatusEnum.REJECTED, now, 0),  # not visible, recent -> REJECTED
        (_channel("v4"), None, None, 0),  # not visible, no membership -> NOT_SUBSCRIBED
    ]
    monkeypatch.setattr(
        mod,
        "batch_check_business_visible",
        AsyncMock(return_value={"v1": True, "v2": False, "v3": False, "v4": False}),
    )
    service = _service(rows, counts=[0, 0, 0, 0])

    result = await service.get_channel_square(
        keyword=None, page=1, page_size=20, login_user=SimpleNamespace(user_id=1)
    )

    status_by_id = {item.id: item.subscription_status for item in result.data}
    assert status_by_id["v1"] == SubscriptionStatusEnum.SUBSCRIBED
    assert status_by_id["v2"] == SubscriptionStatusEnum.PENDING
    assert status_by_id["v3"] == SubscriptionStatusEnum.REJECTED
    assert status_by_id["v4"] == SubscriptionStatusEnum.NOT_SUBSCRIBED
    assert result.total == 4
