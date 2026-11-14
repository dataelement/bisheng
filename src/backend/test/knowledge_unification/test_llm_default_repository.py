"""T466: real default storage preserves tenant, provenance and transaction.

覆盖 AC: AC-71, AC-87, AC-88, AC-89, AC-91
"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.database.models.tenant import Tenant
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from test.knowledge_unification import test_model_reference_owner as models
from test.knowledge_unification.test_ref_repo import tenant

TABLES = [Tenant.__table__, TenantSystemModelConfig.__table__]
model_owner_tenant = models.model_owner_tenant


def seed(session):
    session.add_all(
        [
            Tenant(id=1, tenant_code="root", tenant_name="Root", share_default_to_children=1),
            Tenant(id=101, tenant_code="one", tenant_name="One", parent_tenant_id=1),
            Tenant(id=202, tenant_code="two", tenant_name="Two", parent_tenant_id=1),
            TenantSystemModelConfig(tenant_id=1, key="evaluation_llm", value='{"model_id":99}'),
            TenantSystemModelConfig(tenant_id=202, key="evaluation_llm", value='{"model_id":202}'),
        ]
    )


@pytest.fixture
def store(f118_engine, model_owner_tenant):
    for table in TABLES:
        table.create(f118_engine)
    with Session(f118_engine) as session, session.begin():
        seed(session)
    return f118_engine


@pytest.fixture
async def astore(model_owner_tenant):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        for table in TABLES:
            await conn.run_sync(lambda connection, table=table: table.create(connection))
    async with AsyncSession(engine) as session, session.begin():
        await session.run_sync(seed)
    yield engine
    await engine.dispose()


def test_sync_original_root_default_is_not_a_consumer_copy(store):
    repo = ModelDefaultRepository()
    with Session(store) as session:
        value = repo.resolve(session, "evaluation_llm")
        assert value.inherited_from_root and not value.fallback_blocked
        assert value.source.source_key.tenant_id == 1 and value.source.source_key.source_id == "evaluation_llm"
        assert value.payload_json == '{"model_id":99}' and value.own is None
        assert repo.get_own(session, "evaluation_llm") is None
        assert get_current_tenant_id() == 101 and not session.identity_map


async def test_async_own_invalid_id_remains_original_and_does_not_fall_back(astore):
    repo = ModelDefaultRepository()
    async with AsyncSession(astore) as session:
        assert await repo.alock_root(session, "evaluation_llm") is None
        await repo.aput(session, "evaluation_llm", '{"model_id":777}')
        value = await repo.aresolve(session, "evaluation_llm", for_update=True)
        assert not value.inherited_from_root and value.source.source_key.tenant_id == 101
        assert json.loads(value.payload_json)["model_id"] == 777
        assert session.in_transaction()
        await session.rollback()
    async with AsyncSession(astore) as session:
        assert (await repo.aresolve(session, "evaluation_llm")).source.tenant_id == 1


def test_sync_external_rollback_does_not_partially_save_default(store):
    repo = ModelDefaultRepository()
    with Session(store) as session:
        repo.lock_root(session, "evaluation_llm")
        repo.put(session, "evaluation_llm", '{"model_id":11}')
        assert repo.get_own(session, "evaluation_llm").tenant_id == 101
        session.rollback()
    with Session(store) as check:
        assert repo.get_own(check, "evaluation_llm") is None


async def test_restore_only_removes_leaf_override_in_callers_transaction(astore):
    repo = ModelDefaultRepository()
    async with AsyncSession(astore) as session, session.begin():
        await repo.aput(session, "evaluation_llm", '{"model_id":777}')
    async with AsyncSession(astore) as session:
        await repo.alock_root(session, "evaluation_llm")
        await repo.adelete_override(session, "evaluation_llm")
        assert (await repo.aresolve(session, "evaluation_llm")).source.tenant_id == 1
        await session.rollback()
    async with AsyncSession(astore) as session:
        assert (await repo.aget_own(session, "evaluation_llm")).tenant_id == 101
        await repo.adelete_override(session, "evaluation_llm")
        await session.commit()
    async with AsyncSession(astore) as session:
        assert (await repo.aresolve(session, "evaluation_llm")).source.tenant_id == 1
        with tenant(202):
            assert (await repo.aget_own(session, "evaluation_llm")).value == '{"model_id":202}'


@pytest.mark.parametrize("case", ["disabled_share", "wrong_parent", "missing_root"])
def test_inheritance_requires_actual_root_child_topology_and_share(store, case):
    repo = ModelDefaultRepository()
    with Session(store) as session, session.begin():
        with bypass_tenant_filter():
            root = session.get(Tenant, 1)
            child = session.get(Tenant, 101)
            if case == "disabled_share":
                root.share_default_to_children = 0
            elif case == "wrong_parent":
                child.parent_tenant_id = 202
            else:
                session.delete(root)
            session.flush()
        value = repo.resolve(session, "evaluation_llm")
        assert value.source is None and not value.inherited_from_root and value.fallback_blocked
        assert value.payload_json == "{}"


def test_valid_empty_own_json_remains_own_source_while_null_uses_root(store):
    repo = ModelDefaultRepository()
    with Session(store) as session, session.begin():
        repo.put(session, "evaluation_llm", "{}")
        value = repo.resolve(session, "evaluation_llm")
        assert value.source.tenant_id == 101 and value.payload_json == "{}" and not value.inherited_from_root


def test_reads_never_autoflush_pending_business_changes(store):
    repo = ModelDefaultRepository()
    with Session(store) as session:
        pending = TenantSystemModelConfig(tenant_id=101, key="knowledge_llm", value='{"source_model_id":11}')
        session.add(pending)
        assert repo.get_own(session, "knowledge_llm") is None and pending.id is None
        repo.resolve(session, "evaluation_llm")
        assert pending.id is None


@pytest.mark.parametrize("bad", ["workbench", "initdb_config", "arbitrary"])
def test_storage_rejects_keys_that_are_not_business_sources(store, bad):
    with Session(store) as session:
        with pytest.raises(ResourceReferenceInvalidError):
            ModelDefaultRepository().put(session, bad, '{"model_id":11}')
        assert not session.new and not session.dirty


def test_storage_does_not_write_under_bypass_or_change_another_tenant(store):
    repo = ModelDefaultRepository()
    with Session(store) as session:
        with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
            repo.put(session, "evaluation_llm", '{"model_id":11}')
        repo.put(session, "evaluation_llm", '{"model_id":11}')
        with tenant(202):
            assert repo.get_own(session, "evaluation_llm").value == '{"model_id":202}'
        session.rollback()
    with Session(store) as session:
        with bypass_tenant_filter():
            assert len(session.execute(select(TenantSystemModelConfig.id)).all()) == 2
