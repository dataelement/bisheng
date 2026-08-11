from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import SpaceFileChangeRequestNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    KnowledgeSpaceFileChangeFootprintRepository,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# T044 must set this marker in the same UoW as formal DB deletion and F025
# deferred completion. APPLIED without this explicit cutover marker never hides
# a resource, so prepare/failure paths remain fully readable.
DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY = "deletion_cutover_active"


class KnowledgeSpaceDeletionGuard:
    """Hide durable delete residue only after the atomic visibility cutover."""

    _RESOURCE_TYPES = frozenset(
        {
            KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
            KnowledgeSpaceFileChangeResourceType.FOLDER,
            KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE_VERSION,
        }
    )

    def __init__(self, *, session_factory: SessionFactory = get_async_db_session) -> None:
        self.session_factory = session_factory

    async def list_deleted_ids(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
    ) -> set[int]:
        normalized_space_ids = self._validate_scope(tenant_id=tenant_id, space_ids=space_ids)
        if not normalized_space_ids:
            return set()
        async with self.session_factory() as session:
            return await KnowledgeSpaceFileChangeFootprintRepository(session).list_active_delete_resource_ids(
                tenant_id=int(tenant_id),
                space_ids=normalized_space_ids,
                resource_types=sorted(self._RESOURCE_TYPES),
                cutover_checkpoint_key=DELETION_CUTOVER_ACTIVE_CHECKPOINT_KEY,
            )

    async def filter_not_deleted_ids(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        resource_ids: Sequence[int],
    ) -> list[int]:
        deleted_ids = await self.list_deleted_ids(tenant_id=tenant_id, space_ids=space_ids)
        return [int(resource_id) for resource_id in resource_ids if int(resource_id) not in deleted_ids]

    async def require_not_deleted(
        self,
        *,
        tenant_id: int,
        space_id: int,
        resource_id: int,
    ) -> None:
        deleted_ids = await self.list_deleted_ids(tenant_id=tenant_id, space_ids=[space_id])
        if int(resource_id) in deleted_ids:
            # Do not reveal whether a residual index/object still exists.
            raise SpaceFileChangeRequestNotFoundError()

    @staticmethod
    def _validate_scope(*, tenant_id: int, space_ids: Sequence[int]) -> list[int]:
        if int(tenant_id) <= 0:
            raise ValueError("tenant_id must be a positive integer")
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise RuntimeError("a matching tenant context is required for deletion guards")
        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        if any(space_id <= 0 for space_id in normalized_space_ids):
            raise ValueError("space_ids must contain only positive integers")
        return normalized_space_ids
