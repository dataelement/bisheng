import asyncio
from typing import List, Dict

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore


class MultiRetriever(BaseRetriever):
    """ A retriever that combines multiple retrievers. """
    vectors: List[VectorStore]
    search_kwargs: List[Dict]
    finally_k: int = 0

    def _get_relevant_documents(
            self, query: str, *, run_manager: CallbackManagerForRetrieverRun, **kwargs
    ) -> list[Document]:
        docs: List[tuple[Document, float]] = []
        for index, vector in enumerate(self.vectors):
            kwargs_ = self.search_kwargs[index] | kwargs
            tmp_docs = vector.similarity_search_with_score(query, **kwargs_)
            docs.extend(tmp_docs)
        return self.parse_doc_with_score(docs)

    async def _aget_relevant_documents(
            self, query: str, *, run_manager: CallbackManagerForRetrieverRun, **kwargs
    ) -> list[Document]:
        tasks = []
        for index, vector in enumerate(self.vectors):
            kwargs_ = self.search_kwargs[index] | kwargs
            tasks.append(vector.asimilarity_search_with_score(query, **kwargs_))

        results = await asyncio.gather(*tasks)

        docs: List[tuple[Document, float]] = []
        for tmp_docs in results:
            docs.extend(tmp_docs)

        return self.parse_doc_with_score(docs)

    def parse_doc_with_score(self, docs_with_score: List[tuple[Document, float]]) -> List[Document]:
        """ parse documents with score to documents only """
        docs_with_score.sort(key=lambda x: x[1])
        if self.finally_k > 0:
            docs_with_score = docs_with_score[:self.finally_k]
        return [doc for doc, _ in docs_with_score]
