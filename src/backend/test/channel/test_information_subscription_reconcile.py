"""Remote subscriptions and tenant-local metadata are independent projections."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.services.channel_service import ChannelService

_CS = "bisheng.channel.domain.services.channel_service"


def _rows(ids):
    return [SimpleNamespace(id=i) for i in sorted(ids)]


def _meta(source_id):
    return SimpleNamespace(id=source_id, name=f"name-{source_id}", icon=None, business_type="website", description=None)


def _client(remote_ids):
    actual = set(remote_ids)

    async def subscribe(ids):
        actual.update(ids)

    async def unsubscribe(ids):
        actual.difference_update(ids)

    async def metadata(ids):
        return [_meta(source_id) for source_id in ids]

    return SimpleNamespace(
        actual=actual,
        list_all_subscriptions=AsyncMock(side_effect=lambda: _rows(actual)),
        subscribe_information_source=AsyncMock(side_effect=subscribe),
        unsubscribe_information_source=AsyncMock(side_effect=unsubscribe),
        get_information_source_by_ids=AsyncMock(side_effect=metadata),
    )


def _service(*, desired, current_ids):
    repository = SimpleNamespace(
        find_all=AsyncMock(return_value=_rows(current_ids)),
        batch_add=AsyncMock(),
        delete_by_ids=AsyncMock(),
    )
    service = ChannelService(
        channel_repository=SimpleNamespace(find_all_referenced_source_ids=AsyncMock(return_value=set(desired))),
        space_channel_member_repository=SimpleNamespace(),
        channel_info_source_repository=repository,
        article_es_service=SimpleNamespace(count_articles=AsyncMock(return_value=0)),
    )
    return service, repository


async def _reconcile(service, client):
    with patch(f"{_CS}.get_bisheng_information_client", AsyncMock(return_value=client)):
        return await service.reconcile_information_subscriptions()


async def test_reconcile_unsubscribes_and_deletes_orphan():
    client = _client({"A", "X"})
    service, repo = _service(desired={"A"}, current_ids={"A", "X"})
    result = await _reconcile(service, client)
    client.unsubscribe_information_source.assert_awaited_once_with(["X"])
    repo.delete_by_ids.assert_awaited_once_with(["X"])
    client.subscribe_information_source.assert_not_awaited()
    assert result == {"to_sub": 0, "to_unsub": 1, "failed": 0}


async def test_reconcile_subscribes_and_inserts_missing():
    client = _client({"A"})
    service, repo = _service(desired={"A", "Y"}, current_ids={"A"})
    result = await _reconcile(service, client)
    client.subscribe_information_source.assert_awaited_once_with(["Y"])
    client.get_information_source_by_ids.assert_awaited_once_with(["Y"])
    repo.batch_add.assert_awaited_once()
    assert result == {"to_sub": 1, "to_unsub": 0, "failed": 0}


async def test_reconcile_noop_when_remote_and_local_equal_desired():
    client = _client({"A", "B"})
    service, repo = _service(desired={"A", "B"}, current_ids={"A", "B"})
    result = await _reconcile(service, client)
    client.subscribe_information_source.assert_not_awaited()
    client.unsubscribe_information_source.assert_not_awaited()
    repo.batch_add.assert_not_awaited()
    repo.delete_by_ids.assert_not_awaited()
    assert result == {"to_sub": 0, "to_unsub": 0, "failed": 0}


async def test_service_switch_resubscribes_27_existing_sources_without_resetting_cursors():
    desired = {f"source-{index:02}" for index in range(27)}
    client = _client(set())
    service, repo = _service(desired=desired, current_ids=desired)
    for row in repo.find_all.return_value:
        row.article_cursor_create_time = 123
        row.processed_remote_sync_at = 456
        row.processed_article_list_updated_at = 789
    result = await _reconcile(service, client)
    assert client.actual == desired
    assert [call.args[0] for call in client.subscribe_information_source.await_args_list] == [
        [source_id] for source_id in sorted(desired)
    ]
    assert result == {"to_sub": 27, "to_unsub": 0, "failed": 0}
    repo.batch_add.assert_not_awaited()
    repo.delete_by_ids.assert_not_awaited()
    client.get_information_source_by_ids.assert_not_awaited()
    assert all(
        (row.article_cursor_create_time, row.processed_remote_sync_at, row.processed_article_list_updated_at)
        == (123, 456, 789)
        for row in repo.find_all.return_value
    )


async def test_existing_remote_subscription_only_repairs_missing_local_metadata():
    client = _client({"A"})
    service, repo = _service(desired={"A"}, current_ids=set())
    result = await _reconcile(service, client)
    client.subscribe_information_source.assert_not_awaited()
    client.get_information_source_by_ids.assert_awaited_once_with(["A"])
    repo.batch_add.assert_awaited_once()
    assert result == {"to_sub": 0, "to_unsub": 0, "failed": 0}


async def test_incomplete_remote_snapshot_prevents_all_mutations():
    client = _client(set())
    client.list_all_subscriptions.side_effect = RuntimeError("incomplete subscription snapshot")
    service, repo = _service(desired={"A"}, current_ids={"X"})
    with pytest.raises(RuntimeError, match="incomplete subscription snapshot"):
        await _reconcile(service, client)
    client.subscribe_information_source.assert_not_awaited()
    client.unsubscribe_information_source.assert_not_awaited()
    repo.batch_add.assert_not_awaited()
    repo.delete_by_ids.assert_not_awaited()


async def test_reconcile_isolates_per_source_unsubscribe_failure():
    client = _client({"X1", "X2"})

    async def unsubscribe(ids):
        if ids == ["X1"]:
            raise RuntimeError("failed")
        client.actual.difference_update(ids)

    client.unsubscribe_information_source.side_effect = unsubscribe
    service, repo = _service(desired=set(), current_ids={"X1", "X2"})
    result = await _reconcile(service, client)
    assert client.unsubscribe_information_source.await_count == 2
    repo.delete_by_ids.assert_awaited_once_with(["X2"])
    assert result["failed"] == 1


async def test_failed_remote_subscribe_does_not_insert_metadata_or_block_other_sources():
    client = _client(set())

    async def subscribe(ids):
        if ids == ["A"]:
            raise RuntimeError("failed")
        client.actual.update(ids)

    client.subscribe_information_source.side_effect = subscribe
    service, repo = _service(desired={"A", "B"}, current_ids=set())
    result = await _reconcile(service, client)
    assert client.subscribe_information_source.await_count == 2
    client.get_information_source_by_ids.assert_awaited_once_with(["B"])
    assert [row.id for row in repo.batch_add.await_args.args[0]] == ["B"]
    assert result == {"to_sub": 2, "to_unsub": 0, "failed": 1}


async def test_successful_response_without_remote_subscription_is_reported_as_failure():
    client = _client(set())
    client.subscribe_information_source.side_effect = None
    service, _ = _service(desired={"A"}, current_ids={"A"})
    result = await _reconcile(service, client)
    assert result == {"to_sub": 1, "to_unsub": 0, "failed": 1}


async def test_successful_unsubscribe_without_remote_change_is_reported_as_failure():
    client = _client({"X"})
    client.unsubscribe_information_source.side_effect = None
    service, _ = _service(desired=set(), current_ids={"X"})
    result = await _reconcile(service, client)
    assert result == {"to_sub": 0, "to_unsub": 1, "failed": 1}


async def test_final_snapshot_failure_is_not_reported_as_success():
    client = _client(set())
    client.list_all_subscriptions.side_effect = [[], RuntimeError("final snapshot failed")]
    service, _ = _service(desired={"A"}, current_ids={"A"})
    with pytest.raises(RuntimeError, match="final snapshot failed"):
        await _reconcile(service, client)


async def test_absent_remote_orphan_only_deletes_local_row():
    client = _client(set())
    service, repo = _service(desired=set(), current_ids={"X"})
    result = await _reconcile(service, client)
    client.unsubscribe_information_source.assert_not_awaited()
    repo.delete_by_ids.assert_awaited_once_with(["X"])
    assert result == {"to_sub": 0, "to_unsub": 1, "failed": 0}


async def test_remote_only_sources_are_not_deleted_by_a_tenant():
    client = _client({"other-tenant-source"})
    service, repo = _service(desired=set(), current_ids=set())
    result = await _reconcile(service, client)
    client.unsubscribe_information_source.assert_not_awaited()
    repo.delete_by_ids.assert_not_awaited()
    assert result["failed"] == 0


async def test_second_run_does_not_resubscribe_existing_sources():
    client = _client(set())
    service, repo = _service(desired={"A"}, current_ids={"A"})
    assert (await _reconcile(service, client))["to_sub"] == 1
    assert (await _reconcile(service, client))["to_sub"] == 0
    client.subscribe_information_source.assert_awaited_once_with(["A"])
    repo.batch_add.assert_not_awaited()


async def test_reconcile_returns_counts():
    client = _client({"X"})
    service, _ = _service(desired={"Y"}, current_ids={"X"})
    assert await _reconcile(service, client) == {"to_sub": 1, "to_unsub": 1, "failed": 0}
