"""Local DI for the answer endpoint; no cross-module API imports."""

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.services.knowledge_space_answer_service import KnowledgeSpaceAnswerService
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async


async def get_knowledge_answer_service(request: Request, session: AsyncSession = Depends(get_db_session)):
    user = await get_open_api_operator_async()
    retrieval = KnowledgeSpaceChatService(request=request, login_user=user)
    retrieval.version_repo = KnowledgeDocumentVersionRepositoryImpl(session)
    return KnowledgeSpaceAnswerService(
        login_user=user,
        knowledge_repository=KnowledgeRepositoryImpl(session),
        retrieval_service=retrieval,
    )
