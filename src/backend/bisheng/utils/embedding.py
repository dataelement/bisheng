import httpx
from bisheng.settings import settings
from bisheng_langchain.embeddings import CustomHostEmbedding, HostEmbeddings
from langchain.embeddings.base import Embeddings
from langchain_community.utils.openai import is_openai_v1
from langchain_openai.embeddings import OpenAIEmbeddings


def decide_embeddings(model: str) -> Embeddings:
    """embed method"""
    model_list = settings.get_knowledge().get('embeddings')
    params = model_list.get(model)
    component = params.pop('component', '')
    if model == 'text-embedding-ada-002' or component == 'openai':
        if is_openai_v1() and params.get('openai_proxy'):
            params['http_client'] = httpx.Client(proxies=params.get('openai_proxy'))
            params['http_async_client'] = httpx.AsyncClient(proxies=params.get('openai_proxy'))
        return OpenAIEmbeddings(**params)
    elif component == 'custom':
        return CustomHostEmbedding(**params)
    else:
        return HostEmbeddings(**model_list.get(model))
