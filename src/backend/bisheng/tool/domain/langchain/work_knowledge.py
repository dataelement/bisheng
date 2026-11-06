"""Knowledge retrieval bound to the trusted tool execution identity."""

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.work_retrieval import WorkRetrievalRequest
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.domain.services.space_flow_retrieval import abuild_scoped_login_user
from bisheng.knowledge.domain.services.work_retrieval import retrieve_workspace_chunks
from bisheng.utils.async_utils import run_async_safe


class WorkKnowledgeSearch(BaseTool):
    name: str = "bisheng_knowledge_search"
    description: str = (
        "Search authorized document knowledge bases and knowledge spaces. "
        "Provide a query and the selected resource IDs as space_ids. "
        "Returns relevant passages and document sources for citations."
    )
    args_schema: type[BaseModel] = WorkRetrievalRequest
    user_id: int = Field(exclude=True, gt=0)
    tenant_id: int = Field(exclude=True, gt=0)

    async def _arun(self, query: str, space_ids: list[int]) -> dict:
        request = WorkRetrievalRequest(query=query, space_ids=space_ids)
        if get_current_tenant_id() != self.tenant_id:
            raise PermissionError("Knowledge retrieval tenant context changed.")
        login_user = await abuild_scoped_login_user(self.user_id, self.tenant_id)
        if login_user is None:
            raise PermissionError("Knowledge retrieval requires an active execution user.")
        async with get_async_db_session() as session:
            service = KnowledgeSpaceChatService(request=None, login_user=login_user)
            service.version_repo = KnowledgeDocumentVersionRepositoryImpl(session)
            return await retrieve_workspace_chunks(service, request)

    def _run(self, query: str, space_ids: list[int]) -> dict:
        return run_async_safe(self._arun(query, space_ids), timeout=120)
