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
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


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
                {
                    "id": key,
                    "tenant_id": tenant,
                    "user_id": 7,
                    "name": key,
                    "visibility": "PUBLIC",
                    "source_list": [],
                    "filter_rules": [],
                    "is_pinned": False,
                    "is_released": False,
                }
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
        result = []
        for table in (Channel.__table__, ChannelKnowledgeSync.__table__, SpaceChannelMember.__table__):
            result.append(tuple((await connection.execute(sa.select(table))).all()))
        return tuple(result)


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
                with pytest.raises((ChannelNotFoundError, NoTenantContextError)):
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


@pytest.fixture
async def choices(store):
    async with store.begin() as conn:
        await conn.run_sync(lambda value: Knowledge.__table__.create(value))
        await conn.run_sync(lambda value: KnowledgeFile.__table__.create(value))
    async with AsyncSession(store) as session, session.begin():
        session.add_all(
            [
                Knowledge(id=ident, tenant_id=tenant, user_id=owner, name=str(ident), type=3)
                for ident, tenant, owner in ((10, 101, 7), (11, 101, 8), (20, 202, 7))
            ]
        )
        session.add(SpaceChannelMember(business_id="10", business_type="space", user_id=7, user_role="creator"))
        session.add_all(
            [
                KnowledgeFile(id=ident, tenant_id=101, knowledge_id=space, file_name=str(ident), file_type=kind)
                for ident, space, kind in ((30, 10, 0), (31, 10, 1), (32, 11, 0))
            ]
        )
    return store


@pytest.mark.parametrize(
    "space,folder,allowed",
    [
        ("10", None, True),
        ("10", "30", True),
        ("11", None, False),
        ("20", None, False),
        ("10", "31", False),
        ("10", "32", False),
        ("10", "99", False),
    ],
)
async def test_new_selections_preserve_creator_and_real_folder_parent_rules(choices, space, folder, allowed):
    repo = ChannelReferenceBindingRepository()
    async with AsyncSession(choices) as session:
        root = await repo.aget(session, "own", for_update=True)
        selections = ({"knowledge_space_id": space, "folder_id": folder},)
        if allowed:
            await repo.acheck_new_selections(session, root, user_id=7, rows=selections)
        else:
            with pytest.raises(SpacePermissionDeniedError):
                await repo.acheck_new_selections(session, root, user_id=7, rows=selections)


async def test_visibility_membership_changes_share_owner_transaction_and_rollback(store):
    repo = ChannelReferenceBindingRepository()
    async with AsyncSession(store) as session, session.begin():
        session.add_all(
            [
                SpaceChannelMember(
                    business_id="own", business_type="channel", user_id=ident, user_role=role, status=status
                )
                for ident, role, status in (
                    (7, "creator", "ACTIVE"),
                    (8, "member", "PENDING"),
                    (9, "member", "REJECTED"),
                )
            ]
        )
    before = await snapshot(store)
    async with AsyncSession(store) as session:
        root = await repo.aget(session, "own", for_update=True)
        await repo.amutate_members(session, root, activate_pending=True, remove_rejected=True)
        members = await repo.alist_members(session, root.id)
        assert {row.user_id for row in members} == {7, 8}
        assert all(row.status.value == "ACTIVE" for row in members)
        await repo.amutate_members(session, root, remove_non_creators=True)
        assert {row.user_id for row in await repo.alist_members(session, root.id)} == {7}
        await session.rollback()
    assert await snapshot(store) == before
