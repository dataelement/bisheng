from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError, SpacePermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import KnowledgeDocumentRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
    KnowledgeDocumentEntryResolutionError,
    KnowledgeDocumentEntryResolver,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.domain.schemas.filelib import FileSourceUrlResp
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import (
    EMPTY_RETRIEVE_SOURCE_LINK,
    FilelibRetrieveSourceService,
    RetrieveSourceRef,
)


class FilelibFileSourceService:
    """Authorize a file entry before issuing its original-file link."""

    def __init__(
        self,
        *,
        request: Request,
        login_user: UserPayload,
        file_repository: KnowledgeFileRepository,
        knowledge_repository: KnowledgeRepository,
        document_repository: KnowledgeDocumentRepository,
        version_repository: KnowledgeDocumentVersionRepository,
        source_service: FilelibRetrieveSourceService,
    ) -> None:
        self.login_user = login_user
        self.file_repository = file_repository
        self.knowledge_repository = knowledge_repository
        self.source_service = source_service
        self.space_service = KnowledgeSpaceService(request=request, login_user=login_user)
        self.entry_resolver = KnowledgeDocumentEntryResolver(
            document_repository=document_repository,
            version_repository=version_repository,
            file_repository=file_repository,
            permission_loader=self._load_permissions,
        )

    async def _load_permissions(self, file_id: int, space_id: int) -> set[str]:
        return await self.space_service._get_effective_permission_ids(
            "knowledge_file",
            file_id,
            space_id=space_id,
        )

    async def get_source_url(self, file_id: int) -> FileSourceUrlResp:
        entry = await self.file_repository.find_by_id(file_id)
        if entry is None or entry.file_type != FileType.FILE.value:
            raise SpaceFileNotFoundError()
        knowledge = await self.knowledge_repository.find_by_id(int(entry.knowledge_id))
        if knowledge is None or knowledge.state == KnowledgeState.DELETING.value:
            raise SpaceFileNotFoundError()
        if knowledge.type == KnowledgeTypeEnum.SPACE.value:
            await self.space_service._require_read_permission(int(knowledge.id))
        else:
            await KnowledgeService.permission_service.ensure_knowledge_read_async(
                login_user=self.login_user,
                owner_user_id=knowledge.user_id,
                knowledge_id=knowledge.id,
            )
        if "view_file" not in await self._load_permissions(file_id, int(entry.knowledge_id)):
            raise SpacePermissionDeniedError()
        try:
            resolved = await self.entry_resolver.resolve(
                tenant_id=int(entry.tenant_id or 1),
                space_id=int(entry.knowledge_id),
                file_id=file_id,
            )
        except KnowledgeDocumentEntryResolutionError as exc:
            raise SpaceFileNotFoundError() from exc
        if not resolved.capabilities.can_view:
            raise SpacePermissionDeniedError()
        links = await self.source_service.resolve_links(
            [
                RetrieveSourceRef(
                    entry_file_id=file_id,
                    canonical_document_id=resolved.canonical_document_id,
                    canonical_version_id=resolved.canonical_version_id,
                )
            ]
        )
        return FileSourceUrlResp(
            file_id=file_id,
            source_full_url=links.get(file_id, EMPTY_RETRIEVE_SOURCE_LINK).source_full_url,
        )
