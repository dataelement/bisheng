"""Read the provider's own processing outcome for one frozen upload.

The upload receipt only proves acceptance; WeKnora finishes parsing, indexing
and enrichment afterwards. Activation therefore needs an independent readback
of the remote document, bound to the identity this deployment froze.
"""

from urllib.parse import quote

from loguru import logger
from sqlalchemy import select

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_external_token import provider_external_identity
from bisheng.knowledge.application.provider_processing_readiness import ProcessingProof
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable, instance_client
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderGeneration as Generation
from bisheng.knowledge.infrastructure.providers.registry import PortContext

# WeKnora parse states that will never become completed for this version.
_REJECTED = frozenset({"failed", "cancelled", "deleting"})
# States that are still in flight: no conclusion, so the file stays queued.
_IN_FLIGHT = frozenset({"pending", "processing", "finalizing"})


async def _next_content_revision(target) -> int | None:
    """A local, monotonic revision for the proof that just succeeded.

    The provider has no content revision; readiness only needs a value that
    grows so `activate` can advance `generation.content_revision` once.
    """
    async with get_async_db_session() as session:
        current = await session.scalar(
            select(Generation.content_revision).where(
                Generation.tenant_id == target.tenant_id,
                Generation.space_id == target.space_id,
                Generation.generation == target.generation,
            )
        )
    if type(current) is not int or current < 0 or current >= 2**31 - 1:
        return None
    return current + 1


async def read_weknora_processing_proof(target, *, actor_user_id: int) -> ProcessingProof | None:
    """Tenant-scoped readback of the remote document this deployment uploaded.

    Returns ``None`` whenever the remote state is not yet conclusive, so the
    caller simply retries on its next scan. A rejected remote document is
    reported so the visible file stops claiming to be queued.
    """
    if get_current_tenant_id() != target.tenant_id:
        raise ProviderFeatureUnavailable()
    context = PortContext(
        target.tenant_id,
        target.space_id,
        "weknora",
        "read",
        target.instance_id,
        target.generation,
        target.remote_scope_id,
        target.remote_kb_id,
    )
    with provider_external_identity(actor_user_id):
        async with instance_client(context) as client:
            response = await client.get("knowledge/" + quote(target.remote_id, safe=""))
    if response.status_code == 404:
        # Not yet visible remotely; never treat a miss as a terminal state.
        return None
    if response.status_code != 200:
        logger.warning(
            "provider processing readback unavailable space={} file={} status={}",
            target.space_id,
            target.file_id,
            response.status_code,
        )
        return None
    try:
        envelope = response.json()
    except ValueError:
        return None
    row = envelope.get("data") if isinstance(envelope, dict) and envelope.get("success") is True else None
    if not isinstance(row, dict):
        return None
    if (
        row.get("id") != target.remote_id
        or row.get("knowledge_base_id") != target.remote_kb_id
        or str(row.get("tenant_id")) != target.remote_scope_id
    ):
        # A different document means this readback cannot prove anything.
        logger.warning(
            "provider processing readback identity mismatch space={} file={}", target.space_id, target.file_id
        )
        return None
    state = row.get("parse_status")
    if state == "completed":
        revision = await _next_content_revision(target)
        if revision is None:
            return None
        return ProcessingProof(target, "succeeded", revision)
    if state in _REJECTED:
        return ProcessingProof(target, "failed", 0)
    if state in _IN_FLIGHT or not state:
        return None
    # An unknown new state is not proof of anything; keep the file queued.
    return None
