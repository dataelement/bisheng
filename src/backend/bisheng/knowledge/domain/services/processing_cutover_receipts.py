"""Private same-operation cutover evidence, shared by Owner and repository.

The authority invokes its bound business Owner; it has no issue(before, after)
entry point. Values or a copied dataclass alone never confer authority.
"""

from dataclasses import dataclass
from inspect import ismethod
from weakref import WeakKeyDictionary, ref

from sqlalchemy import inspect

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.resource_reference.application.contracts import TransactionIdentity


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _CutoverReceipt:
    job_id: str
    operation_id: str
    before: tuple[int, str | None]
    after: tuple[int, str | None]


_issued: WeakKeyDictionary = WeakKeyDictionary()


def _job_facts(job, lease):
    if (
        job.kind != "embedding_rebuild"
        or job.tenant_id != get_current_tenant_id()
        or job.state != "running"
        or job.id != lease.job_id
        or job.lease_token != lease.lease_token
        or job.claim_generation != lease.claim_generation
        or job.lease_until is None
        or type(job.accepted_model_config_revision) is not int
        or job.accepted_model_config_revision < 0
        or job.expected_model_config_revision != job.accepted_model_config_revision
        or not isinstance(job.parameters.get("operation_id"), str)
        or not job.parameters["operation_id"]
    ):
        raise ResourceReferenceInvalidError(reason="processing_cutover_original_lease_required")
    return (
        job.id,
        job.tenant_id,
        job.space_id,
        job.parameters["operation_id"],
        job.expected_model_config_revision,
        job.expected_index_generation,
        job.accepted_model_config_revision,
        job.revision,
        job.lease_token,
        job.claim_generation,
    )


def _row_facts(session, row):
    if not isinstance(row, Knowledge):
        raise ResourceReferenceInvalidError(reason="processing_cutover_business_result_required")
    state = inspect(row)
    if not state.persistent or state.session is not getattr(session, "sync_session", session):
        raise ResourceReferenceInvalidError(reason="processing_cutover_business_session_required")
    return (
        row.id,
        row.tenant_id,
        row.model,
        row.model_config_revision,
        row.index_generation,
        row.model_transition,
        row.state,
    )


class _ProcessingCutoverAuthority:
    """Owner-private capability: its only issuance path executes the Owner."""

    def __init__(self, owner):
        callback = getattr(owner, "_aperform_model_cutover", None)
        if not ismethod(callback) or callback.__self__ is not owner:
            raise TypeError("cutover requires its bound business Owner")
        self._owner = owner
        self._callback = callback

    async def afinalize(self, session, job, lease):
        transaction = TransactionIdentity.capture(session)
        before = _job_facts(job, lease)
        state = inspect(job)
        if not state.persistent or state.session is not getattr(session, "sync_session", session):
            raise ResourceReferenceInvalidError(reason="processing_cutover_job_session_required")
        row = await self._callback(session, job, lease)
        transaction.assert_current(session)
        actual = _row_facts(session, row)
        if (
            _job_facts(job, lease) != before
            or actual[0:2] != (job.space_id, job.tenant_id)
            or actual[3] != before[4] + 1
            or actual[4] != before[5]
            or actual[5] is not None
            or actual[6] != 1
        ):
            raise ResourceReferenceInvalidError(reason="processing_cutover_business_result_changed")
        receipt = _CutoverReceipt(
            job.id,
            before[3],
            (before[4], before[5]),
            (actual[3], actual[4]),
        )
        _issued[receipt] = (
            ref(receipt),
            transaction,
            self,
            job,
            lease,
            before,
            row,
            actual,
            (receipt.job_id, receipt.operation_id, receipt.before, receipt.after),
        )
        return receipt


def consume_cutover_receipt(session, receipt, job, lease) -> tuple[int, str | None]:
    registered = _issued.get(receipt) if isinstance(receipt, _CutoverReceipt) else None
    try:
        if registered is None or registered[0]() is not receipt or registered[3] is not job:
            raise ValueError("receipt was not issued for this job")
        registered[1].assert_current(session)
        if (
            _job_facts(job, lease) != registered[5]
            or _row_facts(session, registered[6]) != registered[7]
            or (receipt.job_id, receipt.operation_id, receipt.before, receipt.after) != registered[8]
        ):
            raise ValueError("receipt context changed")
    except (TypeError, ValueError) as error:
        raise ResourceReferenceInvalidError(reason="processing_cutover_receipt_invalid") from error
    del _issued[receipt]
    return receipt.after
