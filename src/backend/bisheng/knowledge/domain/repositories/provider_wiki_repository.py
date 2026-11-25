"""Managed Wiki. The injected GET port is bound to the frozen provider instance/KB.

GET never acknowledges a write. Only a writer with its operation-specific target
revision may checkpoint convergence in the transaction that finishes the write.
"""

from dataclasses import dataclass

from sqlalchemy import select, update

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderBinding as Binding,
)
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderGeneration as Generation,
)
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
from bisheng.knowledge.domain.models.provider_control import (
    KnowledgeProviderMapping as Mapping,
)


class WikiUnavailable(ValueError):
    """A resource is unavailable; do not reveal existence or provider identifiers."""


@dataclass(frozen=True)
class WikiScope:
    tenant_id: int
    space_id: int
    instance_id: int | None
    generation: int | None
    remote_scope_id: str | None
    remote_kb_id: str | None
    revision: int
    target: int
    applied: int
    pending: str | None
    state: str


@dataclass(frozen=True)
class WikiObservation:
    scope: WikiScope
    wire: dict


def read_proof(wire, minimum):
    if not isinstance(wire, dict) or wire.get("success") is not True or not isinstance(wire.get("data"), dict):
        return False
    row = wire["data"]
    target, applied = row.get("target_revision"), row.get("applied_revision")
    return (
        type(minimum) is int
        and minimum >= 0
        and type(target) is int
        and type(applied) is int
        and target == applied >= minimum
        and type(row.get("empty")) is bool
        and (target > 0 or row["empty"])
        and row.get("ready") is True
    )


def target_scope(binding: Binding, generation: Generation) -> WikiScope:
    """The new library's own watermark, which a cutover may install.

    Upstream counts source revisions per library, so the retired library's numbers
    are not interchangeable with the target's. A library that has never had a
    confirmed write locally starts at 0/0; only a verified read may raise that.
    """
    return WikiScope(
        binding.tenant_id,
        binding.space_id,
        generation.provider_instance_id,
        generation.generation,
        generation.remote_scope_id,
        generation.remote_kb_id,
        binding.revision,
        0,
        0,
        binding.pending_write_operation_id,
        generation.state,
    )


def verified_target_watermark(binding: Binding, generation: Generation, observation: WikiObservation) -> int | None:
    """The target library's applied revision, or None to keep the read barrier.

    Accepts only a read-only observation bound to the exact frozen target library,
    so a missing, stale or foreign proof can neither zero the watermark nor carry
    the retired library's value over.
    """
    if not isinstance(observation, WikiObservation) or observation.scope != target_scope(binding, generation):
        return None
    if not read_proof(observation.wire, 0):
        return None
    return observation.wire["data"]["applied_revision"]


class WikiControl:
    def __init__(self, sessions=get_async_db_session):
        self.sessions = sessions

    async def scope(self, space_id):
        tenant = get_current_tenant_id()
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(Binding, Generation, Instance.state)
                    .select_from(Binding)
                    .join(
                        Knowledge,
                        (Knowledge.id == Binding.space_id)
                        & (Knowledge.tenant_id == Binding.tenant_id)
                        & (Knowledge.type == KnowledgeTypeEnum.SPACE.value),
                    )
                    .outerjoin(
                        Generation,
                        (Generation.tenant_id == Binding.tenant_id)
                        & (Generation.space_id == Binding.space_id)
                        & (Generation.generation == Binding.active_generation),
                    )
                    .outerjoin(
                        Instance,
                        (Instance.id == Generation.provider_instance_id)
                        & (Instance.tenant_id == Binding.tenant_id)
                        & (Instance.remote_scope_id == Generation.remote_scope_id)
                        & (Instance.provider_key == Binding.provider_key),
                    )
                    .where(Binding.tenant_id == tenant, Binding.space_id == space_id, Binding.provider_key == "weknora")
                )
            ).one_or_none()
            if not row:
                raise WikiUnavailable()
            b, g, instance_state = row
            if b.state == "ready" and (not g or g.state != "ready" or instance_state != "ready"):
                raise WikiUnavailable()
            return WikiScope(
                tenant,
                space_id,
                g.provider_instance_id if g else None,
                g.generation if g else None,
                g.remote_scope_id if g else None,
                g.remote_kb_id if g else None,
                b.revision,
                b.wiki_target_revision,
                b.wiki_applied_revision,
                b.pending_write_operation_id,
                b.state,
            )

    async def source(self, scope, remote):
        async with self.sessions() as session:
            return await session.scalar(
                select(Mapping.local_resource_id)
                .join(
                    KnowledgeFile,
                    (KnowledgeFile.id == Mapping.local_resource_id)
                    & (KnowledgeFile.tenant_id == Mapping.tenant_id)
                    & (KnowledgeFile.knowledge_id == Mapping.space_id)
                    & (KnowledgeFile.file_type == FileType.FILE.value),
                )
                .join(
                    KnowledgeDocument,
                    (KnowledgeDocument.id == Mapping.logical_document_id)
                    & (KnowledgeDocument.knowledge_id == Mapping.space_id)
                    & (KnowledgeDocument.primary_version_id == Mapping.version_id),
                )
                .join(
                    KnowledgeDocumentVersion,
                    (KnowledgeDocumentVersion.id == Mapping.version_id)
                    & (KnowledgeDocumentVersion.document_id == Mapping.logical_document_id)
                    & (KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id)
                    & KnowledgeDocumentVersion.is_primary.is_(True),
                )
                .where(
                    Mapping.tenant_id == get_current_tenant_id(),
                    Mapping.tenant_id == scope.tenant_id,
                    Mapping.space_id == scope.space_id,
                    Mapping.generation == scope.generation,
                    Mapping.resource_type == "file",
                    Mapping.remote_object_id == remote,
                    Mapping.lifecycle_state == "active",
                    Mapping.tombstoned_at.is_(None),
                )
            )

    @staticmethod
    async def require_native_deletion(session, space_id):
        """Never let native purge consume an external binding or its tombstones."""
        row = await session.scalar(
            select(Binding)
            .where(Binding.tenant_id == get_current_tenant_id(), Binding.space_id == space_id)
            .with_for_update()
        )
        if row and (
            row.provider_key != "native"
            or row.active_generation is not None
            or row.pending_write_operation_id is not None
        ):
            raise KnowledgeOperationPlanConflictError(reason="external_deletion_requires_provider_operation")

    @staticmethod
    async def _cas(session, scope, **values):
        match = update(Binding).where(
            Binding.tenant_id == get_current_tenant_id(),
            Binding.tenant_id == scope.tenant_id,
            Binding.space_id == scope.space_id,
            Binding.provider_key == "weknora",
            Binding.active_generation == scope.generation,
            Binding.state == "ready",
            Binding.revision == scope.revision,
            Binding.pending_write_operation_id == scope.pending,
            Binding.wiki_target_revision == scope.target,
            Binding.wiki_applied_revision == scope.applied,
        )
        return (await session.execute(match.values(revision=Binding.revision + 1, **values))).rowcount == 1

    async def begin(self, session, scope, operation_id):
        """Writer calls in same transaction as its durable intent, BEFORE sending."""
        return bool(
            operation_id
            and scope.pending is None
            and scope.target == scope.applied
            and await self._cas(session, scope, pending_write_operation_id=operation_id)
        )

    async def pin(self, session, scope, operation_id, confirmed_target):
        """Only a verified receipt for this write may supply confirmed_target; never infer from a GET."""
        return bool(
            operation_id
            and scope.pending == operation_id
            and scope.target == scope.applied
            and type(confirmed_target) is int
            and confirmed_target > scope.applied
            and await self._cas(session, scope, wiki_target_revision=confirmed_target)
        )

    async def release(self, session, scope, operation_id, observation):
        # The wire envelope carries no KB or operation identity. Bind it to the
        # exact snapshot on which the authenticated read-only port was called.
        if not isinstance(observation, WikiObservation) or observation.scope != scope:
            return False
        proof = observation.wire
        return bool(
            operation_id
            and scope.pending == operation_id
            and scope.target > scope.applied
            and read_proof(proof, scope.target)
            and await self._cas(session, scope, wiki_applied_revision=scope.target, pending_write_operation_id=None)
        )
