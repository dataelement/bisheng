import os
import httpx
from bisheng_langchain.rag import BishengRAGTool, BishengRetrievalQA
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus
from langchain_openai import ChatOpenAI, OpenAIEmbeddings


openai_proxy = os.getenv('OPENAI_PROXY')
async_http_client = httpx.AsyncClient(proxies=openai_proxy)
httpx_client = httpx.Client(proxies=openai_proxy)
# embedding
embeddings = OpenAIEmbeddings(model='text-embedding-ada-002', http_async_client=async_http_client, http_client=httpx_client)
# llm
llm = ChatOpenAI(model='gpt-4-1106-preview', temperature=0.01, http_async_client=async_http_client, http_client=httpx_client)
# milvus
vector_store = Milvus(
        collection_name='rag_finance_report_0_benchmark_caibao_1000_source_title',
        embedding_function=embeddings,
        connection_args={
            "host": '192.168.106.116',
            "port": '19530',
        },
)
# es
keyword_store = ElasticKeywordsSearch(
    index_name='rag_finance_report_0_benchmark_caibao_1000_source_title',
    elasticsearch_url='http://192.168.106.116:9200',
    ssl_verify={'basic_auth': ["elastic", "oSGL-zVvZ5P3Tm7qkDLC"]},
)


max_content = 15000
sort_by_source_and_index = True
return_source_documents = False
qa = BishengRetrievalQA.from_llm(
    llm=llm, 
    vector_store=vector_store, 
    keyword_store=keyword_store,
    max_content=max_content,
    sort_by_source_and_index=sort_by_source_and_index,
    return_source_documents=return_source_documents
)

response = qa({'query': '能否根据2020年金宇生物技术股份有限公司的年报，给我简要介绍一下报告期内公司的社会责任工作情况？'})
print(response)