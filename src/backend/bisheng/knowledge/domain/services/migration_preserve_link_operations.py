"""Executing a migration unit as a publish, so a shortcut stays at the source.

The normal migration walks a long checkpoint chain — create target rows, copy
objects, build indexes, write permissions, verify, switch, clean the source.
Publishing does all of that itself: the distribution state machine owns the
target entry, its permission projection and its index, and the source row is
not cleaned up at all because it *becomes* the shortcut.

So this reuses the same chain rather than inventing a second one, and simply
has nothing to do in most steps. The publish happens at ``switch_database``,
which is honest: that step is where the normal path flips the document over to
its new home, and publishing is that same flip. Reusing the chain keeps the
lease, the resumable checkpoints, the compensation and the attempt bookkeeping
exactly as they are — and makes retries idempotent for free, since a unit that
already switched resumes past the publish.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationBatch,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
)
from bisheng.knowledge.domain.services.file_migration.executor import (
    MigrationExecutionUnit,
)

logger = logging.getLogger(__name__)


def preserve_link_instance_id(source_file_id: int, target_space_id: int) -> int:
    """A stand-in approval id for a publish nobody approved.

    Publishing is keyed by an approval instance, and this mode has no approval:
    the migration console is already restricted to system administrators. The
    value is negative so it can never collide with a real approval, and
    deterministic so a retry of the same file into the same space is recognised
    as the same publish rather than a second one. Mirrors what auto-publish does.
    """
    return -(source_file_id * 10000 + target_space_id % 10000)


def _merge_target_document_id(overwrite_unit_key: str | None) -> int | None:
    """The document an overwrite should merge into, or None for a plain move.

    Read from ``overwrite_unit_key`` (``document:<id>``) rather than the unit's
    ``target_document_id`` column: that column holds the *source* document id,
    which the copy path carries over to the target unchanged. Passing it to
    publish would ask a document to merge into itself.

    Preflight only reserves an overwrite after checking the target document is
    intact, so a key present here is safe to merge into.
    """
    key = str(overwrite_unit_key or "")
    prefix = "document:"
    if not key.startswith(prefix):
        return None
    candidate = key[len(prefix) :]
    return int(candidate) if candidate.isdigit() else None


def _target_level_from_path(path: str | None) -> int:
    """Folder depth of a target path; a file at the space root is level 0."""
    return len([part for part in (path or "").split("/") if part.isdigit()])


class PreserveLinkContextError(RuntimeError):
    """The unit no longer describes something that can be published."""


class PreserveLinkMigrationOperations:
    """Runs one migration unit as a publish. See the module docstring."""

    def __init__(self, *, publish_service_factory: Any, context_loader: Any = None):
        # Both are injected so tests can drive the whole chain without a live
        # database session or a real OpenFGA; production passes the real
        # distribution service factory and the default loader.
        self.publish_service_factory = publish_service_factory
        self.context_loader = context_loader or self._load_publish_context

    # ── Steps the distribution state machine already owns ──────────

    async def create_target_rows(self, unit: MigrationExecutionUnit) -> None:
        return None

    async def copy_target_objects(self, unit: MigrationExecutionUnit) -> None:
        return None

    async def build_target_indexes(self, unit: MigrationExecutionUnit) -> None:
        return None

    async def write_target_permissions(self, unit: MigrationExecutionUnit) -> None:
        return None

    async def verify_target(self, unit: MigrationExecutionUnit) -> None:
        return None

    # ── Steps that have no meaning once the source becomes a shortcut ──

    async def cleanup_source_external(self, unit: MigrationExecutionUnit) -> None:
        return None

    async def cleanup_source_rows(self, unit: MigrationExecutionUnit) -> None:
        return None

    async def cleanup_new_target(self, unit: MigrationExecutionUnit) -> None:
        """Compensation before the switch.

        Nothing is created before the publish, so there is nothing to undo. A
        publish that failed part-way cleans up after itself inside the
        distribution service.
        """
        return None

    # ── The switch: publish ────────────────────────────────────────

    async def switch_database(self, unit: MigrationExecutionUnit) -> None:
        if unit.attempt_id is None or not unit.execution_token:
            raise RuntimeError("migration execution generation is missing")
        context = await self.context_loader(unit.unit_id)
        await self._publish(context)

    async def _load_publish_context(self, unit_id: int) -> dict[str, Any]:
        async with get_async_db_session() as session:
            unit_row = (
                await session.exec(
                    select(KnowledgeMigrationUnit).where(KnowledgeMigrationUnit.id == unit_id)
                )
            ).first()
            if unit_row is None:
                raise PreserveLinkContextError(f"migration unit {unit_id} no longer exists")
            batch = (
                await session.exec(
                    select(KnowledgeMigrationBatch).where(
                        KnowledgeMigrationBatch.id == int(unit_row.batch_id)
                    )
                )
            ).first()
            if batch is None:
                raise PreserveLinkContextError(f"migration batch for unit {unit_id} no longer exists")
            file_rows = list(
                (
                    await session.exec(
                        select(KnowledgeMigrationFile)
                        .where(KnowledgeMigrationFile.unit_id == unit_id)
                        .order_by(col(KnowledgeMigrationFile.source_version_no).desc())
                    )
                ).all()
            )
            # Publishing addresses the target by folder ids, not by the display
            # path the unit carries for the UI. Resolve the planned folder to
            # its real level path; a unit landing at the space root has none.
            target_file_level_path = ""
            if unit_row.planned_target_folder_id:
                folder = (
                    await session.exec(
                        select(KnowledgeFile).where(
                            KnowledgeFile.id == int(unit_row.planned_target_folder_id)
                        )
                    )
                ).first()
                if folder is None:
                    raise PreserveLinkContextError(
                        f"target folder {unit_row.planned_target_folder_id} no longer exists"
                    )
                target_file_level_path = f"{folder.file_level_path or ''}/{int(folder.id)}"

        if not file_rows:
            raise PreserveLinkContextError(f"migration unit {unit_id} has no files")

        # The manager entry backs the document's primary version, and publishing
        # always moves the manager.
        primary = next((row for row in file_rows if row.is_primary), file_rows[0])
        if unit_row.source_document_id is None:
            raise PreserveLinkContextError(
                f"migration unit {unit_id} has no source document; it cannot be published"
            )

        return {
            "tenant_id": int(batch.tenant_id or 1),
            "document_id": int(unit_row.source_document_id),
            "source_entry_id": int(primary.source_file_id),
            "target_space_id": int(batch.target_space_id),
            "target_file_level_path": target_file_level_path,
            "target_level": _target_level_from_path(target_file_level_path),
            "target_document_id": _merge_target_document_id(unit_row.overwrite_unit_key),
        }

    async def _publish(self, context: dict[str, Any]) -> None:
        from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
            PublishKnowledgeDocumentCommand,
        )

        command = PublishKnowledgeDocumentCommand(
            tenant_id=context["tenant_id"],
            approval_instance_id=preserve_link_instance_id(
                context["source_entry_id"],
                context["target_space_id"],
            ),
            document_id=context["document_id"],
            source_entry_id=context["source_entry_id"],
            target_space_id=context["target_space_id"],
            target_file_level_path=context["target_file_level_path"],
            target_level=context["target_level"],
            # Set only when preflight reserved an existing target document to
            # overwrite: publishing then merges, making the source content the
            # target's new primary version and keeping the old one as history.
            target_document_id=context["target_document_id"],
        )
        async with self.publish_service_factory() as service:
            await service.publish_approved(command)
        logger.info(
            "F100 preserve-link publish document_id=%s source_entry_id=%s "
            "target_space_id=%s merged=%s",
            context["document_id"],
            context["source_entry_id"],
            context["target_space_id"],
            context["target_document_id"] is not None,
        )


class PreserveLinkAwareOperations:
    """Sends each unit down the copy path or the publish path.

    Batches are claimed one at a time by a worker that already holds the global
    lease, so the mode cannot be decided when the service is constructed — it
    belongs to the batch. This looks it up per unit and delegates, leaving the
    execution state machine untouched.
    """

    def __init__(
        self,
        *,
        default_operations: Any,
        preserve_link_operations: Any,
        preserve_link_lookup: Any,
    ):
        self.default_operations = default_operations
        self.preserve_link_operations = preserve_link_operations
        self.preserve_link_lookup = preserve_link_lookup

    async def _operations_for(self, unit: MigrationExecutionUnit) -> Any:
        if await self.preserve_link_lookup(unit.unit_id):
            return self.preserve_link_operations
        return self.default_operations

    async def create_target_rows(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).create_target_rows(unit)

    async def copy_target_objects(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).copy_target_objects(unit)

    async def build_target_indexes(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).build_target_indexes(unit)

    async def write_target_permissions(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).write_target_permissions(unit)

    async def verify_target(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).verify_target(unit)

    async def switch_database(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).switch_database(unit)

    async def cleanup_source_external(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).cleanup_source_external(unit)

    async def cleanup_source_rows(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).cleanup_source_rows(unit)

    async def cleanup_new_target(self, unit: MigrationExecutionUnit) -> None:
        await (await self._operations_for(unit)).cleanup_new_target(unit)

    async def cleanup_empty_source_folders(self, batch_id: int) -> None:
        """Batch-level step.

        Preserve-link batches leave every source row in place as a shortcut, so
        no folder is emptied; the default implementation is a no-op for them and
        is safe to call either way.
        """
        await self.default_operations.cleanup_empty_source_folders(batch_id)


@asynccontextmanager
async def default_publish_service_factory() -> AsyncIterator[Any]:
    """A distribution service bound to its own session, one publish at a time."""
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
        KnowledgeDocumentDistributionService,
    )
    from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
        KnowledgeDocumentPermissionActivationService,
    )

    async with get_async_db_session() as session:
        file_repository = KnowledgeFileRepositoryImpl(session)
        yield KnowledgeDocumentDistributionService(
            session=session,
            document_repository=KnowledgeDocumentRepositoryImpl(session),
            version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
            file_repository=file_repository,
            permission_activation_service=KnowledgeDocumentPermissionActivationService(
                file_repository=file_repository,
            ),
        )


def build_preserve_link_aware_operations(default_operations: Any) -> PreserveLinkAwareOperations:
    """Wrap the copy-path operations so preserve-link batches publish instead."""
    return PreserveLinkAwareOperations(
        default_operations=default_operations,
        preserve_link_operations=PreserveLinkMigrationOperations(
            publish_service_factory=default_publish_service_factory,
        ),
        preserve_link_lookup=batch_prefers_link,
    )


async def batch_prefers_link(unit_id: int) -> bool:
    """Whether the batch owning this unit was created in preserve-link mode."""
    async with get_async_db_session() as session:
        result = await session.exec(
            select(KnowledgeMigrationBatch.preserve_link)
            .join(
                KnowledgeMigrationUnit,
                col(KnowledgeMigrationUnit.batch_id) == col(KnowledgeMigrationBatch.id),
            )
            .where(KnowledgeMigrationUnit.id == unit_id)
        )
        return bool(result.first())
