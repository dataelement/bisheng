"""Canonical entry and durable-reference resolution for F059."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_document_distribution_schema import (
    KnowledgeDocumentEntryCapabilities,
    ResolvedKnowledgeDocumentEntry,
)

logger = logging.getLogger(__name__)

EntryPermissionLoader = Callable[[int, int], Awaitable[set[str]]]


class KnowledgeDocumentEntryResolutionError(ValueError):
    """Raised when an ID cannot be resolved to a safe active access entry."""


class KnowledgeDocumentEntryResolver:
    def __init__(
        self,
        *,
        document_repository: KnowledgeDocumentRepository,
        version_repository: KnowledgeDocumentVersionRepository,
        file_repository: KnowledgeFileRepository,
        permission_loader: EntryPermissionLoader,
    ):
        self.document_repository = document_repository
        self.version_repository = version_repository
        self.file_repository = file_repository
        self.permission_loader = permission_loader

    async def _permission_ids(
        self,
        *,
        file_id: int,
        space_id: int,
    ) -> set[str]:
        try:
            return set(await self.permission_loader(file_id, space_id))
        except Exception:
            logger.exception(
                "F059 entry permission loading failed closed: file_id=%s space_id=%s",
                file_id,
                space_id,
            )
            return set()

    @staticmethod
    def _validate_request_identity(
        entry: KnowledgeFile,
        *,
        tenant_id: int,
        space_id: int,
    ) -> None:
        if int(entry.tenant_id or 0) != int(tenant_id):
            raise KnowledgeDocumentEntryResolutionError(
                "entry tenant does not match request tenant"
            )
        if int(entry.knowledge_id) != int(space_id):
            raise KnowledgeDocumentEntryResolutionError(
                "entry space does not match request space"
            )
        if entry.file_type != FileType.FILE.value:
            raise KnowledgeDocumentEntryResolutionError(
                "folder cannot be resolved as a document entry"
            )

    @staticmethod
    def _projection_ready(entry: KnowledgeFile) -> bool:
        return bool(
            entry.projection_status == KnowledgeFileProjectionStatus.READY.value
            and entry.applied_content_generation
            >= entry.desired_content_generation
            and entry.applied_entry_generation >= entry.desired_entry_generation
        )

    @staticmethod
    def _capabilities(
        entry_type: str,
        permission_ids: set[str],
        *,
        allow_download: bool,
    ) -> KnowledgeDocumentEntryCapabilities:
        can_view = "view_file" in permission_ids
        common = {
            "can_view": can_view,
            "can_preview": can_view,
            "can_move": "move_file" in permission_ids,
            "can_manage_members": "manage_file_relation" in permission_ids,
        }
        if entry_type in (
            "normal",
            KnowledgeFileEntryType.MANAGER.value,
        ):
            return KnowledgeDocumentEntryCapabilities(
                **common,
                can_download="download_file" in permission_ids,
                can_edit_content="rename_file" in permission_ids,
                can_publish="publish_file" in permission_ids,
                can_share="share_file" in permission_ids,
                can_delete="delete_file" in permission_ids,
            )
        if entry_type == KnowledgeFileEntryType.PUBLISH.value:
            return KnowledgeDocumentEntryCapabilities(
                **common,
                can_download="download_file" in permission_ids,
                can_edit_content=False,
                can_publish=False,
                can_share="share_file" in permission_ids,
                can_delete=False,
            )
        if entry_type == KnowledgeFileEntryType.SHARE.value:
            return KnowledgeDocumentEntryCapabilities(
                **common,
                can_download=(
                    allow_download and "download_file" in permission_ids
                ),
                can_edit_content=False,
                can_publish=False,
                can_share=False,
                can_delete="delete_file" in permission_ids,
            )
        raise KnowledgeDocumentEntryResolutionError(
            f"unsupported entry type: {entry_type}"
        )

    async def _resolve_normal(
        self,
        entry: KnowledgeFile,
        *,
        tenant_id: int,
        space_id: int,
    ) -> ResolvedKnowledgeDocumentEntry:
        version = await self.version_repository.find_by_knowledge_file_id(
            int(entry.id)
        )
        if version is not None:
            document = await self.document_repository.find_by_id(
                int(version.document_id)
            )
            if document is None:
                raise KnowledgeDocumentEntryResolutionError(
                    "canonical document does not exist"
                )
            self._validate_document_identity(document, tenant_id=tenant_id)
            # Historical physical versions remain directly readable in their
            # owning space; capability computation below preserves file access rules.
            if int(document.knowledge_id) != int(space_id):
                raise KnowledgeDocumentEntryResolutionError(
                    "canonical document space mismatch"
                )

        permission_ids = await self._permission_ids(
            file_id=int(entry.id),
            space_id=space_id,
        )
        return ResolvedKnowledgeDocumentEntry(
            tenant_id=tenant_id,
            requested_space_id=space_id,
            entry_file_id=int(entry.id),
            entry_type="normal",
            content_file_id=int(entry.id),
            manager_file_id=int(entry.id),
            manager_space_id=space_id,
            capabilities=self._capabilities(
                "normal",
                permission_ids,
                allow_download=True,
            ),
        )

    @staticmethod
    def _validate_document_identity(
        document: KnowledgeDocument,
        *,
        tenant_id: int,
    ) -> None:
        if int(document.tenant_id or 0) != int(tenant_id):
            raise KnowledgeDocumentEntryResolutionError(
                "canonical document tenant mismatch"
            )
        if (
            document.lifecycle_status
            != KnowledgeDocumentLifecycleStatus.ACTIVE.value
        ):
            raise KnowledgeDocumentEntryResolutionError(
                "canonical document is not active"
            )
        if document.primary_version_id is None:
            raise KnowledgeDocumentEntryResolutionError(
                "canonical document has no primary version"
            )

    @staticmethod
    def _validate_logical_entry_has_no_physical_payload(
        entry: KnowledgeFile,
    ) -> None:
        if (
            entry.object_name is not None
            or entry.preview_file_object_name is not None
            or entry.thumbnails is not None
            or int(entry.file_size or 0) != 0
            or entry.md5 is not None
            or (entry.bbox_object_name or "") != ""
        ):
            raise KnowledgeDocumentEntryResolutionError(
                "logical entry contains forbidden physical payload"
            )

    async def resolve(
        self,
        *,
        tenant_id: int,
        space_id: int,
        file_id: int,
    ) -> ResolvedKnowledgeDocumentEntry:
        entry = await self.file_repository.find_by_id(int(file_id))
        if entry is None:
            raise KnowledgeDocumentEntryResolutionError("entry does not exist")
        self._validate_request_identity(
            entry,
            tenant_id=tenant_id,
            space_id=space_id,
        )

        if entry.entry_type is None and entry.reference_document_id is None:
            return await self._resolve_normal(
                entry,
                tenant_id=tenant_id,
                space_id=space_id,
            )
        if entry.entry_type == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value:
            raise KnowledgeDocumentEntryResolutionError(
                "projection tombstone is not an access entry"
            )
        if entry.entry_type not in {
            KnowledgeFileEntryType.MANAGER.value,
            KnowledgeFileEntryType.PUBLISH.value,
            KnowledgeFileEntryType.SHARE.value,
        }:
            raise KnowledgeDocumentEntryResolutionError(
                "entry has an invalid distribution type"
            )
        if entry.entry_status != KnowledgeFileEntryStatus.ACTIVE.value:
            raise KnowledgeDocumentEntryResolutionError("entry is not active")
        if entry.reference_document_id is None:
            raise KnowledgeDocumentEntryResolutionError(
                "distribution entry has no canonical document"
            )

        document = await self.document_repository.find_by_id(
            int(entry.reference_document_id)
        )
        if document is None:
            raise KnowledgeDocumentEntryResolutionError(
                "canonical document does not exist"
            )
        self._validate_document_identity(document, tenant_id=tenant_id)

        primary_version = await self.version_repository.find_by_id(
            int(document.primary_version_id)
        )
        if (
            primary_version is None
            or int(primary_version.document_id) != int(document.id)
        ):
            raise KnowledgeDocumentEntryResolutionError(
                "primary version does not belong to canonical document"
            )
        manager = await self.file_repository.find_by_id(
            int(primary_version.knowledge_file_id)
        )
        if manager is None:
            raise KnowledgeDocumentEntryResolutionError(
                "canonical manager file does not exist"
            )
        if (
            int(manager.tenant_id or 0) != tenant_id
            or int(manager.knowledge_id) != int(document.knowledge_id)
            or manager.entry_type != KnowledgeFileEntryType.MANAGER.value
            or manager.entry_status != KnowledgeFileEntryStatus.ACTIVE.value
            or int(manager.reference_document_id or 0) != int(document.id)
        ):
            raise KnowledgeDocumentEntryResolutionError(
                "primary version does not resolve to the active manager"
            )
        if (
            entry.entry_type == KnowledgeFileEntryType.MANAGER.value
            and int(entry.id) != int(manager.id)
        ):
            raise KnowledgeDocumentEntryResolutionError(
                "non-primary physical file cannot act as manager"
            )
        if entry.entry_type in {
            KnowledgeFileEntryType.PUBLISH.value,
            KnowledgeFileEntryType.SHARE.value,
        }:
            self._validate_logical_entry_has_no_physical_payload(entry)

        permission_ids = await self._permission_ids(
            file_id=int(entry.id),
            space_id=space_id,
        )
        return ResolvedKnowledgeDocumentEntry(
            tenant_id=tenant_id,
            requested_space_id=space_id,
            entry_file_id=int(entry.id),
            entry_type=str(entry.entry_type),
            entry_status=entry.entry_status,
            canonical_document_id=int(document.id),
            canonical_version_id=int(primary_version.id),
            content_file_id=int(manager.id),
            manager_file_id=int(manager.id),
            manager_space_id=int(manager.knowledge_id),
            content_generation=document.content_generation,
            desired_content_generation=entry.desired_content_generation,
            applied_content_generation=entry.applied_content_generation,
            desired_entry_generation=entry.desired_entry_generation,
            applied_entry_generation=entry.applied_entry_generation,
            projection_status=entry.projection_status,
            projection_ready=self._projection_ready(entry),
            capabilities=self._capabilities(
                str(entry.entry_type),
                permission_ids,
                allow_download=entry.allow_download,
            ),
        )


class KnowledgeDocumentDurableReferenceResolver:
    def __init__(
        self,
        *,
        entry_resolver: KnowledgeDocumentEntryResolver,
        version_repository: KnowledgeDocumentVersionRepository,
        file_repository: KnowledgeFileRepository,
    ):
        self.entry_resolver = entry_resolver
        self.version_repository = version_repository
        self.file_repository = file_repository

    async def resolve(
        self,
        *,
        tenant_id: int,
        requested_space_id: int,
        durable_file_id: int,
        require_view_permission: bool = True,
    ) -> ResolvedKnowledgeDocumentEntry:
        durable_file = await self.file_repository.find_by_id(
            int(durable_file_id)
        )
        if durable_file is None:
            raise KnowledgeDocumentEntryResolutionError(
                "durable file reference does not exist"
            )
        if int(durable_file.tenant_id or 0) != int(tenant_id):
            raise KnowledgeDocumentEntryResolutionError(
                "durable reference tenant mismatch"
            )

        try:
            resolved = await self.entry_resolver.resolve(
                tenant_id=tenant_id,
                space_id=requested_space_id,
                file_id=durable_file_id,
            )
        except KnowledgeDocumentEntryResolutionError as direct_error:
            document_id = durable_file.reference_document_id
            if document_id is None:
                version = (
                    await self.version_repository.find_by_knowledge_file_id(
                        int(durable_file_id)
                    )
                )
                document_id = (
                    version.document_id if version is not None else None
                )
            if document_id is None:
                raise direct_error

            candidates = await self.file_repository.find_distribution_entries_by_document_id(
                int(document_id),
                statuses={KnowledgeFileEntryStatus.ACTIVE.value},
            )
            local_candidates = [
                candidate
                for candidate in candidates
                if int(candidate.knowledge_id) == int(requested_space_id)
                and candidate.entry_type
                in {
                    KnowledgeFileEntryType.MANAGER.value,
                    KnowledgeFileEntryType.PUBLISH.value,
                    KnowledgeFileEntryType.SHARE.value,
                }
            ]
            if len(local_candidates) != 1:
                raise KnowledgeDocumentEntryResolutionError(
                    "durable reference has no unique active entry in requested space"
                )
            resolved = await self.entry_resolver.resolve(
                tenant_id=tenant_id,
                space_id=requested_space_id,
                file_id=int(local_candidates[0].id),
            )

        if require_view_permission and not resolved.capabilities.can_view:
            raise KnowledgeDocumentEntryResolutionError(
                "durable reference has no authorized active entry"
            )
        return resolved
