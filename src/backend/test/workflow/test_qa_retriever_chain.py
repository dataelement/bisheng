from __future__ import annotations

import pytest
from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from bisheng_langchain.chains.retrieval.retrieval_chain import RetrievalChain


class RunnableOnlyRetriever(BaseRetriever):
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        return [Document(page_content=f"sync:{query}")]

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        return [Document(page_content=f"async:{query}")]


def test_retrieval_chain_uses_runnable_invoke_for_langchain_core_retrievers():
    retriever = RunnableOnlyRetriever()
    assert not hasattr(retriever, "get_relevant_documents")

    result = RetrievalChain(retriever=retriever).invoke({"query": "weather"})

    assert result["result"] == [Document(page_content="sync:weather")]


@pytest.mark.asyncio
async def test_retrieval_chain_uses_runnable_ainvoke_for_langchain_core_retrievers():
    retriever = RunnableOnlyRetriever()
    assert not hasattr(retriever, "aget_relevant_documents")

    result = await RetrievalChain(retriever=retriever).ainvoke({"query": "weather"})

    assert result["result"] == [Document(page_content="async:weather")]
