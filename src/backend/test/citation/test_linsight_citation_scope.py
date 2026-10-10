"""F069 T001: LinsightCitationScope records the sources a run has seen.

Covers AC-02 (sources retrieved anywhere in the run are counted, keyed by
session-version id) and AC-25 (Redis failures never raise into the tool).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.citation.domain.services import linsight_citation_scope as scope_mod
from bisheng.citation.domain.services.linsight_citation_scope import (
    CITE_SEEN_TTL_SECONDS,
    LinsightCitationScope,
)


def _item(key: str, type_value: str = "rag"):
    return SimpleNamespace(key=key, citationId=key.split(":")[0], itemId=key.split(":")[1], type=type_value)


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch):
    client = SimpleNamespace(ahset=AsyncMock(), aexpire_key=AsyncMock(), ahgetall=AsyncMock(return_value={}))
    monkeypatch.setattr(scope_mod, "get_redis_client", AsyncMock(return_value=client))
    return client


async def test_record_seen_writes_hash_with_ttl(redis):
    scope = LinsightCitationScope(svid="sv-1", session_id="chat-1")

    await scope.record_seen([_item("knowledgesearch_ab12cd34:3"), _item("websearch_11223344:1", "web")])

    assert scope.seen_keys == {"knowledgesearch_ab12cd34:3", "websearch_11223344:1"}
    redis.ahset.assert_awaited_once()
    assert redis.ahset.await_args.args[0] == "linsight:cite_seen:sv-1"
    assert redis.ahset.await_args.kwargs["mapping"] == {
        "knowledgesearch_ab12cd34:3": "rag",
        "websearch_11223344:1": "web",
    }
    redis.aexpire_key.assert_awaited_once_with("linsight:cite_seen:sv-1", CITE_SEEN_TTL_SECONDS)


async def test_record_seen_dedupes_across_calls(redis):
    scope = LinsightCitationScope(svid="sv-1", session_id="chat-1")

    await scope.record_seen([_item("knowledgesearch_ab12cd34:3")])
    await scope.record_seen([_item("knowledgesearch_ab12cd34:3"), _item("knowledgesearch_ab12cd34:4")])

    assert scope.seen_keys == {"knowledgesearch_ab12cd34:3", "knowledgesearch_ab12cd34:4"}
    # second call only ships the new key
    assert redis.ahset.await_args.kwargs["mapping"] == {"knowledgesearch_ab12cd34:4": "rag"}


async def test_record_seen_empty_or_none_does_not_touch_redis(redis):
    scope = LinsightCitationScope(svid="sv-1", session_id="chat-1")

    await scope.record_seen([])
    await scope.record_seen(None)

    redis.ahset.assert_not_awaited()
    assert scope.seen_keys == set()


async def test_record_seen_falls_back_to_citation_id_when_key_missing(redis):
    scope = LinsightCitationScope(svid="sv-1", session_id="chat-1")
    item = SimpleNamespace(
        key=None, citationId="knowledgesearch_ab12cd34", itemId="7", type=SimpleNamespace(value="rag")
    )

    await scope.record_seen([item])

    assert scope.seen_keys == {"knowledgesearch_ab12cd34:7"}
    assert redis.ahset.await_args.kwargs["mapping"] == {"knowledgesearch_ab12cd34:7": "rag"}


async def test_record_seen_survives_redis_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(scope_mod, "get_redis_client", AsyncMock(side_effect=RuntimeError("redis down")))
    scope = LinsightCitationScope(svid="sv-1", session_id="chat-1")

    await scope.record_seen([_item("knowledgesearch_ab12cd34:3")])  # must not raise

    assert scope.seen_keys == {"knowledgesearch_ab12cd34:3"}


async def test_load_hydrates_from_redis(redis):
    redis.ahgetall.return_value = {b"knowledgesearch_ab12cd34:3": b"rag", "websearch_11223344:1": "web"}
    scope = LinsightCitationScope(svid="sv-1", session_id="chat-1")

    await scope.load()

    redis.ahgetall.assert_awaited_once_with("linsight:cite_seen:sv-1")
    assert scope.seen_keys == {"knowledgesearch_ab12cd34:3", "websearch_11223344:1"}


async def test_load_survives_redis_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(scope_mod, "get_redis_client", AsyncMock(side_effect=RuntimeError("redis down")))
    scope = LinsightCitationScope(svid="sv-1", session_id="chat-1")

    await scope.load()  # must not raise

    assert scope.seen_keys == set()
