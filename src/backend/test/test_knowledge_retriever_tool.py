import pytest
from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool


class LoopBoundVectorRetriever(BaseRetriever):
    docs: list[Document] = Field(default_factory=list)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        return self.docs

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        raise RuntimeError("got Future <Future pending> attached to a different loop")


@pytest.mark.asyncio
async def test_async_vector_retrieval_uses_sync_retriever_to_avoid_loop_bound_milvus_channel():
    expected_docs = [
        Document(
            page_content="first chunk", metadata={"document_id": 1580, "document_name": "doc.pdf", "chunk_index": 2}
        ),
        Document(
            page_content="second chunk", metadata={"document_id": 1580, "document_name": "doc.pdf", "chunk_index": 1}
        ),
    ]
    tool = KnowledgeRetrieverTool(
        vector_retriever=LoopBoundVectorRetriever(docs=expected_docs),
        sort_by_source_and_index=True,
    )

    docs = await tool.ainvoke("what is this document about?")

    assert [doc.page_content for doc in docs] == ["second chunk", "first chunk"]
