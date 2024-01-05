# %load ./zgs_vector_store.py
import json
import math
import os
import sys
import time

import langchain
from bisheng_langchain.chains.router.multi_rule import MultiRuleChain
from bisheng_langchain.chains.router.rule_router import RuleBasedRouter
from langchain.chains import RetrievalQA

# from bisheng_langchain.vectorstores import Milvus
from langchain.chat_models import ChatOpenAI
from langchain.docstore.document import Document
from langchain.document_loaders import PyPDFLoader
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter


embeddings = OpenAIEmbeddings()


from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional, Tuple

from langchain.vectorstores import Milvus as MilvusOrigin


class Milvus(MilvusOrigin):
    @staticmethod
    def _relevance_score_fn(distance: float) -> float:
        """Normalize the distance to a score on a scale [0, 1]."""
        # Todo: normalize the es score on a scale [0, 1]
        return 1 - distance

    def _select_relevance_score_fn(self) -> Callable[[float], float]:
        return self._relevance_score_fn


def data_loader():
    start_time = time.time()
    file_path = "/home/youjiachen/bisheng/src/bisheng-langchain/tests/data/达梦数据库招股说明书.pdf"
    loader = PyPDFLoader(file_path)

    documents = loader.load()
    print('documents:', len(documents))
    print('load pdf time:', time.time() - start_time)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=0)
    split_docs = text_splitter.split_documents(documents)
    print('split_docs:', len(split_docs))

    start_time = time.time()
    MILVUS_HOST = '192.168.106.116'
    MILVUS_PORT = '19530'
    vector_store = Milvus.from_documents(
        split_docs,
        embedding=embeddings,
        collection_name="dameng_vector_chunk500",
        drop_old=True,
        connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT},
    )
    print('embedding and vector store time:', time.time() - start_time)

    return vector_store


def retrieval(query):
    MILVUS_HOST = '192.168.106.116'
    MILVUS_PORT = '19530'
    vector_store = Milvus(
        embedding_function=embeddings,
        collection_name="jiumuwang_vector_chunk500",
        connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT},
    )
    # vector_retriever = vector_store.as_retriever(search_type="similarity", search_kwargs={"k": 4})
    vector_retriever = vector_store.as_retriever(
        search_type="similarity_score_threshold", search_kwargs={"k": 4, "score_threshold": 1.0}
    )
    # breakpoint()
    return vector_retriever.get_relevant_documents(query)


def qa_loader():
    dm_qa_json = '/home/youjiachen/bisheng/src/bisheng-langchain/tests/data/dameng_qa.json'

    with open(dm_qa_json, 'r') as f:
        dm_qa = json.load(f)

    doc_list = []
    for i in dm_qa:
        doc_list.append(Document(page_content=i['question'], metadata={'answer': i['answer']}))

    MILVUS_HOST = '192.168.106.116'
    MILVUS_PORT = '19530'
    vector_store = Milvus.from_documents(
        doc_list,
        embedding=embeddings,
        collection_name="dm_qa",
        drop_old=True,
        connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT},
    )

    return vector_store


def retrieval_chain():
    from bisheng_langchain.chains.retrieval.retrieval_chain import RetrievalChain

    MILVUS_HOST = '192.168.106.116'
    MILVUS_PORT = '19530'
    vector_store = Milvus(
        embedding_function=embeddings,
        collection_name="dm_qa",
        connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT},
    )
    qa = RetrievalChain(
        # output_key='result',
        retriever=vector_store.as_retriever(
            # search_type="similarity",
            search_type="similarity_score_threshold",
            search_kwargs={"k": 1, "score_threshold": 0.9},
        ),
    )
    return qa


def retrieval_qa_chain():
    MILVUS_HOST = '192.168.106.116'
    MILVUS_PORT = '19530'
    vector_store = Milvus(
        embedding_function=embeddings,
        collection_name="dameng_vector_chunk500",
        connection_args={"host": MILVUS_HOST, "port": MILVUS_PORT},
    )
    # vector_retriever = vector_store.as_retriever(search_type="similarity", search_kwargs={"k": 4})
    vector_retriever = vector_store.as_retriever(
        search_type="similarity_score_threshold", search_kwargs={"k": 4, "score_threshold": 0.5}
    )
    llm = ChatOpenAI(
        model="gpt-3.5-turbo-16k-0613",
        temperature=0.0,
    )

    return RetrievalQA.from_chain_type(
        retriever=vector_retriever,
        chain_type="stuff",
        llm=llm,
        output_key='query_answer',
    )


if __name__ == '__main__':
    from langchain.chains import SequentialChain, TransformChain
    from langchain.chat_models import ChatOpenAI

    # data_loader()
    # qa_loader()
    _retrieval_chain = retrieval_chain()
    _retrieval_qa_chain = retrieval_qa_chain()

    # Transform
    def func(inputs: Dict) -> Dict:
        return {'query_answer': inputs['result']}

    tsfm = TransformChain(
        transform=func,
        input_variables=['result'],
        output_variables=['query_answer'],
    )

    # Rule
    def rule_fuc(inputs: Dict) -> Dict:
        if not len(inputs['result']):
            return {'destination': None, 'next_inputs': inputs}
        else:
            return {'destination': 'norm', 'next_inputs': inputs}

    rule_router = RuleBasedRouter(rule_function=rule_fuc, input_variables=['result'])
    rule_chain = MultiRuleChain(
        router_chain=rule_router,
        destination_chains={'norm': tsfm},
        default_chain=_retrieval_qa_chain,
        output_variables=['query_answer'],
    )

    seq_chain = SequentialChain(
        chains=[_retrieval_chain, rule_chain],
        input_variables=['query'],
        output_variables=['query_answer'],
        verbose=True,
    )
    res = seq_chain('达梦有dnwhndoin11？')
    print(res)