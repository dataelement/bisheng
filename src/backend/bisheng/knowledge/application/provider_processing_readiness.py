"""Reconcile provider processing completion (not the original upload ACK)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.provider_processing_readiness_repository import (
    ProcessingReadinessRepository,
    ProcessingTarget,
)


@dataclass(frozen=True, slots=True)
class ProcessingProof:
    """Provider-observed identity + successful indexed content revision."""

    target: ProcessingTarget
    state: str
    content_revision: int


async def reconcile_processed_upload(
    *,
    operation_id: str,
    read_proof: Callable[[ProcessingTarget], Awaitable[ProcessingProof | None]],
    sessions=get_async_db_session,
) -> bool:
    """Worker composition: pass a trusted, read-only scoped provider adapter.

    Never accept proof/target fields from an API caller. A remote exception
    propagates for worker retry; no SQL transaction spans the readback.
    """
    repo = ProcessingReadinessRepository()
    async with sessions() as db:
        frozen = await repo.snapshot(db, operation_id)
    if frozen is None:
        return False
    proof = await read_proof(frozen.target)
    if (
        not isinstance(proof, ProcessingProof)
        or proof.target != frozen.target
        or proof.state != "succeeded"
        or type(proof.content_revision) is not int
        or not 0 < proof.content_revision < 2**31
    ):
        return False
    async with sessions() as db, db.begin():
        return await repo.activate(db, frozen, proof.content_revision)
