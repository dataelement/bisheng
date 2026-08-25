"""SharedSpaceStorageWriter contract (M0 frozen, refactor spec section 12.1).

One writer per tenant shared Milvus collection / ES index. The writer is the
only component allowed to mutate shared-store content; business modules must
never assemble Milvus/ES filters or write chunks themselves.

Implementation notes that are part of the frozen contract:

- ``upsert_content`` writes one chunk set per canonical primary version. The
  same (tenant, canonical_version_id, content_generation) must never end up
  with duplicate chunks: implementations write the new generation first and
  delete the old generation afterwards (Milvus ``auto_id=True`` means ARRAY
  updates are a rewrite, not an in-place update).
- ``update_membership`` rewrites ``knowledge_ids`` metadata for **all** chunks
  of the document without recomputing embeddings. An empty ``knowledge_ids``
  tuple is the tombstone signal: the implementation must delete the content
  projection, never write an empty array (``nullable=false``).
- All methods must be idempotent per (identity, generation) so the projection
  worker's lease/CAS/retry loop can safely re-run them.
- Implementations must reject calls when the tenant's routing version no
  longer matches the caller's expectation (ROUTING_VERSION_MISMATCH).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
    ContentFileId,
    TenantId,
)

__all__ = [
    "ContentProjectionIdentity",
    "SharedContentChunk",
    "ContentUpsertRequest",
    "MembershipUpdateRequest",
    "ContentDeleteRequest",
    "SharedSpaceStorageWriter",
    "validate_knowledge_ids",
]


def validate_knowledge_ids(knowledge_ids: Sequence[int], *, allow_empty: bool = False) -> tuple[int, ...]:
    """Validate and normalise a membership array: ascending, deduped, non-empty.

    Raises:
        SharedStorageContractError: EMPTY_MEMBERSHIP when an empty sequence is
            given while ``allow_empty`` is False.
        ValueError: when the input is not strictly ascending after sorting
            semantics would change it (callers must aggregate from SQL active
            entries, see spec section 3.4 - blind add/remove is forbidden).
    """
    ids = tuple(knowledge_ids)
    if not ids:
        if allow_empty:
            return ()
        raise SharedStorageContractError(
            SharedStorageErrorCode.EMPTY_MEMBERSHIP,
            "knowledge_ids must not be empty for content writes; empty membership "
            "must short-circuit to the tombstone flow",
        )
    if list(ids) != sorted(set(ids)):
        raise ValueError(
            "knowledge_ids must be provided ascending and deduplicated "
            f"(got {ids!r}); re-aggregate from SQL active entries"
        )
    return ids


@dataclass(frozen=True)
class ContentProjectionIdentity:
    """Dimension of a content projection (spec section 3.7-A)."""

    tenant_id: TenantId
    canonical_document_id: CanonicalDocumentId
    canonical_version_id: CanonicalVersionId
    content_file_id: ContentFileId
    #: F059 content generation; bumped on re-parse / primary switch.
    content_generation: int
    #: Embedding model identity used for the vectors; written into the shared
    #: store metadata and schema fingerprint, never used for collection naming.
    embedding_model_id: str | None = None


@dataclass(frozen=True)
class SharedContentChunk:
    """One retrievable chunk of a canonical primary version."""

    chunk_index: int
    text: str
    #: Dense embedding; None for BM25/sparse-only chunks.
    vector: Sequence[float] | None = None
    #: Sparse embedding as {dimension_index: weight}.
    sparse_vector: Mapping[int, float] | None = None
    #: Remaining chunk metadata (page, bbox, user_metadata, ...).
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentUpsertRequest:
    """Write/refresh the single chunk copy of one canonical primary version."""

    identity: ContentProjectionIdentity
    #: Membership snapshot at write time; must be non-empty (tombstone goes
    #: through MembershipUpdateRequest with an empty tuple instead).
    knowledge_ids: tuple[int, ...]
    chunks: Sequence[SharedContentChunk]


@dataclass(frozen=True)
class MembershipUpdateRequest:
    """Rewrite ``knowledge_ids`` metadata for all chunks of one document.

    ``knowledge_ids == ()`` means the last active entry is gone: delete the
    content projection (tombstone), do not write an empty array.
    """

    tenant_id: TenantId
    canonical_document_id: CanonicalDocumentId
    knowledge_ids: tuple[int, ...]
    #: Membership generation (entry generation) that produced this snapshot;
    #: stale generations must be rejected by the implementation (CAS).
    membership_generation: int
    #: Content generation the chunks currently belong to; used to locate the
    #: chunk set to rewrite.
    content_generation: int


@dataclass(frozen=True)
class ContentDeleteRequest:
    """Delete chunk content by identity.

    ``canonical_version_id``/``content_generation`` may be None meaning "all
    versions/generations of the document" (used by the tombstone flow).
    """

    tenant_id: TenantId
    canonical_document_id: CanonicalDocumentId
    canonical_version_id: CanonicalVersionId | None = None
    content_generation: int | None = None


class SharedSpaceStorageWriter(ABC):
    """The only write surface for tenant-shared SPACE storage."""

    @abstractmethod
    async def upsert_content(self, request: ContentUpsertRequest) -> None:
        """Idempotently write the chunk set of one canonical primary version."""

    @abstractmethod
    async def update_membership(self, request: MembershipUpdateRequest) -> None:
        """Idempotently rewrite membership metadata without re-embedding."""

    @abstractmethod
    async def delete_content(self, request: ContentDeleteRequest) -> None:
        """Idempotently delete chunk content (single version or whole document)."""
