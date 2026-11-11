"""Actual delivery uses the composed automation facade before import effects.

覆盖 AC: AC-35, AC-71, AC-87, AC-89, AC-91, AC-92. SQL, identity, SourceOwner,
Core and target Owners are real; only article matching/import effects are fake.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.knowledge_space import SpaceFileNameDuplicateError
from bisheng.core import database
from bisheng.worker.information import knowledge_delivery as worker
from test.knowledge_unification import test_ch_execution_admission as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
people = fixtures.people
admitted = fixtures.admitted


@pytest.fixture
async def delivery(admitted, monkeypatch):
    value = admitted
    async with value.context.sessions() as session, session.begin():
        await session.execute(
            sa.update(Channel)
            .where(Channel.id == value.root.id, Channel.tenant_id == 101)
            .values(source_list=["source-A"])
        )
    monkeypatch.setattr(database, "get_async_db_session", value.context.sessions)
    monkeypatch.setattr(ChannelService, "add_articles_to_knowledge_space", AsyncMock(return_value=[]))
    monkeypatch.setattr(ArticleEsService, "match_article_ids_sync", MagicMock(side_effect=lambda ids, *_: ids))
    return value


async def test_production_worker_composes_real_admission_and_preserves_restored_person(delivery):
    value = delivery
    async with worker._service_session(include_channel_service=True) as service:
        result = await service.deliver_to_config(101, value.config_id, ["a", "a", "b"], value.detected_at)
    assert result["accepted"] == 2
    assert ChannelService.add_articles_to_knowledge_space.await_count == 2
    for call in ChannelService.add_articles_to_knowledge_space.await_args_list:
        request, identity = call.args[:2]
        assert request.knowledge_id == 10 and request.parent_id == 30
        assert request.skip_missing_and_duplicates is False
        assert identity.user_id == 7 and identity.tenant_id == 101 and set(identity.user_role) == {4, 6}
        assert identity._runtime_credential_reference is None


async def test_invalid_other_slot_rejects_whole_delivery_without_mutating_choices(delivery):
    value = delivery
    from test.knowledge_unification.test_ch_bindings import UpdateChannelRequest, config, deleted_space, state

    await value.context.service.update_channel(
        value.root.id, UpdateChannelRequest(knowledge_sync=config(10, 20)), value.identity
    )
    async with value.context.sessions() as session:
        config_id = (
            await session.exec(
                sa.select(ChannelKnowledgeSync.id).where(
                    ChannelKnowledgeSync.channel_id == value.root.id, ChannelKnowledgeSync.knowledge_space_id == "20"
                )
            )
        ).scalar_one()
    await deleted_space(value.context)
    before = await state(value.context)
    async with worker._service_session(include_channel_service=True) as service:
        with pytest.raises(ResourceReferenceInvalidError):
            await service.deliver_to_config(101, config_id, ["a"], value.detected_at)
    ChannelService.add_articles_to_knowledge_space.assert_not_awaited()
    assert await state(value.context) == before


async def test_replaced_uuid_does_not_pick_another_configuration(delivery):
    value = delivery
    from test.knowledge_unification.test_ch_bindings import UpdateChannelRequest, config

    await value.context.service.update_channel(
        value.root.id, UpdateChannelRequest(knowledge_sync=config(10)), value.identity
    )
    async with worker._service_session(include_channel_service=True) as service:
        result = await service.deliver_to_config(101, value.config_id, ["a"], value.detected_at)
    assert result["result"] == "config_missing"
    ChannelService.add_articles_to_knowledge_space.assert_not_awaited()


async def test_article_duplicate_still_is_terminal_and_other_article_continues(delivery):
    value = delivery
    ChannelService.add_articles_to_knowledge_space.side_effect = [SpaceFileNameDuplicateError(), []]
    async with worker._service_session(include_channel_service=True) as service:
        result = await service.deliver_to_config(101, value.config_id, ["a", "b"], value.detected_at)
    assert result["accepted"] == 1 and result["failed"] == {"duplicate_name": 1}


async def test_disabled_configuration_never_starts_identity_or_import_side_effects(delivery):
    value = delivery
    async with value.context.sessions() as session, session.begin():
        await session.execute(
            sa.update(ChannelKnowledgeSync).where(ChannelKnowledgeSync.id == value.config_id).values(is_enabled=False)
        )
    async with worker._service_session(include_channel_service=True) as service:
        result = await service.deliver_to_config(101, value.config_id, ["a"], value.detected_at)
    assert result["result"] == "config_disabled"
    ChannelService.add_articles_to_knowledge_space.assert_not_awaited()


async def test_worker_releases_its_short_source_read_transaction_before_existing_importer(delivery, monkeypatch):
    value = delivery
    opened = []

    @asynccontextmanager
    async def sessions():
        async with value.context.sessions() as session:
            opened.append(session)
            yield session

    monkeypatch.setattr(database, "get_async_db_session", sessions)

    async def imported(*args, **kwargs):
        # The normal importer opens independent write transactions for
        # folder/space timestamps. It must not wait on this task's read locks.
        assert len(opened) >= 2
        assert not opened[-1].in_transaction()
        return []

    ChannelService.add_articles_to_knowledge_space.side_effect = imported
    async with worker._service_session(include_channel_service=True) as service:
        result = await service.deliver_to_config(101, value.config_id, ["a"], value.detected_at)
    assert result["accepted"] == 1 and result["failed"] == {}
