"""Home-page discovery recommendations: ``get_recommended_channels`` returns
released PUBLIC channels sorted by ES article count descending.

Article count is computed per channel from Elasticsearch *after* the candidate
rows are fetched (it is not a DB column), so the service must re-sort in memory.
These tests lock that ordering plus the ``total`` (qualifying public count) the
frontend uses to fall back to the empty illustration when < 3.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.services.channel_service import ChannelService


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


class _FakeEs:
    """Returns preset article counts aligned to the order of the batch requests."""

    def __init__(self, counts):
        self.counts = counts

    async def count_articles_batch(self, requests):
        # One count per request, in the same order the service built them (row order).
        return list(self.counts)[: len(requests)]


def _channel(cid: str, name: str):
    return SimpleNamespace(
        id=cid,
        name=name,
        description="",
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],
        is_released=True,
        latest_article_update_time=None,
        create_time=datetime(2024, 1, 1),
        update_time=datetime(2024, 1, 1),
        source_list=[],
    )


def _rows(channels):
    # Repository tuple shape: (Channel, sub_status, sub_update_time, subscriber_count)
    return [(c, None, None, 0) for c in channels]


def _service(rows, counts) -> ChannelService:
    return ChannelService(
        channel_repository=SimpleNamespace(
            find_public_recommend_channels=_async_return(rows),
        ),
        space_channel_member_repository=SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(find_by_ids=_async_return([])),
        article_es_service=_FakeEs(counts),
    )


async def test_recommend_sorts_by_article_count_desc():
    channels = [_channel("a", "A"), _channel("b", "B"), _channel("c", "C")]
    # Candidate (DB) order A, B, C with ES counts 5, 50, 20 → expect B, C, A.
    service = _service(_rows(channels), counts=[5, 50, 20])

    result = await service.get_recommended_channels(
        login_user=SimpleNamespace(user_id=1), limit=12
    )

    assert [item.id for item in result.data] == ["b", "c", "a"]
    assert [item.article_count for item in result.data] == [50, 20, 5]
    # total = number of qualifying public channels (drives the < 3 empty fallback).
    assert result.total == 3


async def test_recommend_respects_limit():
    channels = [_channel(str(i), f"C{i}") for i in range(5)]
    service = _service(_rows(channels), counts=[10, 20, 30, 40, 50])

    result = await service.get_recommended_channels(
        login_user=SimpleNamespace(user_id=1), limit=2
    )

    # Top 2 by count, but total still reports the full qualifying set.
    assert [item.id for item in result.data] == ["4", "3"]
    assert result.total == 5


async def test_recommend_empty_when_no_public_channels():
    service = _service(_rows([]), counts=[])

    result = await service.get_recommended_channels(
        login_user=SimpleNamespace(user_id=1), limit=12
    )

    assert result.data == []
    assert result.total == 0
