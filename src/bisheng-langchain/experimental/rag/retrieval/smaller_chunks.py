import os
import uuid
from typing import Any, Dict, Iterable, List, Optional

from bisheng_langchain.vectorstores.milvus import Milvus
from langchain_core.documents import Document
from langchain_core.pydantic_v1 import Field
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from langchain.callbacks.manager import CallbackManagerForRetrieverRun
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter, TextSplitter
from langchain.vectorstores.milvus import Milvus


class SmallerChunksRetriever(BaseRetriever):
    par_vectorstore: VectorStore
    """The underlying vectorstore to use to store small chunks
    and their embedding vectors"""
    child_vectorstore: VectorStore
    """The storage interface for the parent documents"""
    id_key: str = "doc_id"
    search_kwargs: dict = Field(default_factory=dict)
    """Keyword arguments to pass to the search function."""
    child_splitter: TextSplitter
    parent_splitter: Optional[TextSplitter] = None
    """The text splitter to use to create parent documents.
    If none, then the parent documents will be the raw documents passed in."""

    def add_documents(
        self,
        documents: List[Document],
        ids: Optional[List[str]] = None,
    ) -> None:
        if self.parent_splitter is not None:
            documents = self.parent_splitter.split_documents(documents)
        if ids is None:
            doc_ids = [str(uuid.uuid4()) for _ in documents]
        else:
            if len(documents) != len(ids):
                raise ValueError(
                    "Got uneven list of documents and ids. "
                    "If `ids` is provided, should be same length as `documents`."
                )
            doc_ids = ids

        par_docs = []
        child_docs = []
        for i, par_doc in enumerate(documents):
            _id = doc_ids[i]
            par_doc.metadata[self.id_key] = _id
            sub_docs = self.child_splitter.split_documents([par_doc])
            for _doc in sub_docs:
                _doc.metadata[self.id_key] = _id
            par_docs.append(par_doc)
            child_docs.extend(sub_docs)
        self.par_vectorstore.add_documents(par_docs, no_embedding=True)
        self.child_vectorstore.add_documents(child_docs)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        sub_docs = self.child_vectorstore.similarity_search(query, **self.search_kwargs)

        doc_ids, ret = [], []
        for doc in sub_docs:
            doc_id = doc.metadata[self.id_key]
            if doc_id not in doc_ids:
                doc_ids.append(doc_id)
                par_doc = self.par_vectorstore.query(expr=f'{self.id_key} == "{doc_id}"')
                ret.extend(par_doc)
        return ret
