"""F040 T3: ArticleCountCache (short-TTL Redis cache for a channel's main article
count) + its integration into ``get_channel_detail``.

Locks: cache roundtrip, tenant isolation, cached-0 is a hit, fail-safe degradation,
and AC-27 — a cache hit means ``get_channel_detail`` does NOT issue the ES main count.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

import bisheng.channel.domain.services.article_count_cache as acc_mod
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


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def aget(self, key):
        return self.store.get(key)

    async def aset(self, key, value, expiration=None):
        self.store[key] = value


@pytest.fixture
def fake_redis(monkeypatch):
    redis = _FakeRedis()

    async def _get_redis():
        return redis

    monkeypatch.setattr(acc_mod, "_get_redis", _get_redis)
    monkeypatch.setattr(acc_mod, "_tenant_id", lambda: 1)
    return redis


# ----------------------------- cache unit tests ----------------------------- #


async def test_cache_roundtrip(fake_redis):
    await ArticleCountCache.set_main_count("ch1", 42)
    assert await ArticleCountCache.get_main_count("ch1") == 42


async def test_cache_miss_returns_none(fake_redis):
    assert await ArticleCountCache.get_main_count("absent") is None


async def test_cached_zero_is_a_hit(fake_redis):
    """A channel with 0 articles must read back as 0, never as a miss."""
    await ArticleCountCache.set_main_count("empty", 0)
    assert await ArticleCountCache.get_main_count("empty") == 0


async def test_tenant_isolation(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(acc_mod, "_get_redis", _async_return(redis))
    tid = {"v": 1}
    monkeypatch.setattr(acc_mod, "_tenant_id", lambda: tid["v"])
    await ArticleCountCache.set_main_count("ch", 7)  # tenant 1
    tid["v"] = 2
    assert await ArticleCountCache.get_main_count("ch") is None  # tenant 2 must not hit


async def test_fail_safe_when_redis_down(monkeypatch):
    monkeypatch.setattr(acc_mod, "_get_redis", _async_return(None))
    assert await ArticleCountCache.get_main_count("ch") is None
    await ArticleCountCache.set_main_count("ch", 5)  # must not raise


async def test_batch_get_returns_hits_only(fake_redis):
    await ArticleCountCache.set_main_counts({"a": 1, "b": 2})
    got = await ArticleCountCache.get_main_counts(["a", "b", "c"])
    assert got == {"a": 1, "b": 2}


# --------------------- get_channel_detail integration (AC-27) --------------------- #


class _CountingEs:
    def __init__(self):
        self.count_calls = 0

    async def count_articles(self, source_ids=None, filter_rules=None, **kwargs):
        self.count_calls += 1
        return 1234


class _Repo:
    async def find_membership(self, business_id, business_type, user_id, include_inactive=False):
        return None

    async def find_membership_split(self, business_id, business_type, user_id):
        return None, None

    async def find_members_by_role(self, channel_id, role):
        return []

    async def count_channel_members(self, channel_id):
        return 1


def _channel():
    return SimpleNamespace(
        id="chX",
        name="n",
        description="",
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],  # no sub-channels → unread calc issues no ES count
        is_released=True,
        latest_article_update_time=None,
        create_time=datetime.now(),
        source_list=[],
    )


@pytest.fixture
def _stub_detail_deps(monkeypatch):
    monkeypatch.setattr(
        FineGrainedPermissionService,
        "get_effective_permission_ids_async",
        staticmethod(_async_return([])),
    )

    async def _empty_ctx(self, login_user):
        return {}

    monkeypatch.setattr(ChannelService, "_build_channel_permission_context", _empty_ctx)


async def test_detail_uses_cache_and_skips_es_on_hit(monkeypatch, _stub_detail_deps):
    """AC-27: cache hit → get_channel_detail does NOT call ES count_articles."""
    es = _CountingEs()
    svc = ChannelService(
        channel_repository=SimpleNamespace(find_channels_by_ids=_async_return([_channel()])),
        space_channel_member_repository=_Repo(),
        channel_info_source_repository=SimpleNamespace(),
        article_es_service=es,
    )
    monkeypatch.setattr(ArticleCountCache, "get_main_count", classmethod(_async_return(99)))

    detail = await svc.get_channel_detail("chX", SimpleNamespace(user_id=1, tenant_id=1))

    assert detail.article_count == 99
    assert es.count_calls == 0  # served from cache, no ES round-trip


async def test_detail_queries_es_and_fills_cache_on_miss(monkeypatch, _stub_detail_deps):
    es = _CountingEs()
    svc = ChannelService(
        channel_repository=SimpleNamespace(find_channels_by_ids=_async_return([_channel()])),
        space_channel_member_repository=_Repo(),
        channel_info_source_repository=SimpleNamespace(),
        article_es_service=es,
    )
    monkeypatch.setattr(ArticleCountCache, "get_main_count", classmethod(_async_return(None)))
    filled = {}

    async def _set(cls, channel_id, count):
        filled[channel_id] = count

    monkeypatch.setattr(ArticleCountCache, "set_main_count", classmethod(_set))

    detail = await svc.get_channel_detail("chX", SimpleNamespace(user_id=1, tenant_id=1))

    assert detail.article_count == 1234
    assert es.count_calls == 1  # one ES count for the main total
    assert filled == {"chX": 1234}  # result written back to cache
