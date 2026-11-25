"""Native preview/apply/resume for the default historical classifications."""

from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.domain.models import PermissionGrant, PermissionProjectionOperation, ResourcePermissionMode
from bisheng.permission.domain.services.projection_plan import ProjectionTupleDelta
from bisheng.permission.domain.services.resource_lifecycle_policy import build_delete_plan
from scripts import f118_history_permissions as permissions
from scripts import prepare_f118_history as script
from test.knowledge_unification import test_prepare_history as original
from test.knowledge_unification.test_model_share_projection_deferred import Transport

resource_native, native, history = original.resource_native, original.native, original.history


async def seed(history):
    # SQLite requires INTEGER for the native AUTO_INCREMENT identity. Keep the
    # actual remaining columns/constraints, as the projection-ledger fixture does.
    async with history.db.engine.begin() as connection:
        saved = [
            dict(row) for row in (await connection.execute(sa.select(ResourcePermissionMode.__table__))).mappings()
        ]
        table = ResourcePermissionMode.__table__.to_metadata(sa.MetaData())
        PermissionProjectionOperation.__table__.to_metadata(table.metadata)
        table.c.id.type = sa.Integer()
        await connection.run_sync(lambda conn: ResourcePermissionMode.__table__.drop(conn))
        await connection.run_sync(table.create)
        await connection.execute(table.insert(), saved)
    async with script.global_session(history.sessions) as session:
        session.add(
            ResourcePermissionMode(
                id=10,
                tenant_id=101,
                resource_type="knowledge_library",
                resource_id="10",
                mode="CUSTOM",
                version=1,
                projection_state="CURRENT",
            )
        )
        session.add(
            KnowledgeFile(
                id=90,
                tenant_id=101,
                knowledge_id=404,
                user_id=7,
                file_name="unreachable",
                file_type=1,
                file_level_path="",
            )
        )
        session.add(
            KnowledgeFile(
                id=91,
                tenant_id=101,
                knowledge_id=10,
                user_id=7,
                file_name="successful",
                file_type=1,
                status=2,
                file_level_path="",
            )
        )

    # Real native SQL/ledger/finalizer, with an in-memory transport at the IO boundary.
    async def write_atomic(**kwargs):
        return await Transport.write_atomic(history.fga, **kwargs)

    async def read_tuples(*, object, consistency, relation=None, user=None):
        rows = await original.FGA.read_tuples(history.fga, object=object, consistency=consistency, relation=relation)
        return [row for row in rows if user is None or row["user"] == user]

    history.fga.write_atomic = write_atomic
    history.fga.read_tuples = read_tuples


async def test_default_preview_apply_and_idempotent_resume_preserve_orphan_and_inherit_only(history):
    await seed(history)
    before = history.fga.writes
    plan = await script.capture(history.sessions, history.fga)
    assert not plan["blocked"]
    assert [item["file"]["id"] for item in plan["initializations"]] == [91]
    assert [item["before"]["id"] for item in plan["business"]["retained"]] == [90]
    assert history.fga.writes == before
    first = await script.apply(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )
    writes = history.fga.writes
    second = await script.apply(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )
    assert first == second and writes == history.fga.writes
    async with script.global_session(history.sessions) as session:
        assert (await session.get(KnowledgeFile, 90)).knowledge_id == 404
        mode = (
            await session.exec(select(ResourcePermissionMode).where(ResourcePermissionMode.resource_id == "91"))
        ).one()
        assert (mode.mode, mode.version, mode.projection_state, mode.parent_id) == ("INHERIT", 1, "CURRENT", "10")
        assert not (await session.exec(select(PermissionGrant).where(PermissionGrant.resource_id == "91"))).all()
    keys = {key for key in history.fga.present if key[2] == "knowledge_file:91"}
    assert {relation for _, relation, _ in keys} == {"parent", "inherit_mode", "permission_enabled"}
    assert not any(key[2] == "knowledge_file:90" for key in history.fga.present)


@pytest.mark.parametrize("change", ["foreign_sql", "incoming_fga", "old_ledger", "missing_creator"])
async def test_ambiguous_intent_blocks_before_any_write(history, change):
    await seed(history)
    if change == "foreign_sql":
        async with script.global_session(history.sessions) as session:
            session.add(
                ResourcePermissionMode(
                    tenant_id=202,
                    resource_type="knowledge_file",
                    resource_id="90",
                    mode="CUSTOM",
                    version=1,
                    projection_state="CURRENT",
                )
            )
    elif change == "incoming_fga":
        history.fga.present.add(("knowledge_file:90#visible", "visible", "app:live"))
    elif change == "missing_creator":
        async with script.global_session(history.sessions) as session:
            row = await session.get(KnowledgeFile, 91)
            row.user_id = 999999
    else:
        with tenant_execution_scope(101):
            plan = build_delete_plan(
                script.target_for(
                    {
                        "tenant_id": 101,
                        "resource_type": "knowledge_file",
                        "resource_id": "91",
                        "version": 1,
                        "parent_type": "knowledge_library",
                        "parent_id": "10",
                    }
                ),
                store_id="store",
                model_id="model",
                operator_id=7,
                idempotency_key="unknown-old-intent",
            )
            await history.runtime._projection.prepare(plan)
    plan = await script.capture(history.sessions, history.fga)
    assert plan["blocked"]
    writes = history.fga.writes
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await script.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == writes


async def test_failed_closed_uses_original_ledger_and_rejects_graph_drift(history):
    await seed(history)
    async with script.global_session(history.sessions) as session:
        mode = await session.get(ResourcePermissionMode, 30)
        mode.mode = "CUSTOM"
        pin = await script.read_pin(session)
        fact = script.canonical(mode.model_dump())
    with tenant_execution_scope(101):
        base = build_delete_plan(
            script.target_for(fact),
            store_id=pin["store_id"],
            model_id=pin["model_id"],
            operator_id=7,
            idempotency_key="original-mutation",
        )
        plan = replace(
            base,
            operation_type="GRANT_MUTATION",
            deltas=(ProjectionTupleDelta("COMMIT", 0, "WRITE", "user:7", "visible", "knowledge_file:30"),),
        )
        operation = await history.runtime._projection.prepare(plan)
        await history.runtime._state.mark_projecting(target=script.target_for(fact), operation_id=operation.id)
        await history.runtime._projection._repository.aupdate_operation_status_cas(
            operation_id=operation.id,
            expected_status="PREPARED",
            target_status="FAILED_CLOSED",
            error_code=25009,
            error_message="unknown commit",
        )
        await history.runtime._projection._scope_guard.fail_closed(plan, "unknown commit")
    frozen = await script.capture(history.sessions, history.fga)
    assert not frozen["blocked"] and len(frozen["recoveries"]) == 1
    first = await script.apply(
        frozen, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )
    assert operation.id in first["permission_operation_ids"]
    assert ("user:7", "visible", "knowledge_file:30") in history.fga.present
    writes = history.fga.writes
    assert (
        await script.apply(
            frozen, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
        )
        == first
    )
    assert history.fga.writes == writes


async def test_unknown_result_after_native_initialization_resumes_same_receipt(history, monkeypatch):
    await seed(history)
    plan = await script.capture(history.sessions, history.fga)
    execute = history.runtime._projection.execute
    interrupted = False

    async def unknown_result(value):
        nonlocal interrupted
        outcome = await execute(value)
        if value.idempotency_key.startswith("history-initialize:") and not interrupted:
            interrupted = True
            raise RuntimeError("caller lost committed reply")
        return outcome

    monkeypatch.setattr(history.runtime._projection, "execute", unknown_result)
    with pytest.raises(RuntimeError):
        await script.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert interrupted
    writes = history.fga.writes
    await script.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    # Remaining original parent/delete repairs may write, but the initialized
    # object itself is never enabled twice or assigned another operation.
    assert history.fga.writes >= writes
    async with script.global_session(history.sessions) as session:
        operations = (
            await session.exec(
                select(PermissionProjectionOperation).where(
                    PermissionProjectionOperation.scope_key == "knowledge_file:91"
                )
            )
        ).all()
        assert len(operations) == 1 and operations[0].status == "FINALIZED"


async def test_many_initializations_hash_complete_frozen_plan_only_once(history, monkeypatch):
    await seed(history)
    async with script.global_session(history.sessions) as session:
        session.add(
            KnowledgeFile(
                id=92,
                tenant_id=101,
                knowledge_id=10,
                user_id=7,
                file_name="second-successful",
                file_type=1,
                status=2,
                file_level_path="",
            )
        )
    plan = await script.capture(history.sessions, history.fga)
    assert len(plan["initializations"]) == 2
    original, calls = script.checksum, []

    def checksum(value):
        calls.append(id(value))
        return original(value)

    from bisheng.knowledge.domain.repositories import unification_history_repository as history_owner

    monkeypatch.setattr(history_owner, "checksum", checksum)
    await permissions.apply_repairs(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )
    assert calls == [id(plan)]


@pytest.mark.parametrize("count", [200, 400])
async def test_global_absence_proofs_use_four_queries_per_bounded_batch(history, count):
    statements = []

    def observe(_conn, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    sa.event.listen(history.db.engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with script.global_session(history.sessions) as session:
            assert not await permissions.absent_authorization(session, [{"id": i} for i in range(10000, 10000 + count)])
    finally:
        sa.event.remove(history.db.engine.sync_engine, "before_cursor_execute", observe)
    assert len(statements) == 4 * (count // 200)
    assert max(len(parameters) for _, parameters in statements) <= 401
