from __future__ import annotations

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.domain.repositories.implementations.filelib_sync_repository_impl import (
    FilelibSyncRepositoryImpl,
)
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService
from sqlmodel.ext.asyncio.session import AsyncSession


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
        knowledge_space_service=KnowledgeSpaceService(request=None, login_user=login_user),
    )
