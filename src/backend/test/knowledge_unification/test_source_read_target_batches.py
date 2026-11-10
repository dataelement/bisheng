"""T958 native scalar batches retain source authority and exact deletion facts.

覆盖 AC: AC-37, AC-43, AC-68, AC-83, AC-85, AC-89, AC-91, AC-92
SQLite checks emitted SQL and results, not MySQL/DM8 physical lock scheduling.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import event, literal, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.repositories.source_read_target_repository import ModelSourceReadTargetRepository
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.resource_reference_tombstone import (
    ResourceReferenceTombstone as Tombstone,
)
from test.knowledge_unification import test_source_read_target_scale as scale

owner_tenant = scale.owner_tenant
knowledge_read_context = scale.knowledge_read_context
model_read_context = scale.model_read_context
PATHS = [("knowledge_file", False), ("model", False), ("model", True)]


async def read(ctx, kind, synchronous, session, keys, *, before=None):
    if synchronous:
        verifier = SourceReadVerifier({"assistant": scale.SyncConfigurationOwner()}, scale.SyncIdentity())
        repository = ModelSourceReadTargetRepository(verifier)

        def run(native):
            scope = verifier.issue_scope(native, scale.knowledge.REQUEST, ctx.identity)
            if before:
                before(native)
            return repository.lock_targets(native, scope, keys, identity=ctx.identity)

        return await session.run_sync(run)
    repository = ctx.model.repository if kind == "model" else ctx.knowledge.repository
    scope = await ctx.verifier.aissue_scope(session, scale.knowledge.REQUEST, ctx.identity)
    if before:
        await session.run_sync(before)
    return await repository.alock_targets(session, scope, keys, identity=ctx.identity)


@contextmanager
def observe(session, listener):
    event.listen(session.sync_session, "do_orm_execute", listener)
    try:
        yield
    finally:
        event.remove(session.sync_session, "do_orm_execute", listener)


def tombstone_columns():
    return (
        Tombstone.operation_id,
        Tombstone.stage,
        Tombstone.target_type,
        Tombstone.target_id,
        Tombstone.target_tenant_id,
        Tombstone.tenant_id,
    )


@pytest.mark.parametrize("kind,synchronous", PATHS)
async def test_real_batches_lock_business_numerically_then_tombstones_globally_lexically(
    model_read_context, kind, synchronous
):
    ctx = model_read_context
    ids = (2, *range(1000, 1201))
    keys = tuple(TargetKey(kind, ident) for ident in reversed(ids))
    refs = tuple(scale.knowledge.spec(kind, key.target_id) for key in keys)
    await scale.knowledge.configure(ctx, refs, cached_spaces=dict.fromkeys(keys, "1") if kind != "model" else {})
    async with AsyncSession(ctx.engine) as session, session.begin():
        if kind == "model":
            session.add_all(
                LLMModel(id=i, tenant_id=101, server_id=1, name=str(i), model_name=str(i), model_type="llm")
                for i in ids
            )
        else:
            session.add(Knowledge(id=1, tenant_id=101, user_id=7, name="parent", type=3))
            session.add_all(KnowledgeFile(id=i, tenant_id=101, knowledge_id=1, file_name=str(i)) for i in ids)
    await scale.knowledge.tombstone(ctx, keys[0], "deleting")
    await scale.knowledge.tombstone(ctx, keys[0], "deleted", tenant_id=202)
    await scale.knowledge.tombstone(
        ctx, TargetKey("knowledge_space" if kind == "model" else "model", keys[0].target_id), "deleted"
    )
    locks, tombstone_ids = [], []

    def record(state):
        if not state.is_select or state.statement._for_update_arg is None:
            return
        statement = state.statement
        entities = {item.get("entity") for item in statement.column_descriptions}
        business = entities & {Knowledge, KnowledgeFile, LLMModel, LLMServer}
        if business:
            assert len(business) == 1
            model = next(iter(business))
            locks.append(model)
            batches = [value for value in statement.compile().params.values() if isinstance(value, list)]
            batch = max(batches, key=len)
            assert len(batch) <= 200 and batch == sorted(batch)
        if Tombstone in entities:
            assert tuple(str(c) for c in statement._order_by_clauses) == (
                "resource_reference_tombstone.target_type",
                "resource_reference_tombstone.target_id",
                "resource_reference_tombstone.target_tenant_id",
            )
            batches = [value for value in statement.compile().params.values() if isinstance(value, list)]
            assert sum(map(len, batches)) <= 200
            tombstone_ids.extend(item for batch in batches for item in batch)
        if business or Tombstone in entities:
            assert all(item["expr"] is not item.get("entity") for item in statement.column_descriptions)

    async with AsyncSession(ctx.engine) as session:
        with observe(session, record):
            result = await read(ctx, kind, synchronous, session, keys)
        rows = result.observations if kind == "model" else result
        assert tuple(int(row.key.target_id) for row in rows) == ids
        assert next(row for row in rows if row.key == keys[0]).deletion.stage == "deleting"
        assert not session.sync_session.identity_map and not session.new and not session.dirty
    expected = sorted(str(i) for i in ids)
    if kind != "model":
        expected.append("1")
    assert tombstone_ids == expected
    assert locks == ([LLMServer, LLMModel, LLMModel] if kind == "model" else [Knowledge, KnowledgeFile, KnowledgeFile])


@pytest.mark.parametrize("kind,synchronous", PATHS)
@pytest.mark.parametrize("corruption", ["extra", "duplicate", "tenant", "noncanonical_id"])
async def test_native_scalar_tombstone_transport_rejects_unexpected_duplicate_or_wrong_tenant(
    model_read_context, kind, synchronous, corruption
):
    ctx = model_read_context
    keys, _ = await scale.prepare(ctx, kind, 1)
    await scale.knowledge.tombstone(ctx, TargetKey(kind, 999999), "deleted")

    def corrupt(state):
        if state.is_select and "FROM resource_reference_tombstone" in str(state.statement):
            statement = select(*tombstone_columns())
            if corruption == "duplicate":
                alias = Tombstone.__table__.alias("duplicate_transport")
                statement = statement.join(alias, alias.c.tenant_id == Tombstone.tenant_id)
            elif corruption == "tenant":
                statement = select(*tombstone_columns()[:-1], literal(202).label("tenant_id"))
            elif corruption == "noncanonical_id":
                columns = tombstone_columns()
                statement = select(*columns[:3], literal(f"0{keys[0].target_id}").label("target_id"), *columns[4:])
                statement = statement.where(Tombstone.target_type == kind, Tombstone.target_id == keys[0].target_id)
            state.statement = statement.with_for_update()

    async with AsyncSession(ctx.engine) as session:
        with observe(session, corrupt), pytest.raises(ResourceReferenceInvalidError) as failure:
            await read(ctx, kind, synchronous, session, keys)
        assert "tombstone_result_invalid" in failure.value.kwargs["reason"]
        assert not session.sync_session.identity_map and not session.new and not session.dirty


@pytest.mark.parametrize("kind,synchronous", PATHS)
async def test_missing_original_owner_performs_no_tombstone_lookup(model_read_context, kind, synchronous):
    ctx, key = model_read_context, TargetKey(kind, 999999)
    await scale.knowledge.configure(
        ctx,
        (scale.knowledge.spec(kind, key.target_id),),
        cached_owners={key: None},
        legacy={key: ("run-original", "target-proof")},
    )
    await scale.knowledge.tombstone(ctx, key, "deleted")
    queries = []

    def record(state):
        if state.is_select and "FROM resource_reference_tombstone" in str(state.statement):
            queries.append(state.statement)

    async with AsyncSession(ctx.engine) as session:
        with observe(session, record):
            result = await read(ctx, kind, synchronous, session, (key,))
        row = (result.observations if kind == "model" else result)[0]
        assert not row.exists and row.target_tenant_id is None and row.deletion is None
        assert not queries and not session.sync_session.identity_map


@pytest.mark.parametrize("kind,synchronous", PATHS)
@pytest.mark.parametrize("invalid", ["unselected", "credential", "transaction"])
async def test_invalid_scope_is_refused_before_any_target_select(model_read_context, kind, synchronous, invalid):
    ctx = model_read_context
    keys, _ = await scale.prepare(ctx, kind, 1)
    if invalid == "unselected":
        keys = (TargetKey(kind, 999999),)
    queries = []

    def record(state):
        if state.is_select:
            entities = {item.get("entity") for item in state.statement.column_descriptions}
            if entities & {Knowledge, KnowledgeFile, LLMModel, LLMServer, Tombstone}:
                queries.append(state.statement)

    def change(native):
        if invalid == "credential":
            ctx.identity.credential = "changed"
        elif invalid == "transaction":
            native.commit()
            native.begin()

    async with AsyncSession(ctx.engine) as session:
        with observe(session, record), pytest.raises(ResourceReferenceInvalidError):
            await read(ctx, kind, synchronous, session, keys, before=change)
        assert not queries and not session.sync_session.identity_map


@pytest.mark.parametrize("kind,synchronous", PATHS)
@pytest.mark.parametrize("conflicting", [False, True])
async def test_saved_bucket_keeps_native_first_slot_and_rejects_one_conflicting_slot(
    model_read_context, kind, synchronous, conflicting
):
    from sqlalchemy import update

    from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference

    ctx = model_read_context
    keys, _ = await scale.prepare(ctx, kind, 2)
    if conflicting:
        async with AsyncSession(ctx.engine) as session, session.begin():
            await session.execute(
                update(BusinessResourceReference)
                .where(BusinessResourceReference.slot_key == f"slot-{keys[0].target_id}-2")
                .values(legacy_invalid_reason="target_missing", legacy_run_id="run", legacy_evidence_key="proof")
            )
    async with AsyncSession(ctx.engine) as session:
        if conflicting:
            with pytest.raises(ResourceReferenceInvalidError) as failure:
                await read(ctx, kind, synchronous, session, keys)
            assert failure.value.kwargs["reason"] == "reference_original_evidence_conflict"
        else:
            result = await read(ctx, kind, synchronous, session, keys)
            rows = result.observations if kind == "model" else result
            assert tuple(row.original.slot_key for row in rows) == tuple(f"slot-{key.target_id}-0" for key in keys)
        assert not session.sync_session.identity_map and not session.new and not session.dirty


async def test_saved_knowledge_same_numeric_id_keeps_complete_type_buckets(model_read_context):
    ctx = model_read_context
    keys = (TargetKey("knowledge_space", 1), TargetKey("knowledge_file", 1))
    refs = tuple(
        scale.knowledge.spec(key.target_type, key.target_id, f"{key.target_type.value}-{slot}")
        for key in keys
        for slot in ("z", "a", "m")
    )
    await scale.knowledge.configure(ctx, refs, cached_spaces={keys[0]: "1", keys[1]: "2"})
    async with AsyncSession(ctx.engine) as session, session.begin():
        session.add_all([Knowledge(id=i, tenant_id=101, user_id=7, name=str(i), type=3) for i in (1, 2)])
        session.add(KnowledgeFile(id=1, tenant_id=101, knowledge_id=2, file_name="same-id"))
    async with AsyncSession(ctx.engine) as session:
        rows = await read(ctx, "knowledge_file", False, session, keys)
        assert tuple(row.original.slot_key for row in rows) == ("knowledge_space-a", "knowledge_file-a")
        assert tuple(row.target_space_id for row in rows) == ("1", "2")
        assert not session.sync_session.identity_map


@pytest.mark.parametrize("synchronous", [False, True])
async def test_root_inherited_defaults_keep_scalar_topology_and_all_five_config_keys(model_read_context, synchronous):
    import json

    from bisheng.database.models.tenant import Tenant
    from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
    from bisheng.llm.domain.repositories.reference_target_repository import DEFAULT_SCHEMAS

    ctx, key = model_read_context, TargetKey("model", 22)
    await scale.knowledge.configure(ctx, (scale.knowledge.spec("model", 22),), cached_owners={key: 1})
    async with AsyncSession(ctx.engine) as session, session.begin():
        session.add(
            TenantSystemModelConfig(
                tenant_id=1, key="assistant_llm", value=json.dumps({"llm_list": [{"model_id": 22, "default": True}]})
            )
        )
    locks = []

    def record(state):
        if not state.is_select or state.statement._for_update_arg is None:
            return
        entities = {item.get("entity") for item in state.statement.column_descriptions}
        for model in (LLMServer, LLMModel, Tenant, TenantSystemModelConfig):
            if model in entities:
                locks.append(model)
                assert all(item["expr"] is not item.get("entity") for item in state.statement.column_descriptions)
        if TenantSystemModelConfig in entities:
            assert list(DEFAULT_SCHEMAS) in state.statement.compile().params.values()

    async with AsyncSession(ctx.engine) as session:
        with observe(session, record):
            result = await read(ctx, "model", synchronous, session, (key,))
        assert result.inherited_server_ids == frozenset({2})
        assert result.observations[0].exists and result.observations[0].target_tenant_id == 1
        assert not session.sync_session.identity_map
    assert locks == [LLMServer, LLMModel, Tenant, TenantSystemModelConfig]
