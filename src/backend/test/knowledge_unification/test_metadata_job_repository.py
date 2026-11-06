"""T735: schema revision/digest participate in actual J1 leases and recovery."""

import json
from dataclasses import replace

import pytest
from sqlalchemy import event, update
from sqlalchemy.exc import InvalidRequestError
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeIdempotencyConflictError, ResourceReferenceInvalidError
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingConfiguration
from test.knowledge_unification import test_job_repo as fixtures

job_tenant, job_session, clock = fixtures.job_tenant, fixtures.job_session, fixtures.clock
repository, configuration = fixtures.repository, fixtures.configuration


def metadata_configuration(revision=1, digest="a" * 64):
    return ProcessingConfiguration(7, "index-7", metadata_schema_revision=revision, metadata_schema_digest=digest)


async def created(repository, session):
    config = metadata_configuration()
    result = await fixtures.create(
        repository,
        session,
        config,
        kind="metadata_schema_change",
        parameters={
            "metadata_schema_revision": 1,
            "metadata_schema_digest": "a" * 64,
        },
    )
    return result.job, config


@pytest.mark.parametrize(
    "revision,digest", [(True, "a" * 64), (-1, "a" * 64), (1, "broken"), (None, "a" * 64), (1, None)]
)
def test_schema_configuration_is_optional_pair_with_strict_closed_facts(revision, digest):
    with pytest.raises(ValueError):
        metadata_configuration(revision, digest)


@pytest.mark.parametrize("changed", ["revision", "digest", "missing", "model", "generation"])
async def test_actual_claim_obsoletes_metadata_job_with_missing_or_changed_evidence(job_session, repository, changed):
    job, config = await created(repository, job_session)
    value = {
        "revision": lambda: replace(config, metadata_schema_revision=3),
        "digest": lambda: replace(config, metadata_schema_digest="b" * 64),
        "missing": lambda: ProcessingConfiguration(7, "index-7"),
        "model": lambda: replace(config, model_config_revision=8),
        "generation": lambda: replace(config, index_generation="new-generation"),
    }[changed]()
    assert await repository.aclaim(job_session, job.id, configuration=value) is None
    assert job.state == "obsolete" and not job.pending_dispatch and job.finished_at
    await job_session.commit()
    assert (await repository.aget(job_session, job.id)).state == "obsolete"


@pytest.mark.parametrize("operation", ["renew", "claim_item", "renew_item", "complete", "finalize", "retry"])
async def test_schema_aba_is_checked_at_each_real_leased_transition(job_session, repository, operation):
    job, config = await created(repository, job_session)
    lease = await repository.aclaim(job_session, job.id, configuration=config)
    claimed = await repository.aclaim_next_item(job_session, lease, configuration=config)
    if operation == "retry":
        await repository.acomplete_item(
            job_session, claimed.lease, configuration=config, succeeded=False, error_code=10915
        )
        second = await repository.aclaim_next_item(job_session, lease, configuration=config)
        await repository.acomplete_item(
            job_session, second.lease, configuration=config, succeeded=False, error_code=10915
        )
        await repository.afinalize(job_session, lease, configuration=config)
    stale = replace(config, metadata_schema_revision=3)
    if operation == "renew":
        result = await repository.arenew(job_session, lease, configuration=stale)
    elif operation == "claim_item":
        result = await repository.aclaim_next_item(job_session, lease, configuration=stale)
    elif operation == "renew_item":
        result = await repository.arenew_item(job_session, claimed.lease, configuration=stale)
    elif operation == "complete":
        result = await repository.acomplete_item(job_session, claimed.lease, configuration=stale, succeeded=True)
    elif operation == "finalize":
        result = await repository.afinalize(job_session, lease, configuration=stale)
    else:
        result = await repository.aretry_failed(
            job_session,
            job.id,
            idempotency_key="retry-metadata",
            expected_job_revision=job.revision,
            actor_user_id=11,
            actor_reference=job.actor_reference,
            configuration=stale,
        )
    assert job.state == "obsolete" and not job.pending_dispatch
    assert result is None or result is False or getattr(result, "job", result).state == "obsolete"


async def test_same_schema_retry_preserves_successful_items_and_only_requeues_failure(job_session, repository):
    job, config = await created(repository, job_session)
    lease = await repository.aclaim(job_session, job.id, configuration=config)
    success = await repository.aclaim_next_item(job_session, lease, configuration=config)
    await repository.acomplete_item(
        job_session, success.lease, configuration=config, succeeded=True, result={"kept": 7}
    )
    failed = await repository.aclaim_next_item(job_session, lease, configuration=config)
    await repository.acomplete_item(job_session, failed.lease, configuration=config, succeeded=False, error_code=10915)
    await repository.afinalize(job_session, lease, configuration=config)
    original_attempt = success.item.attempt
    retried = await repository.aretry_failed(
        job_session,
        job.id,
        idempotency_key="fresh-authorized-retry",
        expected_job_revision=job.revision,
        actor_user_id=11,
        actor_reference=job.actor_reference,
        configuration=config,
    )
    assert retried.job.state == "accepted"
    assert (
        success.item.state == "succeeded"
        and success.item.result == {"kept": 7}
        and success.item.attempt == original_attempt
    )
    next_lease = await repository.aclaim(job_session, job.id, configuration=config)
    assert (await repository.aclaim_next_item(job_session, next_lease, configuration=config)).item.id == failed.item.id


@pytest.mark.parametrize("kind", ["embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change"])
async def test_only_metadata_with_private_sql_completion_may_have_no_items(
    job_session, repository, configuration, kind
):
    error = ResourceReferenceInvalidError if kind == "metadata_schema_change" else ValueError
    with pytest.raises(error):
        await fixtures.create(
            repository,
            job_session,
            metadata_configuration() if kind == "metadata_schema_change" else configuration,
            kind=kind,
            items=[],
        )


async def test_other_kinds_do_not_expire_on_metadata_changes(job_session, repository, configuration):
    job = (await fixtures.create(repository, job_session, configuration)).job
    lease = await repository.aclaim(job_session, job.id, configuration=metadata_configuration(99, "b" * 64))
    assert lease is not None and job.state == "running"


@pytest.mark.parametrize("evidence", [{}, [], "legacy-text"])
async def test_old_trial_metadata_without_object_evidence_is_persistently_obsolete(job_session, repository, evidence):
    job, config = await created(repository, job_session)
    job.parameters = evidence
    await job_session.flush()
    assert await repository.aclaim(job_session, job.id, configuration=config) is None
    assert job.state == "obsolete" and job.obsolete_reason == "metadata_schema_evidence_missing"


@pytest.fixture
def json_meter(monkeypatch):
    counts = {"manifest_bytes": 0, "manifest_reads": 0, "snapshot_bytes": 0, "snapshot_reads": 0}
    original = JsonType.process_result_value

    def measured(self, value, dialect):
        parsed = original(self, value, dialect)
        size = len(value.encode()) if isinstance(value, str) else len(json.dumps(value).encode())
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and "expected_space_id" in parsed[0]:
            counts["manifest_bytes"] += size
            counts["manifest_reads"] += 1
        elif isinstance(parsed, dict) and parsed.get("mode") == "metadata_schema_change":
            counts["snapshot_bytes"] += size
            counts["snapshot_reads"] += 1
        return parsed

    monkeypatch.setattr(JsonType, "process_result_value", measured)
    return counts


def large_items(count=401):
    return [
        replace(
            fixtures.item(number),
            processing_snapshot={"mode": "metadata_schema_change", "body": "frozen-" + "x" * 4096},
        )
        for number in range(1, count + 1)
    ]


async def create_large(repository, session):
    config = metadata_configuration()
    result = await fixtures.create(
        repository,
        session,
        config,
        kind="metadata_schema_change",
        items=large_items(),
        parameters={"metadata_schema_revision": 1, "metadata_schema_digest": "a" * 64},
    )
    return result.job, config


async def test_metadata_manifest_retains_ids_and_snapshot_digest_without_duplicate_value_payload(
    job_session, repository
):
    job, config = await create_large(repository, job_session)
    manifest = (
        await job_session.exec(select(KnowledgeProcessingJob.scope_manifest).where(KnowledgeProcessingJob.id == job.id))
    ).one()
    assert len(manifest) == 401
    assert [value["file_id"] for value in manifest] == list(range(1, 402))
    assert all(
        set(value)
        == {
            "file_id",
            "document_id",
            "version_id",
            "expected_space_id",
            "expected_parent_id",
            "processing_snapshot_digest",
        }
        for value in manifest
    )
    assert len(json.dumps(manifest).encode()) < 401 * 260
    stored = (
        await job_session.exec(select(KnowledgeProcessingItem).where(KnowledgeProcessingItem.job_id == job.id).limit(1))
    ).one()
    assert stored.processing_snapshot == large_items()[0].processing_snapshot
    changed = large_items()
    changed[0] = replace(changed[0], processing_snapshot={"mode": "metadata_schema_change", "body": "changed"})
    with pytest.raises(KnowledgeIdempotencyConflictError):
        await fixtures.create(
            repository, job_session, config, kind="metadata_schema_change", items=changed, parameters=job.parameters
        )


async def test_metadata_execution_transitions_never_transfer_full_manifest_or_remaining_snapshots(
    job_session, repository, json_meter
):
    job, config = await create_large(repository, job_session)
    job_id = job.id
    await job_session.commit()
    job_session.expunge_all()
    statements = []
    engine = job_session.bind.sync_engine

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        json_meter.update(dict.fromkeys(json_meter, 0))
        lease = await repository.aclaim(job_session, job_id, configuration=config)
        for number in range(10):
            lease = await repository.arenew(job_session, lease, configuration=config)
            claimed = await repository.aclaim_next_item(job_session, lease, configuration=config)
            renewed = await repository.arenew_item(job_session, claimed.lease, configuration=config)
            assert renewed is not None
            assert await repository.asave_checkpoint(
                job_session, renewed, configuration=config, step="indexed", checkpoint={"count": number}
            )
            assert await repository.acomplete_item(
                job_session, renewed, configuration=config, succeeded=number != 9, error_code=10915
            )
        await job_session.exec(
            update(KnowledgeProcessingItem)
            .where(KnowledgeProcessingItem.job_id == job_id, KnowledgeProcessingItem.state == "pending")
            .values(state="failed")
        )
        finished = await repository.afinalize(job_session, lease, configuration=config)
        assert finished.state == "partial_failed"
        assert (await repository.aretry_eligibility(job_session, job_id)).retryable
        retried = await repository.aretry_failed(
            job_session,
            job_id,
            idempotency_key="large-retry",
            expected_job_revision=finished.revision,
            actor_user_id=11,
            actor_reference=finished.actor_reference,
            configuration=config,
        )
        assert retried.job.state == "accepted"
        await repository.alatest_retry_actor(job_session, job_id)
        assert json_meter["manifest_reads"] == 0, json_meter
        assert json_meter["snapshot_reads"] <= 10 * 5, json_meter
        assert json_meter["snapshot_bytes"] < 10 * 5 * 5000, json_meter
        assert all("knowledge_processing_job.scope_manifest" not in sql for sql in statements)
        print({"items": 401, "processed": 10, **json_meter})
    finally:
        event.remove(engine, "before_cursor_execute", capture)


async def test_execution_read_raiseloads_manifest_even_after_same_session_full_read(job_session, repository):
    job, _ = await create_large(repository, job_session)
    assert len(job.scope_manifest) == 401
    light = await repository.aget_execution(job_session, job.id)
    with pytest.raises(InvalidRequestError):
        _ = light.scope_manifest
