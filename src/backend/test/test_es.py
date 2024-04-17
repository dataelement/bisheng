import httpx
from langchain_elasticsearch import ElasticsearchStore

from langchain_openai import OpenAIEmbeddings

params = {}

params['http_client'] = httpx.Client(proxies=params.get('openai_proxy'))
params['http_async_client'] = httpx.AsyncClient(proxies=params.get('openai_proxy'))
embedding = OpenAIEmbeddings(**params)
vectorstore = ElasticsearchStore(embedding=embedding,
                                 index_name="langchain-demo",
                                 es_url="http://192.168.106.116:9200",
                                 es_user="elastic",
                                 es_password="oSGL-zVvZ5P3Tm7qkDLC")
