"""§126 real long P1 IO advances business time, refreshes credentials and renews."""

from datetime import timedelta

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.permission.domain.models import PermissionProjectionOperation as Operation
from bisheng.permission.domain.services.projection_service import projection_state_expectations
from bisheng.permission.domain.services.resource_lifecycle_policy import build_move_plan
from test.knowledge_unification import test_move_processing_admission as stages
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


async def direct_file(app):
    await stages.reset_to_before(app)
    with request_context(app.actor):
        plan = await app.owner.aprecheck(
            10,
            FileMoveReq(items=[{"id": 81, "type": "file"}], target_space_id=11, target_folder_id=51),
            identity=app.current,
            entry_kind="web",
        )
        result = await app.owner.aaccept(
            10,
            ProcessingCreateRequest(
                confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="long-parent-io"
            ),
            identity=app.current,
            entry_kind="web",
        )
    app.built.job_id = result.job_id
    async with app.owner._session() as session:
        job, _reference = await app.owner._job(session, result.job_id)
        scope = await app.owner._scope_for(session, job)
        expected, _ = await app.owner._materials(session, job, scope.parent_changes, actor_id=7)
    assert len(expected) == 2
    transport = app.built.bridge.components.projection._fga
    initial = set()
    for item in expected:
        original = build_move_plan(
            item.after,
            old_parent=(item.before.parent_type, item.before.parent_id),
            new_parent=(item.after.parent_type, item.after.parent_id),
            mode=item.mode,
            store_id="actual-store",
            model_id="actual-model",
            operator_id=7,
            idempotency_key=f"knowledge-move:{job.id}:{item.resource_type}:{item.resource_id}",
        )
        initial.update(
            key for key, present in projection_state_expectations(original.deltas, after=False).items() if present
        )
    transport.present = initial
    app.owner.chat_rehome = lambda **kwargs: 0
    lease = await app.owner.astart_attempt(job.id, expected_dispatch_revision=job.revision)
    assert lease is not None
    app.calls.clear()
    return lease, transport


async def test_native_per_resource_progress_crosses_original_lease_without_sibling_move_recheck(
    application, monkeypatch
):
    app = application
    lease, transport = await direct_file(app)
    started = app.built.clock[0]
    original = transport.write_atomic

    async def slow(**kwargs):
        assert not any(session.in_transaction() for session in app.sessions_seen)
        app.built.clock[0] += timedelta(seconds=300)
        return await original(**kwargs)

    monkeypatch.setattr(transport, "write_atomic", slow)
    result = await app.owner.aensure_logical(lease)
    assert result.state == "running" and (app.built.clock[0] - started).total_seconds() == 1200
    # Once the selected root81 owns CURRENT after, history82 does not demand a new move81.
    assert app.calls.count(("knowledge_file", 81, "move")) == 2
    async with app.built.sessions() as session:
        job = await session.get(base.Job, app.built.job_id)
        assert job.lease_until > app.built.clock[0] and job.move_logical_marker


@pytest.mark.parametrize("failure", ["revoked", "takeover"])
async def test_progress_stops_new_resource_io_and_keeps_completed_original_ledger(application, monkeypatch, failure):
    app = application
    lease, transport = await direct_file(app)
    original = transport.write_atomic
    resolve = base.processing_identity.resolve_web_runtime_identity
    revoked = []

    async def current(reference):
        if revoked:
            raise PermissionDeniedError(reason="credential_revoked_during_projection")
        return await resolve(reference)

    monkeypatch.setattr(base.processing_identity, "resolve_web_runtime_identity", current)

    async def changed(**kwargs):
        result = await original(**kwargs)
        if len(transport.calls) == 2:
            if failure == "revoked":
                revoked.append(True)
            else:
                async with app.built.sessions() as session, session.begin():
                    await session.execute(
                        sa.update(base.Job.__table__)
                        .where(base.Job.id == app.built.job_id, base.Job.tenant_id == 101)
                        .values(claim_generation=lease.claim_generation + 1, lease_token="real-new-owner")
                    )
        return result

    monkeypatch.setattr(transport, "write_atomic", changed)
    with pytest.raises(PermissionDeniedError if failure == "revoked" else KnowledgeOperationPlanConflictError):
        await app.owner.aensure_logical(lease)
    assert len(transport.calls) == 2
    async with app.built.sessions() as session:
        assert (await session.execute(sa.select(Operation.status))).scalars().all() == ["FINALIZED"]
        assert (await session.get(base.File, 81)).knowledge_id == 10
        assert (await session.get(base.Job, app.built.job_id)).move_logical_marker is None
