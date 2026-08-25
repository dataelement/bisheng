"""In-memory fake implementations of the M0-frozen shared storage contracts.

These back F2/F3/B-module unit tests (no Milvus/ES/F1 dependency). They
reproduce the contract-mandated invariants:

- content is stored once per (tenant, canonical_version, content_generation);
- membership rewrites touch all chunks of the document without re-embedding;
- empty membership deletes content (tombstone), never writes an empty array;
- stale membership generations are rejected (CAS);
- map_and_authorize_hits deduplicates per canonical document and applies the
  entry-selection priority (explicit > space order > entry-type priority).
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence

from bisheng.knowledge.domain.contracts import (
    BackendQueryFilter,
    CanonicalChunkHit,
    ContentDeleteRequest,
    ContentProjectionIdentity,
    ContentUpsertRequest,
    EntryRef,
    KnowledgeRetrievalScopeResolver,
    MappedEntryHit,
    MembershipUpdateRequest,
    ProjectionReadiness,
    ProjectionReadinessService,
    RetrievalScope,
    SharedSpaceStorageWriter,
    validate_knowledge_ids,
)
from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    EntryFileId,
    SpaceId,
    TenantId,
)


class FakeSharedSpaceStorageWriter(SharedSpaceStorageWriter):
    """In-memory single-copy store keyed by (tenant, document, version, gen)."""

    def __init__(self) -> None:
        # (tenant, doc, version, generation) -> {chunk_index: chunk dict}
        self.content: dict[tuple, dict[int, dict]] = {}
        # (tenant, doc) -> membership snapshot {knowledge_ids, generation}
        self.membership: dict[tuple, dict] = {}
        self.routing_version = 1
        self.calls: list[str] = []

    async def upsert_content(self, request: ContentUpsertRequest) -> None:
        self.calls.append("upsert_content")
        identity = request.identity
        key = (
            identity.tenant_id,
            identity.canonical_document_id,
            identity.canonical_version_id,
            identity.content_generation,
        )
        validate_knowledge_ids(request.knowledge_ids)
        self.content[key] = {
            chunk.chunk_index: {
                "text": chunk.text,
                "vector": list(chunk.vector) if chunk.vector is not None else None,
                "sparse_vector": dict(chunk.sparse_vector) if chunk.sparse_vector else None,
                "metadata": dict(chunk.metadata),
                "knowledge_ids": list(request.knowledge_ids),
                "embedding_model_id": identity.embedding_model_id,
            }
            for chunk in request.chunks
        }
        membership_key = (identity.tenant_id, identity.canonical_document_id)
        self.membership[membership_key] = {
            "knowledge_ids": tuple(request.knowledge_ids),
            "generation": identity.content_generation,
        }

    async def update_membership(self, request: MembershipUpdateRequest) -> None:
        self.calls.append("update_membership")
        key = (request.tenant_id, request.canonical_document_id)
        current = self.membership.get(key)
        if current is not None and request.membership_generation < current["generation"]:
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_VERSION_MISMATCH,
                f"stale membership generation {request.membership_generation} "
                f"< current {current['generation']}",
            )
        if not request.knowledge_ids:
            # Tombstone: delete all content of the document, never store [].
            for content_key in [k for k in self.content if k[:2] == key]:
                del self.content[content_key]
            self.membership.pop(key, None)
            return
        validate_knowledge_ids(request.knowledge_ids)
        self.membership[key] = {
            "knowledge_ids": tuple(request.knowledge_ids),
            "generation": request.membership_generation,
        }
        for content_key, chunks in self.content.items():
            if content_key[:2] == key:
                for chunk in chunks.values():
                    chunk["knowledge_ids"] = list(request.knowledge_ids)

    async def delete_content(self, request: ContentDeleteRequest) -> None:
        self.calls.append("delete_content")
        for key in [
            k
            for k in self.content
            if k[0] == request.tenant_id
            and k[1] == request.canonical_document_id
            and (request.canonical_version_id is None or k[2] == request.canonical_version_id)
            and (request.content_generation is None or k[3] == request.content_generation)
        ]:
            del self.content[key]

    # --- test helpers -----------------------------------------------------
    def membership_of(self, tenant_id: int, document_id: int) -> tuple[int, ...] | None:
        snapshot = self.membership.get((tenant_id, document_id))
        return snapshot["knowledge_ids"] if snapshot else None

    def chunk_count(self, tenant_id: int, document_id: int) -> int:
        return sum(len(v) for k, v in self.content.items() if k[:2] == (tenant_id, document_id))


class FakeKnowledgeRetrievalScopeResolver(KnowledgeRetrievalScopeResolver):
    """Configurable fake: visibility map + entry map, no real OpenFGA."""

    def __init__(
        self,
        *,
        visible_spaces: Mapping[str, set[int]] | None = None,
        # (tenant, canonical_document) -> [(space_id, entry_id, entry_type)]
        entries_by_document: Mapping[tuple, list[tuple[int, int, str]]] | None = None,
    ) -> None:
        self.visible_spaces = {k: set(v) for k, v in (visible_spaces or {}).items()}
        self.entries_by_document = {
            k: list(v) for k, v in (entries_by_document or {}).items()
        }
        self.routing_version = 1
        self.mapped_hits: list[MappedEntryHit] = []

    def _user_key(self, user_id: str, tenant_id: int) -> str:
        return f"{tenant_id}:{user_id}"

    async def resolve_request(
        self,
        *,
        user_id: str,
        tenant_id: TenantId,
        space_ids: Sequence[SpaceId],
        entry_refs: Sequence[EntryRef] | None = None,
    ) -> RetrievalScope:
        visible = self.visible_spaces.get(self._user_key(user_id, tenant_id), set())
        for space_id in space_ids:
            if space_id not in visible:
                raise SharedStorageContractError(
                    SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE,
                    f"space {space_id} is not visible for user {user_id}",
                )
        explicit: dict[SpaceId, tuple[EntryFileId, ...]] = {}
        for ref in entry_refs or ():
            explicit.setdefault(ref.space_id, ())
            explicit[ref.space_id] = explicit[ref.space_id] + (ref.entry_file_id,)
        return RetrievalScope(
            tenant_id=tenant_id,
            user_id=user_id,
            requested_space_ids=tuple(space_ids),
            explicit_entry_ids_by_space=explicit,
            routing_version=self.routing_version,
        )

    def build_backend_filter(
        self,
        scope: RetrievalScope,
        *,
        canonical_document_ids: Sequence[CanonicalDocumentId] | None = None,
        canonical_version_ids: Sequence | None = None,
    ) -> BackendQueryFilter:
        return BackendQueryFilter(
            tenant_id=scope.tenant_id,
            requested_space_ids=scope.requested_space_ids,
            routing_version=scope.routing_version,
            canonical_document_ids=tuple(canonical_document_ids) if canonical_document_ids else None,
            canonical_version_ids=tuple(canonical_version_ids) if canonical_version_ids else None,
        )

    async def map_and_authorize_hits(
        self,
        scope: RetrievalScope,
        hits: Sequence[CanonicalChunkHit],
    ) -> Sequence[MappedEntryHit]:
        # Same canonical document keeps only one mapped hit, entry chosen by
        # explicit entry > requested space order > entry-type priority.
        priority = {"manager": 0, "publish": 1, "share": 2}
        space_order = {space: idx for idx, space in enumerate(scope.requested_space_ids)}
        explicit_entries = {
            entry for entries in scope.explicit_entry_ids_by_space.values() for entry in entries
        }
        mapped: list[MappedEntryHit] = []
        for hit in hits:
            candidates = self.entries_by_document.get(
                (scope.tenant_id, hit.canonical_document_id), []
            )
            in_scope = [c for c in candidates if c[0] in space_order]
            if not in_scope:
                continue
            def rank(candidate: tuple[int, int, str]) -> tuple:
                space_id, entry_id, entry_type = candidate
                is_explicit = entry_id in explicit_entries
                return (
                    0 if is_explicit else 1,
                    space_order[space_id],
                    priority.get(entry_type, 99),
                )
            space_id, entry_id, _ = min(in_scope, key=rank)
            chosen_explicit = entry_id in explicit_entries
            mapped.append(
                MappedEntryHit(
                    space_id=SpaceId(space_id),
                    entry_file_id=EntryFileId(entry_id),
                    canonical_document_id=hit.canonical_document_id,
                    canonical_version_id=hit.canonical_version_id,
                    chunk_index=hit.chunk_index,
                    score=hit.score,
                    text=hit.text,
                    entry_selection_rule="explicit" if chosen_explicit else "space_order",
                )
            )
        self.mapped_hits = mapped
        return mapped


class FakeProjectionReadinessService(ProjectionReadinessService):
    """Configurable fake readiness gate for B4/B6 tests."""

    def __init__(self) -> None:
        # (tenant, entry_id or document_id) -> ProjectionReadiness
        self.results: dict[tuple, ProjectionReadiness] = {}
        self.default = ProjectionReadiness(ready=True)

    def set_result(self, key: tuple, readiness: ProjectionReadiness) -> None:
        self.results[key] = copy.deepcopy(readiness)

    async def get_content_membership_readiness(
        self,
        *,
        tenant_id: TenantId,
        entry_file_id: EntryFileId | None = None,
        canonical_document_id: CanonicalDocumentId | None = None,
        canonical_version_id=None,
    ) -> ProjectionReadiness:
        for key in (
            (tenant_id, entry_file_id),
            (tenant_id, canonical_document_id),
        ):
            if key in self.results:
                return self.results[key]
        return self.default
