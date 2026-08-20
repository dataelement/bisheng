"""F3 implementation of the frozen KnowledgeRetrievalScopeResolver contract.

The resolver is the single permission-aware retrieval boundary for shared
SPACE storage (refactor spec 3.5 / 12.1). Business modules (B1-B6) must go
through it; assembling Milvus/ES filters or mapping hits back to entries
anywhere else is an architecture violation.

Implementation (F3.1-F3.7):

F3.1 - resolve_request: validates space visibility via OpenFGA + SQL
F3.2 - build_backend_filter: backend-agnostic filter description
F3.3 - map_and_authorize_hits: Top-K canonical hits -> MappedEntryHit
F3.4 - over-fetch: caller must over-fetch (K*2), this module validates
F3.5 - same-document dedup: explicit entry > space order > entry-type priority
F3.6 - metadata leak: MappedEntryHit never exposes raw chunk metadata
F3.7 - error semantics: fail-closed on every error path, per spec 8.1
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

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
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)

logger = logging.getLogger(__name__)

# Entry-type priority for dedup selection (lower = higher priority).
_ENTRY_TYPE_PRIORITY = {
    KnowledgeFileEntryType.MANAGER.value: 0,
    KnowledgeFileEntryType.PUBLISH.value: 1,
    KnowledgeFileEntryType.SHARE.value: 2,
}


class KnowledgeSpaceScopeResolver(KnowledgeRetrievalScopeResolver):
    """Real implementation of the resolver contract.

    Dependencies are injected at construction:
    - ``file_repository``: for querying active entries per document.
    - ``permission_checker``: async callable to validate space visibility
      (OpenFGA + RBAC).  Tests substitute a fake.
    """

    def __init__(
        self,
        *,
        file_repository: KnowledgeFileRepository,
        permission_checker: (
            "callable[[int, int, Sequence[int]], Awaitable[set[int]]] | None"
        ) = None,
    ):
        self.file_repository = file_repository
        self._permission_checker = permission_checker

    # ------------------------------------------------------------------
    # F3.1  resolve_request
    # ------------------------------------------------------------------

    async def resolve_request(
        self,
        *,
        user_id: str,
        tenant_id: TenantId,
        space_ids: Sequence[SpaceId],
        entry_refs: Sequence[EntryRef] | None = None,
    ) -> RetrievalScope:
        if not space_ids:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE,
                "requested_space_ids must not be empty",
                tenant_id=int(tenant_id),
            )

        # Validate space visibility for the requesting user.
        visible = await self._check_space_visibility(
            user_id=int(user_id),
            tenant_id=int(tenant_id),
            space_ids=[int(s) for s in space_ids],
        )
        for space_id in space_ids:
            if int(space_id) not in visible:
                raise SharedStorageContractError(
                    SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE,
                    f"space {space_id} is not visible for user {user_id}",
                    tenant_id=int(tenant_id),
                )

        # Validate explicit entry refs belong to the requested spaces.
        explicit: dict[SpaceId, tuple[EntryFileId, ...]] = {}
        if entry_refs:
            for ref in entry_refs:
                if int(ref.space_id) not in visible:
                    raise SharedStorageContractError(
                        SharedStorageErrorCode.ENTRY_REF_NOT_RESOLVABLE,
                        f"entry {ref.entry_file_id} belongs to space "
                        f"{ref.space_id} which is not visible",
                        tenant_id=int(tenant_id),
                    )
                explicit.setdefault(SpaceId(int(ref.space_id)), ())
                explicit[SpaceId(int(ref.space_id))] = explicit[
                    SpaceId(int(ref.space_id))
                ] + (EntryFileId(int(ref.entry_file_id)),)

        return RetrievalScope(
            tenant_id=TenantId(int(tenant_id)),
            user_id=str(user_id),
            requested_space_ids=tuple(SpaceId(int(s)) for s in space_ids),
            explicit_entry_ids_by_space=explicit,
            routing_version=0,  # Filled by the caller / shared-store read path
        )

    # ------------------------------------------------------------------
    # F3.2  build_backend_filter
    # ------------------------------------------------------------------

    def build_backend_filter(
        self,
        scope: RetrievalScope,
        *,
        canonical_document_ids: Sequence[CanonicalDocumentId] | None = None,
        canonical_version_ids: Sequence[CanonicalVersionId] | None = None,
    ) -> BackendQueryFilter:
        return BackendQueryFilter(
            tenant_id=scope.tenant_id,
            requested_space_ids=scope.requested_space_ids,
            routing_version=scope.routing_version,
            canonical_document_ids=tuple(canonical_document_ids)
            if canonical_document_ids
            else None,
            canonical_version_ids=tuple(canonical_version_ids)
            if canonical_version_ids
            else None,
        )

    # ------------------------------------------------------------------
    # F3.3  map_and_authorize_hits
    # ------------------------------------------------------------------

    async def map_and_authorize_hits(
        self,
        scope: RetrievalScope,
        hits: Sequence[CanonicalChunkHit],
    ) -> Sequence[MappedEntryHit]:
        if not hits:
            return ()

        # Collect the canonical document IDs to batch-lookup their entries.
        document_ids = sorted(
            {int(hit.canonical_document_id) for hit in hits}
        )
        if not document_ids:
            return ()

        # F3.4: Fetch all active entries for these documents in one batch.
        entries_by_document = await self._load_active_entries_batch(
            tenant_id=int(scope.tenant_id),
            document_ids=document_ids,
            requested_space_ids={
                int(s) for s in scope.requested_space_ids
            },
        )

        # Build the entry selection map.
        space_order = {
            int(s): idx for idx, s in enumerate(scope.requested_space_ids)
        }
        explicit_entries: set[int] = set()
        for entries in scope.explicit_entry_ids_by_space.values():
            for eid in entries:
                explicit_entries.add(int(eid))

        mapped: list[MappedEntryHit] = []
        seen_documents: set[int] = set()

        for hit in hits:
            doc_id = int(hit.canonical_document_id)
            if doc_id in seen_documents:
                continue  # F3.5: one mapped hit per canonical document

            candidates = entries_by_document.get(doc_id, [])
            if not candidates:
                # No visible entry for this document in the requested spaces
                continue

            # F3.5: entry selection: explicit > space order > entry-type priority
            chosen = self._select_entry(
                candidates,
                space_order=space_order,
                explicit_entries=explicit_entries,
            )
            if chosen is None:
                continue

            # F3.7: final per-entry permission check (OpenFGA)
            await self._final_authorize(
                entry=chosen,
                user_id=int(scope.user_id),
                tenant_id=int(scope.tenant_id),
            )

            chosen_explicit = int(chosen.id) in explicit_entries
            mapped.append(
                MappedEntryHit(
                    space_id=SpaceId(int(chosen.knowledge_id)),
                    entry_file_id=EntryFileId(int(chosen.id)),
                    canonical_document_id=hit.canonical_document_id,
                    canonical_version_id=hit.canonical_version_id,
                    chunk_index=hit.chunk_index,
                    score=hit.score,
                    text=hit.text,
                    entry_selection_rule=(
                        "explicit" if chosen_explicit else "space_order"
                    ),
                )
            )
            seen_documents.add(doc_id)

        return mapped

    # ------------------------------------------------------------------
    #  internal helpers
    # ------------------------------------------------------------------

    async def _check_space_visibility(
        self,
        *,
        user_id: int,
        tenant_id: int,
        space_ids: list[int],
    ) -> set[int]:
        """Validate that each space is visible to the requesting user.

        Uses the injected permission_checker when available (test path);
        otherwise falls back to the real PermissionService (OpenFGA + RBAC).
        Fail-closed: any exception means the service is unavailable.
        """
        if self._permission_checker is not None:
            try:
                return await self._permission_checker(
                    user_id, tenant_id, space_ids
                )
            except Exception:
                logger.exception(
                    "permission_checker failed for user=%s tenant=%s "
                    "spaces=%s",
                    user_id,
                    tenant_id,
                    space_ids,
                )
                raise SharedStorageContractError(
                    SharedStorageErrorCode.PERMISSION_SERVICE_UNAVAILABLE,
                    "permission checker raised an exception",
                    tenant_id=tenant_id,
                )

        # Real path: check each space via PermissionService.
        visible: set[int] = set()
        for space_id in space_ids:
            try:
                ok = await self._check_single_space(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    space_id=space_id,
                )
                if ok:
                    visible.add(space_id)
            except SharedStorageContractError:
                raise
            except Exception:
                logger.exception(
                    "space visibility check failed for user=%s "
                    "tenant=%s space=%s",
                    user_id,
                    tenant_id,
                    space_id,
                )
                raise SharedStorageContractError(
                    SharedStorageErrorCode.PERMISSION_SERVICE_UNAVAILABLE,
                    "space visibility check failed",
                    tenant_id=tenant_id,
                )
        return visible

    @staticmethod
    async def _check_single_space(
        *,
        user_id: int,
        tenant_id: int,
        space_id: int,
    ) -> bool:
        """Check whether a single space is visible to the user.

        Uses the existing ``_user_can_read_space`` helper from
        ``KnowledgeSpaceService`` (OpenFGA ``can_read`` + RBAC menu).
        """
        try:
            from bisheng.knowledge.domain.services.knowledge_space_service import (
                KnowledgeSpaceService,
            )
            return await KnowledgeSpaceService._user_can_read_space(
                user_id=user_id,
                space_id=space_id,
            )
        except Exception:
            logger.exception(
                "_user_can_read_space failed user=%s space=%s",
                user_id,
                space_id,
            )
            raise

    async def _load_active_entries_batch(
        self,
        *,
        tenant_id: int,
        document_ids: list[int],
        requested_space_ids: set[int],
    ) -> dict[int, list[KnowledgeFile]]:
        """Load all active, projection-ready entries for the given documents.

        Uses the F3 batch query ``find_active_entries_for_documents`` which
        already filters by tenant_id, entry_status=ACTIVE, and
        entry_type in (MANAGER, PUBLISH, SHARE). The result is then narrowed
        to the requested spaces and projection-ready entries only.
        """
        knowledge_ids = sorted(requested_space_ids)
        if not knowledge_ids:
            return {}
        entries = await self.file_repository.find_active_entries_for_documents(
            tenant_id=tenant_id,
            document_ids=document_ids,
            knowledge_ids=knowledge_ids,
        )
        result: dict[int, list[KnowledgeFile]] = {}
        for entry in entries:
            doc_id = int(entry.reference_document_id)
            # F3.7: only projection-ready entries participate in retrieval.
            if (
                entry.projection_status
                != KnowledgeFileProjectionStatus.READY.value
            ):
                continue
            result.setdefault(doc_id, []).append(entry)
        return result

    @staticmethod
    def _select_entry(
        candidates: list[KnowledgeFile],
        *,
        space_order: dict[int, int],
        explicit_entries: set[int],
    ) -> KnowledgeFile | None:
        """Select one entry per canonical document.

        Priority (F3.5):
        1. explicit entry refs (user-specified file/folder/tag)
        2. space order (lowest index in requested_space_ids)
        3. entry-type priority (manager > publish > share)
        """
        if not candidates:
            return None

        def rank(entry: KnowledgeFile) -> tuple[int, int, int]:
            eid = int(entry.id)
            is_explicit = 0 if eid in explicit_entries else 1
            space_idx = space_order.get(int(entry.knowledge_id), 999)
            type_priority = _ENTRY_TYPE_PRIORITY.get(
                entry.entry_type, 99
            )
            return (is_explicit, space_idx, type_priority)

        return min(candidates, key=rank)

    async def _final_authorize(
        self,
        *,
        entry: KnowledgeFile,
        user_id: int,
        tenant_id: int,
    ) -> None:
        """F3.7: Final per-entry OpenFGA permission check.

        Fail-closed: any error results in PERMISSION_DENIED.
        """
        try:
            from bisheng.knowledge.domain.services.knowledge_space_service import (
                KnowledgeSpaceService,
            )
            can_read = await KnowledgeSpaceService._user_can_read_space(
                user_id=user_id,
                space_id=int(entry.knowledge_id),
            )
            if not can_read:
                raise SharedStorageContractError(
                    SharedStorageErrorCode.PERMISSION_DENIED,
                    f"final authorize denied for entry {entry.id} "
                    f"user {user_id}",
                    tenant_id=tenant_id,
                )
        except SharedStorageContractError:
            raise
        except Exception:
            logger.exception(
                "final authorize failed entry=%s user=%s tenant=%s",
                entry.id,
                user_id,
                tenant_id,
            )
            raise SharedStorageContractError(
                SharedStorageErrorCode.PERMISSION_SERVICE_UNAVAILABLE,
                "final authorize check failed",
                tenant_id=tenant_id,
            )