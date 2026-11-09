"""§123: real Owner receipts and existing RRT evidence in the caller's SP."""

import importlib
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, management_tenant_scope
from bisheng.core.database import tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.permission.application.identity import PermissionActor
from bisheng.resource_reference.application.contracts import ReferenceState, TargetKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet as Source
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as BRR
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone as RRT
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_model_reference_owner as original

model_owner_tenant = original.model_owner_tenant
NOW = datetime(2026, 11, 9, 12, 30, 45, 987654)
ACTOR = PermissionActor(user_id=7, tenant_id=101)


@pytest.fixture
async def built(monkeypatch):
    engine = await original.async_database()
    names = {
        "knowledge",
        "knowledge_file",
        "business_reference_set",
        "business_resource_reference",
        "resource_reference_tombstone",
    }
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: [
                table.create(sync, checkfirst=True)
                for table in (
                    Knowledge.__table__,
                    KnowledgeFile.__table__,
                    Source.__table__,
                    BRR.__table__,
                    RRT.__table__,
                )
            ]
        )
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session, session.begin():
        session.add_all(
            [
                Knowledge(id=1, tenant_id=101, user_id=7, name="one", type=3),
                Knowledge(id=2, tenant_id=101, user_id=7, name="two", type=3),
                KnowledgeFile(id=8, tenant_id=101, user_id=7, knowledge_id=1, file_name="file", file_type=1),
                KnowledgeFile(id=9, tenant_id=101, user_id=7, knowledge_id=1, file_name="folder", file_type=0),
                LLMServer(id=5, tenant_id=101, name="empty", type="openai"),
            ]
        )
        for tenant, target, owner in ((101, "11", 101), (101, "22", 1), (202, "22", 1)):
            session.add(
                Source(
                    tenant_id=tenant,
                    source_type="assistant",
                    source_id=f"private-{tenant}-{target}",
                    source_version="current",
                    source_revision=3,
                    extractor_version="native",
                    digest="a" * 64,
                    ready=True,
                    effective=True,
                )
            )
            session.add(
                BRR(
                    tenant_id=tenant,
                    source_type="assistant",
                    source_id=f"private-{tenant}-{target}",
                    source_version="current",
                    source_revision=3,
                    slot_key="model",
                    target_type="model",
                    target_id=target,
                    target_tenant_id=owner,
                )
            )
    owner = KnowledgeReferenceTargetOwner()
    verifier = ReferenceTargetVerifier(
        {"model": ModelReferenceTargetOwner(), "knowledge_space": owner, "knowledge_file": owner}
    )
    references = ReferenceRepository(verifier=verifier)
    result = SimpleNamespace(engine=engine, sessions=sessions, verifier=verifier, references=references, clock=[NOW])
    yield result
    await engine.dispose()


def runtime(built):
    module = importlib.import_module("bisheng.resource_reference.domain.repositories.target_deletion_repository")
    repository = module.TargetDeletionRepository(built.references, clock=lambda: built.clock[0])
    return ReferenceBindingRuntime(built.references, built.verifier, target_deletions=repository)


async def caller(session):
    await session.execute(update(Tenant).where(Tenant.id == 101).values(tenant_name="outer unrelated write"))


async def receipts(built, session, *keys):
    return await built.verifier.averify_owner_targets(
        session, tuple(TargetKey(kind, str(ident)) for kind, ident in keys)
    )


async def rows(session):
    with bypass_tenant_filter():
        return tuple(dict(row) for row in (await session.execute(select(RRT.__table__).order_by(RRT.id))).mappings())


async def source_bytes(session):
    with bypass_tenant_filter():
        snapshots = [
            tuple(dict(row) for row in (await session.execute(select(table).order_by(table.c.id))).mappings())
            for table in (Source.__table__, BRR.__table__)
        ]
    return json.dumps(snapshots, sort_keys=True, default=str)


def count_sql(engine):
    statements = []

    def capture(_conn, _cursor, sql, params, _context, many):
        statements.append((sql, params, many))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    return statements, lambda: event.remove(engine.sync_engine, "before_cursor_execute", capture)


def no_source_sql(statements):
    assert not any("business_reference_set" in sql or "business_resource_reference" in sql for sql, _, _ in statements)


async def test_actual_owner_and_source_snapshot_remain_a_working_control(built):
    async with built.sessions() as session, session.begin():
        result = await receipts(built, session, ("model", 11), ("knowledge_space", 1), ("knowledge_file", 8))
        scope = built.references.target_owner_scope(session, result)
        assert len(scope.targets) == 3 and all(item.target.state == ReferenceState.VALID for item in result)
        assert len(json.loads(await source_bytes(session))) == 2 and await rows(session) == ()


@pytest.mark.parametrize(
    "keys,operation",
    [
        ((("model", 11),), "model_delete_server"),
        ((("model", 11),), "model_update_server"),
        ((("knowledge_file", 8),), "knowledge_file_delete"),
        ((("knowledge_file", 8),), "knowledge_space_clear"),
        ((("knowledge_space", 1), ("knowledge_file", 8)), "knowledge_space_delete"),
    ],
)
async def test_native_prepare_business_delete_finalize_and_fresh_owner_invalid_deleted(built, keys, operation):
    rt = runtime(built)
    async with built.sessions() as session:
        await caller(session)
        before = await source_bytes(session)
        async with session.begin_nested():
            issued = await receipts(built, session, *keys)
            arguments = {
                "receipts": issued,
                "operation_id": "native-delete",
                "operation_type": operation,
                "actor": ACTOR,
            }
            statements, stop = count_sql(built.engine)
            try:
                assert await rt.aprepare_target_deletion(session, **arguments) == len(keys)
                assert await rt.aprepare_target_deletion(session, **arguments) == 0
            finally:
                stop()
            no_source_sql(statements)
            prepared = await rows(session)
            assert all(row["stage"] == "deleting" and row["deleted_at"] is None for row in prepared)
            assert all(row["create_time"] == NOW.replace(microsecond=0) for row in prepared)
            if keys[0][0] == "model":
                await session.execute(delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
            else:
                await session.execute(
                    delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == 1, KnowledgeFile.tenant_id == 101)
                )
                if operation == "knowledge_space_delete":
                    await session.execute(delete(Knowledge).where(Knowledge.id == 1, Knowledge.tenant_id == 101))
            built.clock[0] = NOW.replace(hour=13)
            statements, stop = count_sql(built.engine)
            try:
                assert await rt.afinalize_target_deletion(session, **arguments) == len(keys)
                assert await rt.afinalize_target_deletion(session, **arguments) == 0
                assert await rt.aprepare_target_deletion(session, **arguments) == 0
            finally:
                stop()
            no_source_sql(statements)
            fresh = await receipts(built, session, *keys)
            assert all(item.target.state == ReferenceState.INVALID_DELETED for item in fresh)
            arguments["receipts"] = fresh
            final = await rows(session)
            built.clock[0] = NOW.replace(hour=14)
            assert await rt.aprepare_target_deletion(session, **arguments) == 0
            assert await rt.afinalize_target_deletion(session, **arguments) == 0
            assert await rows(session) == final
            assert all(row["deleted_at"] == NOW.replace(hour=13, microsecond=0) for row in final)
            for old, new in zip(prepared, final, strict=True):
                assert {
                    key: value for key, value in old.items() if key not in {"stage", "deleted_at", "update_time"}
                } == {key: value for key, value in new.items() if key not in {"stage", "deleted_at", "update_time"}}
        assert await source_bytes(session) == before
        await session.commit()


async def test_shared_root_deletion_keeps_both_source_tenants_and_uses_typed_subject_not_home_tenant(built):
    rt = runtime(built)
    async with built.sessions() as session:
        await caller(session)
        before = await source_bytes(session)
        with management_tenant_scope(1):
            async with session.begin_nested():
                issued = await receipts(built, session, ("model", 22))
                actor = PermissionActor(subject_type="service_account", subject_id=9, tenant_id=202)
                arguments = {
                    "receipts": issued,
                    "operation_id": "root-delete",
                    "operation_type": "model_delete_server",
                    "actor": actor,
                }
                assert await rt.aprepare_target_deletion(session, **arguments) == 1
                await session.execute(delete(LLMModel).where(LLMModel.id == 22, LLMModel.tenant_id == 1))
                assert await rt.afinalize_target_deletion(session, **arguments) == 1
                row = (await rows(session))[0]
                assert row["tenant_id"] == row["target_tenant_id"] == 1
                assert (row["actor_type"], row["actor_id"]) == ("service_account", "9")
        assert await source_bytes(session) == before


async def test_deleting_receipt_replay_can_only_advance_and_never_demote(built):
    rt = runtime(built)
    async with built.sessions() as session:
        await caller(session)
        async with session.begin_nested():
            issued = await receipts(built, session, ("model", 11))
            args = {"operation_id": "one", "operation_type": "model_delete_server", "actor": ACTOR}
            assert await rt.aprepare_target_deletion(session, receipts=issued, **args) == 1
            deleting = await receipts(built, session, ("model", 11))
            assert deleting[0].target.state == ReferenceState.DELETING
            await session.execute(delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
            assert await rt.afinalize_target_deletion(session, receipts=deleting, **args) == 1
            assert await rt.afinalize_target_deletion(session, receipts=deleting, **args) == 0
            assert await rt.aprepare_target_deletion(session, receipts=deleting, **args) == 0
            deleted = await receipts(built, session, ("model", 11))
            await session.execute(
                update(RRT).where(RRT.target_id == "11", RRT.tenant_id == 101).values(stage="deleting", deleted_at=None)
            )
            with pytest.raises(ResourceReferenceInvalidError):
                await rt.aprepare_target_deletion(session, receipts=deleted, **args)


async def test_empty_receipts_validate_context_but_never_create_a_scope_or_evidence(built):
    rt = runtime(built)
    async with built.sessions() as session:
        await caller(session)
        statements, stop = count_sql(built.engine)
        try:
            args = {
                "receipts": (),
                "operation_id": "empty-server",
                "operation_type": "model_delete_server",
                "actor": ACTOR,
            }
            assert await rt.aprepare_target_deletion(session, **args) == 0
            assert await rt.afinalize_target_deletion(session, **args) == 0
        finally:
            stop()
        assert statements == [] and await rows(session) == ()
