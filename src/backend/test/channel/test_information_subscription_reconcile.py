"""F031 — daily reconcile of information-source subscriptions (spec §7.2).

`ChannelService.reconcile_information_subscriptions()` runs inside one tenant's context and
converges three sides:
  desired  = union of every channel.source_list
  current  = channel_info_source rows
  to_unsub = current - desired  → unsubscribe + delete row
  to_sub   = desired - current  → subscribe + fetch metadata + insert row
Per-source failures are isolated (logged, counted) and never abort the rest.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.services.channel_service import ChannelService

_CS = "bisheng.channel.domain.services.channel_service"


def _rows(ids):
    return [SimpleNamespace(id=i) for i in ids]


def _meta(sid):
    return SimpleNamespace(id=sid, name=f"name-{sid}", icon=None, business_type="rss", description=None)


def _service(*, desired, current_ids, info_client):
    channel_repository = SimpleNamespace(
        find_all_referenced_source_ids=AsyncMock(return_value=set(desired)),
    )
    info_source_repository = SimpleNamespace(
        find_all=AsyncMock(return_value=_rows(current_ids)),
        batch_add=AsyncMock(),
        delete_by_ids=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=SimpleNamespace(),
        channel_info_source_repository=info_source_repository,
        article_es_service=SimpleNamespace(count_articles=AsyncMock(return_value=0)),
    )
    return service, info_source_repository


@pytest.mark.asyncio
async def test_reconcile_unsubscribes_and_deletes_orphan():
    """X referenced by no channel → unsubscribe(['X']) + delete row; A untouched. (AC-09)"""
    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        unsubscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(return_value=[]),
    )
    service, repo = _service(desired={"A"}, current_ids=["A", "X"], info_client=info_client)

    with patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)):
        result = await service.reconcile_information_subscriptions()

    info_client.unsubscribe_information_source.assert_awaited_once_with(["X"])
    repo.delete_by_ids.assert_awaited_once_with(["X"])
    info_client.subscribe_information_source.assert_not_awaited()
    assert result["to_unsub"] == 1


@pytest.mark.asyncio
async def test_reconcile_subscribes_and_inserts_missing():
    """Y referenced but not in channel_info_source → subscribe + fetch meta + insert. (AC-10)"""
    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        unsubscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(return_value=[_meta("Y")]),
    )
    service, repo = _service(desired={"A", "Y"}, current_ids=["A"], info_client=info_client)

    with patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)):
        result = await service.reconcile_information_subscriptions()

    info_client.subscribe_information_source.assert_awaited_once_with(["Y"])
    info_client.get_information_source_by_ids.assert_awaited_once_with(["Y"])
    repo.batch_add.assert_awaited_once()
    info_client.unsubscribe_information_source.assert_not_awaited()
    assert result["to_sub"] == 1


@pytest.mark.asyncio
async def test_reconcile_noop_when_equal():
    """desired == current → no information-service calls, no row changes. (AC-11)"""
    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        unsubscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(return_value=[]),
    )
    service, repo = _service(desired={"A", "B"}, current_ids=["A", "B"], info_client=info_client)

    with patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)):
        result = await service.reconcile_information_subscriptions()

    info_client.subscribe_information_source.assert_not_awaited()
    info_client.unsubscribe_information_source.assert_not_awaited()
    repo.batch_add.assert_not_awaited()
    repo.delete_by_ids.assert_not_awaited()
    assert result["to_sub"] == 0 and result["to_unsub"] == 0


@pytest.mark.asyncio
async def test_reconcile_isolates_per_source_failure():
    """One source failing must not abort the rest; it is counted in `failed`. (AC-13)"""

    async def _unsub(ids):
        if ids == ["X1"]:
            raise RuntimeError("boom")

    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        unsubscribe_information_source=AsyncMock(side_effect=_unsub),
        get_information_source_by_ids=AsyncMock(return_value=[]),
    )
    service, repo = _service(desired=set(), current_ids=["X1", "X2"], info_client=info_client)

    with patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)):
        result = await service.reconcile_information_subscriptions()

    # Both attempted; X2 still removed despite X1 failing.
    assert info_client.unsubscribe_information_source.await_count == 2
    repo.delete_by_ids.assert_awaited_once_with(["X2"])
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_reconcile_returns_counts():
    """Returns a {to_sub, to_unsub, failed} stats dict for observability."""
    info_client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        unsubscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(return_value=[_meta("Y")]),
    )
    service, _repo = _service(desired={"Y"}, current_ids=["X"], info_client=info_client)

    with patch(f"{_CS}.get_bisheng_information_client", new=AsyncMock(return_value=info_client)):
        result = await service.reconcile_information_subscriptions()

    assert set(result.keys()) == {"to_sub", "to_unsub", "failed"}
    assert result["to_sub"] == 1
    assert result["to_unsub"] == 1
    assert result["failed"] == 0
