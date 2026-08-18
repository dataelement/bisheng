"""F2 implementation of the frozen ProjectionReadinessService contract.

``projection_ready`` in the shared-storage world means all three conditions
hold (refactor spec 3.7 / 8.1-6, fail closed):

1. content projection of the current primary version has converged
   (some active entry applied the document's current ``content_generation``
   with projection_status ready);
2. space-membership projection converged (every active entry applied its
   desired entry generation);
3. the entry points at the current primary version
   (entry content generation not behind the document generation, and an
   explicitly requested version matches ``primary_version_id``).

Everything is derived from SQL projection bookkeeping on the KnowledgeFile /
KnowledgeDocument rows - no Milvus/ES access, so the gate itself can never be
slow or partitioned from the storage layer.
"""
from __future__ import annotations

import logging

from bisheng.knowledge.domain.contracts.errors import SharedStorageErrorCode
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
    EntryFileId,
    TenantId,
)
from bisheng.knowledge.domain.contracts.projection_readiness import (
    ProjectionReadiness,
    ProjectionReadinessService,
)
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.domain.services.shared_space_projection_support import (
    MEMBERSHIP_ENTRY_TYPES,
)

logger = logging.getLogger(__name__)


def _not_ready(reason: SharedStorageErrorCode) -> ProjectionReadiness:
    return ProjectionReadiness(ready=False, reason=reason)


class KnowledgeProjectionReadinessService(ProjectionReadinessService):
    """SQL-side combined content+membership readiness gate."""

    def __init__(
        self,
        *,
        file_repository: KnowledgeFileRepository,
        document_repository: KnowledgeDocumentRepository,
    ):
        self.file_repository = file_repository
        self.document_repository = document_repository

    async def get_content_membership_readiness(
        self,
        *,
        tenant_id: TenantId,
        entry_file_id: EntryFileId | None = None,
        canonical_document_id: CanonicalDocumentId | None = None,
        canonical_version_id: CanonicalVersionId | None = None,
    ) -> ProjectionReadiness:
        if (entry_file_id is None) == (canonical_document_id is None):
            raise ValueError(
                "exactly one of entry_file_id / canonical_document_id "
                "must be provided"
            )

        entry: KnowledgeFile | None = None
        if entry_file_id is not None:
            entry = await self.file_repository.find_by_id(int(entry_file_id))
            if (
                entry is None
                or int(entry.tenant_id or 0) != int(tenant_id)
                or entry.reference_document_id is None
                or entry.entry_status
                != KnowledgeFileEntryStatus.ACTIVE.value
                or entry.entry_type not in MEMBERSHIP_ENTRY_TYPES
            ):
                return _not_ready(SharedStorageErrorCode.ENTRY_NOT_ACTIVE)
            canonical_document_id = CanonicalDocumentId(
                int(entry.reference_document_id)
            )

        document = await self.document_repository.find_by_id(
            int(canonical_document_id)
        )
        if (
            document is None
            or int(document.tenant_id or 0) != int(tenant_id)
            or document.lifecycle_status
            != KnowledgeDocumentLifecycleStatus.ACTIVE.value
            or document.primary_version_id is None
        ):
            return _not_ready(SharedStorageErrorCode.ENTRY_NOT_ACTIVE)

        entries = list(
            await self.file_repository.find_distribution_entries_by_document_id(
                int(canonical_document_id),
            )
        )
        active_entries = [
            candidate
            for candidate in entries
            if candidate.entry_status
            == KnowledgeFileEntryStatus.ACTIVE.value
            and candidate.entry_type in MEMBERSHIP_ENTRY_TYPES
        ]
        if not active_entries:
            return _not_ready(SharedStorageErrorCode.ENTRY_NOT_ACTIVE)

        content_generation = int(document.content_generation)

        # 1. content projection of the current primary version converged.
        content_converged = any(
            candidate.projection_status
            == KnowledgeFileProjectionStatus.READY.value
            and int(candidate.applied_content_generation)
            >= content_generation
            for candidate in active_entries
        )
        if not content_converged:
            return _not_ready(
                SharedStorageErrorCode.CONTENT_PROJECTION_NOT_READY
            )

        # 2. space-membership projection converged for every active entry.
        membership_converged = all(
            candidate.projection_status
            == KnowledgeFileProjectionStatus.READY.value
            and int(candidate.applied_entry_generation)
            >= int(candidate.desired_entry_generation)
            for candidate in active_entries
        )
        if not membership_converged:
            return _not_ready(
                SharedStorageErrorCode.MEMBERSHIP_PROJECTION_NOT_READY
            )

        # 3. the entry points at the current primary version.
        if canonical_version_id is not None and int(canonical_version_id) != int(
            document.primary_version_id
        ):
            return _not_ready(
                SharedStorageErrorCode.ENTRY_NOT_ON_PRIMARY_VERSION
            )
        if (
            entry is not None
            and int(entry.applied_content_generation) < content_generation
        ):
            return _not_ready(
                SharedStorageErrorCode.ENTRY_NOT_ON_PRIMARY_VERSION
            )

        return ProjectionReadiness(ready=True, reason=None)
