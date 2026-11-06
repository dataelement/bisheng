"""T735: schema revision/digest participate in actual J1 leases and recovery."""

from dataclasses import replace

import pytest

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
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
    assert result is None or result is False or result.job.state == "obsolete" or result.state == "obsolete"


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
