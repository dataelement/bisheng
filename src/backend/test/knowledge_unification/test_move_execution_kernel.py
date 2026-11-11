"""Move execution joins the original Job algorithm; ordinary paths stay unchanged."""

from dataclasses import asdict, replace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from bisheng.worker.knowledge.move_worker import MoveIndexCheckpoint, MoveMetadataPolicy, _scope
from test.knowledge_unification import test_move_execution_repository as facts
from test.knowledge_unification import test_move_job_ready as ready

store, tenant, moving, accepted = facts.store, facts.tenant, facts.moving, facts.accepted
built = facts.built


def composed(built):
    execution = facts.execution(built)
    built.repo = ProcessingJobRepository(
        move_jobs=built.move, move_ready=built.ready, move_execution=execution, clock=lambda: built.clock[0]
    )
    built.execution = execution
    return built


async def proof(session, built):
    return await built.bridge.arequire_finalized(session, job_id=built.job_id, expectations=built.expectations)


async def claim(session, built, *, evidence=None):
    evidence = evidence or await proof(session, built)
    return await built.repo.aclaim_next_item(
        session, built.lease, configuration=ready.CONFIG, _move=True, move_projection_evidence=evidence
    )


async def cleaned(session, built, claimed, *, evidence=None):
    evidence = evidence or await proof(session, built)
    snapshot = await built.execution.aread_item(session, job_id=built.job_id, item_id=claimed.item.id)
    policy = snapshot.snapshot["metadata_policy"]
    binding = _scope(
        built.job_id,
        snapshot.leaf.target,
        Knowledge(**snapshot.source),
        Knowledge(**snapshot.destination),
        7,
        MoveMetadataPolicy(tuple(policy["retained_fields"]), tuple(policy["removed_fields"])),
    )
    checkpoint = MoveIndexCheckpoint(
        **binding,
        step="move_source_cleaned",
        source_count=2,
        source_digest="1" * 64,
        target_milvus_count=2,
        target_es_count=2,
        target_payload_digest="2" * 64,
    )
    assert await built.repo.asave_checkpoint(
        session,
        claimed.lease,
        configuration=ready.CONFIG,
        step=checkpoint.step,
        checkpoint=asdict(checkpoint),
        _move=True,
        move_projection_evidence=evidence,
    )
    return {
        "source_count": 2,
        "milvus_count": 2,
        "es_count": 2,
        "source_digest": checkpoint.source_digest,
        "target_payload_digest": checkpoint.target_payload_digest,
    }


async def finish(session, built, claimed, *, evidence=None):
    evidence = evidence or await proof(session, built)
    result = await cleaned(session, built, claimed, evidence=evidence)
    return await built.execution.acomplete_item(
        session, claimed.lease, jobs=built.repo, projection_evidence=evidence, **result
    )


async def test_missing_composition_and_default_generic_path_never_mutate_move(built):
    unconfigured = ProcessingJobRepository(move_jobs=built.move, move_ready=built.ready)
    async with built.sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await unconfigured.arenew(session, built.lease, configuration=ready.CONFIG, _move=True)
    composed(built)
    async with built.sessions() as session, session.begin():
        before = (await built.repo.aget_execution(session, built.job_id)).revision
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.arenew(session, built.lease, configuration=ready.CONFIG)
        assert (await built.repo.aget_execution(session, built.job_id)).revision == before


@pytest.mark.parametrize(
    "side,field,value",
    [
        (10, "model_config_revision", 99),
        (11, "index_generation", "changed"),
        (10, "index_name", "other-index"),
        (11, "collection_name", "other-collection"),
    ],
)
async def test_real_dual_configuration_drift_is_durably_obsolete(built, side, field, value):
    composed(built)
    async with built.sessions() as session, session.begin():
        await session.execute(sa.update(Knowledge).where(Knowledge.id == side).values(**{field: value}))
    async with built.sessions() as session, session.begin():
        assert await built.repo.arenew(session, built.lease, configuration=ready.CONFIG, _move=True) is None
    async with built.sessions() as session:
        job = await built.repo.aget_execution(session, built.job_id)
        assert job.state == "obsolete" and not job.pending_dispatch and job.lease_until is None
        assert ("index_digest" if field in {"index_name", "collection_name"} else field) in job.obsolete_reason


@pytest.mark.parametrize("bad", ["missing", "copied", "old-tx"])
async def test_item_claim_requires_real_same_transaction_p1_before_any_lease_change(built, bad):
    composed(built)
    async with built.sessions() as session, session.begin():
        await ready.mark(session, built, await ready.logical(session, built))
        old = await proof(session, built)
    async with built.sessions() as session, session.begin():
        evidence = None if bad == "missing" else old
        if bad == "copied":
            evidence = replace(await proof(session, built))
        with pytest.raises((PermissionPublishNotReadyError, KnowledgeOperationPlanConflictError, ValueError)):
            await built.repo.aclaim_next_item(
                session, built.lease, configuration=ready.CONFIG, _move=True, move_projection_evidence=evidence
            )
        item = (await session.execute(sa.select(ready.Item).where(ready.Item.job_id == built.job_id))).scalars().one()
        assert item.state == "pending" and item.attempt == 0 and item.lease_token is None


async def test_missing_cleaned_checkpoint_cannot_ack_success_even_with_valid_marker_and_evidence(built):
    composed(built)
    async with built.sessions() as session, session.begin():
        await ready.mark(session, built, await ready.logical(session, built))
        evidence = await proof(session, built)
        claimed = await claim(session, built, evidence=evidence)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.acomplete_item(
                session,
                claimed.lease,
                configuration=ready.CONFIG,
                succeeded=True,
                _move=True,
                move_projection_evidence=evidence,
            )
    async with built.sessions() as session:
        item = (await session.execute(sa.select(ready.Item).where(ready.Item.job_id == built.job_id))).scalars().one()
        file = await session.get(ready.File, item.file_id)
        assert item.state == "running" and file.status == 4


async def test_native_cleaned_result_file_item_and_counts_ack_together(built):
    composed(built)
    async with built.sessions() as session, session.begin():
        await ready.mark(session, built, await ready.logical(session, built))
    async with built.sessions() as session, session.begin(), session.begin_nested():
        evidence = await proof(session, built)
        claimed = await claim(session, built, evidence=evidence)
        assert await finish(session, built, claimed, evidence=evidence)
        done = await built.repo.afinalize(session, built.lease, configuration=ready.CONFIG, _move=True)
        assert done.state == "succeeded" and done.succeeded_count == 1
        assert (await session.get(ready.File, claimed.item.file_id)).status == 2
    async with built.sessions() as session:
        item = (await session.execute(sa.select(ready.Item).where(ready.Item.job_id == built.job_id))).scalars().one()
        assert item.state == "succeeded" and item.result["source_count"] == 2


async def test_item_guard_never_adopts_a_later_savepoint_for_old_evidence(built):
    composed(built)
    async with built.sessions() as session, session.begin():
        await ready.mark(session, built, await ready.logical(session, built))
        evidence = await proof(session, built)
        claimed = await claim(session, built, evidence=evidence)
    async with built.sessions() as session, session.begin():
        outer = await proof(session, built)
        async with session.begin_nested():
            with pytest.raises((PermissionPublishNotReadyError, ValueError)):
                await built.execution.aguard_item(session, claimed.lease, jobs=built.repo, projection_evidence=outer)


async def test_owner_savepoint_before_p1_rolls_back_file_and_item_when_outer_catches_and_commits(built, monkeypatch):
    composed(built)
    async with built.sessions() as session, session.begin():
        await ready.mark(session, built, await ready.logical(session, built))
        claimed = await claim(session, built)
        await cleaned(session, built, claimed)
    async with built.sessions() as session, session.begin():
        native = session.execute

        async def fail_after_file(statement, *args, **kwargs):
            result = await native(statement, *args, **kwargs)
            if statement.is_update and statement.table.name == ready.File.__tablename__:
                raise RuntimeError("native failure after File UPDATE")
            return result

        try:
            async with session.begin_nested():
                evidence = await proof(session, built)
                monkeypatch.setattr(session, "execute", fail_after_file)
                await built.execution.acomplete_item(
                    session,
                    claimed.lease,
                    jobs=built.repo,
                    projection_evidence=evidence,
                    source_count=2,
                    milvus_count=2,
                    es_count=2,
                    source_digest="1" * 64,
                    target_payload_digest="2" * 64,
                )
        except RuntimeError:
            pass
    async with built.sessions() as session:
        item = (await session.execute(sa.select(ready.Item).where(ready.Item.job_id == built.job_id))).scalars().one()
        assert item.state == "running" and (await session.get(ready.File, item.file_id)).status == 4
        assert (await built.repo.aget_execution(session, built.job_id)).succeeded_count == 0
