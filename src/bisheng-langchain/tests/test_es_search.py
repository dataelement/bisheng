# %load ./zgs_vector_store.py
import os
import math
import time
import langchain
from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.docstore.document import Document
from langchain.chat_models import ChatOpenAI
from bisheng_langchain.vectorstores import ElasticKeywordsSearch

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
    ssl_verify = {'basic_auth': ("elastic", "oSGL-zVvZ5P3Tm7qkDLC")}
    es_store = ElasticKeywordsSearch.from_documents(
        split_docs,
        embeddings,
        llm=llm,
        elasticsearch_url="http://192.168.106.116:9200",
        index_name="zhaogushuglx_keyword_chunk500",
        ssl_verify=ssl_verify,
    )
    # keyword_retriever = es_store.as_retriever(search_type="similarity", search_kwargs={"k": 4})
    keyword_retriever = es_store.as_retriever(search_type="similarity_score_threshold", search_kwargs={"k": 4, "score_threshold": 0.0})
    print('keyword store time:', time.time() - start_time)

    return keyword_retriever, es_store


def retrieval(query, keyword_retriever):
    print('---------------------------------------------')
    print(keyword_retriever.get_relevant_documents(query))

keyword_retriever, es_store = data_loader()
retrieval("达梦公司聘请了哪些券商作为主要保荐机构?", keyword_retriever)
retrieval("公司所聘请的会计师事务所是哪家？该会计师事务所是否具有丰富的上市公司审计经验?", keyword_retriever)
retrieval("公司是否有债务或其他财务义务?", keyword_retriever)
es_store.delete()
