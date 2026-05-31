"""F026 KnowledgeFileVisibilityService.

Implements the two-layer view_file permission filter shared by
KnowledgeSpaceChatService.chat_folder, WorkStationService.queryChunksFromDB
and CitationResolveService.

Design rationale: see
features/v2.6.0/026-knowledge-qa-permission-filter/spec.md §4 (AD-01/02/03/08).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set

from fastapi import Request
from loguru import logger
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core.config.settings import KnowledgeQAFilterConf
from bisheng.core.database import get_async_db_session


@dataclass
class IndexFilter:
    """Index-layer filter to be injected into Milvus / ES search_kwargs.

    Strategy values:
    - ``in``    — ``document_id in [visible ids]``; small visible set.
    - ``notin`` — ``document_id not in [excluded ids]``; almost everything
      visible.
    - ``none``  — no filter; either admin caller or both sides too large
      (result-layer post-filter alone enforces visibility).
    - ``empty`` — user has zero visible files in the space; caller must skip
      retrieval entirely.
    """

    strategy: str
    milvus_expr: Optional[str] = None
    es_filter: Optional[list] = None
    accessible_size: int = 0
    excluded_ids: List[int] = field(default_factory=list)

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
    # Lazy KnowledgeSpaceService accessor — reused by is_space_visible and
    # post_filter_visible_files to share the permission-binding context.
    # ------------------------------------------------------------------

    def _space_service(self):
        from bisheng.knowledge.domain.services.knowledge_space_service import (
            KnowledgeSpaceService,
        )

        if not hasattr(self, "_knowledge_space_service"):
            self._knowledge_space_service = KnowledgeSpaceService(
                self.request, self.login_user
            )
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
        """Non-throwing wrapper around the view_space gate.

        Returns True for admin users (the underlying PermissionService
        short-circuits) and for any user whose effective permissions on the
        space include view_space; False otherwise. Errors other than
        ``SpacePermissionDeniedError`` propagate.
        """
        svc = self._space_service()
        try:
            await svc._require_read_permission(space_id)
            await svc._require_permission_id(
                "knowledge_space", space_id, "view_space"
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
        candidate_file_ids: Optional[List[int]],
    ) -> IndexFilter:
        """Decide the Milvus / ES filter for the upcoming retrieval round.

        See spec §4 AD-02 for the IN / NOT-IN / none strategy matrix.
        """
        from bisheng.permission.domain.services.permission_service import (
            PermissionService,
        )

        accessible_ids = await PermissionService.list_accessible_ids(
            user_id=self.login_user.user_id,
            relation="can_read",
            object_type="knowledge_file",
            login_user=self.login_user,
        )

        # Admin: list_accessible_ids returns None → no filter pushdown.
        if accessible_ids is None:
            return IndexFilter(strategy="none")

        accessible_int = {int(x) for x in accessible_ids if str(x).isdigit()}

        # Scope to this space — the user's full accessible set spans every
        # knowledge_file they can read tenant-wide. We only care about files
        # in the queried space.
        space_primary_ids = await self._list_primary_file_ids_in_space(space_id)
        scoped = accessible_int & space_primary_ids
        if candidate_file_ids is not None:
            scoped &= {int(x) for x in candidate_file_ids}

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

        # NOT IN path only beats IN when the complement is smaller than the
        # configured threshold; otherwise fall through to no pushdown.
        complement = sorted(space_primary_ids - scoped)
        if n - k <= threshold and complement:
            return IndexFilter(
                strategy="notin",
                milvus_expr=f"document_id not in {complement}",
                es_filter=[
                    {
                        "bool": {
                            "must_not": {
                                "terms": {"metadata.document_id": complement}
                            }
                        }
                    }
                ],
                accessible_size=k,
                excluded_ids=complement,
            )

        # Both sides too large — push the work entirely to the result layer.
        return IndexFilter(strategy="none", accessible_size=k)

    # ------------------------------------------------------------------
    # post_filter_visible_files — AD-01 / AD-08
    # ------------------------------------------------------------------

    async def post_filter_visible_files(
        self,
        space_id: int,
        file_ids: Iterable[int],
    ) -> Set[int]:
        """Return the subset of ``file_ids`` for which the current user holds
        ``view_file`` in effective permissions.

        Admin short-circuits to the input set.
        Empty input short-circuits before building the permission context.
        Otherwise the per-file effective-permission resolution runs with a
        bounded semaphore (``fine_grained_concurrency``) and a shared
        tuple_cache for OpenFGA reads.
        """
        file_id_set: Set[int] = {int(x) for x in file_ids}
        if not file_id_set:
            return set()

        if self.login_user.is_admin():
            return file_id_set

        from bisheng.permission.domain.services.fine_grained_permission_service import (
            FineGrainedPermissionService,
        )

        space_svc = self._space_service()
        context = await space_svc._build_child_permission_context(space_id)
        semaphore = asyncio.Semaphore(self._config().fine_grained_concurrency)

        async def resolve(file_id: int) -> Optional[int]:
            async with semaphore:
                try:
                    effective = (
                        await FineGrainedPermissionService.get_effective_permission_ids_async(
                            self.login_user,
                            "knowledge_file",
                            file_id,
                            models=context.get("models"),
                            bindings=context.get("bindings"),
                            binding_department_paths=context.get(
                                "binding_department_paths"
                            ),
                            user_subject_strings=context.get(
                                "user_subject_strings"
                            ),
                            tuple_cache=context.get("tuple_cache"),
                            tuple_department_paths=context.get(
                                "tuple_department_paths"
                            ),
                        )
                    )
                except Exception:
                    logger.exception(
                        "post_filter_visible_files: fine-grained resolution failed for "
                        "file_id=%s space_id=%s",
                        file_id,
                        space_id,
                    )
                    return None
            return file_id if "view_file" in effective else None

        results = await asyncio.gather(*(resolve(fid) for fid in file_id_set))
        return {fid for fid in results if fid is not None}

    # ------------------------------------------------------------------
    # Internal helpers (patched by tests via monkeypatch)
    # ------------------------------------------------------------------

    async def _count_primary_files_in_space(self, space_id: int) -> int:
        """Count primary-version files in the space (total − non-primary)."""
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        total = await KnowledgeFileDao.async_count_file_by_knowledge_id(space_id)
        non_primary = await self._non_primary_ids(space_id)
        return max(int(total or 0) - len(non_primary), 0)

    async def _list_primary_file_ids_in_space(self, space_id: int) -> Set[int]:
        """List the primary-version file ids in the space."""
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(KnowledgeFile.id).where(
                        KnowledgeFile.knowledge_id == space_id
                    )
                )
            ).all()
        all_ids = {int(row) for row in rows}
        return all_ids - await self._non_primary_ids(space_id)

    async def _non_primary_ids(self, space_id: int) -> Set[int]:
        """Resolve the set of non-primary file ids for the given space."""
        if self.version_repo is None:
            return set()
        excluded = await self.version_repo.find_non_primary_file_ids_by_knowledge_ids(
            [space_id]
        )
        return {int(x) for x in (excluded or [])}
