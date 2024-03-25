import httpx
import openai
from bisheng.interface.initialize.utils import langchain_bug_openv1
from bisheng.settings import settings
from bisheng_langchain.embeddings import CustomHostEmbedding, HostEmbeddings
from langchain.embeddings.base import Embeddings
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain_community.utils.openai import is_openai_v1


def decide_embeddings(model: str) -> Embeddings:
    """embed method"""
    model_list = settings.get_knowledge().get('embeddings')
    params = model_list.get(model)
    component = params.pop('component', '')
    if model == 'text-embedding-ada-002' or component == 'openai':
        if is_openai_v1() and params.get('openai_proxy'):
            client_params = langchain_bug_openv1(params)
            client_params['http_client'] = httpx.Client(proxies=params['openai_proxy'])
            params['client'] = openai.OpenAI(**client_params).embeddings
            client_params['http_client'] = httpx.AsyncClient(proxies=params['openai_proxy'])
            params['async_client'] = openai.AsyncOpenAI(**client_params).embeddings
        return OpenAIEmbeddings(**params)
    elif component == 'custom':
        return CustomHostEmbedding(**params)
    else:
        return HostEmbeddings(**model_list.get(model))
