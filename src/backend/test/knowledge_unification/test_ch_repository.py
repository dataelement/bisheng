"""Real channel/tenant-less child persistence joins the external transaction.

覆盖 AC: AC-87, AC-88, AC-89, AC-91, AC-92. SQLite proves SQL rollback and
C3 listener behavior, not MySQL/DM8 row locking.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.repositories.reference_binding_repository import ChannelReferenceBindingRepository
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.core.database import tenant_filter


@pytest.fixture(autouse=True)
def tenant():
    token = set_current_tenant_id(101)
    visible = set_visible_tenant_ids(frozenset({101, 1}))
    yield
    visible_tenant_ids.reset(visible)
    current_tenant_id.reset(token)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    names = tenant_filter._tenant_aware_tables | {"channel"}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'channel.db'}")
    metadata = sa.MetaData()
    for model in (Channel, ChannelKnowledgeSync, SpaceChannelMember):
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    c.name,
                    c.type.copy(),
                    primary_key=c.primary_key,
                    nullable=c.nullable,
                    server_default=sa.text("CURRENT_TIMESTAMP")
                    if c.name in {"create_time", "update_time"}
                    else c.server_default,
                )
                for c in model.__table__.columns
            ],
        )
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            sa.insert(Channel),
            [
                {"id": key, "tenant_id": tenant, "user_id": 7, "name": key, "visibility": "PUBLIC"}
                for key, tenant in (("own", 101), ("root", 1), ("foreign", 202))
            ],
        )
        await connection.execute(
            sa.insert(ChannelKnowledgeSync),
            [
                {"id": key, "channel_id": key, "knowledge_space_id": "10", "user_id": 7}
                for key in ("own", "root", "foreign")
            ],
        )
    try:
        yield engine
    finally:
        await engine.dispose()


async def snapshot(engine):
    async with engine.connect() as connection:
        return tuple(
            tuple((await connection.execute(sa.select(table))).all())
            for table in (Channel.__table__, ChannelKnowledgeSync.__table__, SpaceChannelMember.__table__)
        )


def sync_row(channel="own", **changes):
    return ChannelKnowledgeSync(channel_id=channel, knowledge_space_id="11", user_id=7, **changes)


async def test_replace_and_business_change_rollback_together_without_repository_commit(store):
    repo = ChannelReferenceBindingRepository()
    before = await snapshot(store)
    async with AsyncSession(store) as session:
        root = await repo.aget(session, "own", for_update=True)
        root.name = "changed"
        await repo.areplace_sync_rows(session, root, [sync_row(is_enabled=False)])
        await repo.asave(session, root)
        await session.rollback()
    assert await snapshot(store) == before


async def test_new_root_creator_and_configuration_are_one_external_unit(store):
    repo = ChannelReferenceBindingRepository()
    before = await snapshot(store)
    async with AsyncSession(store) as session:
        root = await repo.ainsert(session, Channel(id="new", tenant_id=101, user_id=7, name="new", visibility="public"))
        await repo.aensure_creator(session, root, binding_key="self:new:7")
        await repo.aensure_creator(session, root, binding_key="self:new:7")
        await repo.areplace_sync_rows(session, root, [sync_row("new")])
        assert len(await repo.alist_members(session, "new")) == 1
        await session.rollback()
    assert await snapshot(store) == before


async def test_exact_parent_prevents_unscoped_sync_rows_from_cross_tenant_reads(store):
    repo = ChannelReferenceBindingRepository()
    async with AsyncSession(store) as session:
        assert [row.id for row in await repo.alist_sync_rows(session, "own")] == ["own"]
        for key in ("root", "foreign"):
            assert await repo.aget(session, key) is None
            with pytest.raises(ChannelNotFoundError):
                await repo.alist_sync_rows(session, key)


async def test_delete_root_and_children_rolls_back_as_one_unit(store):
    repo = ChannelReferenceBindingRepository()
    before = await snapshot(store)
    async with AsyncSession(store) as session:
        root = await repo.aget(session, "own", for_update=True)
        await repo.adelete_channel_configuration(session, root)
        assert await repo.aget(session, "own") is None
        await session.rollback()
    assert await snapshot(store) == before


@pytest.mark.parametrize("bad", ["wrong_parent", "foreign_entity", "mutated_tenant", "bypass", "missing_context"])
async def test_write_boundary_is_not_caller_controlled(store, bad):
    repo = ChannelReferenceBindingRepository()
    before = await snapshot(store)
    async with AsyncSession(store) as session:
        root = await repo.aget(session, "own", for_update=True)
        if bad == "wrong_parent":
            with pytest.raises(ChannelNotFoundError):
                await repo.areplace_sync_rows(session, root, [sync_row("foreign")])
        elif bad == "foreign_entity":
            with pytest.raises(ChannelNotFoundError):
                await repo.asave(
                    session, Channel(id="foreign", tenant_id=101, name="fake", user_id=7, visibility="public")
                )
        elif bad == "mutated_tenant":
            root.tenant_id = 202
            with pytest.raises(ChannelNotFoundError):
                await repo.asave(session, root)
        elif bad == "bypass":
            with bypass_tenant_filter(), pytest.raises(ChannelNotFoundError):
                await repo.asave(session, root)
        else:
            token = set_current_tenant_id(None)
            try:
                with pytest.raises(ChannelNotFoundError):
                    await repo.asave(session, root)
            finally:
                current_tenant_id.reset(token)
        await session.rollback()
    assert await snapshot(store) == before


async def test_lock_refreshes_existing_identity_map_from_current_sql(store):
    repo = ChannelReferenceBindingRepository()
    async with AsyncSession(store) as session:
        root = await repo.aget(session, "own")
        await session.execute(
            sa.update(Channel)
            .where(Channel.id == "own", Channel.tenant_id == 101)
            .values(name="sql-current")
            .execution_options(synchronize_session=False)
        )
        assert root.name == "own"
        assert (await repo.aget(session, "own", for_update=True)).name == "sql-current"
