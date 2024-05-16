import uuid
from typing import List, Optional

from bisheng_langchain.vectorstores.milvus import Milvus
from langchain_core.documents import Document
from langchain_core.pydantic_v1 import Field
from langchain_core.retrievers import BaseRetriever

from langchain.text_splitter import TextSplitter


class SmallerChunksVectorRetriever(BaseRetriever):
    vector_store: Milvus
    child_search_kwargs: dict = Field(default_factory=dict)
    """Keyword arguments to pass to the search function."""
    child_splitter: TextSplitter
    parent_splitter: Optional[TextSplitter] = None
    """The text splitter to use to create parent documents.
    If none, then the parent documents will be the raw documents passed in."""
    id_key = 'doc_id'

    def add_documents(
        self,
        documents: List[Document],
        collection_name: str,
        drop_old: bool = False,
        **kwargs,
    ) -> None:
        if self.parent_splitter is not None:
            documents = self.parent_splitter.split_documents(documents)
        for chunk_index, split_doc in enumerate(documents):
            if 'chunk_bboxes' in split_doc.metadata:
                split_doc.metadata.pop('chunk_bboxes')
            split_doc.metadata['chunk_index'] = chunk_index
            if kwargs.get('add_aux_info', False):
                split_doc.page_content = split_doc.metadata["source"] + '\n' + split_doc.metadata["title"] + '\n' + split_doc.page_content
        doc_ids = [str(uuid.uuid4()) for _ in documents]

        par_docs = []
        child_docs = []
        for i, par_doc in enumerate(documents):
            _id = doc_ids[i]
            par_doc.metadata[self.id_key] = _id
            sub_docs = self.child_splitter.split_documents([par_doc])
            for _doc in sub_docs:
                _doc.metadata[self.id_key] = _id
                if kwargs.get('add_aux_info', False):
                    _doc.page_content = _doc.metadata["source"] + '\n' + _doc.metadata["title"] + '\n' + _doc.page_content
            par_docs.append(par_doc)
            child_docs.extend(sub_docs)
        
        self.vector_store.from_documents(
            par_docs,
            embedding=self.vector_store.embedding_func,
            collection_name=collection_name + 'parent',
            connection_args=self.vector_store.connection_args,
            drop_old=drop_old,
            no_embedding=True,
        )
        self.vector_store.from_documents(
            child_docs,
            embedding=self.vector_store.embedding_func,
            collection_name=collection_name + 'child',
            connection_args=self.vector_store.connection_args,
            drop_old=drop_old,
        )

    def _get_relevant_documents(
        self,
        query: str,
        collection_name: Optional[str] = None,
    ) -> List[Document]:
        if collection_name:
            child_vectorstore = self.vector_store.__class__(
                collection_name=collection_name + 'child',
                embedding_function=self.vector_store.embedding_func,
                connection_args=self.vector_store.connection_args,
            )
            parent_vectorstore = self.vector_store.__class__(
                collection_name=collection_name + 'parent',
                embedding_function=self.vector_store.embedding_func,
                connection_args=self.vector_store.connection_args,
            )
        sub_docs = child_vectorstore.similarity_search(query, **self.child_search_kwargs)
        doc_ids, ret = [], []
        for doc in sub_docs:
            doc_id = doc.metadata[self.id_key]
            if doc_id not in doc_ids:
                doc_ids.append(doc_id)
                par_doc = parent_vectorstore.query(expr=f'{self.id_key} == "{doc_id}"')
                ret.extend(par_doc)
        return ret
