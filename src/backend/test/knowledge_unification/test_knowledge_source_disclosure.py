"""Actual Knowledge SQL projections and loaded-target permissions for metadata."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.application import reference_source_owner as module
from bisheng.knowledge.application.reference_source_owner import KnowledgeReferenceSourceOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    KnowledgeContainerDaoPermissionLoader,
)
from bisheng.permission.application import business_authorization
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure
from test.knowledge_unification import test_kn_reference_repository as original

store = original.store
tenant = original.tenant


def key(ident, *, tenant_id=101, version="current", kind=SourceType.KNOWLEDGE):
    return SourceKey(tenant_id, kind, str(ident), version)


@pytest.fixture
async def metadata(store, monkeypatch):
    sync, engine = store
    actor = PermissionActor(user_id=7, tenant_id=101)
    token = set_current_permission_actor(actor)
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    facts = SimpleNamespace(
        queries=[],
        checks=[],
        snapshots=[],
        allowed={10, 12, 13},
        action_error=None,
        snapshot_changes={},
        missing_snapshots=False,
    )

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def observe(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            facts.queries.append((statement, parameters))

    async def snapshots(keys):
        facts.snapshots.append(keys)
        return (
            {}
            if facts.missing_snapshots
            else {
                k: replace(
                    PermissionResourceSnapshot(*k, 3, "ctx", "CUSTOM", None, None, "CURRENT"), **facts.snapshot_changes
                )
                for k in keys
            }
        )

    async def check(received_actor, targets, action):
        assert received_actor is actor and action == "visible"
        facts.checks.append(targets)
        if facts.action_error:
            raise facts.action_error
        return tuple(int(target.resource_id) in facts.allowed for target in targets)

    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=KnowledgeContainerDaoPermissionLoader(SimpleNamespace(get_permission_snapshots=snapshots)),
        permission=SimpleNamespace(),
    )
    monkeypatch.setattr(module, "get_f048_resource_adapter", AsyncMock(return_value=adapter), raising=False)
    runtime = SimpleNamespace(batch_check_actions=check, get_permission_snapshots=snapshots)
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=runtime), raising=False)
    monkeypatch.setattr(
        business_authorization,
        "get_f048_runtime",
        AsyncMock(return_value=runtime),
    )
    try:
        yield SimpleNamespace(
            **vars(facts),
            facts=facts,
            sync=sync,
            engine=engine,
            actor=actor,
            user=user,
            owner=KnowledgeReferenceSourceOwner(),
            repository=KnowledgeModelReferenceRepository(),
        )
    finally:
        reset_current_permission_actor(token)


async def test_real_metadata_uses_actual_namespace_and_keeps_duplicates_and_hidden_positions(metadata):
    keys = (key(10), key(11), key(12), key(13), key(20, tenant_id=202), key(10))
    async with AsyncSession(metadata.engine) as session, session.begin():
        result = await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=keys)
        assert not session.new and not session.dirty and not session.deleted
    assert result == (
        SourceDisclosure(keys[0], "10", None, "/filelib/10"),
        None,
        SourceDisclosure(keys[2], "12", None, "/filelib/qalib/12"),
        SourceDisclosure(keys[3], "13", None, "/filelib/13"),
        None,
        SourceDisclosure(keys[5], "10", None, "/filelib/10"),
    )
    assert len(metadata.facts.queries) == 1
    targets = [target for batch in metadata.facts.checks for target in batch]
    assert {(t.resource_type, t.resource_id) for t in targets} == {
        ("knowledge_space", "10"),
        ("knowledge_space", "11"),
        ("knowledge_library", "12"),
        ("knowledge_library", "13"),
    }


async def test_empty_and_foreign_batches_do_not_read_or_check_any_business(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        assert await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=()) == ()
        assert await metadata.repository.aload_disclosure_sources(session, knowledge_ids=()) == ()
        assert await metadata.owner.adisclose_sources(
            session, identity=metadata.user, source_keys=(key(20, tenant_id=202), key(30, tenant_id=1))
        ) == (None, None)
    assert metadata.facts.queries == metadata.facts.checks == metadata.facts.snapshots == []


@pytest.mark.parametrize(
    "keys",
    [
        [key(10)],
        (key(10),) * 201,
        (key(10, version="old"),),
        (key(10, kind=SourceType.ASSISTANT),),
        (key(10).source_id,),
    ],
)
async def test_invalid_protocol_fails_before_business_io(metadata, keys):
    async with AsyncSession(metadata.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=keys)
    assert metadata.facts.queries == metadata.facts.checks == []


@pytest.mark.parametrize("ident", [999, 20, 77])
async def test_current_tenant_missing_foreign_id_or_retired_type_is_not_hidden(metadata, ident):
    if ident == 77:
        with Session(metadata.sync) as session:
            session.add(Knowledge(id=77, tenant_id=101, name="retired", type=2, user_id=7))
            session.commit()
    async with AsyncSession(metadata.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(ident),))
    assert metadata.facts.checks == []


async def test_metadata_projection_has_no_model_or_configuration_columns_and_cannot_lazy_load(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        rows = await metadata.repository.aload_disclosure_sources(session, knowledge_ids=(10, 12, 13))
        assert tuple(row.id for row in rows) == (10, 12, 13)
        assert all({"model", "model_transition", "description"} <= sa.inspect(row).unloaded for row in rows)
        with pytest.raises(sa.exc.InvalidRequestError):
            _ = rows[0].model
    assert len(metadata.facts.queries) == 1
    selected = metadata.facts.queries[0][0].split("FROM")[0].lower()
    assert "knowledge.model" not in selected and "description" not in selected and "config" not in selected


async def test_permission_changes_are_not_cached_and_io_errors_fail_closed(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        assert (await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(10),)))[0]
        metadata.facts.allowed.clear()
        assert await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(10),)) == (
            None,
        )
        metadata.facts.action_error = OSError("offline permission transport")
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(10),))
    assert len(metadata.facts.checks) == 3


async def test_401_actual_sources_use_three_sql_batches_and_five_permission_batches(metadata):
    with Session(metadata.sync) as session:
        session.add_all(Knowledge(id=i, tenant_id=101, name=str(i), type=3, user_id=7) for i in range(1000, 1401))
        session.commit()
    found = []
    keys = tuple(key(i) for i in range(1000, 1401))
    async with AsyncSession(metadata.engine) as session, session.begin():
        for start in range(0, len(keys), 200):
            found.extend(
                await metadata.owner.adisclose_sources(
                    session, identity=metadata.user, source_keys=keys[start : start + 200]
                )
            )
    assert found == [None] * 401
    assert len(metadata.facts.queries) == 3
    assert [len(batch) for batch in metadata.facts.checks] == [100, 100, 100, 100, 1]
    assert len(metadata.facts.snapshots) == 6  # Native preflight plus the unchanged loaded-target loader.


async def test_preloaded_clean_orm_metadata_is_refreshed_from_actual_sql(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        cached = await session.get(Knowledge, 10)
        await session.execute(sa.update(Knowledge.__table__).where(Knowledge.id == 10).values(name="current SQL name"))
        assert cached.name == "10" and not session.dirty
        result = await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(10),))
        assert result[0].name == "current SQL name"


async def test_pending_orm_source_changes_are_not_disclosed_or_discarded(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        cached = await session.get(Knowledge, 10)
        cached.name = "unflushed name"
        cached.type = 0
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(10),))
        assert cached.name == "unflushed name" and cached.type == 0 and cached in session.dirty
        await session.rollback()


async def test_pending_primary_key_changes_match_original_identity_and_remain_pending(metadata):
    async with AsyncSession(metadata.engine) as session, session.begin():
        cached = await session.get(Knowledge, 10)
        cached.id = 99
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(10),))
        assert cached.id == 99 and cached in session.dirty
        assert sa.inspect(cached).identity == (10,)
        assert sa.inspect(cached).attrs.id.history.deleted == [10]
        await session.rollback()


@pytest.mark.parametrize(
    "changes", [{"mode": "INHERIT"}, {"parent_type": "knowledge_space", "parent_id": "11"}, {"version": 0}]
)
async def test_current_invalid_permission_metadata_is_not_qualified_or_normally_hidden(metadata, changes):
    metadata.facts.snapshot_changes = changes
    async with AsyncSession(metadata.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(10),))


async def test_current_missing_permission_snapshot_is_not_normally_hidden(metadata):
    metadata.facts.missing_snapshots = True
    async with AsyncSession(metadata.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await metadata.owner.adisclose_sources(session, identity=metadata.user, source_keys=(key(10),))
