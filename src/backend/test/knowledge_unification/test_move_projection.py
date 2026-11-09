"""Real runtime/ledger/Mode composition with Catalog-result and transport isolation."""

import asyncio
import importlib
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionProjectionFailedError, PermissionPublishNotReadyError
from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.application.control_state import SqlPermissionControlState
from bisheng.permission.application.identity import PermissionActor
from bisheng.permission.application.runtime import F048PermissionRuntime, F048RuntimeComponents
from bisheng.permission.application.sql_runtime import SqlProjectionFinalizer, SqlProjectionScopeGuard
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionMigrationItem,
    PermissionMigrationRun,
    PermissionVisibleSourceProjection,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.projection_plan import ProjectionOutcome, projection_state_expectations
from bisheng.permission.domain.services.projection_service import ProjectionService
from test.knowledge_unification import test_move_projection_repository as native
from test.permission.test_f048_projection_service import FakeFGAProjection, FakeRecentMarker

database = native.database


def api():
    return importlib.import_module("bisheng.permission.application.knowledge_move_projection")


async def compose(database, monkeypatch, items):
    # The original finalizer reads these empty canonical tables as well as Mode.
    metadata = sa.MetaData()
    for model in (
        AuthorizationModelRelease,
        PermissionCatalogRelease,
        PermissionMigrationRun,
        PermissionMigrationItem,
        native.Operation,
        native.TupleRow,
        native.Mode,
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionVisibleSourceProjection,
    ):
        model.__table__.to_metadata(metadata).c.id.type = sa.Integer()
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    seen = []

    @asynccontextmanager
    async def sessions():
        async with database.sessions() as session:
            seen.append(session)
            yield session

    monkeypatch.setattr(control_state, "get_async_db_session", sessions)
    monkeypatch.setattr(sql_runtime, "get_async_db_session", sessions)
    state, marker = SqlPermissionControlState(), FakeRecentMarker()
    # Catalog derivation has its own suites; this test isolates that pure result,
    # while the new proof still reads the actual CURRENT/ACTIVE native SQL pin.
    monkeypatch.setattr(
        state,
        "current_catalog",
        AsyncMock(return_value=SimpleNamespace(release_id=1, store_id="actual-store", model_id="actual-model")),
    )
    initial = set()
    from bisheng.permission.domain.services.resource_lifecycle_policy import build_move_plan

    for item in items:
        plan = build_move_plan(
            item.after,
            old_parent=(item.before.parent_type, item.before.parent_id),
            new_parent=(item.after.parent_type, item.after.parent_id),
            mode=item.mode,
            store_id="actual-store",
            model_id="actual-model",
            operator_id=item.allowed_operator_ids[0],
            idempotency_key=f"knowledge-move:{native.JOB}:{item.resource_type}:{item.resource_id}",
        )
        initial.update(
            key for key, present in projection_state_expectations(plan.deltas, after=False).items() if present
        )

    class CheckedTransport(FakeFGAProjection):
        async def write_atomic(self, **kwargs):
            assert not any(session.in_transaction() for session in seen)
            return await super().write_atomic(**kwargs)

        async def read_present(self, *args, **kwargs):
            assert not any(session.in_transaction() for session in seen)
            return await super().read_present(*args, **kwargs)

    transport = CheckedTransport(initial)
    projection = ProjectionService(
        repository=ProjectionRepository(sessions),
        marker=marker,
        scope_guard=SqlProjectionScopeGuard(),
        fga=transport,
        finalizer=SqlProjectionFinalizer(),
    )
    facade = F048PermissionRuntime(
        client=SimpleNamespace(store_id="actual-store", model_id="actual-model"),
        state=state,
        marker=marker,
        projection=projection,
        decision=None,
        sources=None,
        owner=None,
        grants=None,
        modes=None,
        explain=None,
    )
    components = F048RuntimeComponents(facade=facade, state=state, projection=projection, marker=marker, relations=None)
    repository = native.api().MoveProjectionRepository(environment="test")
    bridge = api().KnowledgeMoveProjectionApplication(
        repository=repository, components=components, session_factory=sessions
    )
    return SimpleNamespace(bridge=bridge, facade=facade, projection=projection, marker=marker, transport=transport)


async def before_modes(database, items):
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.insert(native.Mode),
            [
                {
                    "tenant_id": 101,
                    "resource_type": item.resource_type,
                    "resource_id": item.resource_id,
                    "mode": item.mode,
                    "version": item.expected_permission_version,
                    "parent_type": item.before.parent_type,
                    "parent_id": item.before.parent_id,
                    "projection_state": "CURRENT",
                }
                for item in items
            ],
        )


@pytest.mark.parametrize("subject_type,subject_id", [("user", 7), ("service_account", 50)])
async def test_original_runtime_native_finalize_and_real_evidence_keep_actor_subject(
    database, monkeypatch, subject_type, subject_id
):
    item = native.expectation(operator=subject_id)
    built = await compose(database, monkeypatch, (item,))
    await before_modes(database, (item,))
    actor = PermissionActor(subject_type=subject_type, subject_id=subject_id, tenant_id=101)
    original = actor
    progress = await built.bridge.aexecute_or_resume(job_id=native.JOB, changes=(item,), actor=actor)
    assert (progress.total_count, progress.finalized_count, progress.complete) == (1, 1, True) and actor is original
    assert len(built.transport.calls) == 2
    async with database.sessions() as session, session.begin():
        evidence = await built.bridge.arequire_finalized(session, job_id=native.JOB, expectations=(item,))
        built.bridge.assert_current(
            evidence, session, job_id=native.JOB, expected_changes=(native.change(item),), changes_digest=native.DIGEST
        )
        row = (await session.execute(sa.select(native.Operation.__table__))).mappings().one()
        assert row["operator_id"] == subject_id and row["status"] == "FINALIZED"
        assert row["commit_checksum"] != row["after_checksum"]
    calls = len(built.transport.calls)
    assert (await built.bridge.aexecute_or_resume(job_id=native.JOB, changes=(item,), actor=actor)).complete
    assert len(built.transport.calls) == calls


async def test_retry_actor_resumes_original_failed_closed_plan_without_replacing_operator(database, monkeypatch):
    original = native.expectation()
    await native.seed(database, (original,), status="FAILED_CLOSED")
    item = replace(original, allowed_operator_ids=(7, 9))
    built = await compose(database, monkeypatch, (item,))
    async with database.engine.connect() as connection:
        checksum = (await connection.execute(sa.select(native.Operation.request_checksum))).scalar_one()
    result = await built.bridge.aexecute_or_resume(
        job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=9, current_tenant_id=101)
    )
    assert result.complete
    async with database.sessions() as session:
        rows = (await session.execute(sa.select(native.Operation.__table__))).mappings().all()
        assert len(rows) == 1 and rows[0]["operator_id"] == 7 and rows[0]["request_checksum"] == checksum
        assert rows[0]["status"] == "FINALIZED"


async def test_unknown_commit_resumes_original_real_ledger(database, monkeypatch):
    item = native.expectation()
    built = await compose(database, monkeypatch, (item,))
    await before_modes(database, (item,))
    built.transport.timeout_mode, built.transport.timeout_call = "after", 2
    progress = await built.bridge.aexecute_or_resume(
        job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=7, current_tenant_id=101)
    )
    assert progress.complete
    async with database.sessions() as session, session.begin():
        assert (await built.bridge.arequire_finalized(session, job_id=native.JOB, expectations=(item,))).count == 1


async def test_outcome_alone_without_real_sql_cannot_claim_completion(database, monkeypatch):
    item = native.expectation()
    built = await compose(database, monkeypatch, (item,))
    await before_modes(database, (item,))
    monkeypatch.setattr(
        built.facade,
        "project_parent_change",
        AsyncMock(
            return_value=ProjectionOutcome(
                operation_id=99, target_version=5, status="FINALIZED", request_checksum="a" * 64
            )
        ),
    )
    with pytest.raises(PermissionPublishNotReadyError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )


async def test_failed_second_projection_preserves_first_and_forward_resumes_same_keys(database, monkeypatch):
    items = (native.expectation(1), native.expectation(2))
    built = await compose(database, monkeypatch, items)
    await before_modes(database, items)
    built.transport.fail_call = 3
    actor = PermissionActor(user_id=7, current_tenant_id=101)
    with pytest.raises(PermissionProjectionFailedError):
        await built.bridge.aexecute_or_resume(job_id=native.JOB, changes=items, actor=actor)
    async with database.sessions() as session:
        rows = (
            (await session.execute(sa.select(native.Operation.__table__).order_by(native.Operation.id)))
            .mappings()
            .all()
        )
        assert len(rows) == 2 and rows[0]["status"] == "FINALIZED"
    assert (await built.bridge.aexecute_or_resume(job_id=native.JOB, changes=items, actor=actor)).complete
    async with database.sessions() as session, session.begin():
        assert (await built.bridge.arequire_finalized(session, job_id=native.JOB, expectations=items)).count == 2
        assert (await session.execute(sa.select(sa.func.count()).select_from(native.Operation))).scalar_one() == 2


async def test_marker_not_ready_and_unaccepted_actor_fail_before_projection(database, monkeypatch):
    item = native.expectation()
    built = await compose(database, monkeypatch, (item,))
    built.marker.ready = False
    database.queries.clear()
    with pytest.raises(PermissionPublishNotReadyError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )
    assert not built.transport.calls and not database.queries
    built.marker.ready = True
    with pytest.raises(PermissionPublishNotReadyError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=99, current_tenant_id=101)
        )
    assert not built.transport.calls and not database.queries


async def test_bridge_native_parent_state_read_and_missing_composition_fail_closed(database, monkeypatch):
    item = native.expectation()
    await native.seed(database, (item,))
    bridge = api().KnowledgeMoveProjectionApplication(
        repository=native.api().MoveProjectionRepository(environment="test"), session_factory=database.sessions
    )
    async with database.sessions() as session, session.begin():
        (row,) = await bridge.aread_parent_states(session, targets=(("knowledge_file", "1"),))
        assert row.parent_id == "12" and row.version == 5
    from bisheng.permission.application import process_runtime

    monkeypatch.setattr(
        process_runtime, "get_f048_process_runtime", AsyncMock(side_effect=RuntimeError("not composed"))
    )
    with pytest.raises(PermissionPublishNotReadyError):
        await bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )


async def test_invalid_tail_cannot_begin_a_valid_prefix_projection(database, monkeypatch):
    item = native.expectation()
    built = await compose(database, monkeypatch, (item,))
    database.queries.clear()
    with pytest.raises(PermissionPublishNotReadyError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item, object()), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )
    assert not built.transport.calls and not database.queries


async def test_cancelled_projection_is_not_ready_and_resumes_same_native_operation(database, monkeypatch):
    item = native.expectation()
    built = await compose(database, monkeypatch, (item,))
    await before_modes(database, (item,))
    original, write = asyncio.CancelledError("cancel actual projection"), built.transport.write_atomic
    monkeypatch.setattr(built.transport, "write_atomic", AsyncMock(side_effect=original))
    actor = PermissionActor(user_id=7, current_tenant_id=101)
    with pytest.raises(asyncio.CancelledError) as caught:
        await built.bridge.aexecute_or_resume(job_id=native.JOB, changes=(item,), actor=actor)
    assert caught.value is original
    async with database.sessions() as session, session.begin():
        with pytest.raises(PermissionPublishNotReadyError):
            await built.bridge.arequire_finalized(session, job_id=native.JOB, expectations=(item,))
    monkeypatch.setattr(built.transport, "write_atomic", write)
    assert (await built.bridge.aexecute_or_resume(job_id=native.JOB, changes=(item,), actor=actor)).complete
    async with database.sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(native.Operation))).scalar_one() == 1


async def test_recovery_preview_is_bound_to_original_request_before_any_forward_write(database, monkeypatch):
    item = native.expectation()
    await native.seed(database, (item,), status="FAILED_CLOSED")
    built = await compose(database, monkeypatch, (item,))
    preview = await built.projection.inspect_failed_closed_recovery(1)
    monkeypatch.setattr(
        built.projection,
        "inspect_failed_closed_recovery",
        AsyncMock(return_value=replace(preview, request_checksum="0" * 64)),
    )
    with pytest.raises(PermissionPublishNotReadyError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )
    assert not built.transport.calls


@pytest.mark.parametrize("retry_operator", [7, 9])
async def test_prepare_only_commit_reserves_original_mode_without_rebuilding_retry_actor(
    database, monkeypatch, retry_operator
):
    item = replace(native.expectation(), allowed_operator_ids=(7, 9))
    built = await compose(database, monkeypatch, (item,))
    await before_modes(database, (item,))
    plan = native.build_move_plan(
        item.after,
        old_parent=(item.before.parent_type, item.before.parent_id),
        new_parent=(item.after.parent_type, item.after.parent_id),
        mode=item.mode,
        store_id="actual-store",
        model_id="actual-model",
        operator_id=7,
        idempotency_key=f"knowledge-move:{native.JOB}:{item.resource_type}:{item.resource_id}",
    )
    operation = await built.projection.prepare(plan)
    assert operation.status == "PREPARED" and not built.transport.calls
    checksum = operation.request_checksum
    assert (
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=retry_operator, current_tenant_id=101)
        )
    ).complete
    async with database.sessions() as session:
        row = (await session.execute(sa.select(native.Operation.__table__))).mappings().one()
        assert row["id"] == operation.id and row["operator_id"] == 7 and row["request_checksum"] == checksum
        assert row["status"] == "FINALIZED"


@pytest.mark.parametrize("patch", [{"parent_id": "999"}, {"version": 3}])
async def test_nonfinalized_wrong_mode_scope_never_reaches_transport_or_fences_the_resource(
    database, monkeypatch, patch
):
    item = native.expectation()
    await native.seed(database, (item,), status="STAGING")
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(native.Mode).values(version=4, projection_state="PROJECTING"))
        await connection.execute(sa.update(native.Mode).values(**patch))
    built = await compose(database, monkeypatch, (item,))
    async with database.engine.connect() as connection:
        before = tuple((await connection.execute(sa.select(native.Mode.__table__))).mappings())
    with pytest.raises(PermissionPublishNotReadyError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )
    async with database.engine.connect() as connection:
        assert tuple((await connection.execute(sa.select(native.Mode.__table__))).mappings()) == before
    assert not built.transport.calls


async def test_stale_operation_cannot_fail_closed_another_real_operation_mode(database, monkeypatch):
    item = native.expectation()
    await native.seed(database, (item,), status="STAGING")
    other_job = "e0e4b210-560a-4215-b787-9ac61158b6d2"
    plan = native.normalize_projection_plan(
        native.build_move_plan(
            item.after,
            old_parent=(item.before.parent_type, item.before.parent_id),
            new_parent=(item.after.parent_type, item.after.parent_id),
            mode=item.mode,
            store_id="actual-store",
            model_id="actual-model",
            operator_id=7,
            idempotency_key=f"knowledge-move:{other_job}:{item.resource_type}:{item.resource_id}",
        )
    )
    operation, rows = native.build_projection_operation(plan, request_checksum=native.projection_request_checksum(plan))
    operation.id, operation.status = 2, "STAGING"
    async with database.engine.begin() as connection:
        await connection.execute(
            sa.insert(native.Operation), operation.model_dump(exclude={"create_time", "update_time"})
        )
        for row in rows:
            row.operation_id = 2
        await connection.execute(
            sa.insert(native.TupleRow), [row.model_dump(exclude={"id", "create_time", "update_time"}) for row in rows]
        )
        await connection.execute(
            sa.update(native.Mode).values(version=4, projection_state="PROJECTING", operation_id=2)
        )
    built = await compose(database, monkeypatch, (item,))
    with pytest.raises(PermissionPublishNotReadyError):
        await built.bridge.aexecute_or_resume(
            job_id=native.JOB, changes=(item,), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )
    async with database.engine.connect() as connection:
        mode = (await connection.execute(sa.select(native.Mode.__table__))).mappings().one()
        assert mode["operation_id"] == 2 and mode["projection_state"] == "PROJECTING" and mode["version"] == 4
    assert not built.transport.calls


@pytest.mark.parametrize("lock", [False, True])
@pytest.mark.parametrize("status", ["PREPARED", "STAGING", "FAILED_CLOSED", "FINALIZED"])
async def test_owned_fact_bridge_keeps_actual_native_session_transaction_and_lock(database, monkeypatch, lock, status):
    item = native.expectation()
    await native.seed(database, (item,), status=status)
    repo = native.api().MoveProjectionRepository(environment="test")
    bridge = api().KnowledgeMoveProjectionApplication(
        repository=repo, session_factory=lambda: pytest.fail("owned fact read must not create a session")
    )
    observed = []
    sa.event.listen(
        database.engine.sync_engine,
        "before_cursor_execute",
        lambda c, u, sql, p, context, many: observed.append(context.compiled.statement),
    )
    async with database.sessions() as session, session.begin():
        transaction = session.sync_session.get_transaction()
        original = repo.alist_owned_operations

        async def actual_native(current, *, expectations, lock=False):
            assert current is session and current.sync_session.get_transaction() is transaction
            assert expectations is requested
            return await original(current, expectations=expectations, lock=lock)

        monkeypatch.setattr(repo, "alist_owned_operations", actual_native)
        monkeypatch.setattr(session, "commit", AsyncMock(side_effect=AssertionError("unexpected commit")))
        requested = (item,)
        (fact,) = await bridge.alist_owned_operations(session, expectations=requested, lock=lock)
        assert type(fact) is api().MoveProjectionFact is native.api().MoveProjectionFact
        assert (fact.id, fact.status, fact.operator_id, fact.parent_state.operation_id) == (1, status, 7, 1)
        assert fact.parent_state.parent_id == "12"
        assert session.sync_session.get_transaction() is transaction and session.in_transaction()
        session.commit.assert_not_awaited()
        operations = [
            statement
            for statement in observed
            if any(getattr(table, "name", None) == "permission_projection_operation" for table in statement.get_final_froms())
        ]
        assert operations and all((statement._for_update_arg is not None) == lock for statement in operations)
        assert all(statement.is_select for statement in observed)
        if status != "FINALIZED":
            with pytest.raises(PermissionPublishNotReadyError):
                await bridge.arequire_finalized(session, job_id=native.JOB, expectations=(item,))


@pytest.mark.parametrize("bad", ["scope", "pin", "tuple", "checksum", "operator"])
async def test_owned_fact_bridge_retains_original_native_fail_closed_controls(database, bad):
    item = native.expectation()
    await native.seed(database, (item,))
    patch = {
        "scope": {"scope_key": "folder:1"},
        "pin": {"store_id": "foreign-store"},
        "checksum": {"request_checksum": "a" * 64},
        "operator": {"operator_id": 999},
    }
    async with database.engine.begin() as connection:
        if bad == "tuple":
            await connection.execute(sa.update(native.TupleRow).where(native.TupleRow.id == 1).values(fga_object="bad"))
        else:
            await connection.execute(sa.update(native.Operation).values(**patch[bad]))
    repo = native.api().MoveProjectionRepository(environment="test")
    bridge = api().KnowledgeMoveProjectionApplication(repository=repo)
    async with database.sessions() as session, session.begin():
        with pytest.raises(PermissionPublishNotReadyError):
            await repo.alist_owned_operations(session, expectations=(item,))
        with pytest.raises(PermissionPublishNotReadyError):
            await bridge.alist_owned_operations(session, expectations=(item,))


async def test_owned_fact_bridge_returns_actual_mode_facts_but_never_claims_finalized_authority(database):
    item = native.expectation()
    await native.seed(database, (item,))
    async with database.engine.begin() as connection:
        await connection.execute(sa.update(native.Mode).values(operation_id=999, parent_id="88"))
    repo = native.api().MoveProjectionRepository(environment="test")
    bridge = api().KnowledgeMoveProjectionApplication(repository=repo)
    async with database.sessions() as session, session.begin():
        facts = await bridge.alist_owned_operations(session, expectations=(item,))
        assert facts == await repo.alist_owned_operations(session, expectations=(item,))
        assert facts[0].parent_state.operation_id == 999 and facts[0].parent_state.parent_id == "88"
        with pytest.raises(PermissionPublishNotReadyError):
            await bridge.arequire_finalized(session, job_id=native.JOB, expectations=(item,))


async def test_owned_fact_bridge_preserves_empty_missing_foreign_and_native_batch_bound(database):
    repo = native.api().MoveProjectionRepository(environment="test")
    bridge = api().KnowledgeMoveProjectionApplication(repository=repo)
    async with database.sessions() as session:
        with pytest.raises(PermissionPublishNotReadyError):
            await bridge.alist_owned_operations(session, expectations=())
    async with database.sessions() as session, session.begin():
        database.queries.clear()
        assert await bridge.alist_owned_operations(session, expectations=()) == () and not database.queries
        item = native.expectation()
        assert await bridge.alist_owned_operations(session, expectations=(item,)) == ()
        database.queries.clear()
        with pytest.raises(PermissionPublishNotReadyError):
            await bridge.alist_owned_operations(session, expectations=(replace(item, tenant_id=202),))
        assert not database.queries
        with pytest.raises(PermissionPublishNotReadyError):
            await bridge.alist_owned_operations(
                session, expectations=tuple(native.expectation(i) for i in range(1, 202))
            )
        assert not database.queries
