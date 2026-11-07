"""Real runtime/ledger/Mode composition; only FGA and marker transport is isolated."""

import importlib
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
    monkeypatch.setattr(control_state, "get_async_db_session", database.sessions)
    monkeypatch.setattr(sql_runtime, "get_async_db_session", database.sessions)
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
    transport = FakeFGAProjection(initial)
    projection = ProjectionService(
        repository=ProjectionRepository(database.sessions),
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
        repository=repository, components=components, session_factory=database.sessions
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
