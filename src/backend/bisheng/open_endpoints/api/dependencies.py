import logging
from typing import TYPE_CHECKING

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.developer_token import DeveloperTokenInvalidFileSyncRuleError
from bisheng.common.errcode.filelib_sync import FilelibSyncRuleNotConfiguredError
from bisheng.developer_token.api.dependencies import (
    get_developer_token_principal,
    get_developer_token_user,
)
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenFileSyncRule,
    DeveloperTokenPrincipal,
)
from bisheng.developer_token.domain.services import DeveloperTokenService
from bisheng.knowledge.api.dependencies import get_knowledge_document_version_repository
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.domain.repositories.implementations.filelib_sync_repository_impl import (
    FilelibSyncRepositoryImpl,
)
from bisheng.open_endpoints.domain.repositories.interfaces.filelib_sync_repository import (
    FilelibSyncRepository,
)
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService

if TYPE_CHECKING:
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService


logger = logging.getLogger(__name__)


async def get_filelib_sync_principal(
    principal: DeveloperTokenPrincipal = Depends(get_developer_token_principal),
) -> DeveloperTokenPrincipal:
    try:
        rule = DeveloperTokenService._normalize_file_sync_rule(principal.raw_file_sync_rule)
    except DeveloperTokenInvalidFileSyncRuleError as exc:
        logger.warning("developer token file sync rule is invalid token_id=%s", principal.token_id)
        raise FilelibSyncRuleNotConfiguredError() from exc
    if rule is None:
        raise FilelibSyncRuleNotConfiguredError()
    return principal.model_copy(
        update={"raw_file_sync_rule": rule.model_dump(mode="json")},
    )


async def get_knowledge_repository(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeRepository:
    """Dapatkan KnowledgeRepositoryInstance Dependencies"""
    return KnowledgeRepositoryImpl(session)


async def get_knowledge_file_repository(
    session: AsyncSession = Depends(get_db_session),
) -> "KnowledgeFileRepository":
    """Dapatkan KnowledgeFileRepositoryInstance Dependencies"""

    return KnowledgeFileRepositoryImpl(session)


async def get_knowledge_service(
    knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
    knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> "KnowledgeService":
    """Dapatkan KnowledgeServiceInstance Dependencies"""
    return KnowledgeService(
        knowledge_repository=knowledge_repository, knowledge_file_repository=knowledge_file_repository
    )


async def get_knowledge_file_service(
    knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
    knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> "KnowledgeFileService":
    """Dapatkan KnowledgeFileServiceInstance Dependencies"""
    return KnowledgeFileService(
        knowledge_repository=knowledge_repository,
        knowledge_file_repository=knowledge_file_repository,
    )


async def get_knowledge_space_chat_service_for_openapi(
    request: Request,
    developer_user: UserPayload = Depends(get_developer_token_user),
    version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
) -> "KnowledgeSpaceChatService":
    """KnowledgeSpaceChatService bound to the authenticated developer-token user.

    Used by the OpenAPI surface so external systems authenticate with
    ``X-Developer-Token`` instead of user JWTs.
    """
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService

    service = KnowledgeSpaceChatService(request=request, login_user=developer_user)
    service.version_repo = version_repo
    return service


async def get_filelib_sync_repository(
    session: AsyncSession = Depends(get_db_session),
) -> FilelibSyncRepository:
    return FilelibSyncRepositoryImpl(session)


async def get_filelib_sync_service(
    request: Request,
    principal: DeveloperTokenPrincipal = Depends(get_filelib_sync_principal),
    repository: FilelibSyncRepository = Depends(get_filelib_sync_repository),
) -> FilelibSyncService:
    knowledge_space_service = KnowledgeSpaceService(
        request=request,
        login_user=principal.user,
    )
    return FilelibSyncService(
        login_user=principal.user,
        token_id=principal.token_id,
        file_sync_rule=DeveloperTokenFileSyncRule.model_validate(principal.raw_file_sync_rule),
        repository=repository,
        knowledge_space_service=knowledge_space_service,
    )
