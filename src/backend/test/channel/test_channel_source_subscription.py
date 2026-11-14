"""F060 desired-source behavior through real F118 channel transactions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest, UpdateChannelRequest
from bisheng.channel.domain.services.channel_service import ChannelService
from test.knowledge_unification import test_ch_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
_CS = "bisheng.channel.domain.services.channel_service"


def _info_source_meta(sid):
    return SimpleNamespace(id=sid, name=f"name-{sid}", icon=None, business_type="rss", description=None)


@pytest.fixture
async def source_business(business, monkeypatch):
    client = SimpleNamespace(
        subscribe_information_source=AsyncMock(),
        unsubscribe_information_source=AsyncMock(),
        get_information_source_by_ids=AsyncMock(side_effect=lambda ids: [_info_source_meta(ident) for ident in ids]),
    )
    sources = SimpleNamespace(upsert_metadata=AsyncMock(), delete_by_ids=AsyncMock())
    business.service.channel_info_source_repository = sources
    business.service._best_effort_sync_channel_info_source_metadata = (
        ChannelService._best_effort_sync_channel_info_source_metadata.__get__(business.service)
    )
    business.service._get_channel_latest_article_create_time = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "bisheng.channel.domain.services.channel_service.get_bisheng_information_client", AsyncMock(return_value=client)
    )
    return business, client, sources


async def create(context, sources):
    return await context.service.create_channel(
        CreateChannelRequest(name="资讯频道", source_list=sources, visibility="public", is_released=True), context.user
    )


async def test_create_never_subscribes_and_refreshes_public_metadata(source_business):
    context, client, sources = source_business
    await create(context, ["A", "B"])
    client.subscribe_information_source.assert_not_awaited()
    client.get_information_source_by_ids.assert_awaited_once_with(["A", "B"])
    sources.upsert_metadata.assert_awaited_once()


async def test_create_metadata_failure_does_not_roll_back_channel(source_business):
    context, client, _sources = source_business
    client.get_information_source_by_ids.side_effect = RuntimeError("metadata unavailable")
    result = await create(context, ["A", "B"])
    client.subscribe_information_source.assert_not_awaited()
    state = await fixtures.state(context)
    assert any(row["id"] == result.id for row in state["channel"])
    assert len([row for row in state["space_channel_member"] if row["business_id"] == result.id]) == 1


async def test_create_upserts_selected_source_metadata(source_business):
    context, client, sources = source_business
    await create(context, ["B"])
    client.get_information_source_by_ids.assert_awaited_once_with(["B"])
    client.subscribe_information_source.assert_not_awaited()
    sources.upsert_metadata.assert_awaited_once()


async def test_create_is_not_blocked_by_remote_subscription_limit(source_business):
    context, client, _sources = source_business
    client.subscribe_information_source.side_effect = RuntimeError("must not be called")
    client.get_information_source_by_ids.side_effect = RuntimeError("metadata unavailable")
    result = await create(context, ["B"])
    state = await fixtures.state(context)
    client.subscribe_information_source.assert_not_awaited()
    assert any(row["id"] == result.id for row in state["channel"])
    assert len([row for row in state["space_channel_member"] if row["business_id"] == result.id]) == 1
    context.adapter.authorize_created.assert_awaited_once()


async def test_update_add_never_subscribes_and_refreshes_metadata(source_business):
    context, client, sources = source_business
    root = await create(context, ["A"])
    sources.upsert_metadata.reset_mock()
    await context.service.update_channel(root.id, UpdateChannelRequest(source_list=["A", "B", "C"]), context.user)
    client.subscribe_information_source.assert_not_awaited()
    client.unsubscribe_information_source.assert_not_awaited()
    sources.upsert_metadata.assert_awaited_once()
    assert next(row["source_list"] for row in (await fixtures.state(context))["channel"] if row["id"] == root.id) == [
        "A",
        "B",
        "C",
    ]


async def test_update_remove_does_not_unsubscribe(source_business):
    context, client, _sources = source_business
    root = await create(context, ["A", "B"])
    await context.service.update_channel(root.id, UpdateChannelRequest(source_list=["A"]), context.user)
    client.unsubscribe_information_source.assert_not_awaited()
    client.subscribe_information_source.assert_not_awaited()


async def test_dismiss_does_not_unsubscribe(source_business):
    context, client, sources = source_business
    root = await create(context, ["X"])
    await context.service.dismiss_channel(root.id, context.user)
    client.unsubscribe_information_source.assert_not_awaited()
    sources.delete_by_ids.assert_not_awaited()


async def test_dismiss_shared_source_stays_subscribed(source_business):
    context, client, sources = source_business
    first, second = await create(context, ["X"]), await create(context, ["X"])
    await context.service.dismiss_channel(first.id, context.user)
    client.unsubscribe_information_source.assert_not_awaited()
    sources.delete_by_ids.assert_not_awaited()
    assert any(
        row["id"] == second.id and row["source_list"] == ["X"] for row in (await fixtures.state(context))["channel"]
    )


# --------------------------------------------------- channel_info_source batch_add


@pytest.mark.asyncio
async def test_batch_add_idempotent_on_integrity_error():
    """A concurrent duplicate-id insert is recovered: rollback, drop existing, retry new only."""
    from sqlalchemy.exc import IntegrityError

    from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
    from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import (
        ChannelInfoSourceRepositoryImpl,
    )

    added_batches: list[list[str]] = []
    commits = {"n": 0}

    class _Result:
        def all(self):
            # On the post-conflict re-query, 'A' is reported as already present.
            return [ChannelInfoSource(id="A", source_name="a", source_type="rss")]

    async def _commit():
        commits["n"] += 1
        if commits["n"] == 1:
            raise IntegrityError("duplicate", None, Exception("duplicate"))

    session = SimpleNamespace(
        add_all=lambda rows: added_batches.append([r.id for r in rows]),
        commit=_commit,
        rollback=AsyncMock(),
        exec=AsyncMock(return_value=_Result()),
    )

    repo = ChannelInfoSourceRepositoryImpl(session)
    await repo.batch_add(
        [
            ChannelInfoSource(id="A", source_name="a", source_type="rss"),
            ChannelInfoSource(id="B", source_name="b", source_type="rss"),
        ]
    )

    assert added_batches[0] == ["A", "B"]  # first attempt: both
    assert added_batches[1] == ["B"]  # retry: only the genuinely-new one
    assert commits["n"] == 2
    session.rollback.assert_awaited_once()
