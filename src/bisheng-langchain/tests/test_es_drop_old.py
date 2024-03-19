import os

import httpx
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from loguru import logger

from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.schema import Document

EMBEDDING = OpenAIEmbeddings(model='text-embedding-ada-002')
ssl_verify = {'basic_auth': ("elastic", "oSGL-zVvZ5P3Tm7qkDLC")}

docs = [Document(page_content='hello world')]
es_index_name = 'drop_old_test'
for i in range(5):
    es_store = ElasticKeywordsSearch.from_documents(
        documents=docs,
        embedding=EMBEDDING,
        elasticsearch_url="http://192.168.106.116:9200",
        index_name=es_index_name,
        ssl_verify=ssl_verify,
        drop_old=False,
    )
    retiever = es_store.as_retriever()
    res = retiever.get_relevant_documents('hello')
    print(res)

logger.info('when drop old is True')

for i in range(5):
    es_store = ElasticKeywordsSearch.from_documents(
        documents=docs,
        embedding=EMBEDDING,
        elasticsearch_url="http://192.168.106.116:9200",
        index_name=es_index_name,
        ssl_verify=ssl_verify,
        drop_old=True,
    )
    retiever = es_store.as_retriever()
    res = retiever.get_relevant_documents('hello')
    print(res)
