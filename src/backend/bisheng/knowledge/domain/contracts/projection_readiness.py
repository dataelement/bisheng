"""ProjectionReadinessService contract (M0 frozen, refactor spec 3.7).

``projection_ready`` for the shared-storage world means all three hold:

1. content projection of the current primary version has converged;
2. space-membership projection (knowledge_ids) has converged;
3. the entry points at the current primary version.

Readiness gates retrieval and interactive features; when not ready the
caller must fail closed (spec 8.1-6) - never fall back to unvalidated
manager content.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from bisheng.knowledge.domain.contracts.errors import SharedStorageErrorCode
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
    EntryFileId,
    TenantId,
)

__all__ = ["ProjectionReadiness", "ProjectionReadinessService"]


@dataclass(frozen=True)
class ProjectionReadiness:
    """Combined readiness result; ``ready`` implies all three conditions hold."""

    ready: bool
    #: Machine-readable first failing condition, None when ready.
    reason: SharedStorageErrorCode | None = None


class ProjectionReadinessService(ABC):
    """Answers "can this entry be served from the shared store right now?"."""

    @abstractmethod
    async def get_content_membership_readiness(
        self,
        *,
        tenant_id: TenantId,
        entry_file_id: EntryFileId | None = None,
        canonical_document_id: CanonicalDocumentId | None = None,
        canonical_version_id: CanonicalVersionId | None = None,
    ) -> ProjectionReadiness:
        """Check combined content+membership readiness for an entry or document.

        Exactly one of ``entry_file_id`` / ``canonical_document_id`` should be
        provided (the version is resolved from the entry/document when not
        given). Implementations must return a reason code when not ready.
        """
