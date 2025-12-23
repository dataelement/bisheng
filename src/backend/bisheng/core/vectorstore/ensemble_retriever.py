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


# 输入检索器参数模型
class VectorRetrieverParams(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    vector_store: VectorStore = Field(..., description="向量库实例")
    search_kwargs: Dict = Field(default_factory=dict, description="检索参数")
    weight: float = Field(default=1.0, description="检索器权重")


class RRFMultiVectorRetriever(BaseRetriever):
    """
    基于 RRF (Reciprocal Rank Fusion) 的多路向量检索器。
    支持同步/异步调用，支持基于字符长度的上下文截断。
    """

    vector_store_params: List[VectorRetrieverParams] = Field(
        ..., description="多个向量库及其检索参数和权重"
    )
    top_k: int = Field(default=5, description="最终返回的文档数量。注意：建议设置 >0 的值")
    rrf_c: int = Field(default=60, description="RRF 常数 c，平滑排名权重")
    remove_zero_score: bool = Field(default=True, description="是否移除 RRF 分数为 0 的文档")
    max_context_length: int = Field(default=0, description="返回文档的最大字符总长度，0表示不限制")

    _rrf_rerank: RRFRerank = PrivateAttr()
    _retrievers: List[BaseRetriever] = PrivateAttr(default_factory=list)

    def __init__(self, **data: Any):
        super().__init__(**data)

        weights = []
        self._retrievers = []

        for param in self.vector_store_params:
            weights.append(param.weight)
            # 转换为 retriever
            self._retrievers.append(
                param.vector_store.as_retriever(search_kwargs=param.search_kwargs)
            )

        # 初始化 RRF 重排序器
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
        # 传递回调配置
        run_config: RunnableConfig = {"callbacks": run_manager.get_child()}

        for retriever in self._retrievers:
            try:
                tmp_docs = retriever.invoke(query, config=run_config, **kwargs)
                docs_lists.append(tmp_docs)
            except Exception as e:
                # 记录异常但继续执行其他检索器
                run_manager.on_text(f"Retriever {retriever} failed with error: {e}", end="\n")
                docs_lists.append([])

        # 调用 RRF 进行重排序
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

        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)


        docs_lists = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                # 记录异常但继续执行其他检索器
                await run_manager.on_text(f"Retriever {self._retrievers[idx]} failed with error: {result}", end="\n")
                docs_lists.append([])
            else:
                docs_lists.append(result)

        # RRF 重排
        reranked_docs = self._rrf_rerank.compress_documents(query=query, documents=docs_lists)

        return self._post_process_documents(reranked_docs)

    def _post_process_documents(self, documents: Sequence[Document]) -> List[Document]:
        """截断 TopK 和 长度过滤"""
        # Top K 截断
        if self.top_k > 0:
            documents = documents[:self.top_k]

        # 长度过滤
        return self._filter_by_context_length(list(documents))

    def _filter_by_context_length(self, documents: List[Document]) -> List[Document]:
        """根据 max_context_length 过滤文档列表"""
        if self.max_context_length <= 0:
            return documents

        curr_size = 0
        filtered_docs = []
        for doc in documents:
            doc_size = len(doc.page_content)
            # 判断加入该文档后是否超出限制
            if curr_size + doc_size <= self.max_context_length:
                filtered_docs.append(doc)
                curr_size += doc_size
            else:
                break
        return filtered_docs
