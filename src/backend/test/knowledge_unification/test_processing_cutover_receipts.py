"""T640: private receipt authority binds a real SQL transaction and lease.

This domain test isolates the business callback; the real Model/R2 Owner
composition is exercised separately by test_job_cutover_receipt.
"""

from dataclasses import replace

import pytest

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.processing_cutover_receipts import (
    _ProcessingCutoverAuthority,
    consume_cutover_receipt,
)
from test.knowledge_unification import test_job_repo as fixtures

job_tenant = fixtures.job_tenant
job_session = fixtures.job_session
clock = fixtures.clock
repository = fixtures.repository
configuration = fixtures.configuration


class SqlCutover:
    def __init__(self):
        self.calls = 0

    async def _aperform_model_cutover(self, session, job, lease):
        self.calls += 1
        row = await session.get(Knowledge, job.space_id)
        row.model_config_revision = job.expected_model_config_revision + 1
        row.index_generation = job.expected_index_generation
        row.model_transition = None
        row.state = 1
        await session.flush()
        return row


async def receipt(repository, session, configuration):
    created = await fixtures.create(repository, session, configuration, parameters={"operation_id": "own"})
    lease = await repository.aclaim(session, created.job.id, configuration=configuration)
    owner = SqlCutover()
    authority = _ProcessingCutoverAuthority(owner)
    result = await authority.afinalize(session, created.job, lease)
    return created.job, lease, owner, result


async def test_authority_calls_business_callback_and_receipt_is_consumed_once(job_session, repository, configuration):
    job, lease, owner, issued = await receipt(repository, job_session, configuration)
    assert owner.calls == 1
    after = consume_cutover_receipt(job_session, issued, job, lease)
    assert after == (8, "index-7")
    assert job.accepted_model_config_revision == 7
    with pytest.raises(ResourceReferenceInvalidError):
        consume_cutover_receipt(job_session, issued, job, lease)


@pytest.mark.parametrize("invalid", ["clone", "lease", "operation", "job", "before", "row"])
async def test_receipt_values_and_object_identity_cannot_be_rebound(job_session, repository, configuration, invalid):
    job, lease, _, issued = await receipt(repository, job_session, configuration)
    if invalid == "clone":
        issued = replace(issued)
    elif invalid == "lease":
        lease = replace(lease, lease_token="other")
    elif invalid == "operation":
        job.parameters = {"operation_id": "other"}
    elif invalid == "job":
        job.id = "other"
    elif invalid == "before":
        job.expected_model_config_revision += 1
    else:
        row = await job_session.get(Knowledge, job.space_id)
        row.index_generation = "new-intent"
    with pytest.raises(ResourceReferenceInvalidError):
        consume_cutover_receipt(job_session, issued, job, lease)


async def test_receipt_from_prior_transaction_cannot_survive_commit(job_session, repository, configuration):
    job, lease, _, issued = await receipt(repository, job_session, configuration)
    await job_session.commit()
    await job_session.get(Knowledge, 1)
    with pytest.raises(ResourceReferenceInvalidError):
        consume_cutover_receipt(job_session, issued, job, lease)


async def test_missing_acceptance_evidence_never_invokes_cutover(job_session, repository, configuration):
    created = await fixtures.create(repository, job_session, configuration, parameters={"operation_id": "own"})
    lease = await repository.aclaim(job_session, created.job.id, configuration=configuration)
    created.job.accepted_model_config_revision = None
    owner = SqlCutover()
    with pytest.raises(ResourceReferenceInvalidError):
        await _ProcessingCutoverAuthority(owner).afinalize(job_session, created.job, lease)
    assert owner.calls == 0
