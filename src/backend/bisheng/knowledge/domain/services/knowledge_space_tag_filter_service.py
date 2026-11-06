"""Resolve immutable user tag selections into index-level retrieval scope."""

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.tag import TagNotExistError
from bisheng.knowledge.domain.repositories.knowledge_space_tag_repository import KnowledgeSpaceTagRepository
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
    IndexFilter,
    KnowledgeFileVisibilityService,
)


class KnowledgeSpaceTagFilterService:
    def __init__(self, repository: KnowledgeSpaceTagRepository | None = None):
        self.repository = repository or KnowledgeSpaceTagRepository()

    async def validate_selection(self, filters: dict[int, int]) -> None:
        for space_id, tag_id in filters.items():
            if not await self.repository.tag_belongs_to_space(space_id, tag_id):
                raise TagNotExistError()

    async def build_index_prefilter(self, space_id: int, tag_id: int, login_user: UserPayload) -> IndexFilter:
        # Validate again at retrieval time: tags may be deleted after tool creation.
        await self.validate_selection({space_id: tag_id})
        file_ids = await self.repository.list_tagged_file_ids(space_id, tag_id)
        if not file_ids:
            return IndexFilter(strategy="empty")
        visibility = KnowledgeFileVisibilityService(request=None, login_user=login_user)
        return await visibility.build_index_prefilter(space_id, candidate_file_ids=file_ids)
