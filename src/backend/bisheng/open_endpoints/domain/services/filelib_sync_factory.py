from __future__ import annotations

from fastapi import Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    KnowledgeDocumentDistributionService,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.domain.repositories.implementations.filelib_sync_repository_impl import (
    FilelibSyncRepositoryImpl,
)
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService


def attach_document_distribution_service(
    knowledge_space_service: KnowledgeSpaceService,
    session: AsyncSession,
) -> KnowledgeSpaceService:
    """Wire the same distribution lifecycle used by portal knowledge APIs.

    File overwrite / version replace calls ``_mark_document_content_changed``,
    which raises if ``document_distribution_service`` is unset.
    """
    file_repository = KnowledgeFileRepositoryImpl(session)
    knowledge_space_service.knowledge_file_repo = file_repository
    knowledge_space_service.doc_repo = KnowledgeDocumentRepositoryImpl(session)
    knowledge_space_service.version_repo = KnowledgeDocumentVersionRepositoryImpl(session)
    knowledge_space_service.document_distribution_service = KnowledgeDocumentDistributionService(
        session=session,
        document_repository=knowledge_space_service.doc_repo,
        version_repository=knowledge_space_service.version_repo,
        file_repository=file_repository,
        permission_activation_service=KnowledgeDocumentPermissionActivationService(
            file_repository=file_repository,
        ),
    )
    return knowledge_space_service


def build_knowledge_space_service_for_filelib_sync(
    *,
    session: AsyncSession,
    login_user: UserPayload,
    request: Request | None = None,
) -> KnowledgeSpaceService:
    knowledge_space_service = KnowledgeSpaceService(request=request, login_user=login_user)
    return attach_document_distribution_service(knowledge_space_service, session)


def build_filelib_sync_service_for_scheduled_sync(
    *,
    session: AsyncSession,
    token: DeveloperToken,
    file_sync_rule: DeveloperTokenFileSyncRule,
    login_user: UserPayload,
) -> FilelibSyncService:
    return FilelibSyncService(
        request=None,
        login_user=login_user,
        token_id=int(token.id),
        token_name=str(token.name or ""),
        file_sync_rule=file_sync_rule,
        repository=FilelibSyncRepositoryImpl(session),
        knowledge_space_service=build_knowledge_space_service_for_filelib_sync(
            session=session,
            login_user=login_user,
            request=None,
        ),
    )
