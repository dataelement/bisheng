import os
import uuid
from typing import Any, Dict, Iterable, List, Optional
from loguru import logger

import httpx
from langchain_core.documents import Document
from langchain_core.pydantic_v1 import Field
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from langchain.callbacks.manager import CallbackManagerForRetrieverRun
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter, TextSplitter
from langchain.vectorstores.milvus import Milvus
from bisheng_langchain.vectorstores.milvus import Milvus

openai_proxy = os.environ.get('OPENAI_PROXY')
httpx_client = httpx.Client(proxies=openai_proxy)

EMBEDDING = OpenAIEmbeddings(model='text-embedding-ada-002', http_client=httpx_client)


class SmallerChunkRetriever(BaseRetriever):
    """Retrieve from a set of multiple embeddings for the same document."""

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

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> List[Document]:
        sub_docs = self.child_vectorstore.similarity_search(query, **self.search_kwargs)

        doc_ids, ret = [], []
        for doc in sub_docs:
            doc_id = doc.metadata[self.id_key]
            if doc_id not in doc_ids:
                doc_ids.append(doc_id)
                par_doc = self.par_vectorstore.query(expr=f'{self.id_key} == "{doc_id}"')
                # logger.info(f'child doc : {doc.page_content} ---> parent doc : {par_doc[0].page_content}')
                ret.extend(par_doc)
        return ret
            

# 排序
# 1. 原文档顺序
# 2. mmr
# 3. 语义相似度


if __name__ == '__main__':
    milvus_connection_args = {'host': '192.168.106.116', 'port': '19530'}

    elasticsearch_url = "http://192.168.106.116:9200"
    ssl_verify = {'basic_auth': ("elastic", "oSGL-zVvZ5P3Tm7qkDLC")}

    ori_text = Document(
        page_content="""马里兰法律评论
2017
研讨会论文集：网络法律现状：数字时代的安全与隐私
由马里兰法律评论在马里兰大学弗朗西斯·金·凯里法学院主办
2017年2月10日 伍德罗·哈茨格1
版权所有 © 2017 伍德罗·哈茨格
信息公平实践的不足与不可或缺
目录 引言 952
I. 信息公平实践的不可或缺性 956
   A. 隐私的共同语言 958
   B. 可塑性与可分割性 961
   C. 负责任的数据处理者的更好试金石 962
II. 信息公平实践的不足 964
   A. 信息公平实践的盲点 966
      1. 我们对彼此的脆弱性 966
      2. 我们易受操纵的性质 968
      3. 我们对自动化决策的无助 970
   B. 信息公平实践的带宽问题 972
III. 转向设计：信息公平实践作为一个良好的开端 977
   A. 隐私的未来在市场、心智和机器中 977
   B. 隐私法应关注设计 979
IV. 结论
982"""
    )

    par_spliter = RecursiveCharacterTextSplitter(chunk_size=20, chunk_overlap=0)
    child_spliter = RecursiveCharacterTextSplitter(chunk_size=5, chunk_overlap=0)

    par_collection_name = 'par_chunk'
    child_collection_name = 'child_chunk'

    par_vectorstore = Milvus(
        embedding_function=EMBEDDING,
        collection_name=par_collection_name,
        connection_args=milvus_connection_args,
        drop_old=True,
    )

    child_vectorstore = Milvus(
        embedding_function=EMBEDDING,
        collection_name=child_collection_name,
        connection_args=milvus_connection_args,
        drop_old=True,
    )

    smaller_chunk_retriever = SmallerChunkRetriever(
        par_vectorstore=par_vectorstore,
        child_vectorstore=child_vectorstore,
        parent_splitter=par_spliter,
        child_splitter=child_spliter,
    )
    
    smaller_chunk_retriever.add_documents([ori_text])
    res = smaller_chunk_retriever.get_relevant_documents('隐私')
    logger.info(res)
