import os
import uuid
from loguru import logger
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from bisheng_langchain.vectorstores.milvus import Milvus
from langchain_core.documents import Document
from langchain_core.pydantic_v1 import Field
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from langchain.callbacks.manager import CallbackManagerForRetrieverRun
from langchain.text_splitter import TextSplitter


class KeywordRetriever(BaseRetriever):
    keyword_store: VectorStore
    text_splitter: TextSplitter
    search_type: str = 'similarity'
    search_kwargs: dict = Field(default_factory=dict)

    def add_documents(
        self,
        documents: List[Document],
        collection_name: str,
        drop_old: bool = False,
        **kwargs,
    ) -> None:
        split_docs = self.text_splitter.split_documents(documents)
        logger.info(f"KeywordRetriever: split document into {len(split_docs)} chunks")
        for chunk_index, split_doc in enumerate(split_docs):
            if 'chunk_bboxes' in split_doc.metadata:
                split_doc.metadata.pop('chunk_bboxes')
            split_doc.metadata['chunk_index'] = chunk_index
            if kwargs.get('add_aux_info', False):
                split_doc.page_content = split_doc.metadata["source"] + '\n' + split_doc.metadata["title"] + '\n' + split_doc.page_content

        elasticsearch_url = self.keyword_store.elasticsearch_url
        ssl_verify = self.keyword_store.ssl_verify
        self.keyword_store.from_documents(
            split_docs,
            embedding='',
            index_name=collection_name,
            elasticsearch_url=elasticsearch_url,
            ssl_verify=ssl_verify,
            drop_old=drop_old,
        )

    def _get_relevant_documents(
        self,
        query: str,
        collection_name: Optional[str] = None,
    ) -> List[Document]:
        if collection_name:
            self.keyword_store = self.keyword_store.__class__(
                index_name=collection_name,
                elasticsearch_url=self.keyword_store.elasticsearch_url,
                ssl_verify=self.keyword_store.ssl_verify,
                llm_chain=self.keyword_store.llm_chain
            )
        if self.search_type == 'similarity':
            result = self.keyword_store.similarity_search(query, **self.search_kwargs)
        return result
