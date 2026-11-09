"""T991: native logical retry, typed receipts and unchanged original reset semantics."""

from copy import deepcopy

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect

from bisheng.common.errcode.knowledge import (
    KnowledgeIdempotencyConflictError,
    KnowledgeProcessingJobNotRetryableError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt as Retry
from bisheng.knowledge.domain.schemas.processing_job_acceptance import ProcessingConfiguration, _digest
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_job_repo import clock as clock
from test.knowledge_unification.test_job_repo import configuration as configuration
from test.knowledge_unification.test_job_repo import create as original_create
from test.knowledge_unification.test_job_repo import job_session as job_session
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant
from test.knowledge_unification.test_job_repo import repository as repository
from test.knowledge_unification.test_move_job_ready import CONFIG, Item, Job, logical, mark, pipeline
from test.knowledge_unification.test_move_job_ready import accepted as accepted
from test.knowledge_unification.test_move_job_ready import moving as moving
from test.knowledge_unification.test_move_job_ready import store as store
from test.knowledge_unification.test_move_job_ready import tenant as tenant
from test.knowledge_unification.test_move_job_reservation import actor


def retry_actor(kind="service_account", ident=50):
    value = actor(kind, ident)
    value["actor_user_id"] = 12
    return value


async def fail(session, built):
    revision = (await session.execute(sa.select(Job.revision).where(Job.id == built.job_id))).scalar_one()
    return await built.repo.afail_attempt(
        session, built.job_id, expected_job_revision=revision, error_code=10994, lease=built.lease
    )


def retry_args(revision, **changes):
    return {
        "idempotency_key": "explicit-retry",
        "expected_job_revision": revision,
        "actor_user_id": 12,
        "actor_reference": retry_actor(),
        "configuration": CONFIG,
        **changes,
    }


@pytest.mark.parametrize("zero", ["empty", "skipped"])
async def test_zero_logical_failure_retries_and_fresh_native_k1_p1_can_finish(
    moving, accepted, monkeypatch, actual_processing_task, zero
):
    built = await pipeline(moving, accepted, monkeypatch, zero=zero)
    async with built.sessions() as session, session.begin():
        failed = await fail(session, built)
        original = (
            failed.actor_user_id,
            deepcopy(failed.actor_reference),
            failed.actor_subject_type,
            failed.actor_subject_id,
        )
        args = retry_args(failed.revision)
        eligibility = await built.repo.aretry_eligibility(session, built.job_id)
        assert eligibility.retryable and not eligibility.finalize_only
        result = await built.repo.aretry_failed(session, built.job_id, **args)
        assert not result.reused and result.job.state == "accepted" and result.job.pending_dispatch
        assert result.job.total_count == result.job.pending_count == 0 and result.job.move_logical_marker is None
        receipt = (await session.execute(sa.select(Retry))).scalars().one()
        assert receipt.item_count == 0 and (receipt.actor_subject_type, receipt.actor_subject_id) == (
            "service_account",
            50,
        )
        assert receipt.request_hash == _digest(
            {
                "tenant_id": 101,
                "job_id": built.job_id,
                "expected_job_revision": args["expected_job_revision"],
                "actor_user_id": 12,
                "actor_reference": retry_actor(),
            }
        )
        assert (
            result.job.actor_user_id,
            result.job.actor_reference,
            result.job.actor_subject_type,
            result.job.actor_subject_id,
        ) == original
        assert await built.repo.alatest_retry_actor(session, built.job_id) == retry_actor()
        assert await built.repo.aoperator_membership(session, job_id=built.job_id, operator_ids=(7, 50)) == frozenset(
            {7, 50}
        )
    async with built.sessions() as session, session.begin():
        built.lease = await built.repo.aclaim(session, built.job_id, configuration=CONFIG)
        assert built.lease is not None
        final = await mark(session, built, await logical(session, built))
        assert final.state == "succeeded"
        assert not (await built.repo.aretry_eligibility(session, built.job_id)).retryable


async def test_retry_replay_keeps_original_hash_and_revision_cas(moving, accepted, monkeypatch, actual_processing_task):
    built = await pipeline(moving, accepted, monkeypatch, zero="empty")
    async with built.sessions() as session, session.begin():
        failed = await fail(session, built)
        args = retry_args(failed.revision)
        assert not (await built.repo.aretry_failed(session, built.job_id, **args)).reused
        assert (await built.repo.aretry_failed(session, built.job_id, **args)).reused
        for changes in ({"actor_reference": retry_actor("user", 50)}, {"expected_job_revision": failed.revision}):
            with pytest.raises(KnowledgeIdempotencyConflictError):
                await built.repo.aretry_failed(session, built.job_id, **(args | changes))
        with pytest.raises(KnowledgeProcessingJobNotRetryableError):
            await built.repo.aretry_failed(session, built.job_id, **(args | {"idempotency_key": "other-key"}))


@pytest.mark.parametrize("bad", ["null", "wrong-type", "wrong-id"])
async def test_old_same_key_receipt_cannot_gain_a_guessed_subject(
    moving, accepted, monkeypatch, actual_processing_task, bad
):
    built = await pipeline(moving, accepted, monkeypatch, zero="empty")
    async with built.sessions() as session, session.begin():
        failed = await fail(session, built)
        args = retry_args(failed.revision)
        await built.repo.aretry_failed(session, built.job_id, **args)
        values = {
            "null": {"actor_subject_type": None, "actor_subject_id": None},
            "wrong-type": {"actor_subject_type": "user"},
            "wrong-id": {"actor_subject_id": 12},
        }[bad]
        await session.execute(sa.update(Retry.__table__).where(Retry.job_id == built.job_id).values(**values))
        with pytest.raises(KnowledgeIdempotencyConflictError):
            await built.repo.aretry_failed(session, built.job_id, **args)


@pytest.mark.parametrize("ready", [False, True])
async def test_nonzero_failure_retry_preserves_original_actor_and_all_success_bytes(
    moving, accepted, monkeypatch, actual_processing_task, ready
):
    built = await pipeline(moving, accepted, monkeypatch, count=2)
    async with built.sessions() as session, session.begin():
        saved = None
        if ready:
            await mark(session, built, await logical(session, built))
            done = await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)
            assert await built.repo.acomplete_item(
                session, done.lease, configuration=CONFIG, succeeded=True, result={"native": [0, False]}
            )
            saved = deepcopy(done.item.model_dump())
        failed = await fail(session, built)
        marker = deepcopy(failed.move_logical_marker)
        source_actor = deepcopy(failed.actor_reference)
        result = await built.repo.aretry_failed(
            session, built.job_id, **retry_args(failed.revision, actor_reference=retry_actor("user", 17))
        )
        assert result.job.move_logical_marker == marker and result.job.actor_reference == source_actor
        receipt = (await session.execute(sa.select(Retry))).scalars().one()
        assert (receipt.actor_subject_type, receipt.actor_subject_id) == ("user", 17)
        assert receipt.item_count == (1 if ready else 2)
        if saved is not None:
            assert (await session.get(Item, saved["id"])).model_dump() == saved


async def test_ready_finalize_only_reuses_original_successes_without_new_logical_receipt(
    moving, accepted, monkeypatch, actual_processing_task
):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        await mark(session, built, await logical(session, built))
        done = await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)
        await built.repo.acomplete_item(session, done.lease, configuration=CONFIG, succeeded=True)
        snapshot = deepcopy(done.item.model_dump())
        failed = await fail(session, built)
        eligibility = await built.repo.aretry_eligibility(session, built.job_id)
        assert eligibility.retryable and eligibility.finalize_only
        await built.repo.aretry_failed(session, built.job_id, **retry_args(failed.revision))
        assert (await session.get(Item, done.item.id)).model_dump() == snapshot
        receipt = (await session.execute(sa.select(Retry))).scalars().one()
        assert receipt.item_count == 0 and receipt.actor_subject_id == 50


@pytest.mark.parametrize(
    "bad", ["false", "true", "scope", "total", "stored-success", "actual-success", "running", "bypass", "foreign"]
)
async def test_unproved_or_wrong_scope_retry_facts_fail_closed(
    moving, accepted, monkeypatch, actual_processing_task, bad
):
    from contextlib import nullcontext

    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        failed = await fail(session, built)
        revision = failed.revision
        if bad in ("false", "true"):
            await session.execute(
                sa.update(Job.__table__).where(Job.id == built.job_id).values(move_logical_marker=bad == "true")
            )
        elif bad == "scope":
            p = deepcopy(failed.parameters)
            p.pop("source_space_id")
            await session.execute(sa.update(Job.__table__).where(Job.id == built.job_id).values(parameters=p))
        elif bad in ("total", "stored-success"):
            await session.execute(
                sa.update(Job.__table__)
                .where(Job.id == built.job_id)
                .values(**{"total_count" if bad == "total" else "succeeded_count": 2 if bad == "total" else 1})
            )
        elif bad in ("actual-success", "running"):
            await session.execute(
                sa.update(Item.__table__)
                .where(Item.job_id == built.job_id)
                .values(state="succeeded" if bad == "actual-success" else "running")
            )
        token = set_current_tenant_id(202) if bad == "foreign" else None
        try:
            with bypass_tenant_filter() if bad == "bypass" else nullcontext():
                if bad == "running":
                    assert not (await built.repo.aretry_eligibility(session, built.job_id)).retryable
                else:
                    with pytest.raises(Exception) as failure:
                        await built.repo.aretry_eligibility(session, built.job_id)
                    assert type(failure.value).__module__.startswith("bisheng.common.errcode")
                with pytest.raises(Exception) as failure:
                    await built.repo.aretry_failed(session, built.job_id, **retry_args(revision))
                assert type(failure.value).__module__.startswith("bisheng.common.errcode")
        finally:
            if token is not None:
                current_tenant_id.reset(token)


async def test_read_eligibility_preserves_already_loaded_public_manifest(
    moving, accepted, monkeypatch, actual_processing_task
):
    built = await pipeline(moving, accepted, monkeypatch, zero="empty")
    async with built.sessions() as session, session.begin():
        await fail(session, built)
        public = await built.repo.aget(session, built.job_id)
        before = public.scope_manifest
        assert "scope_manifest" not in inspect(public).unloaded
        assert (await built.repo.aretry_eligibility(session, built.job_id)).retryable
        assert public.scope_manifest is before and "scope_manifest" not in inspect(public).unloaded


@pytest.mark.parametrize("changed", ["revision", "generation"])
async def test_original_configuration_mismatch_still_records_obsolete_without_receipt(
    moving, accepted, monkeypatch, actual_processing_task, changed
):
    built = await pipeline(moving, accepted, monkeypatch, zero="empty")
    async with built.sessions() as session, session.begin():
        failed = await fail(session, built)
        config = (
            ProcessingConfiguration(99, "generation-4")
            if changed == "revision"
            else ProcessingConfiguration(4, "other-generation")
        )
        result = await built.repo.aretry_failed(
            session, built.job_id, **retry_args(failed.revision, configuration=config)
        )
        assert result.job.state == "obsolete" and not result.job.pending_dispatch
        assert not (await session.execute(sa.select(Retry))).all()


async def test_zero_ready_failure_is_not_mistaken_for_finalize_only_retry(moving, accepted, monkeypatch):
    built = await pipeline(moving, accepted, monkeypatch, zero="empty")
    async with built.sessions() as session, session.begin():
        await mark(session, built, await logical(session, built))
        await session.execute(
            sa.update(Job.__table__).where(Job.id == built.job_id).values(state="failed", error_code=10994)
        )
        eligibility = await built.repo.aretry_eligibility(session, built.job_id)
        assert not eligibility.retryable and not eligibility.finalize_only
        revision = (await session.execute(sa.select(Job.revision).where(Job.id == built.job_id))).scalar_one()
        with pytest.raises(KnowledgeProcessingJobNotRetryableError):
            await built.repo.aretry_failed(session, built.job_id, **retry_args(revision))


@pytest.mark.parametrize("kind", ["embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change"])
async def test_four_original_read_projections_do_not_gain_move_json_queries(
    job_session, repository, configuration, kind
):
    result = await original_create(repository, job_session, configuration, kind=kind)
    result.job.state = "failed"
    await job_session.execute(sa.update(Item.__table__).where(Item.job_id == result.job.id).values(state="failed"))
    await job_session.flush()
    statements = []
    sa.event.listen(job_session.get_bind(), "before_cursor_execute", lambda _c, _cu, sql, *_: statements.append(sql))
    assert (await repository.aretry_eligibility(job_session, result.job.id)).retryable
    assert all(
        "parameters" not in sql.partition("FROM")[0]
        and "move_logical_marker" not in sql.partition("FROM")[0]
        and "processing_snapshot" not in sql.partition("FROM")[0]
        for sql in statements
    )
