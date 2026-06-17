"""F037-B: per-page unread counts via one ES msearch round-trip.

``get_my_channels`` computed unread per channel as ``total - (read in channel)``
with a separate ES query per channel (plus per-1000 chunked read-id queries).
The batched path expresses unread directly as ``count(channel filter AND NOT
read_ids)`` and sends all channels in a single ``count_articles_batch`` (msearch).

These tests lock: (1) ``_build_count_query`` emits a must_not terms clause for
exclusions, (2) the batched result equals the per-channel oracle and uses one
batch call, (3) the oversized-read-set fallback preserves correctness.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.channel.domain.services import channel_service as channel_service_module
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.channel.domain.services.channel_service import ChannelService


class _FakeEs:
    """In-memory article universe (article_id -> source_id) mirroring ES count
    semantics for source terms + _id include/exclude. filter_rules is ignored;
    tests use channels with no rules so both code paths receive the same input."""

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
    ) -> int:
        self.count_calls += 1
        return self._count(source_ids, include_article_ids, exclude_article_ids)

    async def count_articles_batch(self, requests) -> list[int]:
        self.batch_calls += 1
        return [
            self._count(r.get("source_ids"), r.get("include_article_ids"), r.get("exclude_article_ids"))
            for r in requests
        ]


def _channel(cid: str, sources: list[str]):
    return SimpleNamespace(id=cid, source_list=sources, filter_rules=[])


def _service(es: _FakeEs) -> ChannelService:
    return ChannelService(
        channel_repository=SimpleNamespace(),
        space_channel_member_repository=SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(),
        article_es_service=es,
    )


def test_build_count_query_exclude_emits_must_not():
    svc = ArticleEsService()
    q = svc._build_count_query(source_ids=["s1"], exclude_article_ids=["a1", "a2"])
    assert q["bool"]["must_not"] == [{"terms": {"_id": ["a1", "a2"]}}]
    # An empty exclusion list means "exclude nothing" — never a definitive zero.
    q2 = svc._build_count_query(source_ids=["s1"], exclude_article_ids=[])
    assert "must_not" not in q2.get("bool", {})


@pytest.mark.asyncio
async def test_batch_unread_equals_per_channel_oracle():
    # 6 articles across two sources; the user has read a1, a3, b2.
    universe = {"a1": "s1", "a2": "s1", "a3": "s1", "b1": "s2", "b2": "s2", "b3": "s2"}
    read_ids = ["a1", "a3", "b2"]
    channels = [_channel("c1", ["s1"]), _channel("c2", ["s2"]), _channel("c3", ["s1", "s2"])]

    es = _FakeEs(universe)
    svc = _service(es)

    batched = await svc._calculate_unread_counts_batch(channels, read_ids)
    oracle = [await svc._calculate_unread_count(ch, read_ids) for ch in channels]

    assert batched == oracle
    # c1: s1 has 3, read 2 -> 1; c2: s2 has 3, read 1 -> 2; c3: 6 total, read 3 -> 3
    assert batched == [1, 2, 3]
    # The whole page resolved in exactly one msearch round-trip.
    assert es.batch_calls == 1


@pytest.mark.asyncio
async def test_batch_unread_no_read_ids_returns_totals():
    universe = {"a1": "s1", "a2": "s1", "b1": "s2"}
    channels = [_channel("c1", ["s1"]), _channel("c2", ["s2"])]
    es = _FakeEs(universe)
    svc = _service(es)

    batched = await svc._calculate_unread_counts_batch(channels, [])
    assert batched == [2, 1]
    assert es.batch_calls == 1


@pytest.mark.asyncio
async def test_batch_unread_falls_back_for_oversized_read_set(monkeypatch):
    universe = {"a1": "s1", "a2": "s1", "a3": "s1"}
    read_ids = ["a1", "a2"]
    channels = [_channel("c1", ["s1"])]
    es = _FakeEs(universe)
    svc = _service(es)

    # Force the read set to be considered oversized so the per-channel path runs.
    monkeypatch.setattr(channel_service_module, "_MAX_UNREAD_EXCLUDE_TERMS", 1)

    result = await svc._calculate_unread_counts_batch(channels, read_ids)

    assert result == [1]  # 3 total - 2 read
    assert es.batch_calls == 0, "oversized read set must not use the batch msearch path"
    assert es.count_calls > 0, "fallback should use the per-channel count path"


@pytest.mark.asyncio
async def test_batch_unread_empty_channels():
    svc = _service(_FakeEs({}))
    assert await svc._calculate_unread_counts_batch([], ["a1"]) == []
