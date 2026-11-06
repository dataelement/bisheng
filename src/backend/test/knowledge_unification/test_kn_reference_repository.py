"""Knowledge model business writes use the caller's SQL transaction and C3.

覆盖 AC: AC-74, AC-79, AC-83, AC-87, AC-88, AC-89. SQLite proves native
sync/async persistence and rollback, not production MySQL/DM8 locks.
"""

from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository


@pytest.fixture(autouse=True)
def tenant():
    token = set_current_tenant_id(101)
    visible = set_visible_tenant_ids(frozenset({101, 1}))
    yield
    visible_tenant_ids.reset(visible)
    current_tenant_id.reset(token)


@pytest.fixture
async def store(tmp_path, monkeypatch):
    names = tenant_filter._tenant_aware_tables | {"knowledge"}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()
    path = tmp_path / "knowledge.db"
    sync = sa.create_engine(f"sqlite:///{path}")
    Knowledge.__table__.create(sync)
    with Session(sync) as session:
        with bypass_tenant_filter():
            session.add_all(
                [
                    Knowledge(
                        id=ident,
                        tenant_id=tenant,
                        user_id=7,
                        name=str(ident),
                        type=kind,
                        model="11",
                        model_config_revision=4,
                        index_generation="generation-4",
                    )
                    for ident, tenant, kind in (
                        (10, 101, 3),
                        (11, 101, 3),
                        (12, 101, 1),
                        (13, 101, 0),
                        (20, 202, 3),
                        (30, 1, 3),
                    )
                ]
            )
            session.commit()
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        yield sync, async_engine
    finally:
        await async_engine.dispose()
        sync.dispose()


def rows(sync):
    with sync.connect() as conn:
        return conn.execute(sa.select(Knowledge.__table__).order_by(Knowledge.id)).mappings().all()


def stage():
    return {"schema_version": 1, "operation_id": "change-1", "current_model_id": "11", "pending_model_id": "12"}


def test_native_insert_model_change_and_delete_share_external_rollback(store):
    sync, _ = store
    before = rows(sync)
    repo = KnowledgeModelReferenceRepository()
    with Session(sync) as session:
        new = repo.insert(session, Knowledge(tenant_id=101, user_id=7, name="new", model="11", type=3))
        assert new.id is not None
        row = repo.get(session, 10, for_update=True)
        repo.apply_model_configuration(
            session,
            row,
            model="11",
            transition=stage(),
            expected_revision=4,
            expected_generation="generation-4",
            new_generation="generation-5",
        )
        assert row.model == "11" and row.model_transition == stage() and row.model_config_revision == 5
        repo.delete(session, repo.get(session, 12, for_update=True))
        session.rollback()
    assert rows(sync) == before


async def test_native_async_operations_are_equivalent_and_do_not_commit(store):
    sync, engine = store
    before = rows(sync)
    repo = KnowledgeModelReferenceRepository()
    async with AsyncSession(engine) as session:
        new = await repo.ainsert(session, Knowledge(tenant_id=101, user_id=7, name="new", model="11", type=3))
        assert new.id is not None
        row = await repo.aget(session, 10, for_update=True)
        await repo.aapply_model_configuration(
            session,
            row,
            model="11",
            transition=stage(),
            expected_revision=4,
            expected_generation="generation-4",
            new_generation="generation-5",
        )
        assert row.model_transition == stage() and row.model_config_revision == 5
        await repo.adelete(session, await repo.aget(session, 12, for_update=True))
        await session.rollback()
    assert rows(sync) == before


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_owned_reads_are_strict_and_space_inventory_is_complete_stable_and_tenant_local(store, mode):
    sync, engine = store
    repo = KnowledgeModelReferenceRepository()
    if mode == "sync":
        with Session(sync) as session:
            assert repo.get(session, 20) is None and repo.get(session, 30) is None
            assert [row.id for row in repo.list_spaces(session, for_update=True)] == [10, 11]
    else:
        async with AsyncSession(engine) as session:
            assert await repo.aget(session, 20) is None and await repo.aget(session, 30) is None
            assert [row.id for row in await repo.alist_spaces(session, for_update=True)] == [10, 11]


@pytest.mark.parametrize("revision,generation", [(3, "generation-4"), (4, "different")])
async def test_revision_and_generation_cas_mismatch_are_zero_writes(store, revision, generation):
    sync, engine = store
    before = rows(sync)
    repo = KnowledgeModelReferenceRepository()
    async with AsyncSession(engine) as session:
        row = await repo.aget(session, 10, for_update=True)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aapply_model_configuration(
                session,
                row,
                model="12",
                transition=None,
                expected_revision=revision,
                expected_generation=generation,
                new_generation="generation-5",
            )
        await session.rollback()
    assert rows(sync) == before


async def test_metadata_write_does_not_advance_model_revision_or_generation(store):
    _, engine = store
    repo = KnowledgeModelReferenceRepository()
    async with AsyncSession(engine) as session, session.begin():
        row = await repo.aget(session, 10, for_update=True)
        row.description = "metadata only"
        await repo.asave(session, row)
        assert (row.model_config_revision, row.index_generation) == (4, "generation-4")


@pytest.mark.parametrize("bad", ["other_session", "changed_tenant", "changed_id", "bypass"])
async def test_persistent_identity_and_write_tenant_cannot_be_forged(store, bad):
    sync, engine = store
    before = rows(sync)
    repo = KnowledgeModelReferenceRepository()
    async with AsyncSession(engine) as session, AsyncSession(engine) as other:
        row = await repo.aget(session, 10, for_update=True)
        if bad == "changed_tenant":
            row.tenant_id = 202
        if bad == "changed_id":
            row.id = 20
        with bypass_tenant_filter() if bad == "bypass" else _unchanged():
            with pytest.raises(ResourceReferenceInvalidError):
                await repo.asave(other if bad == "other_session" else session, row)
        await session.rollback()
    assert rows(sync) == before


@contextmanager
def _unchanged():
    yield


async def test_database_cas_rejects_a_stale_identity_map_even_for_same_model_request(store):
    sync, engine = store
    before = rows(sync)
    repo = KnowledgeModelReferenceRepository()
    async with AsyncSession(engine) as session:
        row = await repo.aget(session, 10)
        await session.execute(
            sa.update(Knowledge)
            .where(Knowledge.id == 10, Knowledge.tenant_id == 101)
            .values(model_config_revision=5)
            .execution_options(synchronize_session=False)
        )
        assert row.model_config_revision == 4
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aapply_model_configuration(
                session,
                row,
                model="11",
                transition=None,
                expected_revision=4,
                expected_generation="generation-4",
                new_generation="generation-5",
            )
        await session.rollback()
    assert rows(sync) == before
