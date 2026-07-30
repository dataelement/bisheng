"""F029 KnowledgeFileVisibilityService.

Implements the two-layer F048 ``visible`` filter shared by
KnowledgeSpaceChatService.chat_folder, WorkStationService.queryChunksFromDB
and CitationResolveService.

Design rationale: see
features/v2.6.0/029-knowledge-qa-permission-filter/spec.md §4 (AD-01/02/03/08).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from fastapi import Request
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core.config.settings import KnowledgeQAFilterConf
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
        # (post_filter_visible_files only enforces ``visible``), so whenever it
        # is provided it MUST be pushed down into the index — it can never be
        # dropped via the both-sides-too-large 'none' shortcut.
        has_business_scope = candidate_file_ids is not None

        space_primary_ids = await self._list_primary_file_ids_in_space(space_id)
        candidates = set(space_primary_ids)
        if has_business_scope:
            candidates &= {int(x) for x in candidate_file_ids}

        action_map = await batch_check_business_actions(
            self.login_user,
            resource_type="knowledge_file",
            resource_ids=sorted(candidates),
            actions=("visible",),
        )
        scoped = {
            file_id
            for file_id in candidates
            if "visible"
            in action_map.get(str(file_id), frozenset())
        }

        if not scoped:
            return IndexFilter(strategy="empty", accessible_size=0)

        n = await self._count_primary_files_in_space(space_id)
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
        complement = sorted(space_primary_ids - scoped)
        if complement and (n - k <= threshold or (has_business_scope and len(complement) <= k)):
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

        # Permission-only path, both sides too large — push the work entirely to
        # the result layer (post_filter_visible_files is the backstop).
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

        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        items = await KnowledgeFileDao.aget_file_by_ids(list(file_id_set))
        candidate_ids = {
            int(item.id)
            for item in items
            if item.knowledge_id == space_id
        }
        if not candidate_ids:
            return set()
        action_map = await batch_check_business_actions(
            self.login_user,
            resource_type="knowledge_file",
            resource_ids=sorted(candidate_ids),
            actions=("visible",),
        )
        return {
            file_id
            for file_id in candidate_ids
            if "visible"
            in action_map.get(str(file_id), frozenset())
        }

    # ------------------------------------------------------------------
    # Internal helpers (patched by tests via monkeypatch)
    # ------------------------------------------------------------------

    async def _count_primary_files_in_space(self, space_id: int) -> int:
        """Count primary-version files in the space (total − non-primary)."""
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        total = await KnowledgeFileDao.async_count_file_by_knowledge_id(space_id)
        non_primary = await self._non_primary_ids(space_id)
        return max(int(total or 0) - len(non_primary), 0)

    async def _list_primary_file_ids_in_space(self, space_id: int) -> set[int]:
        """List the primary-version file ids in the space."""
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        async with get_async_db_session() as session:
            rows = (await session.exec(select(KnowledgeFile.id).where(KnowledgeFile.knowledge_id == space_id))).all()
        all_ids = {int(row) for row in rows}
        return all_ids - await self._non_primary_ids(space_id)

    async def _non_primary_ids(self, space_id: int) -> set[int]:
        """Resolve the set of non-primary file ids for the given space."""
        if self.version_repo is None:
            return set()
        excluded = await self.version_repo.find_non_primary_file_ids_by_knowledge_ids([space_id])
        return {int(x) for x in (excluded or [])}
