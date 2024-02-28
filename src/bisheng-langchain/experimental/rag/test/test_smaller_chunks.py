import os
import sys
import uuid
from typing import Any, Dict, Iterable, List, Optional

import httpx
from bisheng_langchain.vectorstores.milvus import Milvus
from langchain_core.documents import Document
from langchain_core.pydantic_v1 import Field
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore
from loguru import logger

from langchain.callbacks.manager import CallbackManagerForRetrieverRun
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter, TextSplitter
from langchain.vectorstores.milvus import Milvus

sys.path.append('../')

from retrieval.smaller_chunks import SmallerChunksRetriever

openai_proxy = os.environ.get('OPENAI_PROXY')
httpx_client = httpx.Client(proxies=openai_proxy)

EMBEDDING = OpenAIEmbeddings(model='text-embedding-ada-002', http_client=httpx_client)


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

    smaller_chunk_retriever = SmallerChunksRetriever(
        par_vectorstore=par_vectorstore,
        child_vectorstore=child_vectorstore,
        parent_splitter=par_spliter,
        child_splitter=child_spliter,
    )

    smaller_chunk_retriever.add_documents([ori_text])
    res = smaller_chunk_retriever.get_relevant_documents('隐私')
    logger.info(res)
