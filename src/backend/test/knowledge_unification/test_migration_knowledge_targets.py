"""T703: true global PK facts distinguish absence from filtered business rows."""

import importlib
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    get_current_tenant_id,
    is_strict_tenant_filter,
    is_tenant_filter_bypassed,
    set_current_tenant_id,
)
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey

SOURCE = SourceKey(101, "assistant", "original-assistant", "current")


@pytest.fixture
def repo():
    return importlib.import_module(
        "bisheng.knowledge.domain.repositories.unification_target_repository"
    ).KnowledgeMigrationTargetRepository()


@pytest.fixture
async def storage(monkeypatch):
    models = (Knowledge, KnowledgeFile, LLMModel, LLMServer)
    names = {model.__tablename__ for model in models}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    token = set_current_tenant_id(101)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: SQLModel.metadata.create_all(conn, tables=[model.__table__ for model in models])
            )
        yield engine
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


def queries(session):
    observed = []

    def record(state):
        if state.is_select:
            observed.append(
                (state.statement, get_current_tenant_id(), is_tenant_filter_bypassed(), is_strict_tenant_filter())
            )

    event.listen(session.sync_session, "do_orm_execute", record)
    return observed


def corrupt_target(kind, value):
    target = object.__new__(TargetKey)
    object.__setattr__(target, "target_type", kind)
    object.__setattr__(target, "target_id", value)
    return target


async def test_exact_physical_rows_keep_foreign_qa_retired_folder_missing_and_broken_parent_distinct(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        for ident, tenant, kind in ((10, 101, 0), (11, 101, 1), (12, 101, 2), (13, 101, 3), (20, 202, 3)):
            session.add(
                Knowledge(
                    id=ident,
                    tenant_id=tenant,
                    user_id=7,
                    name="private-name",
                    type=kind,
                    model="private-model",
                    processing_defaults={"secret": "do-not-read"},
                )
            )
        for ident, tenant, parent, kind in (
            (100, 101, 10, 1),
            (101, 101, 13, 0),
            (102, 202, 20, 1),
            (103, 101, 999, 1),
            (104, 101, 20, 1),
            (105, 202, 13, 1),
        ):
            session.add(
                KnowledgeFile(
                    id=ident,
                    tenant_id=tenant,
                    knowledge_id=parent,
                    file_type=kind,
                    file_name="private-file-name",
                    object_name="private-object",
                )
            )
        await session.flush()
        targets = tuple(TargetKey("knowledge_space", ident) for ident in (10, 11, 12, 13, 20, 999)) + tuple(
            TargetKey("knowledge_file", ident) for ident in (100, 101, 102, 103, 104, 105, 999)
        )
        observed = queries(session)
        facts = await repo.ainspect(session, source_key=SOURCE, targets=targets)
        assert tuple(row.key for row in facts) == targets
        by = {(row.key.target_type.value, row.key.target_id): row for row in facts}
        assert [by["knowledge_space", str(i)].knowledge_type for i in (10, 11, 12, 13)] == [0, 1, 2, 3]
        assert by["knowledge_space", "20"].exists and by["knowledge_space", "20"].target_tenant_id == 202
        assert by["knowledge_file", "101"].exists and by["knowledge_file", "101"].file_type == 0
        assert by["knowledge_file", "102"].target_tenant_id == by["knowledge_file", "102"].space_tenant_id == 202
        missing_parent = by["knowledge_file", "103"]
        assert missing_parent.exists and missing_parent.knowledge_id == 999 and not missing_parent.space_exists
        assert missing_parent.space_tenant_id is missing_parent.knowledge_type is None
        assert by["knowledge_file", "104"].space_exists and by["knowledge_file", "104"].space_tenant_id == 202
        assert (
            by["knowledge_file", "105"].target_tenant_id == 202 and by["knowledge_file", "105"].space_tenant_id == 101
        )
        for kind in ("knowledge_space", "knowledge_file"):
            assert not by[kind, "999"].exists and by[kind, "999"].target_tenant_id is None
        assert by["knowledge_space", "999"].knowledge_id == 999
        assert by["knowledge_file", "999"].knowledge_id is None
        assert len(observed) <= 2 and all(current == 101 and cross and strict for _, current, cross, strict in observed)
        assert all("private" not in repr(row) and len(row.revision_digest) == 64 for row in facts)
        assert not is_tenant_filter_bypassed() and not is_strict_tenant_filter()
        assert all("object_name" not in str(q) and "processing_defaults" not in str(q) for q, *_ in observed)


async def test_mixed_200_exact_pk_batch_is_constant_queries_preserves_first_order_and_no_cartesian(repo, storage):
    targets = tuple(TargetKey("knowledge_file" if i % 2 else "knowledge_space", i + 1) for i in range(200))
    async with AsyncSession(storage) as session, session.begin():
        observed = queries(session)
        facts = await repo.ainspect(session, source_key=SOURCE, targets=(*targets, targets[0], targets[-1]))
        assert tuple(row.key for row in facts) == targets and all(not row.exists for row in facts)
        assert len(observed) <= 2
        for query, *_ in observed:
            assert query._offset_clause is None and len(query.get_final_froms()) == 1
            assert " IN " in str(query) and all(
                len(value) <= 200 for value in query.compile().params.values() if isinstance(value, list)
            )


async def test_facts_are_closed_frozen_scalars_and_digest_tracks_related_revision_without_raw_config(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        row = Knowledge(
            id=10, tenant_id=101, name="not-in-fact", type=3, model_config_revision=1, index_generation="g1"
        )
        session.add(row)
        await session.flush()
        keys = (TargetKey("knowledge_space", 10),)
        first = (await repo.ainspect(session, source_key=SOURCE, targets=keys))[0]
        assert [item.name for item in fields(first)] == [
            "key",
            "exists",
            "target_tenant_id",
            "knowledge_id",
            "knowledge_type",
            "file_type",
            "space_exists",
            "space_tenant_id",
            "revision_digest",
        ]
        assert not hasattr(first, "__dict__")
        with pytest.raises(FrozenInstanceError):
            first.exists = False
        row.model_config_revision += 1
        await session.flush()
        second = (await repo.ainspect(session, source_key=SOURCE, targets=keys))[0]
        assert first.revision_digest != second.revision_digest
        await session.execute(
            update(Knowledge)
            .where(Knowledge.id == 10)
            .values(update_time=datetime(2026, 1, 1) + timedelta(seconds=1), index_generation="g2")
        )
        third = (await repo.ainspect(session, source_key=SOURCE, targets=keys))[0]
        assert third.revision_digest != second.revision_digest


async def test_pending_writes_and_scope_survive_reads_and_empty_batch_has_zero_queries(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        pending = Knowledge(name="caller-pending", type=0)
        session.add(pending)
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        observed = queries(session)
        assert await repo.ainspect(session, source_key=SOURCE, targets=()) == () and not observed
        assert not (await repo.ainspect(session, source_key=SOURCE, targets=(TargetKey("knowledge_space", 999),)))[
            0
        ].exists
        assert pending in session.new and pending.tenant_id is None and not flushes
        assert not is_tenant_filter_bypassed() and get_current_tenant_id() == 101


@pytest.mark.parametrize(
    "change", ["source", "source_type", "container", "target_type", "bool_id", "negative_id", "batch"]
)
async def test_invalid_input_is_rejected_before_sql(repo, storage, change):
    source, targets = SOURCE, (TargetKey("knowledge_space", 10),)
    if change == "source":
        source = SourceKey(202, "assistant", "outside", "current")
    elif change == "source_type":
        source = {"tenant_id": 101}
    elif change == "container":
        targets = list(targets)
    elif change == "target_type":
        targets = (TargetKey("model", 1),)
    elif change == "bool_id":
        targets = (corrupt_target("knowledge_space", True),)
    elif change == "negative_id":
        targets = (corrupt_target("knowledge_space", "-1"),)
    else:
        targets = tuple(TargetKey("knowledge_space", i + 1) for i in range(201))
    async with AsyncSession(storage) as session, session.begin():
        observed = queries(session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.ainspect(session, source_key=source, targets=targets)
        assert not observed and not is_tenant_filter_bypassed()


async def test_native_transaction_concrete_tenant_and_nonbypass_are_required_even_for_empty(repo, storage):
    for session in (object(), AsyncSession(storage)):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.ainspect(session, source_key=SOURCE, targets=())
        if isinstance(session, AsyncSession):
            await session.close()
    async with AsyncSession(storage) as session, session.begin():
        observed = queries(session)
        with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.ainspect(session, source_key=SOURCE, targets=())
        token = set_current_tenant_id(None)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.ainspect(session, source_key=SOURCE, targets=())
        finally:
            current_tenant_id.reset(token)
        assert not observed


async def test_real_sql_failure_is_never_reclassified_as_missing_and_restores_scope(repo, storage):
    async with storage.begin() as connection:
        await connection.run_sync(lambda conn: Knowledge.__table__.drop(conn))
    async with AsyncSession(storage) as session, session.begin():
        with pytest.raises(SQLAlchemyError):
            await repo.ainspect(session, source_key=SOURCE, targets=(TargetKey("knowledge_space", 10),))
        assert get_current_tenant_id() == 101
        assert not is_tenant_filter_bypassed() and not is_strict_tenant_filter()
        await session.rollback()
