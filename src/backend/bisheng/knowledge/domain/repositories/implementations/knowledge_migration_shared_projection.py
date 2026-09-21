"""Shared content/membership convergence at the migration commit boundary."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.contracts.identifiers import CanonicalDocumentId, TenantId
from bisheng.knowledge.domain.contracts.shared_space_storage import ContentDeleteRequest
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_runtime_repository_impl import (
    KnowledgeMigrationRuntimeRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_projection_service import KnowledgeDocumentProjectionService
from bisheng.knowledge.domain.services.knowledge_projection_readiness_service import KnowledgeProjectionReadinessService
from bisheng.knowledge.domain.services.shared_space_content_loader import load_shared_content_from_original
from bisheng.knowledge.rag.shared_space_storage import (
    aresolve_space_shared_routing,
    build_shared_space_components_for_tenant,
)


class KnowledgeMigrationSharedProjection:
    def __init__(self, *, session_factory=None, components_factory=None, content_loader=None):
        self.session_factory = session_factory or get_async_db_session
        self.components_factory = components_factory or build_shared_space_components_for_tenant
        self.content_loader = content_loader or load_shared_content_from_original

    async def validate_source(self, context) -> None:
        if context.unit.source_document_id is None:
            raise RuntimeError("shared migration requires a canonical document")
        tenant_id = int(context.batch.tenant_id)
        for space in [context.target_space, *context.source_spaces.values()]:
            if space.type != KnowledgeTypeEnum.SPACE.value or int(space.tenant_id or 1) != tenant_id:
                raise RuntimeError("migration spaces must share one tenant storage route")
        await aresolve_space_shared_routing(tenant_id, KnowledgeTypeEnum.SPACE.value)

    async def _plan(self, unit):
        if unit.cancelled is not None and unit.cancelled():
            from bisheng.knowledge.domain.services.file_migration.executor import StaleMigrationAttemptError

            raise StaleMigrationAttemptError("migration execution lease was lost")
        async with self.session_factory() as session:
            repository = KnowledgeMigrationRuntimeRepositoryImpl(session)
            plan = await repository.shared_projection_plan(
                unit.unit_id,
                attempt_id=unit.attempt_id,
                execution_token=unit.execution_token,
            )
            # No DB locks are retained during external writes.
            await session.commit()
            return plan

    async def converge_unit(self, unit) -> None:
        plan = await self._plan(unit)
        tenant_id, document_id = plan["tenant_id"], plan["document_id"]
        writer, _ = await asyncio.to_thread(self.components_factory, tenant_id)

        async with self.session_factory() as session:
            files = KnowledgeFileRepositoryImpl(session)
            documents = KnowledgeDocumentRepositoryImpl(session)
            service = KnowledgeDocumentProjectionService(
                session=session,
                file_repository=files,
                document_repository=documents,
                version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
                shared_storage_writer=writer,
                shared_content_chunk_loader=self.content_loader,
                shared_embedding_model_id=writer.schema_spec.embedding_model_id,
            )
            entries = await files.find_distribution_entries_by_document_id(document_id, statuses={"active"})
            if not entries:
                raise RuntimeError("migration destination has no active canonical entry")
            # Snapshot IDs before process_entry commits/rolls back its own session.
            entry_ids = [int(entry.id) for entry in entries if entry.entry_type in {"manager", "publish", "share"}]
            await session.commit()
            for entry_id in entry_ids:
                await self._plan(unit)
                entry = await files.find_by_id(entry_id)
                if entry is not None and entry.projection_status == "failed":
                    # An explicit migration retry may retry an exhausted projection,
                    # but must never steal a live projection lease.
                    await files.request_projection_rebuild(entry_id)
                    await session.commit()
                result = await service.process_entry(
                    tenant_id=tenant_id,
                    entry_id=entry_id,
                    lease_owner=f"migration:{unit.unit_id}:{uuid4().hex}",
                )
                if result.status not in {"ready", "not_claimed"}:
                    raise RuntimeError(f"shared migration projection {entry_id}: {result.status}")
            readiness = await KnowledgeProjectionReadinessService(
                file_repository=files,
                document_repository=documents,
            ).get_content_membership_readiness(
                tenant_id=TenantId(tenant_id),
                canonical_document_id=CanonicalDocumentId(document_id),
            )
            if not readiness.ready:
                raise RuntimeError(f"shared migration projection is not ready: {readiness.reason}")
            await session.commit()

        # Only confirmed, now-absent canonical documents may be tombstoned.
        # A source document is never deleted merely because its old file moved.
        current = await self._plan(unit)
        for overwritten_id in current["deleted_document_ids"]:
            await writer.delete_content(
                ContentDeleteRequest(
                    tenant_id=TenantId(tenant_id),
                    canonical_document_id=CanonicalDocumentId(overwritten_id),
                )
            )
        await self._plan(unit)
