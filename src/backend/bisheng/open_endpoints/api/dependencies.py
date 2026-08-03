import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Query, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.developer_token import DeveloperTokenInvalidFileSyncRuleError
from bisheng.common.errcode.filelib_sync import FilelibSyncRuleNotConfiguredError
from bisheng.developer_token.api.dependencies import (
    get_developer_token_principal,
)
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenFileSyncRule,
    DeveloperTokenPrincipal,
)
from bisheng.developer_token.domain.services import DeveloperTokenService
from bisheng.knowledge.api.dependencies import (
    get_knowledge_document_repository,
    get_knowledge_document_version_repository,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
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
from bisheng.open_endpoints.domain.services.filelib_user_context_service import (
    EXTERNAL_USER_ID_MAX_LENGTH,
    FilelibUserContextService,
)
from bisheng.user.domain.repositories.implementations.user_repository_impl import UserRepositoryImpl
from bisheng.user.domain.repositories.interfaces.user_repository import UserRepository

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


async def get_filelib_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    return UserRepositoryImpl(session)


async def get_filelib_user_context_service(
    user_repository: UserRepository = Depends(get_filelib_user_repository),
) -> FilelibUserContextService:
    return FilelibUserContextService(user_repository)


async def get_filelib_developer_token_principal(
    principal: DeveloperTokenPrincipal = Depends(get_developer_token_principal),
) -> DeveloperTokenPrincipal:
    return principal


async def get_filelib_knowledge_document_version_repository(
    repository: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
) -> KnowledgeDocumentVersionRepository:
    return repository


async def get_filelib_knowledge_document_repository(
    repository: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
) -> KnowledgeDocumentRepository:
    return repository


async def get_filelib_request_user(
    principal: DeveloperTokenPrincipal = Depends(get_developer_token_principal),
    service: FilelibUserContextService = Depends(get_filelib_user_context_service),
    external_id: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=EXTERNAL_USER_ID_MAX_LENGTH,
            pattern=r".*\S.*",
        ),
    ] = None,
) -> AsyncGenerator[UserPayload, None]:
    async with service.use_user(principal, external_id) as login_user:
        yield login_user


def build_knowledge_space_chat_service_for_openapi(
    request: Request,
    request_user: UserPayload,
    version_repo: KnowledgeDocumentVersionRepository,
    doc_repo: KnowledgeDocumentRepository,
) -> "KnowledgeSpaceChatService":
    """Build the retrieval service inside the resolved Filelib user context."""
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService

    service = KnowledgeSpaceChatService(request=request, login_user=request_user)
    service.version_repo = version_repo
    service.doc_repo = doc_repo
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
