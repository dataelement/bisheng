"""F040 T4: per-sub-channel unread is split out of channel detail into a dedicated
endpoint, and computed in one batched ES round-trip.

Locks:
- AC-05 equivalence: batched sub-channel unread == the per-call oracle, in one msearch.
- AC-26: get_channel_detail no longer computes unread (no _calculate_sub_channel_...
  call) and the response no longer carries sub_channel_unread_counts.
- the service method backing GET /channel/manager/{id}/unread-counts returns the dict.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.services.article_count_cache import ArticleCountCache
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


class _FakeEs:
    """In-memory article universe mirroring ES source-term + _id include/exclude
    semantics (filter_rules ignored — both code paths get the same inputs)."""

    def __init__(self, universe: dict[str, str]):
        self.universe = universe
        self.count_calls = 0
        self.batch_calls = 0

    def _count(self, source_ids, include, exclude) -> int:
        if source_ids is not None and not source_ids:
            return 0
        ids = {a for a, s in self.universe.items() if source_ids is None or s in source_ids}
        if include is not None:
            if not include:
                return 0
            ids &= set(include)
        if exclude:
            ids -= set(exclude)
        return len(ids)

    async def count_articles(
        self, source_ids=None, filter_rules=None, include_article_ids=None, exclude_article_ids=None
    ):
        self.count_calls += 1
        return self._count(source_ids, include_article_ids, exclude_article_ids)

    async def count_articles_batch(self, requests):
        self.batch_calls += 1
        return [
            self._count(r.get("source_ids"), r.get("include_article_ids"), r.get("exclude_article_ids"))
            for r in requests
        ]


def _sub_channel(cid: str, sources: list[str], sub_names: list[str]):
    filter_rules = [{"channel_type": "sub", "name": n, "type": "group", "rules": []} for n in sub_names]
    return SimpleNamespace(
        id=cid,
        name="n",
        description="",
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=filter_rules,
        is_released=True,
        latest_article_update_time=None,
        create_time=datetime.now(),
        source_list=sources,
    )


def _service(es, *, channel=None, read_ids=None, repo=None):
    return ChannelService(
        channel_repository=SimpleNamespace(find_channels_by_ids=_async_return([channel] if channel else [])),
        space_channel_member_repository=repo or SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(find_by_ids=_async_return([])),
        article_es_service=es,
        article_read_repository=SimpleNamespace(get_all_read_article_ids=_async_return(read_ids or [])),
    )


async def test_batched_sub_unread_equals_per_call_oracle():
    """AC-05: batch path == per-sub total-minus-read oracle, in a single msearch."""
    universe = {"a1": "s1", "a2": "s1", "a3": "s1", "a4": "s1"}
    read_ids = ["a1", "a3"]
    channel = _sub_channel("c1", ["s1"], ["subA", "subB"])
    es = _FakeEs(universe)
    svc = _service(es)

    oracle = await svc._calculate_sub_channel_unread_counts(channel, read_ids)
    es.batch_calls = 0
    batched = await svc._calculate_sub_channel_unread_counts_batch(channel, read_ids)

    assert batched == oracle
    assert es.batch_calls == 1  # one round-trip for all sub-channels


async def test_no_sub_channels_returns_empty_without_es():
    es = _FakeEs({})
    channel = _sub_channel("c1", ["s1"], [])  # no sub-channels
    out = await _service(es)._calculate_sub_channel_unread_counts_batch(channel, [])
    assert out == {}
    assert es.batch_calls == 0


async def test_unread_endpoint_service_returns_counts():
    universe = {"a1": "s1", "a2": "s1"}
    channel = _sub_channel("cX", ["s1"], ["subA"])
    es = _FakeEs(universe)
    svc = _service(es, channel=channel, read_ids=["a1"])

    out = await svc.get_sub_channel_unread_counts("cX", SimpleNamespace(user_id=1, tenant_id=1))

    assert out == {"subA": 1}  # 2 articles - 1 read


# ----------------------- AC-26: detail no longer computes unread ----------------------- #


class _Repo:
    async def find_membership(self, business_id, business_type, user_id, include_inactive=False):
        return None

    async def find_membership_split(self, business_id, business_type, user_id):
        return None, None

    async def find_members_by_role(self, channel_id, role):
        return []

    async def count_channel_members(self, channel_id):
        return 1


@pytest.fixture
def _stub_detail(monkeypatch):
    monkeypatch.setattr(
        FineGrainedPermissionService, "get_effective_permission_ids_async", staticmethod(_async_return([]))
    )

    async def _empty_ctx(self, login_user):
        return {}

    monkeypatch.setattr(ChannelService, "_build_channel_permission_context", _empty_ctx)
    monkeypatch.setattr(ArticleCountCache, "get_main_count", classmethod(_async_return(0)))


async def test_detail_does_not_compute_unread(monkeypatch, _stub_detail):
    """AC-26: get_channel_detail must not invoke the per-sub-channel unread calc,
    and the response must not carry sub_channel_unread_counts. (Detail no longer looks
    at sub-channels at all, so an empty filter_rules channel suffices.)"""
    channel = _sub_channel("cD", [], [])  # no sources / sub-channels — detail ignores them now
    es = _FakeEs({"a1": "s1"})
    svc = _service(es, channel=channel, read_ids=["a1"], repo=_Repo())

    called = {"unread": False}

    async def _spy(self, channel, all_read_ids):
        called["unread"] = True
        return {}

    monkeypatch.setattr(ChannelService, "_calculate_sub_channel_unread_counts", _spy)

    detail = await svc.get_channel_detail("cD", SimpleNamespace(user_id=1, tenant_id=1))

    assert called["unread"] is False
    assert not hasattr(detail, "sub_channel_unread_counts")
    assert es.batch_calls == 0  # detail issues no sub-channel unread msearch
