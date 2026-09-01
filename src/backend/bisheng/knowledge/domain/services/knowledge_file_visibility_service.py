"""F029 KnowledgeFileVisibilityService.

Implements the two-layer F048 ``visible`` filter shared by
KnowledgeSpaceChatService.chat_folder, WorkStationService.queryChunksFromDB
and CitationResolveService.

Design rationale: see
features/v2.6.0/029-knowledge-qa-permission-filter/spec.md §4 (AD-01/02/03/08).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    SpaceFileChangeRequestNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.core.config.settings import KnowledgeQAFilterConf
from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
)


@dataclass
class IndexFilter:
    """Index-layer filter to be injected into Milvus / ES search_kwargs.

    Strategy values:
    - ``in``    — ``document_id in [visible ids]``; small visible set.
    - ``notin`` — ``document_id not in [excluded ids]``; almost everything
      visible.
    - ``none``  — no index filter; both sides are too large
      (result-layer post-filter alone enforces visibility).
    - ``empty`` — user has zero visible files in the space; caller must skip
      retrieval entirely.
    """

    strategy: str
    milvus_expr: str | None = None
    es_filter: list | None = None
    accessible_size: int = 0
    excluded_ids: list[int] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.strategy == "empty"


class KnowledgeFileVisibilityService:
    """Centralised view_file visibility decisions for AI Q&A retrieval paths.

    Mirrors the constructor shape of ``KnowledgeSpaceChatService`` so callers
    can build it from the same FastAPI dependency factory and share the same
    request-scoped login_user.

    Attributes:
        version_repo: injected via the FastAPI factory; used to exclude
            non-primary file ids from the candidate pool.
    """

    def __init__(self, request: Request, login_user: UserPayload):
        self.request = request
        self.login_user = login_user
        # version_repo is attached by the FastAPI dependency factory.
        self.version_repo = None

    # ------------------------------------------------------------------
    # Lazy KnowledgeSpaceService accessor used by the space-level gate.
    # ------------------------------------------------------------------

    def _space_service(self):
        from bisheng.knowledge.domain.services.knowledge_space_service import (
            KnowledgeSpaceService,
        )

        if not hasattr(self, "_knowledge_space_service"):
            self._knowledge_space_service = KnowledgeSpaceService(self.request, self.login_user)
        return self._knowledge_space_service

    def _config(self) -> KnowledgeQAFilterConf:
        """Read the runtime config; fresh lookup keeps Redis cache TTL semantics."""
        try:
            from bisheng.common.services.config_service import settings

            conf = settings.knowledge_qa_filter
        except (AttributeError, ImportError):
            conf = None
        return conf or KnowledgeQAFilterConf()

    def _publication_guard(self):
        if not hasattr(self, "_knowledge_space_file_publication_guard"):
            from bisheng.knowledge.domain.services.knowledge_space_file_publication_guard import (
                KnowledgeSpaceFilePublicationGuard,
            )

            self._knowledge_space_file_publication_guard = KnowledgeSpaceFilePublicationGuard()
        return self._knowledge_space_file_publication_guard

    def _deletion_guard(self):
        if not hasattr(self, "_knowledge_space_deletion_guard"):
            from bisheng.knowledge.domain.services.knowledge_space_deletion_guard import (
                KnowledgeSpaceDeletionGuard,
            )

            self._knowledge_space_deletion_guard = KnowledgeSpaceDeletionGuard()
        return self._knowledge_space_deletion_guard

    def _mutation_read_projection(self):
        if not hasattr(self, "_knowledge_space_mutation_read_projection"):
            from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
                MutationReadProjectionService,
            )

            self._knowledge_space_mutation_read_projection = MutationReadProjectionService()
        return self._knowledge_space_mutation_read_projection

    def _require_explicit_tenant(self) -> int:
        """Require the request identity and ContextVar to name the same tenant."""
        login_tenant_id = int(self.login_user.tenant_id)
        user_id = int(self.login_user.user_id)
        current_tenant_id = get_current_tenant_id()
        if login_tenant_id <= 0 or user_id <= 0 or current_tenant_id is None or int(current_tenant_id) <= 0:
            raise ValueError("positive tenant_id and user_id are required for file visibility")
        effective_tenant_id = int(current_tenant_id)
        if effective_tenant_id == login_tenant_id:
            return effective_tenant_id
        admin_scope_tenant_id = get_admin_scope_tenant_id()
        if (
            admin_scope_tenant_id is not None
            and int(admin_scope_tenant_id) == effective_tenant_id
            and self.login_user.is_global_super is True
        ):
            return effective_tenant_id
        raise RuntimeError("a matching tenant context is required for file visibility")

    def require_explicit_tenant(self) -> int:
        """Expose the validated effective tenant to composed knowledge services."""
        return self._require_explicit_tenant()

    async def _list_file_change_excluded_ids(self, *, space_ids: list[int]) -> set[int]:
        tenant_id = self._require_explicit_tenant()
        publication_guard = self._publication_guard()
        deletion_guard = self._deletion_guard()
        unpublished_ids, deleted_ids, fenced_ids = await asyncio.gather(
            publication_guard.list_unpublished_ids(
                tenant_id=tenant_id,
                space_ids=space_ids,
            ),
            deletion_guard.list_deleted_ids(
                tenant_id=tenant_id,
                space_ids=space_ids,
            ),
            self._mutation_read_projection().list_invisible_ids(
                tenant_id=tenant_id,
                space_ids=space_ids,
            ),
        )
        return {int(resource_id) for resource_id in unpublished_ids | deleted_ids | fenced_ids}

    async def list_file_change_excluded_ids(self, *, space_ids: list[int]) -> set[int]:
        """Return F046 hard-deny IDs with one batched guard read per space set."""
        return await self._list_file_change_excluded_ids(space_ids=space_ids)

    async def filter_file_change_visible_ids(
        self,
        *,
        space_ids: list[int],
        resource_ids: Iterable[int],
    ) -> set[int]:
        """Apply only F046's publication/deletion hard deny to a batch of IDs."""
        candidate_ids = {int(resource_id) for resource_id in resource_ids}
        if not candidate_ids:
            return set()
        excluded_ids = await self._list_file_change_excluded_ids(space_ids=space_ids)
        visible = candidate_ids - excluded_ids
        authoritative = await self._mutation_read_projection().authoritative_space_ids(
            tenant_id=self._require_explicit_tenant(),
            space_ids=space_ids,
            resource_ids=visible,
        )
        if not authoritative:
            return visible
        allowed_spaces = {
            space_id: await self.is_space_visible(space_id)
            for space_id in sorted(set(authoritative.values()))
        }
        return {
            resource_id
            for resource_id in visible
            if resource_id not in authoritative or allowed_spaces[authoritative[resource_id]]
        }

    async def require_file_change_visible(
        self,
        *,
        space_id: int,
        resource_id: int,
        allow_unpublished_stakeholder: bool = False,
    ) -> None:
        """Deny an F046-hidden row after the caller's existing ReBAC check."""
        tenant_id = self._require_explicit_tenant()
        await self._deletion_guard().require_not_deleted(
            tenant_id=tenant_id,
            space_id=int(space_id),
            resource_id=int(resource_id),
        )
        await self._mutation_read_projection().require_current_view(
            tenant_id=tenant_id,
            space_id=int(space_id),
            resource_id=int(resource_id),
        )
        authoritative = await self._mutation_read_projection().authoritative_space_ids(
            tenant_id=tenant_id,
            space_ids=[int(space_id)],
            resource_ids=[int(resource_id)],
        )
        authoritative_space_id = authoritative.get(int(resource_id))
        if authoritative_space_id is not None and not await self.is_space_visible(authoritative_space_id):
            raise SpaceFileChangeRequestNotFoundError()
        if allow_unpublished_stakeholder:
            await self._publication_guard().require_published_or_stakeholder(
                tenant_id=tenant_id,
                space_id=int(space_id),
                resource_id=int(resource_id),
                viewer_user_id=int(self.login_user.user_id),
            )
            return
        unpublished_ids = await self._publication_guard().list_unpublished_ids(
            tenant_id=tenant_id,
            space_ids=[int(space_id)],
        )
        if int(resource_id) in unpublished_ids:
            raise SpaceFileChangeRequestNotFoundError()

    async def project_mutation_retrieval_names(self, *, space_id: int, documents: list[Any]) -> list[Any]:
        """Project retrieval names to the durable OLD_VIEW or NEW_VIEW."""

        document_ids = {
            int(document.metadata["document_id"])
            for document in documents
            if getattr(document, "metadata", None) and document.metadata.get("document_id") is not None
        }
        names = await self._mutation_read_projection().name_projection(
            tenant_id=self._require_explicit_tenant(),
            space_id=int(space_id),
            resource_ids=document_ids,
        )
        for document in documents:
            metadata = getattr(document, "metadata", None)
            if not metadata or metadata.get("document_id") is None:
                continue
            old_and_new = names.get(int(metadata["document_id"]))
            if old_and_new is None:
                continue
            projected_name, replaced_name = old_and_new
            document.metadata = {**metadata, "document_name": projected_name}
            if isinstance(getattr(document, "page_content", None), str):
                document.page_content = document.page_content.replace(replaced_name, projected_name)
        return documents

    async def old_name_projection(
        self,
        *,
        space_id: int,
        resource_ids: Iterable[int],
    ) -> dict[int, tuple[str, str]]:
        return await self._mutation_read_projection().name_projection(
            tenant_id=self._require_explicit_tenant(),
            space_id=int(space_id),
            resource_ids=resource_ids,
        )

    async def authoritative_mutation_space_ids(
        self,
        *,
        space_ids: list[int],
        resource_ids: Iterable[int],
    ) -> dict[int, int]:
        """Resolve active OLD/NEW mutation locations within the current tenant."""

        return await self._mutation_read_projection().authoritative_space_ids(
            tenant_id=self._require_explicit_tenant(),
            space_ids=space_ids,
            resource_ids=resource_ids,
        )

    async def project_mutation_retrieval_query(self, *, space_id: int, query: str) -> str:
        return await self._mutation_read_projection().expand_retrieval_query(
            tenant_id=self._require_explicit_tenant(),
            space_id=int(space_id),
            query=str(query),
        )

    # ------------------------------------------------------------------
    # is_space_visible — AC-11
    # ------------------------------------------------------------------

    async def is_space_visible(self, space_id: int) -> bool:
        """Non-throwing wrapper around the concrete space ``visible`` gate.

        Returns False on an ordinary authorization denial. Business/resource
        errors still propagate.
        """
        svc = self._space_service()
        try:
            await svc._require_read_permission(space_id)
            await svc._require_action(
                "knowledge_space",
                space_id,
                "visible",
            )
            return True
        except SpacePermissionDeniedError:
            return False

    # ------------------------------------------------------------------
    # build_index_prefilter — AD-02 strategy decision
    # ------------------------------------------------------------------

    async def build_index_prefilter(
        self,
        space_id: int,
        candidate_file_ids: list[int] | None,
    ) -> IndexFilter:
        """Decide the Milvus / ES filter for the upcoming retrieval round.

        See spec §4 AD-02 for the IN / NOT-IN / none strategy matrix.
        """
        # candidate_file_ids carries the explicit folder / tag business scope.
        # Unlike the permission set, it has NO result-layer backstop
        # (post_filter_retrievable_files enforces visibility and primary
        # version, not folder / tag scope), so whenever it is provided it MUST
        # be pushed down into the index — it can never be dropped via the
        # both-sides-too-large 'none' shortcut.
        has_business_scope = candidate_file_ids is not None
        file_change_excluded_ids = await self._list_file_change_excluded_ids(space_ids=[int(space_id)])

        non_primary_ids = await self._non_primary_ids(space_id)
        space_primary_ids = await self._list_primary_file_ids_in_space(
            space_id,
            non_primary_ids=non_primary_ids,
        )
        # F046: files locked by a pending change request are not retrievable.
        candidates = set(space_primary_ids) - file_change_excluded_ids
        if has_business_scope:
            candidates &= {int(x) for x in candidate_file_ids}

        action_map = await batch_check_business_actions(
            self.login_user,
            resource_type="knowledge_file",
            resource_ids=sorted(candidates),
            actions=("visible",),
        )
        scoped = {file_id for file_id in candidates if "visible" in action_map.get(str(file_id), frozenset())}

        if not scoped:
            return IndexFilter(strategy="empty", accessible_size=0)

        k = len(scoped)
        threshold = self._config().index_filter_threshold

        if k <= threshold:
            sorted_ids = sorted(scoped)
            return IndexFilter(
                strategy="in",
                milvus_expr=f"document_id in {sorted_ids}",
                es_filter=[{"terms": {"metadata.document_id": sorted_ids}}],
                accessible_size=k,
            )

        # NOT IN path beats IN when the complement is smaller than the
        # configured threshold. When a business scope is in force we must still
        # push down even past the threshold, so fall back to whichever of the
        # IN / NOT-IN lists is smaller rather than dropping the scope.
        # Historical versions remain in Milvus / ES until explicitly deleted.
        # A NOT-IN filter must therefore exclude them as well as permission-
        # invisible primary files. The result-layer retrievable-file filter is
        # still the hard backstop when this complement is too large to push down.
        complement = sorted((space_primary_ids - scoped) | non_primary_ids | file_change_excluded_ids)
        if complement and (len(complement) <= threshold or (has_business_scope and len(complement) <= k)):
            return IndexFilter(
                strategy="notin",
                milvus_expr=f"document_id not in {complement}",
                es_filter=[{"bool": {"must_not": {"terms": {"metadata.document_id": complement}}}}],
                accessible_size=k,
                excluded_ids=complement,
            )

        if has_business_scope:
            # Large explicit scope with a large complement: enforce via IN. The
            # folder / tag boundary is correctness, not an optimisation, so a
            # big IN list is preferable to leaking outside it.
            sorted_ids = sorted(scoped)
            return IndexFilter(
                strategy="in",
                milvus_expr=f"document_id in {sorted_ids}",
                es_filter=[{"terms": {"metadata.document_id": sorted_ids}}],
                accessible_size=k,
            )

        if file_change_excluded_ids:
            excluded_ids = sorted(file_change_excluded_ids)
            return IndexFilter(
                strategy="notin",
                milvus_expr=f"document_id not in {excluded_ids}",
                es_filter=[
                    {
                        "bool": {
                            "must_not": {
                                "terms": {"metadata.document_id": excluded_ids},
                            }
                        }
                    }
                ],
                accessible_size=k,
                excluded_ids=excluded_ids,
            )

        # Permission-only path, both sides too large — push the work entirely to
        # the result layer (post_filter_retrievable_files is the backstop).
        return IndexFilter(strategy="none", accessible_size=k)

    # ------------------------------------------------------------------
    # post_filter_visible_files — AD-01 / AD-08
    # ------------------------------------------------------------------

    async def post_filter_visible_files(
        self,
        space_id: int,
        file_ids: Iterable[int],
    ) -> set[int]:
        """Return the subset of ``file_ids`` allowing F048 ``visible``.

        Empty input short-circuits before building the permission context.
        Business rows are loaded first, then the exact F048 ``visible`` action
        is BatchChecked. OpenFGA identity relations handle super administrators;
        this service has no creator/admin fallback.
        """
        file_id_set: set[int] = {int(x) for x in file_ids}
        if not file_id_set:
            return set()

        rebac_visible_ids = await self.post_filter_rebac_visible_files(space_id, file_id_set)
        return await self.filter_file_change_visible_ids(
            space_ids=[int(space_id)],
            resource_ids=rebac_visible_ids,
        )

    async def post_filter_rebac_visible_files(
        self,
        space_id: int,
        file_ids: Iterable[int],
    ) -> set[int]:
        """Run the original F029 ReBAC/effective-permission post-filter only."""
        file_id_set: set[int] = {int(x) for x in file_ids}
        if not file_id_set:
            return set()

        if self.login_user.is_admin():
            return file_id_set

        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        items = await KnowledgeFileDao.aget_file_by_ids(list(file_id_set))
        candidate_ids = {int(item.id) for item in items if item.knowledge_id == space_id}
        if not candidate_ids:
            return set()
        action_map = await batch_check_business_actions(
            self.login_user,
            resource_type="knowledge_file",
            resource_ids=sorted(candidate_ids),
            actions=("visible",),
        )
        return {file_id for file_id in candidate_ids if "visible" in action_map.get(str(file_id), frozenset())}

    async def post_filter_retrievable_files(
        self,
        space_id: int,
        file_ids: Iterable[int],
    ) -> set[int]:
        """Return visible current-primary files eligible for RAG retrieval.

        Non-primary versions stay indexed by design, so index filters are only
        an optimization. This result-layer intersection is the correctness
        boundary for IN, NOT-IN, and unfiltered retrieval strategies.
        """
        visible_ids = await self.post_filter_visible_files(space_id, file_ids)
        if not visible_ids:
            return set()
        return visible_ids - await self._non_primary_ids(space_id)

    # ------------------------------------------------------------------
    # Internal helpers (patched by tests via monkeypatch)
    # ------------------------------------------------------------------

    async def _count_primary_files_in_space(self, space_id: int) -> int:
        """Count primary-version files in the space (total minus non-primary)."""
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        total = await KnowledgeFileDao.async_count_file_by_knowledge_id(space_id)
        non_primary = await self._non_primary_ids(space_id)
        return max(int(total or 0) - len(non_primary), 0)

    async def _list_primary_file_ids_in_space(
        self,
        space_id: int,
        *,
        non_primary_ids: set[int] | None = None,
    ) -> set[int]:
        """List the primary-version file ids in the space."""
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        async with get_async_db_session() as session:
            rows = (await session.exec(select(KnowledgeFile.id).where(KnowledgeFile.knowledge_id == space_id))).all()
        all_ids = {int(row) for row in rows}
        excluded = non_primary_ids
        if excluded is None:
            excluded = await self._non_primary_ids(space_id)
        return all_ids - excluded

    async def _non_primary_ids(self, space_id: int) -> set[int]:
        """Resolve the set of non-primary file ids for the given space."""
        if self.version_repo is not None:
            excluded = await self.version_repo.find_non_primary_file_ids_by_knowledge_ids([space_id])
            return {int(x) for x in (excluded or [])}

        from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
            KnowledgeDocumentVersionRepositoryImpl,
        )

        async with get_async_db_session() as session:
            repo = KnowledgeDocumentVersionRepositoryImpl(session)
            excluded = await repo.find_non_primary_file_ids_by_knowledge_ids([space_id])
        return {int(x) for x in (excluded or [])}
