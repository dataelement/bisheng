"""Shared content/membership convergence at the migration commit boundary."""

from __future__ import annotations

import asyncio

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.contracts.identifiers import CanonicalDocumentId, TenantId
from bisheng.knowledge.domain.contracts.shared_space_storage import ContentDeleteRequest
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_runtime_repository_impl import (
    KnowledgeMigrationRuntimeRepositoryImpl,
)
from bisheng.knowledge.rag.shared_space_storage import (
    aresolve_space_shared_routing,
    build_shared_space_components_for_tenant,
)


class KnowledgeMigrationSharedProjection:
    def __init__(self, *, session_factory=None, components_factory=None, content_loader=None):
        self.session_factory = session_factory or get_async_db_session
        self.components_factory = components_factory or build_shared_space_components_for_tenant
        self.content_loader = content_loader

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
        tenant_id = plan["tenant_id"]
        writer, _ = await asyncio.to_thread(self.components_factory, tenant_id)

        from bisheng.knowledge.domain.contracts.shared_space_storage import (
            ContentProjectionIdentity,
            ContentRelocationRequest,
        )
        from bisheng.knowledge.domain.contracts.identifiers import CanonicalVersionId, ContentFileId

        def identity(value):
            return ContentProjectionIdentity(
                tenant_id=TenantId(tenant_id),
                canonical_document_id=CanonicalDocumentId(value["document_id"]),
                canonical_version_id=CanonicalVersionId(value["version_id"]),
                content_file_id=ContentFileId(value["file_id"]),
                content_generation=value["generation"],
                embedding_model_id=str(writer.schema_spec.embedding_model_id),
            )

        if not plan["ready"]:
            await writer.relocate_content(
                ContentRelocationRequest(
                    source=identity(plan["source_content"]),
                    target=identity(plan["target_content"]),
                    knowledge_ids=plan["knowledge_ids"],
                    membership_generation=plan["membership_generation"],
                    manager_knowledge_id=plan["manager_knowledge_id"],
                )
            )
            await self._plan(unit)
            async with self.session_factory() as session:
                await KnowledgeMigrationRuntimeRepositoryImpl(session).finish_shared_projection(
                    unit.unit_id,
                    plan,
                    attempt_id=unit.attempt_id,
                    execution_token=unit.execution_token,
                )

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
