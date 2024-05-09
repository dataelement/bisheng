from typing import Any, Dict, Iterable, List, Optional

from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from bisheng_langchain.vectorstores.milvus import Milvus
from langchain_core.documents import Document
from langchain_core.pydantic_v1 import Field
from langchain_core.retrievers import BaseRetriever

from langchain.schema import BaseRetriever, Document
from langchain.text_splitter import TextSplitter


class MixRetriever(BaseRetriever):
    vector_store: Milvus
    keyword_store: ElasticKeywordsSearch
    vector_text_splitter: TextSplitter
    keyword_text_splitter: TextSplitter
    # retrieval
    search_type: str = 'similarity'
    vector_search_kwargs: dict = Field(default_factory=dict)
    keyword_search_kwargs: dict = Field(default_factory=dict)
    combine_strategy: str = 'mix'  # "keyword_front, vector_front, mix"

    def add_documents(
        self,
        documents: List[Document],
        collection_name: str,
        drop_old: bool = False,
        **kwargs,
    ) -> None:
        vector_split_docs = self.vector_text_splitter.split_documents(documents)
        for chunk_index, split_doc in enumerate(vector_split_docs):
            if 'chunk_bboxes' in split_doc.metadata:
                split_doc.metadata.pop('chunk_bboxes')
            split_doc.metadata['chunk_index'] = chunk_index
            if kwargs.get('add_aux_info', False):
                split_doc.page_content = split_doc.metadata["source"] + '\n' + split_doc.metadata["title"] + '\n' + split_doc.page_content
        keyword_split_docs = self.keyword_text_splitter.split_documents(documents)
        for chunk_index, split_doc in enumerate(keyword_split_docs):
            if 'chunk_bboxes' in split_doc.metadata:
                split_doc.metadata.pop('chunk_bboxes')
            split_doc.metadata['chunk_index'] = chunk_index
            if kwargs.get('add_aux_info', False):
                split_doc.page_content = split_doc.metadata["source"] + '\n' + split_doc.metadata["title"] + '\n' + split_doc.page_content

        self.keyword_store.from_documents(
            keyword_split_docs,
            embedding='',
            index_name=collection_name,
            elasticsearch_url=self.keyword_store.elasticsearch_url,
            ssl_verify=self.keyword_store.ssl_verify,
            drop_old=drop_old,
        )

        self.vector_store.from_documents(
            vector_split_docs,
            embedding=self.vector_store.embedding_func,
            collection_name=collection_name,
            connection_args=self.vector_store.connection_args,
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
            self.vector_store = self.vector_store.__class__(
                collection_name=collection_name,
                embedding_function=self.vector_store.embedding_func,
                connection_args=self.vector_store.connection_args,
            )
        if self.search_type == 'similarity':
            keyword_docs = self.keyword_store.similarity_search(query, **self.keyword_search_kwargs)
            vector_docs = self.vector_store.similarity_search(query, **self.vector_search_kwargs)
            if self.combine_strategy == 'keyword_front':
                return keyword_docs + vector_docs
            elif self.combine_strategy == 'vector_front':
                return vector_docs + keyword_docs
            elif self.combine_strategy == 'mix':
                combine_docs = []
                min_len = min(len(keyword_docs), len(vector_docs))
                for i in range(min_len):
                    combine_docs.append(keyword_docs[i])
                    combine_docs.append(vector_docs[i])
                combine_docs.extend(keyword_docs[min_len:])
                combine_docs.extend(vector_docs[min_len:])
                return combine_docs
            else:
                raise ValueError(
                    f'Expected combine_strategy to be one of '
                    f'(keyword_front, vector_front, mix),'
                    f'instead found {self.combine_strategy}'
                )
        else:
            raise ValueError(f'Expected search_type to be one of (similarity), instead found {self.search_type}')
