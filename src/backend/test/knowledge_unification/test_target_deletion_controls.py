"""§123 negative authority, corruption and caller-owned rollback controls."""

import asyncio
from copy import copy
from datetime import datetime

import pytest
from sqlalchemy import MetaData, delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.permission.application.identity import PermissionActor
from bisheng.resource_reference.application.contracts import LegacyEvidence, SourceKey, TargetKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from test.knowledge_unification import test_target_deletion_native as native

model_owner_tenant = native.model_owner_tenant
built = native.built


def evidence(identifier="11", **changes):
    return {
        "tenant_id": 101,
        "target_type": "model",
        "target_id": identifier,
        "target_tenant_id": 101,
        "operation_id": "same",
        "operation_type": "model_delete_server",
        "stage": "deleting",
        "actor_type": "user",
        "actor_id": "7",
        "deleted_at": None,
        "create_time": datetime(2026, 11, 9, 1),
        "update_time": datetime(2026, 11, 9, 1),
        **changes,
    }


async def run(rt, session, issued, **changes):
    return await rt.aprepare_target_deletion(
        session,
        **{
            "receipts": issued,
            "operation_id": "same",
            "operation_type": "model_delete_server",
            "actor": native.ACTOR,
            **changes,
        },
    )


@pytest.mark.parametrize(
    "key,operation",
    [
        (("knowledge_space", 1), "knowledge_space_clear"),
        (("knowledge_file", 8), "model_delete_server"),
        (("model", 11), "knowledge_file_delete"),
        (("model", 11), "force_delete"),
    ],
)
async def test_operation_target_type_is_a_closed_business_pair(built, key, operation):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        async with session.begin_nested():
            issued = await native.receipts(built, session, key)
            statements, stop = native.count_sql(built.engine)
            try:
                with pytest.raises(ResourceReferenceInvalidError):
                    await run(rt, session, issued, operation_type=operation)
            finally:
                stop()
            assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql, _, _ in statements)


@pytest.mark.parametrize("operation_id", ["", " ", "x\x00y", "x" * 65, 123])
async def test_even_empty_receipts_require_the_original_operation_shape(built, operation_id):
    async with built.sessions() as session:
        await native.caller(session)
        with pytest.raises(ResourceReferenceInvalidError):
            await run(native.runtime(built), session, (), operation_id=operation_id)
        assert await native.rows(session) == ()


@pytest.mark.parametrize("subject", [True, 0, -1])
async def test_typed_actor_does_not_accept_bool_or_audit_user_as_the_subject(built, subject):
    actor = PermissionActor(user_id=7, tenant_id=101)
    object.__setattr__(actor, "subject_id", subject)
    async with built.sessions() as session:
        await native.caller(session)
        with pytest.raises(ResourceReferenceInvalidError):
            await run(native.runtime(built), session, (), actor=actor)
        with pytest.raises(ResourceReferenceInvalidError):
            await run(native.runtime(built), session, (), actor={"user_id": 7})


@pytest.mark.parametrize("bad", ["copy", "list", "other_runtime", "nested", "foreign", "pending", "bypass"])
async def test_original_registry_scope_transaction_and_context_are_required(built, bad):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        async with session.begin_nested():
            if bad == "foreign":
                with tenant_execution_scope(202):
                    issued = await native.receipts(built, session, ("model", 33))
            else:
                issued = await native.receipts(built, session, ("model", 11))
            if bad == "copy":
                issued = (copy(issued[0]),)
            elif bad == "list":
                issued = list(issued)
            elif bad == "other_runtime":
                verifier = ReferenceTargetVerifier({"model": ModelReferenceTargetOwner()})
                rt.verifier = verifier
            elif bad == "pending":
                session.add(native.LLMModel(id=77, tenant_id=101, server_id=1, model_name="pending", model_type="llm"))
            if bad == "nested":
                async with session.begin_nested():
                    with pytest.raises(ResourceReferenceInvalidError):
                        await run(rt, session, issued)
            elif bad == "bypass":
                with bypass_tenant_filter(), pytest.raises(ResourceReferenceInvalidError):
                    await run(rt, session, issued)
            else:
                with pytest.raises(ResourceReferenceInvalidError):
                    await run(rt, session, issued)
            if bad == "pending":
                session.expunge(next(iter(session.new)))
            assert await native.rows(session) == ()


async def test_copied_owner_scope_and_expired_receipts_cannot_write(built):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        async with session.begin_nested():
            issued = await native.receipts(built, session, ("model", 11))
            scope = built.references.target_owner_scope(session, issued)
            with pytest.raises(ResourceReferenceInvalidError):
                await rt.target_deletions.aprepare(
                    session,
                    scope=copy(scope),
                    operation_id="same",
                    operation_type="model_delete_server",
                    actor=native.ACTOR,
                )
        with pytest.raises(ResourceReferenceInvalidError):
            await run(rt, session, issued)
        assert await native.rows(session) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"operation_id": "other"},
        {"operation_type": "model_update_server"},
        {"actor_type": "service_account"},
        {"actor_id": "9"},
        {"stage": "deleted", "deleted_at": None},
        {"stage": "deleting", "deleted_at": datetime(2026, 1, 1)},
        {"tenant_id": 202, "target_tenant_id": 202},
    ],
)
async def test_existing_evidence_is_validated_in_full_before_any_dml(built, changes):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        async with session.begin_nested():
            issued = await native.receipts(built, session, ("model", 11))
            # A corrupt owner pair must not be hidden by SQL/C3 predicates.
            await session.execute(native.RRT.__table__.insert(), evidence(**changes))
            before = await native.rows(session)
            statements, stop = native.count_sql(built.engine)
            try:
                with pytest.raises(ResourceReferenceInvalidError):
                    await run(rt, session, issued)
            finally:
                stop()
            assert await native.rows(session) == before
            assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql, _, _ in statements)


@pytest.mark.parametrize("column", ["tenant_id", "target_tenant_id"])
async def test_raw_null_owner_is_not_filtered_into_a_missing_row(built, column):
    # Native damaged storage shape, not an ORM/receipt double. Production DDL is unchanged.
    clone = native.RRT.__table__.to_metadata(MetaData())
    clone.c[column].nullable = True
    async with built.engine.begin() as connection:
        await connection.run_sync(native.RRT.__table__.drop)
        await connection.run_sync(clone.create)
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        async with session.begin_nested():
            issued = await native.receipts(built, session, ("model", 11))
            await session.execute(insert(native.RRT.__table__), evidence(**{column: None}))
            with pytest.raises(ResourceReferenceInvalidError):
                await run(rt, session, issued)
            assert len(await native.rows(session)) == 1


async def test_ancestor_space_evidence_cannot_mint_a_direct_file_tombstone(built):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        async with session.begin_nested():
            issued = await native.receipts(built, session, ("knowledge_space", 1))
            assert await run(rt, session, issued, operation_type="knowledge_space_delete") == 1
            file = await native.receipts(built, session, ("knowledge_file", 8))
            assert file[0].target.state == "deleting"
            with pytest.raises(ResourceReferenceInvalidError):
                await run(rt, session, file, operation_type="knowledge_space_delete")
            assert [(row["target_type"], row["target_id"]) for row in await native.rows(session)] == [
                ("knowledge_space", "1")
            ]


async def test_registered_legacy_binding_receipt_is_not_target_deletion_authority(built):
    class Ledger:
        def resolve(self, _s, _source, _target, *, run_id, evidence_key):
            return LegacyEvidence(run_id, "a" * 64, evidence_key)

        async def aresolve(self, *args, **kwargs):
            return self.resolve(*args, **kwargs)

    verifier = ReferenceTargetVerifier({"model": ModelReferenceTargetOwner(legacy_evidence=Ledger())})
    legacy = copy(built)
    legacy.verifier, legacy.references = verifier, native.ReferenceRepository(verifier=verifier)
    async with built.sessions() as session:
        await native.caller(session)
        session.add(
            native.BRR(
                tenant_id=101,
                source_type="assistant",
                source_id="legacy",
                source_version="current",
                slot_key="model",
                target_type="model",
                target_id="80",
                target_tenant_id=None,
                source_revision=1,
                legacy_invalid_reason="target_missing",
                legacy_run_id="frozen",
                legacy_evidence_key="original",
            )
        )
        await session.flush()
        async with session.begin_nested():
            issued = await verifier.averify_targets(
                session, SourceKey(101, "assistant", "legacy", "current"), (TargetKey("model", "80"),)
            )
            assert issued[0].target.state == "invalid_legacy"
            with pytest.raises(ResourceReferenceInvalidError):
                await run(native.runtime(legacy), session, issued)
            assert await native.rows(session) == ()


async def add_models(session, count):
    ids = (11, *range(1000, 1000 + count - 1))
    await session.execute(
        insert(native.LLMModel.__table__),
        [
            {"id": ident, "tenant_id": 101, "server_id": 1, "model_name": str(ident), "model_type": "llm"}
            for ident in ids[1:]
        ],
    )
    return ids


async def test_last_target_conflict_is_found_before_first_insert_batch(built):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        ids = await add_models(session, 401)
        async with session.begin_nested():
            issued = await native.receipts(built, session, *(("model", ident) for ident in ids))
            await session.execute(
                insert(native.RRT.__table__), evidence(sorted(map(str, ids))[-1], operation_id="other")
            )
            statements, stop = native.count_sql(built.engine)
            try:
                with pytest.raises(ResourceReferenceInvalidError):
                    await run(rt, session, issued)
            finally:
                stop()
            assert sum("FROM resource_reference_tombstone" in sql for sql, _, _ in statements) == 3
            assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql, _, _ in statements)


@pytest.mark.parametrize("phase", ["prepare", "finalize"])
async def test_second_native_dml_batch_failure_uses_only_the_callers_common_savepoint(built, monkeypatch, phase):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        ids = await add_models(session, 401)
        execute, batches = session.execute, []

        async def failed(statement, *args, **kwargs):
            sql = str(statement).upper()
            prefix = (
                "INSERT INTO RESOURCE_REFERENCE_TOMBSTONE"
                if phase == "prepare"
                else "UPDATE RESOURCE_REFERENCE_TOMBSTONE"
            )
            if sql.startswith(prefix):
                batches.append(1)
                if len(batches) == 2:
                    raise RuntimeError("second native RRT batch")
            return await execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", failed)
        with pytest.raises(RuntimeError):
            async with session.begin_nested():
                issued = await native.receipts(built, session, *(("model", ident) for ident in ids))
                if phase == "prepare":
                    await run(rt, session, issued)
                else:
                    assert await run(rt, session, issued) == 401
                    await session.execute(
                        delete(native.LLMModel).where(native.LLMModel.server_id == 1, native.LLMModel.tenant_id == 101)
                    )
                    await rt.afinalize_target_deletion(
                        session,
                        receipts=issued,
                        operation_id="same",
                        operation_type="model_delete_server",
                        actor=native.ACTOR,
                    )
        assert len(batches) == 2
        await session.commit()
        assert await native.rows(session) == ()
        assert (
            await session.execute(
                select(func.count()).select_from(native.LLMModel).where(native.LLMModel.server_id == 1)
            )
        ).scalar_one() == 401
        assert (
            await session.execute(select(native.Tenant.tenant_name).where(native.Tenant.id == 101))
        ).scalar_one() == "outer unrelated write"


async def test_real_task_cancellation_after_first_rrt_insert_uses_the_common_caller_savepoint(built, monkeypatch):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        ids = await add_models(session, 401)
        execute, inserted, waiting = session.execute, asyncio.Event(), asyncio.Event()

        async def stall(statement, *args, **kwargs):
            result = await execute(statement, *args, **kwargs)
            if str(statement).upper().startswith("INSERT INTO RESOURCE_REFERENCE_TOMBSTONE"):
                inserted.set()
                await waiting.wait()
            return result

        monkeypatch.setattr(session, "execute", stall)

        async def operation():
            async with session.begin_nested():
                issued = await native.receipts(built, session, *(("model", ident) for ident in ids))
                return await run(rt, session, issued)

        task = asyncio.create_task(operation())
        await asyncio.wait_for(inserted.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await session.commit()
        assert await native.rows(session) == ()
        assert (
            await session.execute(select(native.Tenant.tenant_name).where(native.Tenant.id == 101))
        ).scalar_one() == "outer unrelated write"


async def test_unknown_native_stage_and_finalize_missing_row_are_not_evidence(built):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        async with session.begin_nested():
            issued = await native.receipts(built, session, ("model", 11))
            with pytest.raises(ResourceReferenceInvalidError):
                await rt.afinalize_target_deletion(
                    session,
                    receipts=issued,
                    operation_id="same",
                    operation_type="model_delete_server",
                    actor=native.ACTOR,
                )
            await session.execute(text("PRAGMA ignore_check_constraints=ON"))
            await session.execute(insert(native.RRT.__table__), evidence(stage="unknown"))
            with pytest.raises(ResourceReferenceInvalidError):
                await run(rt, session, issued)


async def test_empty_receipts_still_require_active_native_transaction(built):
    rt = native.runtime(built)
    async with AsyncSession(built.engine) as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await run(rt, session, ())
        assert not session.in_transaction()


async def test_await_cannot_replace_positive_actor_id_with_equal_bool_alias(built, monkeypatch):
    rt = native.runtime(built)
    actor = PermissionActor(user_id=1, tenant_id=101)
    async with built.sessions() as session:
        await native.caller(session)
        execute = session.execute
        async with session.begin_nested():
            issued = await native.receipts(built, session, ("model", 11))

            async def alias(statement, *args, **kwargs):
                result = await execute(statement, *args, **kwargs)
                if "FROM resource_reference_tombstone" in str(statement):
                    object.__setattr__(actor, "subject_id", True)
                return result

            monkeypatch.setattr(session, "execute", alias)
            with pytest.raises(ResourceReferenceInvalidError):
                await run(rt, session, issued, actor=actor)
        assert await native.rows(session) == ()


@pytest.mark.parametrize("phase", ["prepare", "finalize"])
async def test_runtime_tail_await_cannot_leave_pending_business_writes(built, monkeypatch, phase):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        name = "aprepare" if phase == "prepare" else "afinalize"
        method = getattr(rt.target_deletions, name)

        async def pending(*args, **kwargs):
            result = await method(*args, **kwargs)
            session.add(native.LLMModel(id=77, tenant_id=101, server_id=1, model_name="tail", model_type="llm"))
            return result

        monkeypatch.setattr(rt.target_deletions, name, pending)
        with pytest.raises(ResourceReferenceInvalidError):
            async with session.begin_nested():
                issued = await native.receipts(built, session, ("model", 11))
                if phase == "prepare":
                    await run(rt, session, issued)
                else:
                    await run(rt, session, issued)
                    await session.execute(
                        delete(native.LLMModel).where(native.LLMModel.id == 11, native.LLMModel.tenant_id == 101)
                    )
                    await rt.afinalize_target_deletion(
                        session,
                        receipts=issued,
                        operation_id="same",
                        operation_type="model_delete_server",
                        actor=native.ACTOR,
                    )
        await session.commit()
        assert await native.rows(session) == ()
        assert (
            await session.execute(select(native.LLMModel.id).where(native.LLMModel.id == 77))
        ).scalar_one_or_none() is None
