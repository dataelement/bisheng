from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Collection, Dict, List
from venv import logger

import requests
from langchain.schema.document import Document
from langchain.vectorstores.base import VectorStore, VectorStoreRetriever
from langchain_core.pydantic_v1 import Field, root_validator

if TYPE_CHECKING:
    from langchain.callbacks.manager import (
        AsyncCallbackManagerForRetrieverRun,
        CallbackManagerForRetrieverRun,
    )


class VectorStoreFilterRetriever(VectorStoreRetriever):
    vectorstore: VectorStore
    search_type: str = 'similarity'
    search_kwargs: dict = Field(default_factory=dict)
    allowed_search_types: ClassVar[Collection[str]] = (
        'similarity',
        'similarity_score_threshold',
        'mmr',
    )
    access_url: str = None

    class Config:
        """Configuration for this pydantic object."""

        arbitrary_types_allowed = True

    @root_validator()
    def validate_search_type(cls, values: Dict) -> Dict:
        """Validate search type."""
        search_type = values['search_type']
        if search_type not in cls.allowed_search_types:
            raise ValueError(f'search_type of {search_type} not allowed. Valid values are: '
                             f'{cls.allowed_search_types}')
        if search_type == 'similarity_score_threshold':
            score_threshold = values['search_kwargs'].get('score_threshold')
            if (score_threshold is None) or (not isinstance(score_threshold, float)):
                raise ValueError('`score_threshold` is not specified with a float value(0~1) '
                                 'in `search_kwargs`.')
        return values

    def _get_relevant_documents(self, query: str, *,
                                run_manager: CallbackManagerForRetrieverRun) -> List[Document]:
        if self.search_type == 'similarity':
            docs = self.vectorstore.similarity_search(query, **self.search_kwargs)
        elif self.search_type == 'similarity_score_threshold':
            docs_and_similarities = (self.vectorstore.similarity_search_with_relevance_scores(
                query, **self.search_kwargs))
            docs = [doc for doc, _ in docs_and_similarities]
        elif self.search_type == 'mmr':
            docs = self.vectorstore.max_marginal_relevance_search(query, **self.search_kwargs)
        else:
            raise ValueError(f'search_type of {self.search_type} not allowed.')

        return self.get_file_access(docs)

    async def _aget_relevant_documents(
            self, query: str, *,
            run_manager: AsyncCallbackManagerForRetrieverRun) -> List[Document]:
        if self.search_type == 'similarity':
            docs = await self.vectorstore.asimilarity_search(query, **self.search_kwargs)
        elif self.search_type == 'similarity_score_threshold':
            docs_and_similarities = (await
                                     self.vectorstore.asimilarity_search_with_relevance_scores(
                                         query, **self.search_kwargs))
            docs = [doc for doc, _ in docs_and_similarities]
        elif self.search_type == 'mmr':
            docs = await self.vectorstore.amax_marginal_relevance_search(
                query, **self.search_kwargs)
        else:
            raise ValueError(f'search_type of {self.search_type} not allowed.')
        return self.get_file_access(docs)

    def get_file_access(self, docs: List[Document]):
        file_ids = [doc.metadata.get('file_id') for doc in docs if 'file_id' in doc.metadata]
        if file_ids:
            res = requests.get(self.access_url, json=file_ids)
            if res.status_code == 200:
                doc_res = res.json().get('data') or []
                doc_right = {doc.get('docid') for doc in doc_res if doc.get('result') == 1}
                for doc in docs:
                    if doc.metadata.get('file_id') and doc.metadata.get(
                            'file_id') not in doc_right:
                        doc.page_content = ''
                        doc.metadata['right'] = False
                return docs
            else:
                logger.error(f'query_file_access_fail url={self.access_url} res={res.text}')
                return [Document(page_content='', metadata={})]
        else:
            return docs
