from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceFileChangeRequestNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    KnowledgeSpaceFileChangeFootprintRepository,
    MutationReadProjection,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY = "mutation_transition_active"
MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY = "mutation_transition_phase"
MUTATION_TRANSITION_OLD_VIEW = "old_view"
MUTATION_TRANSITION_NEW_VIEW = "new_view"


class MutationReadProjectionService:
    """Project one durable rename/move generation as an old or new formal view."""

    def __init__(self, *, session_factory: SessionFactory = get_async_db_session) -> None:
        self.session_factory = session_factory

    async def list_projections(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
    ) -> list[MutationReadProjection]:
        normalized = self._validate_scope(tenant_id=tenant_id, space_ids=space_ids)
        if not normalized:
            return []
        async with self.session_factory() as session:
            return await KnowledgeSpaceFileChangeFootprintRepository(
                session
            ).list_active_mutation_projections(
                tenant_id=int(tenant_id),
                space_ids=normalized,
                transition_active_key=MUTATION_TRANSITION_ACTIVE_CHECKPOINT_KEY,
                transition_phase_key=MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY,
            )

    async def list_invisible_ids(self, *, tenant_id: int, space_ids: Sequence[int]) -> set[int]:
        normalized = set(self._validate_scope(tenant_id=tenant_id, space_ids=space_ids))
        invisible: set[int] = set()
        for projection in await self.list_projections(tenant_id=tenant_id, space_ids=sorted(normalized)):
            rows = projection.manifest.get("rows") or []
            for row in rows:
                resource_id = int(row["id"])
                old_space_id = int(row.get("old_space_id") or projection.source_space_id)
                new_space_id = int(row.get("new_space_id") or projection.target_space_id)
                if projection.phase == MUTATION_TRANSITION_OLD_VIEW:
                    if new_space_id != old_space_id and new_space_id in normalized:
                        invisible.add(resource_id)
                elif projection.phase == MUTATION_TRANSITION_NEW_VIEW:
                    if new_space_id != old_space_id and old_space_id in normalized:
                        invisible.add(resource_id)
                else:
                    raise RuntimeError(f"unsupported F046 mutation projection phase: {projection.phase}")
        return invisible

    async def require_current_view(self, *, tenant_id: int, space_id: int, resource_id: int) -> None:
        if int(resource_id) in await self.list_invisible_ids(
            tenant_id=tenant_id,
            space_ids=[int(space_id)],
        ):
            raise SpaceFileChangeRequestNotFoundError()

    async def authoritative_space_ids(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        resource_ids: Iterable[int],
    ) -> dict[int, int]:
        candidates = {int(resource_id) for resource_id in resource_ids}
        authoritative: dict[int, int] = {}
        if not candidates:
            return authoritative
        for projection in await self.list_projections(tenant_id=tenant_id, space_ids=space_ids):
            current_space_id = (
                projection.source_space_id
                if projection.phase == MUTATION_TRANSITION_OLD_VIEW
                else projection.target_space_id
            )
            for row in projection.manifest.get("rows") or []:
                resource_id = int(row["id"])
                if resource_id in candidates:
                    authoritative[resource_id] = int(current_space_id)
        return authoritative

    async def name_projection(
        self,
        *,
        tenant_id: int,
        space_id: int,
        resource_ids: Iterable[int],
    ) -> dict[int, tuple[str, str]]:
        candidates = {int(resource_id) for resource_id in resource_ids}
        if not candidates:
            return {}
        projected: dict[int, tuple[str, str]] = {}
        for transition in await self.list_projections(tenant_id=tenant_id, space_ids=[space_id]):
            if transition.action != KnowledgeSpaceFileChangeAction.RENAME or int(
                transition.source_space_id
            ) != int(space_id):
                continue
            root = transition.manifest.get("root") or {}
            resource_id = int(root.get("id") or 0)
            old_name = str(root.get("old_name") or "")
            new_name = str(transition.manifest.get("new_name") or "")
            if resource_id in candidates and old_name and new_name:
                if transition.phase == MUTATION_TRANSITION_OLD_VIEW:
                    projected[resource_id] = (old_name, new_name)
                elif transition.phase == MUTATION_TRANSITION_NEW_VIEW:
                    projected[resource_id] = (new_name, old_name)
                else:
                    raise RuntimeError(f"unsupported F046 mutation projection phase: {transition.phase}")
        return projected

    async def expand_retrieval_query(self, *, tenant_id: int, space_id: int, query: str) -> str:
        """Keep NEW_VIEW rename recall live while official retrieval cleanup is pending."""

        expanded = str(query)
        fallbacks: list[str] = []
        for transition in await self.list_projections(tenant_id=tenant_id, space_ids=[space_id]):
            if (
                transition.action != KnowledgeSpaceFileChangeAction.RENAME
                or transition.phase != MUTATION_TRANSITION_NEW_VIEW
            ):
                continue
            root = transition.manifest.get("root") or {}
            old_name = str(root.get("old_name") or "")
            new_name = str(transition.manifest.get("new_name") or "")
            if old_name and new_name and new_name in expanded:
                fallback = expanded.replace(new_name, old_name)
                if fallback != expanded and fallback not in fallbacks:
                    fallbacks.append(fallback)
        return "\n".join([expanded, *fallbacks])

    @staticmethod
    def _validate_scope(*, tenant_id: int, space_ids: Sequence[int]) -> list[int]:
        if int(tenant_id) <= 0:
            raise ValueError("tenant_id must be a positive integer")
        current = get_current_tenant_id()
        if current is None or int(current) != int(tenant_id):
            raise RuntimeError("a matching tenant context is required for mutation read projection")
        normalized = sorted({int(space_id) for space_id in space_ids})
        if any(space_id <= 0 for space_id in normalized):
            raise ValueError("space_ids must contain only positive integers")
        return normalized
