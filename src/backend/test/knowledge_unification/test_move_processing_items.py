"""§121 actual Owner ports feed the original File/Item/count native ACK kernel."""

import asyncio
from dataclasses import asdict

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.worker.knowledge.move_worker import MoveIndexCheckpoint, MoveMetadataPolicy, _scope
from test.knowledge_unification import test_move_processing_owner as base

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


async def checkpoint(app, lease):
    snapshot = await app.owner.aguard_item(lease)
    policy = snapshot.snapshot["metadata_policy"]
    binding = _scope(
        app.built.job_id,
        snapshot.leaf.target,
        Knowledge(**snapshot.source),
        Knowledge(**snapshot.destination),
        7,
        MoveMetadataPolicy(tuple(policy["retained_fields"]), tuple(policy["removed_fields"])),
    )
    return MoveIndexCheckpoint(
        **binding,
        step="move_source_cleaned",
        source_count=0,
        source_digest="1" * 64,
        target_milvus_count=0,
        target_es_count=0,
        target_payload_digest="2" * 64,
    )


async def test_real_owner_checkpoint_and_five_scalar_ack_then_final_counts(application):
    app = application
    await app.owner.aensure_logical(app.built.lease)
    lease = await app.owner.aclaim_item(app.built.lease)
    assert lease is not None
    assert await app.owner.arenew_item(lease)
    value = await checkpoint(app, lease)
    assert await app.owner.asave_item_checkpoint(lease, step=value.step, checkpoint=asdict(value))
    assert await app.owner.acomplete_item(
        lease, source_count=0, milvus_count=0, es_count=0, source_digest="1" * 64, target_payload_digest="2" * 64
    )
    result = await app.owner.afinalize_attempt(app.built.lease)
    assert result.state == "succeeded"
    async with app.built.sessions() as session:
        job = await session.get(base.Job, app.built.job_id)
        item = (await session.execute(sa.select(Item).where(Item.job_id == job.id))).scalars().one()
        file = await session.get(base.File, item.file_id)
        assert (file.status, item.state, job.succeeded_count, job.failed_count, job.pending_count) == (
            2,
            "succeeded",
            1,
            0,
            0,
        )
        assert item.checkpoint["logical_move"] and item.checkpoint["step"] == "move_source_cleaned"


async def test_real_owner_failure_and_retry_preserve_logical_marker_and_success_material(application):
    from bisheng.knowledge.domain.schemas.processing_job import ProcessingRetryRequest
    from test.knowledge_unification.test_processing_identity import request_context

    app = application
    await app.owner.aensure_logical(app.built.lease)
    lease = await app.owner.aclaim_item(app.built.lease)
    assert await app.owner.afail_item(lease, error_code=10900)
    assert (await app.owner.afinalize_attempt(app.built.lease)).state == "failed"
    async with app.built.sessions() as session:
        job = await session.get(base.Job, app.built.job_id)
        marker, revision = job.move_logical_marker, job.revision
        params, actor = job.parameters, job.actor_reference
    with request_context(app.actor):
        result = await app.owner.aretry_failed(
            app.built.job_id,
            ProcessingRetryRequest(idempotency_key="real-retry", expected_job_revision=revision),
            identity=app.current,
            entry_kind="web",
        )
    assert result.state == "accepted"
    async with app.built.sessions() as session:
        job = await session.get(base.Job, app.built.job_id)
        assert job.move_logical_marker == marker and job.parameters == params and job.actor_reference == actor


@pytest.mark.parametrize("call", ["guard", "checkpoint", "complete", "claim", "renew"])
async def test_actual_configuration_drift_none_false_is_committed(application, call):
    app = application
    await app.owner.aensure_logical(app.built.lease)
    lease = await app.owner.aclaim_item(app.built.lease)
    async with app.built.sessions() as session, session.begin():
        await session.execute(sa.update(Knowledge.__table__).where(Knowledge.id == 10).values(model_config_revision=5))
    if call == "guard":
        assert await app.owner.aguard_item(lease) is None
    elif call == "checkpoint":
        assert not await app.owner.asave_item_checkpoint(lease, step="attempt", checkpoint={})
    elif call == "complete":
        assert not await app.owner.acomplete_item(
            lease, source_count=0, milvus_count=0, es_count=0, source_digest="1" * 64, target_payload_digest="2" * 64
        )
    elif call == "claim":
        assert await app.owner.aclaim_item(app.built.lease) is None
    else:
        assert not await app.owner.arenew_item(lease)
    async with app.built.sessions() as session:
        assert (await session.get(base.Job, app.built.job_id)).state == "obsolete"


@pytest.mark.parametrize("fault", ["r2", "ready", "cancel", "wrong_claim"])
async def test_real_common_savepoint_and_peek_claim_mismatch_roll_back(application, monkeypatch, fault):
    app = application
    before = await base.refs.facts(app.built)
    if fault == "wrong_claim":
        await app.owner.aensure_logical(app.built.lease)
        original = app.owner.jobs.aclaim_next_item

        async def wrong(*args, **kwargs):
            result = await original(*args, **kwargs)
            result.item.id = "wrong-native-result"
            return result

        monkeypatch.setattr(app.owner.jobs, "aclaim_next_item", wrong)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await app.owner.aclaim_item(app.built.lease)
        async with app.built.sessions() as session:
            item = (await session.execute(sa.select(Item).where(Item.job_id == app.built.job_id))).scalars().one()
            assert item.state == "pending" and item.attempt == 0
        return

    async def fail(*args, **kwargs):
        if fault == "cancel":
            raise asyncio.CancelledError()
        raise RuntimeError("real composed phase failed")

    monkeypatch.setattr(
        app.owner.reference_owner if fault == "r2" else app.owner.jobs,
        "amove_file_ownership" if fault == "r2" else "amark_move_ready",
        fail,
    )
    with pytest.raises(asyncio.CancelledError if fault == "cancel" else RuntimeError):
        await app.owner.aensure_logical(app.built.lease)
    assert await base.refs.facts(app.built) == before
    assert not app.chat
