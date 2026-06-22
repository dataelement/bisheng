import asyncio
import logging
import warnings
from typing import Any, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_elasticsearch import ElasticsearchStore, AsyncElasticsearchStore
from langchain_elasticsearch.vectorstores import BM25Strategy, AsyncBM25Strategy
from langchain_milvus import Milvus as LangchainMilvus

logger = logging.getLogger(__name__)


def _ensure_current_thread_event_loop() -> None:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
        return

    if loop.is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())


class Milvus(LangchainMilvus):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ensure_current_thread_event_loop()
        super().__init__(*args, **kwargs)

    async def asimilarity_search_with_score_by_vector(
            self,
            embedding: Any,
            k: int = 4,
            param: Optional[dict] = None,
            expr: Optional[str] = None,
            timeout: Optional[float] = None,
            **kwargs: Any,
    ) -> List[Tuple[Document, float]]:
        return await asyncio.to_thread(
            self.similarity_search_with_score_by_vector,
            embedding=embedding,
            k=k,
            param=param,
            expr=expr,
            timeout=timeout,
            **kwargs,
        )

    async def asimilarity_search_with_relevance_scores_by_vector(
            self,
            embedding: Any,
            k: int = 4,
            **kwargs: Any,
    ) -> List[Tuple[Document, float]]:
        score_threshold = kwargs.pop("score_threshold", None)
        relevance_score_fn = self._select_relevance_score_fn()
        docs_and_scores = await self.asimilarity_search_with_score_by_vector(
            embedding,
            k=k,
            **kwargs,
        )
        docs_and_similarities = [(doc, relevance_score_fn(score)) for doc, score in docs_and_scores]
        if any(similarity < 0.0 or similarity > 1.0 for _, similarity in docs_and_similarities):
            warnings.warn(
                f"Relevance scores must be between 0 and 1, got {docs_and_similarities}",
                stacklevel=2,
            )

        if score_threshold is not None:
            docs_and_similarities = [
                (doc, similarity)
                for doc, similarity in docs_and_similarities
                if similarity >= score_threshold
            ]
            if not docs_and_similarities:
                logger.warning(
                    "No relevant docs were retrieved using the relevance score threshold %s",
                    score_threshold,
                )
        return docs_and_similarities

__all__ = [
    'Milvus',
    'ElasticsearchStore',
    'AsyncElasticsearchStore',
    'BM25Strategy',
    'AsyncBM25Strategy'
]
