from typing import List, Dict, Any, Sequence, Coroutine

from pydantic import Field
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore
from langchain_core.documents import Document
from langchain_core.callbacks import (
    CallbackManagerForRetrieverRun,
    AsyncCallbackManagerForRetrieverRun
)

from bisheng.core.ai.rerank.rrf_rerank import RRFRerank
from bisheng.core.vectorstore.multi_retriever import MultiRetriever


class RRFMultiVectorRetriever(BaseRetriever):
    """
    A retriever that uses Reciprocal Rank Fusion (RRF) to combine results from multiple vector stores.
    It supports both synchronous and asynchronous retrieval.
    """

    vector_stores: List[VectorStore] = Field(..., description="向量库列表")
    search_kwargs_list: List[Dict] = Field(default_factory=list, description="每个retriever的搜索参数列表")
    top_k: int = Field(default=5, description="最终返回文档数")
    c_constant: int = Field(default=60, description="RRF 算法中的常数 k (通常为 60)")
    remove_zero_score: bool = Field(default=True, description="是否移除得分为 0 的文档")
    multiple_retrievers: MultiRetriever = Field(default=None, description="多路检索器实例")
    rrf_rerank: RRFRerank = Field(default=None, description="RRF 重排序器实例")

    def __init__(self, **data: Any):
        super().__init__(**data)

        # 补全参数
        if len(self.search_kwargs_list) < len(self.vector_stores):
            self.search_kwargs_list.extend([{}] * (len(self.vector_stores) - len(self.search_kwargs_list)))
        if not self.multiple_retrievers:
            self.multiple_retrievers = MultiRetriever(
                vectors=self.vector_stores,
                search_kwargs=self.search_kwargs_list,
                finally_k=self.top_k * 3 if self.top_k > 0 else 0
            )
        if not self.rrf_rerank:
            self.rrf_rerank = RRFRerank(
                retrievers=[self.multiple_retrievers],
                c=self.c_constant,
                remove_zero_score=self.remove_zero_score
            )

    def _get_relevant_documents(
            self,
            query: str,
            *,
            run_manager: CallbackManagerForRetrieverRun
    ) -> Sequence[Document]:

        # 多路串行召回 (同步模式下通常只能串行，除非用 ThreadPool)
        results = self.multiple_retrievers.invoke(query)

        # RRF 融合
        fused_docs = self.rrf_rerank.compress_documents([results], query=query)

        if self.top_k > 0:
            return fused_docs[:self.top_k]

        return fused_docs

    async def _aget_relevant_documents(
            self,
            query: str,
            *,
            run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> Sequence[Document]:

        # 多路并行召回
        results = await self.multiple_retrievers.ainvoke(query)

        # RRF 融合
        fused_docs = self.rrf_rerank.compress_documents([results], query=query)

        if self.top_k > 0:
            return fused_docs[:self.top_k]
        return fused_docs
