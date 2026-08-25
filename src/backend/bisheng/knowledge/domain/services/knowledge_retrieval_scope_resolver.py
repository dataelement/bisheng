"""F3: permission-aware retrieval scope resolver for shared SPACE storage.

Implements the frozen ``KnowledgeRetrievalScopeResolver`` contract
(refactor spec sections 3.5/3.6/8.1). This service is the single
permission-aware boundary between retrieval requests and the shared
Milvus/ES store:

- ``resolve_request`` validates visibility of the requested spaces through
  the injected OpenFGA-backed checkers and never expands whole-space
  requests into file IDs.
- ``build_backend_filter`` produces the backend-agnostic filter
  description; the module-level Milvus/ES renderers turn it into concrete
  pre-filters. "Fetch Top-K globally, then filter by space" is impossible
  to express with these structures (spec 3.6).
- ``map_and_authorize_hits`` maps Top-K canonical hits back to active
  entries of the requested spaces with one batched repository query
  (O(Top-K)), runs the OpenFGA file-level check plus the F059
  entry-status/generation final checks and deduplicates per canonical
  chunk. ``knowledge_ids`` is a retrieval projection only and never
  authorizes anything (spec 8.1-3).
- ``map_and_authorize_with_overfetch`` drives the store-side over-fetch
  loop (default K x 2) so post-filter results are not under-filled when
  dirty members (revoked shares, deleted entries) consume Top-K slots.

Every failure path raises :class:`SharedStorageContractError` with a
stable code and fails closed - no silent degradation (spec 8.1).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
    EntryFileId,
    SpaceId,
    TenantId,
)
from bisheng.knowledge.domain.contracts.retrieval_scope import (
    BackendQueryFilter,
    CanonicalChunkHit,
    EntryRef,
    KnowledgeRetrievalScopeResolver,
    MappedEntryHit,
    RetrievalScope,
)
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

logger = logging.getLogger(__name__)

__all__ = [
    "RetrievalScopeResolverSettings",
    "SqlKnowledgeRetrievalScopeResolver",
    "SpaceReadPermissionChecker",
    "EntryViewPermissionChecker",
    "FetchHitsCallable",
    "render_milvus_expr",
    "render_es_membership_query",
]

#: Async OpenFGA-backed checker: does ``user`` hold space-level read
#: (visible/can_read) on ``space`` within ``tenant``? Must raise on service
#: unavailability; returning False is a plain deny.
SpaceReadPermissionChecker = Callable[[TenantId, str, SpaceId], Awaitable[bool]]

#: Async OpenFGA-backed file-level checker for the final per-entry check
#: (``view_file`` on the entry in the requested space).
EntryViewPermissionChecker = Callable[
    [TenantId, str, SpaceId, EntryFileId], Awaitable[bool]
]

#: Store-side page fetch for the over-fetch loop: (filter, offset, limit).
FetchHitsCallable = Callable[
    [BackendQueryFilter, int, int], Awaitable[Sequence[CanonicalChunkHit]]
]

_ENTRY_TYPE_PRIORITY = {
    KnowledgeFileEntryType.MANAGER.value: 0,
    KnowledgeFileEntryType.PUBLISH.value: 1,
    KnowledgeFileEntryType.SHARE.value: 2,
}

_DEFAULT_OVERFETCH_FACTOR = 2
_DEFAULT_MAX_OVERFETCH_ROUNDS = 4


@dataclass(frozen=True)
class RetrievalScopeResolverSettings:
    """Runtime knobs for the scope resolver.

    ``from_global_settings`` reads the F1 shared-storage config block with
    defensive ``getattr`` so this module keeps working while F1 lands; a
    missing block means the feature is OFF (fail closed).
    """

    enabled: bool = False
    routing_version: int = 1
    overfetch_factor: int = _DEFAULT_OVERFETCH_FACTOR
    max_overfetch_rounds: int = _DEFAULT_MAX_OVERFETCH_ROUNDS

    @classmethod
    def from_global_settings(cls, settings: Any | None = None) -> "RetrievalScopeResolverSettings":
        try:
            if settings is None:
                from bisheng.common.services.config_service import (
                    settings as global_settings,
                )

                settings = global_settings
            block = getattr(settings, "knowledge_space_shared_storage", None)
            if block is None:
                return cls(enabled=False)

            def _get(name: str, default: Any) -> Any:
                value = getattr(block, name, None)
                return default if value is None else value

            return cls(
                enabled=bool(_get("enabled", False)),
                routing_version=int(_get("routing_version", 1) or 1),
                overfetch_factor=max(1, int(_get("retrieval_overfetch_factor", _DEFAULT_OVERFETCH_FACTOR))),
                max_overfetch_rounds=max(1, int(_get("retrieval_max_overfetch_rounds", _DEFAULT_MAX_OVERFETCH_ROUNDS))),
            )
        except Exception:
            logger.exception("failed to read shared storage settings; treating as disabled")
            return cls(enabled=False)


class SqlKnowledgeRetrievalScopeResolver(KnowledgeRetrievalScopeResolver):
    """Contract implementation backed by SQL repositories and OpenFGA checkers."""

    def __init__(
        self,
        *,
        file_repository: KnowledgeFileRepository,
        document_repository: KnowledgeDocumentRepository,
        version_repository: KnowledgeDocumentVersionRepository,
        space_read_checker: SpaceReadPermissionChecker,
        entry_view_checker: EntryViewPermissionChecker,
        settings_provider: Callable[[], RetrievalScopeResolverSettings] | None = None,
    ):
        self.file_repository = file_repository
        self.document_repository = document_repository
        self.version_repository = version_repository
        self.space_read_checker = space_read_checker
        self.entry_view_checker = entry_view_checker
        self._settings_provider = settings_provider or RetrievalScopeResolverSettings.from_global_settings

    # ------------------------------------------------------------------
    # F3.1 scope resolution
    # ------------------------------------------------------------------
    async def resolve_request(
        self,
        *,
        user_id: str,
        tenant_id: TenantId,
        space_ids: Sequence[SpaceId],
        entry_refs: Sequence[EntryRef] | None = None,
    ) -> RetrievalScope:
        settings = self._require_enabled()
        if not user_id:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE,
                "retrieval request has no user identity",
                tenant_id=int(tenant_id),
            )
        requested = tuple(dict.fromkeys(int(s) for s in space_ids))
        if not requested:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE,
                "retrieval request carries no space ids",
                tenant_id=int(tenant_id),
            )

        for space_id in requested:
            allowed = await self._check_space_read(tenant_id, user_id, space_id)
            if not allowed:
                raise SharedStorageContractError(
                    SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE,
                    f"space {space_id} is not readable for user {user_id}",
                    tenant_id=int(tenant_id),
                )

        explicit: dict[int, tuple[int, ...]] = {}
        if entry_refs:
            requested_set = set(requested)
            for ref in entry_refs:
                if int(ref.space_id) not in requested_set:
                    raise SharedStorageContractError(
                        SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE,
                        f"explicit entry ref {ref.entry_file_id} references space "
                        f"{ref.space_id} outside the requested spaces",
                        tenant_id=int(tenant_id),
                    )
            await self._validate_explicit_refs(
                tenant_id=int(tenant_id),
                entry_refs=entry_refs,
            )
            for ref in entry_refs:
                bucket = explicit.setdefault(int(ref.space_id), ())
                entry_id = int(ref.entry_file_id)
                if entry_id not in bucket:
                    explicit[int(ref.space_id)] = bucket + (entry_id,)

        return RetrievalScope(
            tenant_id=tenant_id,
            user_id=user_id,
            requested_space_ids=tuple(SpaceId(s) for s in requested),
            explicit_entry_ids_by_space={SpaceId(k): tuple(EntryFileId(i) for i in v) for k, v in explicit.items()},
            routing_version=settings.routing_version,
        )

    async def _check_space_read(
        self,
        tenant_id: TenantId,
        user_id: str,
        space_id: int,
    ) -> bool:
        try:
            return bool(await self.space_read_checker(tenant_id, user_id, SpaceId(space_id)))
        except SharedStorageContractError:
            raise
        except Exception as exc:
            # OpenFGA / permission service unavailable: fail closed (spec 8.1).
            logger.error(
                "space permission check failed closed: tenant=%s user=%s space=%s error=%r",
                int(tenant_id),
                user_id,
                space_id,
                exc,
            )
            raise SharedStorageContractError(
                SharedStorageErrorCode.PERMISSION_SERVICE_UNAVAILABLE,
                f"space permission service unavailable while checking space {space_id}",
                tenant_id=int(tenant_id),
            ) from exc

    async def _validate_explicit_refs(
        self,
        *,
        tenant_id: int,
        entry_refs: Sequence[EntryRef],
    ) -> None:
        ref_ids = sorted({int(ref.entry_file_id) for ref in entry_refs})
        rows = {int(row.id): row for row in await self.file_repository.find_by_ids(ref_ids)}
        expected_space_by_id = {int(ref.entry_file_id): int(ref.space_id) for ref in entry_refs}
        for entry_id in ref_ids:
            entry = rows.get(entry_id)
            if entry is None or not self._is_resolvable_explicit_entry(
                entry,
                tenant_id=tenant_id,
                expected_space_id=expected_space_by_id[entry_id],
            ):
                raise SharedStorageContractError(
                    SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE,
                    f"explicit entry ref {entry_id} does not resolve to an active "
                    f"entry of the requested space in tenant {tenant_id}",
                    tenant_id=tenant_id,
                )

    @staticmethod
    def _is_resolvable_explicit_entry(
        entry: KnowledgeFile,
        *,
        tenant_id: int,
        expected_space_id: int,
    ) -> bool:
        if int(entry.tenant_id or 0) != tenant_id:
            # Cross-tenant entry ids are rejected outright (spec 8.1-1).
            return False
        if int(entry.knowledge_id) != expected_space_id:
            return False
        if entry.file_type != FileType.FILE.value:
            return False
        if entry.entry_status not in (None, KnowledgeFileEntryStatus.ACTIVE.value):
            return False
        if entry.entry_type is None:
            return True
        return entry.entry_type in _ENTRY_TYPE_PRIORITY

    # ------------------------------------------------------------------
    # F3.2 filter builder
    # ------------------------------------------------------------------
    def build_backend_filter(
        self,
        scope: RetrievalScope,
        *,
        canonical_document_ids: Sequence[CanonicalDocumentId] | None = None,
        canonical_version_ids: Sequence[CanonicalVersionId] | None = None,
    ) -> BackendQueryFilter:
        settings = self._require_enabled()
        if int(scope.routing_version) != settings.routing_version:
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_VERSION_MISMATCH,
                f"scope routing version {scope.routing_version} does not match "
                f"current routing version {settings.routing_version}",
                tenant_id=int(scope.tenant_id),
            )
        if not scope.requested_space_ids:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE,
                "retrieval scope carries no requested spaces",
                tenant_id=int(scope.tenant_id) if scope.tenant_id is not None else None,
            )
        return BackendQueryFilter(
            tenant_id=scope.tenant_id,
            requested_space_ids=scope.requested_space_ids,
            routing_version=scope.routing_version,
            canonical_document_ids=_dedupe_optional(canonical_document_ids),
            canonical_version_ids=_dedupe_optional(canonical_version_ids),
        )

    async def resolve_explicit_canonical_constraints(
        self,
        scope: RetrievalScope,
    ) -> tuple[tuple[CanonicalDocumentId, ...] | None, tuple[CanonicalVersionId, ...] | None]:
        """Expand a scope's explicit entry refs into canonical document/version ids.

        Used by callers before ``build_backend_filter`` for file/folder/tag
        narrowed requests (spec 3.5 rule 2). The version list pins every
        document to its *current primary version*; explicit content ids
        never come from the client (spec 8.1-4). Returns ``(None, None)``
        when the scope has no explicit refs (whole-space retrieval).
        """
        self._require_enabled()
        if not scope.explicit_entry_ids_by_space:
            return None, None
        entry_ids = sorted(
            {int(entry_id) for ids in scope.explicit_entry_ids_by_space.values() for entry_id in ids}
        )
        rows = {int(row.id): row for row in await self.file_repository.find_by_ids(entry_ids)}

        document_ids: list[int] = []
        for entry_id in entry_ids:
            entry = rows.get(entry_id)
            if entry is not None and entry.reference_document_id is not None:
                document_ids.append(int(entry.reference_document_id))
                continue
            version = await self.version_repository.find_by_knowledge_file_id(entry_id)
            if entry is None or version is None:
                raise SharedStorageContractError(
                    SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE,
                    f"explicit entry {entry_id} has no canonical document",
                    tenant_id=int(scope.tenant_id),
                )
            document_ids.append(int(version.document_id))

        documents = await self._load_documents(int(scope.tenant_id), sorted(set(document_ids)))
        resolved_docs: list[int] = []
        version_ids: list[int] = []
        for document_id in sorted(set(document_ids)):
            document = documents.get(document_id)
            if document is None or document.primary_version_id is None:
                raise SharedStorageContractError(
                    SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE,
                    f"explicit entry resolves to unavailable canonical document {document_id}",
                    tenant_id=int(scope.tenant_id),
                )
            resolved_docs.append(document_id)
            version_ids.append(int(document.primary_version_id))
        return (
            tuple(CanonicalDocumentId(d) for d in resolved_docs),
            tuple(CanonicalVersionId(v) for v in version_ids),
        )

    # ------------------------------------------------------------------
    # F3.3/F3.5/F3.6 Top-K back-mapping, final checks, dedupe
    # ------------------------------------------------------------------
    async def map_and_authorize_hits(
        self,
        scope: RetrievalScope,
        hits: Sequence[CanonicalChunkHit],
    ) -> Sequence[MappedEntryHit]:
        self._require_enabled()
        if not hits:
            return []

        space_order = {int(space): idx for idx, space in enumerate(scope.requested_space_ids)}
        explicit_entries = {
            int(entry_id)
            for ids in scope.explicit_entry_ids_by_space.values()
            for entry_id in ids
        }

        document_ids = sorted({int(hit.canonical_document_id) for hit in hits})
        documents = await self._load_documents(int(scope.tenant_id), document_ids)
        entries_by_document = await self._load_scope_entries(
            tenant_id=int(scope.tenant_id),
            document_ids=document_ids,
            space_ids=list(space_order),
        )

        mapped: list[MappedEntryHit] = []
        seen_chunks: set[tuple[int, int]] = set()
        for hit in hits:
            document_id = int(hit.canonical_document_id)
            chunk_key = (document_id, int(hit.chunk_index))
            if chunk_key in seen_chunks:
                # Same canonical chunk hitting several requested spaces keeps
                # exactly one mapped hit (spec 3.5 rule 6).
                continue
            candidates = self._final_document_check(
                documents.get(document_id),
                hit,
                entries_by_document.get(document_id, []),
                space_ids=space_order,
            )
            if not candidates:
                # Dirty member (revoked share / deleted entry / stale version):
                # drop the hit; the over-fetch loop refills the Top-K slots.
                logger.info(
                    "retrieval hit dropped at final check: tenant=%s document=%s chunk=%s",
                    int(scope.tenant_id),
                    document_id,
                    int(hit.chunk_index),
                )
                continue
            chosen = await self._select_and_authorize_entry(
                scope,
                hit,
                candidates,
                space_order=space_order,
                explicit_entries=explicit_entries,
            )
            if chosen is None:
                continue
            mapped_hit, _ = chosen
            seen_chunks.add(chunk_key)
            mapped.append(mapped_hit)
        return mapped

    async def _load_documents(
        self,
        tenant_id: int,
        document_ids: list[int],
    ) -> dict[int, KnowledgeDocument]:
        rows = await self.document_repository.find_by_ids(document_ids)
        return {
            int(row.id): row
            for row in rows
            if int(row.tenant_id or 0) == tenant_id
        }

    async def _load_scope_entries(
        self,
        *,
        tenant_id: int,
        document_ids: list[int],
        space_ids: list[int],
    ) -> dict[int, list[KnowledgeFile]]:
        rows = await self.file_repository.find_active_entries_for_documents(
            tenant_id=tenant_id,
            document_ids=document_ids,
            knowledge_ids=space_ids,
        )
        grouped: dict[int, list[KnowledgeFile]] = {}
        for row in rows:
            if int(row.tenant_id or 0) != tenant_id:
                # Defensive: the repository already filters by tenant; a
                # mismatch here means cross-tenant leakage - drop, never map.
                logger.warning(
                    "cross-tenant entry returned by mapping query: entry=%s tenant=%s",
                    int(row.id),
                    row.tenant_id,
                )
                continue
            grouped.setdefault(int(row.reference_document_id or 0), []).append(row)
        return grouped

    def _final_document_check(
        self,
        document: KnowledgeDocument | None,
        hit: CanonicalChunkHit,
        entries: list[KnowledgeFile],
        *,
        space_ids: dict[int, int],
    ) -> list[KnowledgeFile]:
        """Structural F059 checks on document + entry rows.

        Returns the candidate entries of the requested spaces (best-first
        order preserved) or an empty list when the hit must be dropped as a
        dirty member (soft-deleted document, entry gone, stale version).
        """
        if document is None:
            return []
        if document.lifecycle_status != KnowledgeDocumentLifecycleStatus.ACTIVE.value:
            return []
        if document.primary_version_id is None:
            return []
        if int(hit.canonical_version_id) != int(document.primary_version_id):
            # Entry must point at the current primary version (spec 3.5.5);
            # hits on superseded versions are stale, not errors.
            return []
        candidates = [
            entry
            for entry in entries
            if int(entry.knowledge_id) in space_ids
            and entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
            and entry.entry_type in _ENTRY_TYPE_PRIORITY
        ]
        return sorted(candidates, key=lambda entry: int(entry.id))

    async def _select_and_authorize_entry(
        self,
        scope: RetrievalScope,
        hit: CanonicalChunkHit,
        candidates: list[KnowledgeFile],
        *,
        space_order: dict[int, int],
        explicit_entries: set[int],
    ) -> tuple[MappedEntryHit, KnowledgeFile] | None:
        ranked = sorted(
            candidates,
            key=lambda entry: self._candidate_rank(entry, space_order, explicit_entries),
        )
        same_space_counts: dict[int, int] = {}
        for entry in candidates:
            same_space_counts[int(entry.knowledge_id)] = (
                same_space_counts.get(int(entry.knowledge_id), 0) + 1
            )

        for entry in ranked:
            self._require_projection_ready(entry)
            allowed = await self._check_entry_view(
                int(scope.tenant_id),
                scope.user_id,
                int(entry.knowledge_id),
                int(entry.id),
            )
            if not allowed:
                # OpenFGA file-level final check denied this entry; try the
                # next visible candidate of another requested space.
                logger.info(
                    "entry view permission denied at final check: tenant=%s user=%s entry=%s space=%s",
                    int(scope.tenant_id),
                    scope.user_id,
                    int(entry.id),
                    int(entry.knowledge_id),
                )
                continue
            entry_id = int(entry.id)
            is_explicit = entry_id in explicit_entries
            if is_explicit:
                rule = "explicit"
            elif same_space_counts[int(entry.knowledge_id)] > 1:
                rule = "entry_type_priority"
            else:
                rule = "space_order"
            # F3.6: only MappedEntryHit fields leave the resolver - raw
            # chunk metadata / knowledge_ids are never forwarded (8.1-8).
            return (
                MappedEntryHit(
                    space_id=SpaceId(int(entry.knowledge_id)),
                    entry_file_id=EntryFileId(entry_id),
                    canonical_document_id=hit.canonical_document_id,
                    canonical_version_id=hit.canonical_version_id,
                    chunk_index=int(hit.chunk_index),
                    score=float(hit.score),
                    text=hit.text,
                    entry_selection_rule=rule,
                ),
                entry,
            )
        return None

    @staticmethod
    def _candidate_rank(
        entry: KnowledgeFile,
        space_order: dict[int, int],
        explicit_entries: set[int],
    ) -> tuple[int, int, int]:
        return (
            0 if int(entry.id) in explicit_entries else 1,
            space_order.get(int(entry.knowledge_id), len(space_order)),
            _ENTRY_TYPE_PRIORITY.get(str(entry.entry_type), 99),
        )

    @staticmethod
    def _require_projection_ready(entry: KnowledgeFile) -> None:
        """Fail closed on projection not converged (spec 8.1-6, F059 generations)."""
        if entry.projection_status != KnowledgeFileProjectionStatus.READY.value:
            raise SharedStorageContractError(
                SharedStorageErrorCode.MEMBERSHIP_PROJECTION_NOT_READY,
                f"entry {int(entry.id)} projection status is {entry.projection_status}, not ready",
                tenant_id=int(entry.tenant_id or 0),
            )
        if int(entry.applied_entry_generation) < int(entry.desired_entry_generation):
            raise SharedStorageContractError(
                SharedStorageErrorCode.MEMBERSHIP_PROJECTION_NOT_READY,
                f"entry {int(entry.id)} entry generation "
                f"{entry.applied_entry_generation} < desired {entry.desired_entry_generation}",
                tenant_id=int(entry.tenant_id or 0),
            )
        if int(entry.applied_content_generation) < int(entry.desired_content_generation):
            raise SharedStorageContractError(
                SharedStorageErrorCode.CONTENT_PROJECTION_NOT_READY,
                f"entry {int(entry.id)} content generation "
                f"{entry.applied_content_generation} < desired {entry.desired_content_generation}",
                tenant_id=int(entry.tenant_id or 0),
            )

    async def _check_entry_view(
        self,
        tenant_id: int,
        user_id: str,
        space_id: int,
        entry_file_id: int,
    ) -> bool:
        try:
            return bool(
                await self.entry_view_checker(
                    TenantId(tenant_id),
                    user_id,
                    SpaceId(space_id),
                    EntryFileId(entry_file_id),
                )
            )
        except SharedStorageContractError:
            raise
        except Exception as exc:
            logger.error(
                "entry permission check failed closed: tenant=%s user=%s entry=%s error=%r",
                tenant_id,
                user_id,
                entry_file_id,
                exc,
            )
            raise SharedStorageContractError(
                SharedStorageErrorCode.PERMISSION_SERVICE_UNAVAILABLE,
                f"permission service unavailable while checking entry {entry_file_id}",
                tenant_id=tenant_id,
            ) from exc

    # ------------------------------------------------------------------
    # F3.4 over-fetch refill loop (consumed by B1/B2/B3 via F1 store client)
    # ------------------------------------------------------------------
    async def map_and_authorize_with_overfetch(
        self,
        scope: RetrievalScope,
        *,
        top_k: int,
        fetch_hits: FetchHitsCallable,
        overfetch_factor: int | None = None,
    ) -> list[MappedEntryHit]:
        """Map hits with store-side over-fetch so the result is not under-filled.

        ``fetch_hits(filter, offset, limit)`` must return the shared store
        page in score order. The loop keeps fetching (default K x 2 pages)
        until ``top_k`` post-check hits are collected or the store has no
        more candidates (spec 3.5 - dirty members must not shrink recall).
        """
        if top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        settings = self._require_enabled()
        factor = max(1, int(overfetch_factor or settings.overfetch_factor))
        page_limit = max(top_k * factor, top_k)
        query_filter = self.build_backend_filter(scope)

        collected: list[MappedEntryHit] = []
        seen: set[tuple[int, int]] = set()
        offset = 0
        rounds = 0
        while len(collected) < top_k and rounds < settings.max_overfetch_rounds:
            hits = await fetch_hits(query_filter, offset, page_limit)
            if not hits:
                break
            for mapped in await self.map_and_authorize_hits(scope, hits):
                key = (int(mapped.canonical_document_id), int(mapped.chunk_index))
                if key not in seen:
                    seen.add(key)
                    collected.append(mapped)
            if len(hits) < page_limit:
                # Store exhausted: no more candidates to refill from.
                break
            offset += len(hits)
            rounds += 1
        return collected[:top_k]

    # ------------------------------------------------------------------
    def _require_enabled(self) -> RetrievalScopeResolverSettings:
        settings = self._settings_provider()
        if not settings.enabled:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SHARED_STORAGE_NOT_ENABLED,
                "shared space storage retrieval is not enabled for this deployment",
            )
        return settings


def _dedupe_optional(
    ids: Sequence[Any] | None,
) -> tuple[Any, ...] | None:
    if ids is None:
        return None
    return tuple(dict.fromkeys(int(i) for i in ids))


def render_milvus_expr(query_filter: BackendQueryFilter) -> str:
    """Render the membership pre-filter as a Milvus boolean expression (spec 3.6).

    Single space uses ``ARRAY_CONTAINS``; multi-space uses
    ``ARRAY_CONTAINS_ANY``. The expression always carries the tenant
    boundary; "global Top-K then filter" cannot be expressed here.
    """
    spaces = [int(s) for s in query_filter.requested_space_ids]
    if not spaces:
        raise ValueError("BackendQueryFilter without requested spaces is not renderable")
    parts = [f"tenant_id == {int(query_filter.tenant_id)}"]
    if len(spaces) == 1:
        parts.append(f"ARRAY_CONTAINS(knowledge_ids, {spaces[0]})")
    else:
        parts.append(f"ARRAY_CONTAINS_ANY(knowledge_ids, [{', '.join(str(s) for s in spaces)}])")
    if query_filter.canonical_document_ids is not None:
        ids = [int(i) for i in query_filter.canonical_document_ids]
        parts.append(f"canonical_document_id in [{', '.join(str(i) for i in ids)}]")
    if query_filter.canonical_version_ids is not None:
        ids = [int(i) for i in query_filter.canonical_version_ids]
        parts.append(f"canonical_version_id in [{', '.join(str(i) for i in ids)}]")
    return " and ".join(parts)


def render_es_membership_query(query_filter: BackendQueryFilter) -> dict:
    """Render the membership pre-filter as an ES bool/filter query (spec 3.6)."""
    spaces = [int(s) for s in query_filter.requested_space_ids]
    if not spaces:
        raise ValueError("BackendQueryFilter without requested spaces is not renderable")
    filters = [
        {"term": {"metadata.tenant_id": int(query_filter.tenant_id)}},
        {"terms": {"metadata.knowledge_ids": spaces}},
    ]
    if query_filter.canonical_document_ids is not None:
        filters.append(
            {"terms": {"metadata.canonical_document_id": [int(i) for i in query_filter.canonical_document_ids]}}
        )
    if query_filter.canonical_version_ids is not None:
        filters.append(
            {"terms": {"metadata.canonical_version_id": [int(i) for i in query_filter.canonical_version_ids]}}
        )
    return {"bool": {"filter": filters}}
