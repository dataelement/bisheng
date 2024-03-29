# %load ./zgs_vector_store.py
import os
import math
import time
import langchain
from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Milvus
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.docstore.document import Document
from langchain.chat_models import ChatOpenAI
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from bisheng_langchain.retrievers import MixEsVectorRetriever

embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
llm = ChatOpenAI(model="gpt-3.5-turbo-16k-0613", temperature=0.0)


def data_loader():
    start_time = time.time()
    file_path = "/home/public/招股书/达梦数据库招股说明书.pdf"
    loader = PyPDFLoader(file_path)

    documents = loader.load()
    print('documents:', len(documents))
    print('load pdf time:', time.time() - start_time)

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=0)
    split_docs = text_splitter.split_documents(documents)
    print('split_docs:', len(split_docs))

    start_time = time.time()
    MILVUS_HOST = '192.168.106.12'
    MILVUS_PORT = '19530'
    vector_store = Milvus.from_documents(split_docs,
                                         embedding=embeddings,
                                         collection_name="zhaogushuglx_vector_chunk500",
                                         drop_old=True,
                                         connection_args={
                                             "host": MILVUS_HOST,
                                             "port": MILVUS_PORT
                                         })
    print('embedding and vector store time:', time.time() - start_time)

    start_time = time.time()
    ssl_verify = {
        'ca_certs': "/home/public/liuqingjie/Elasticsearch/http_ca.crt",
        'basic_auth': ("elastic", "F94h5JtdQn6EQB-G9Hjv"),
        'verify_certs': False
    }
    vector_store = ElasticKeywordsSearch.from_documents(
        split_docs,
        embeddings,
        elasticsearch_url="https://192.168.106.14:9200",
        index_name="zhaogushuglx_keyword_chunk500",
        ssl_verify=ssl_verify)
    print('keyword store time:', time.time() - start_time)


def multi_retrieval(query):
    MILVUS_HOST = '192.168.106.12'
    MILVUS_PORT = '19530'
    vector_store = Milvus(embedding_function=embeddings,
                          collection_name="zhaogushuglx_vector_chunk500",
                          connection_args={
                              "host": MILVUS_HOST,
                              "port": MILVUS_PORT
                          })
    vector_retriever = vector_store.as_retriever(search_type="similarity", search_kwargs={"k": 4})

    ssl_verify = {
        'ca_certs': "/home/public/liuqingjie/Elasticsearch/http_ca.crt",
        'basic_auth': ("elastic", "F94h5JtdQn6EQB-G9Hjv"),
        'verify_certs': False
    }
    es_store = ElasticKeywordsSearch(elasticsearch_url="https://192.168.106.14:9200",
                                     index_name="zhaogushuglx_keyword_chunk500",
                                     ssl_verify=ssl_verify)
    keyword_retriever = es_store.as_retriever(search_type="similarity", search_kwargs={"k": 4})

    combine_strategy = 'mix'
    es_vector_retriever = MixEsVectorRetriever(vector_retriever=vector_retriever,
                                               keyword_retriever=keyword_retriever,
                                               combine_strategy=combine_strategy)
    print(es_vector_retriever.get_relevant_documents(query),
          len(es_vector_retriever.get_relevant_documents(query)))


# data_loader()
multi_retrieval("达梦公司聘请了哪些券商作为主要保荐机构?")
