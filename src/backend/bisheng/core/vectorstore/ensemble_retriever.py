import asyncio
from typing import List, Dict, Any, Sequence, Coroutine, Optional

from pydantic import Field, BaseModel, PrivateAttr, ConfigDict
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore
from langchain_core.documents import Document
from langchain_core.callbacks import (
    CallbackManagerForRetrieverRun,
    AsyncCallbackManagerForRetrieverRun
)
from langchain_core.runnables import RunnableConfig

from bisheng.core.ai.rerank.rrf_rerank import RRFRerank


# Input Retriever Parameter Model
class VectorRetrieverParams(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    vector_store: VectorStore = Field(..., description="Vector Library Instance")
    search_kwargs: Dict = Field(default_factory=dict, description="Retrieve Parameters")
    weight: float = Field(default=1.0, description="Retriever Weight")


class RRFMultiVectorRetriever(BaseRetriever):
    """
    predicated upon RRF (Reciprocal Rank Fusion) Multiple vector retriever.
    Sync enabled/Asynchronous calls that support character-length-based context truncation.
    """

    vector_store_params: List[VectorRetrieverParams] = Field(
        ..., description="Multiple vector libraries and their retrieval parameters and weights"
    )
    top_k: int = Field(default=5, description="The final number of documents returned. Note: Recommended settings >0 Value of")
    rrf_c: int = Field(default=60, description="RRF constant c, smooth ranking weights")
    remove_zero_score: bool = Field(default=True, description="Remove or not RRF Score is 0 Documents")
    max_context_length: int = Field(default=0, description="Returns the maximum total character length of a document,0Indicates unlimited")

    _rrf_rerank: RRFRerank = PrivateAttr()
    _retrievers: List[BaseRetriever] = PrivateAttr(default_factory=list)

    def __init__(self, **data: Any):
        super().__init__(**data)

        weights = []
        self._retrievers = []

        for param in self.vector_store_params:
            weights.append(param.weight)
            # Convert To retriever
            self._retrievers.append(
                param.vector_store.as_retriever(search_kwargs=param.search_kwargs)
            )

        # Inisialisasi RRF Reorder
        self._rrf_rerank = RRFRerank(
            retrievers=self._retrievers,
            weights=weights,
            c=self.rrf_c,
            remove_zero_score=self.remove_zero_score
        )

    def _get_relevant_documents(
            self, query: str, *, run_manager: CallbackManagerForRetrieverRun, **kwargs
    ) -> Sequence[Document]:
        docs_lists = []
        # Pass-through callback configuration
        run_config: RunnableConfig = {"callbacks": run_manager.get_child()}

        for retriever in self._retrievers:
            try:
                tmp_docs = retriever.invoke(query, config=run_config, **kwargs)
                docs_lists.append(tmp_docs)
            except Exception as e:
                # Log exceptions but continue to execute other retrievers
                run_manager.on_text(f"Retriever {retriever} failed with error: {e}", end="\n")
                docs_lists.append([])

        # Recall RRF Reorder
        reranked_docs = self._rrf_rerank.compress_documents(query=query, documents=docs_lists)

        return self._post_process_documents(reranked_docs)

    async def _aget_relevant_documents(
            self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun, **kwargs
    ) -> Sequence[Document]:
        tasks: List[Coroutine] = []
        run_config: RunnableConfig = {"callbacks": run_manager.get_child()}

        for retriever in self._retrievers:
            tasks.append(
                retriever.ainvoke(query, config=run_config, **kwargs)
            )

        # Concurrent execution
        results = await asyncio.gather(*tasks, return_exceptions=True)


        docs_lists = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                # Log exceptions but continue to execute other retrievers
                await run_manager.on_text(f"Retriever {self._retrievers[idx]} failed with error: {result}", end="\n")
                docs_lists.append([])
            else:
                docs_lists.append(result)

        # RRF Rearrangements
        reranked_docs = self._rrf_rerank.compress_documents(query=query, documents=docs_lists)

        return self._post_process_documents(reranked_docs)

    def _post_process_documents(self, documents: Sequence[Document]) -> List[Document]:
        """cut off TopK And Length filtering"""
        # Top K cut off
        if self.top_k > 0:
            documents = documents[:self.top_k]

        # Length filtering
        return self._filter_by_context_length(list(documents))

    def _filter_by_context_length(self, documents: List[Document]) -> List[Document]:
        """according max_context_length Filter Documents List"""
        if self.max_context_length <= 0:
            return documents

        curr_size = 0
        filtered_docs = []
        for doc in documents:
            doc_size = len(doc.page_content)
            # Determine if the limit has been exceeded after joining the document
            if curr_size + doc_size <= self.max_context_length:
                filtered_docs.append(doc)
                curr_size += doc_size
            else:
                break
        return filtered_docs
