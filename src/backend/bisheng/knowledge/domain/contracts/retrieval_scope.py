"""KnowledgeRetrievalScopeResolver contract (M0 frozen, refactor spec 3.5/12.1).

The resolver is the single permission-aware retrieval boundary for shared
SPACE storage. Business modules (knowledge space chat, Portal QA, Workflow,
Workstation, Agent/Tool/Linsight) must go through it; assembling Milvus/ES
filters or mapping hits back to entries anywhere else is an architecture
violation checked at M3.

Frozen behaviour:

- ``resolve_request`` validates visibility of the requested spaces and builds
  the scope. Whole-space requests never expand file IDs; explicit
  file/folder/tag entry refs are kept per space for later narrowing.
- ``build_backend_filter`` returns a backend-agnostic filter description.
  Rendering it into Milvus expressions / ES queries is F1+F3 internal work;
  the description carries ``tenant_id`` for physical store routing and, when
  resolving explicit refs, canonical version constraints. The tenant value is
  not persisted in chunk metadata or repeated in backend filters.
- ``map_and_authorize_hits`` takes Top-K canonical hits, maps them back to
  active entries of the *requested* spaces (O(Top-K), never O(space size)),
  runs OpenFGA + entry status + generation final checks, deduplicates per
  canonical document (explicit entry > requested-space order >
  manager/publish/share priority) and must fail closed on any check error.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
    EntryFileId,
    SpaceId,
    TenantId,
)

__all__ = [
    "EntryRef",
    "RetrievalScope",
    "CanonicalGenerationConstraint",
    "BackendQueryFilter",
    "CanonicalChunkHit",
    "MappedEntryHit",
    "KnowledgeRetrievalScopeResolver",
]


@dataclass(frozen=True)
class EntryRef:
    """An explicitly requested entry (file/folder/tag narrowed request)."""

    space_id: SpaceId
    entry_file_id: EntryFileId


@dataclass(frozen=True)
class RetrievalScope:
    """Resolved, permission-checked retrieval scope."""

    tenant_id: TenantId
    #: Opaque identity of the requesting user (User.user_id as str).
    user_id: str
    requested_space_ids: tuple[SpaceId, ...]
    #: Only set for explicitly narrowed requests; whole-space retrieval keeps
    #: this empty (no file-ID expansion, spec section 3.5).
    explicit_entry_ids_by_space: Mapping[SpaceId, tuple[EntryFileId, ...]] = field(
        default_factory=dict
    )
    #: Routing version asserted on every store access (risk R16).
    routing_version: int = 0


@dataclass(frozen=True)
class CanonicalGenerationConstraint:
    """Current shared projection identity for one canonical document."""

    canonical_document_id: CanonicalDocumentId
    canonical_version_id: CanonicalVersionId
    content_generation: int
    membership_generation: int


@dataclass(frozen=True)
class BackendQueryFilter:
    """Backend-agnostic query description produced by the resolver.

    Renderers must include the membership filter; ``tenant_id`` selects the
    tenant-bound physical store and is not rendered into the data-plane query.
    ``canonical_*`` constraints narrow explicit file/folder/tag requests.
    "Fetch Top-K globally, then filter by space" is forbidden.
    """

    tenant_id: TenantId
    requested_space_ids: tuple[SpaceId, ...]
    routing_version: int
    canonical_document_ids: tuple[CanonicalDocumentId, ...] | None = None
    #: Primary-version constraint; None means "current primary versions only"
    #: is handled by the renderer via version metadata, not by the caller.
    canonical_version_ids: tuple[CanonicalVersionId, ...] | None = None
    generation_constraints: tuple[CanonicalGenerationConstraint, ...] = ()


@dataclass(frozen=True)
class CanonicalChunkHit:
    """A raw hit coming back from the shared store (Top-K)."""

    canonical_document_id: CanonicalDocumentId
    canonical_version_id: CanonicalVersionId
    chunk_index: int
    score: float
    text: str | None = None
    content_generation: int | None = None
    membership_generation: int | None = None


@dataclass(frozen=True)
class MappedEntryHit:
    """A canonical hit mapped back to one visible entry of a requested space.

    ``raw_chunk_metadata`` must never be forwarded to clients (spec 8.1-8);
    only the mapped entry identity below is exposed.
    """

    space_id: SpaceId
    entry_file_id: EntryFileId
    canonical_document_id: CanonicalDocumentId
    canonical_version_id: CanonicalVersionId
    chunk_index: int
    score: float
    text: str | None = None
    document_name: str | None = None
    #: Which rule selected this entry among multiple visible candidates
    #: ("explicit" | "space_order" | "entry_type_priority").
    entry_selection_rule: str = "space_order"


class KnowledgeRetrievalScopeResolver(ABC):
    """Single permission-aware boundary between requests and shared storage."""

    @abstractmethod
    async def resolve_request(
        self,
        *,
        user_id: str,
        tenant_id: TenantId,
        space_ids: Sequence[SpaceId],
        entry_refs: Sequence[EntryRef] | None = None,
    ) -> RetrievalScope:
        """Validate space visibility and build the retrieval scope."""

    @abstractmethod
    def build_backend_filter(
        self,
        scope: RetrievalScope,
        *,
        canonical_document_ids: Sequence[CanonicalDocumentId] | None = None,
        canonical_version_ids: Sequence[CanonicalVersionId] | None = None,
        generation_constraints: Sequence[CanonicalGenerationConstraint] | None = None,
    ) -> BackendQueryFilter:
        """Build the backend-agnostic filter for the shared store query."""

    @abstractmethod
    async def map_and_authorize_hits(
        self,
        scope: RetrievalScope,
        hits: Sequence[CanonicalChunkHit],
    ) -> Sequence[MappedEntryHit]:
        """Map Top-K canonical hits to visible entries and final-check them.

        Implementations must over-fetch upstream (default K*2) and iterate so
        that post-filter results are not under-filled (spec section 3.5).
        """
