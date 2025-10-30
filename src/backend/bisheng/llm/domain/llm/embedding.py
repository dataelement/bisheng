import json
from typing import Optional, Dict, List

import numpy as np
from langchain_core.embeddings import Embeddings
from loguru import logger
from pydantic import Field
from typing_extensions import Self

from bisheng.core.ai import OllamaEmbeddings, OpenAIEmbeddings, AzureOpenAIEmbeddings, DashScopeEmbeddings
from .base import BishengBase
from ..utils import wrapper_bisheng_model_limit_check
from ...const import LLMServerType
from ...models.llm_server import LLMModel, LLMServer, LLMModelType


def _get_user_kwargs(model_config: dict) -> dict:
    user_kwargs = model_config.get('user_kwargs', {})
    if isinstance(user_kwargs, str):
        return json.loads(user_kwargs)
    return user_kwargs


def _get_ollama_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['base_url'] = server_config.get('base_url', '').rstrip('/')

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_openai_params(params: dict, server_config: dict, model_config: dict) -> dict:
    if server_config:
        params.update({
            'api_key': server_config.get('openai_api_key') or server_config.get('api_key') or 'empty',
            'base_url': server_config.get('openai_api_base', '') or server_config.get('base_url', ''),
        })
        params['base_url'] = params['base_url'].rstrip('/')
    if server_config.get('openai_proxy'):
        params['openai_proxy'] = server_config.get('openai_proxy')

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_azure_openai_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params.update({
        'azure_endpoint': server_config.get('azure_endpoint').rstrip('/'),
        'openai_api_key': server_config.get('openai_api_key'),
        'openai_api_version': server_config.get('openai_api_version'),
        'azure_deployment': params.pop('model'),
    })

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_qwen_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['dashscope_api_key'] = server_config.get('openai_api_key', '')

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


_node_type: Dict = {
    # 开源推理框架
    LLMServerType.OLLAMA.value: {"client": OllamaEmbeddings, "params_handler": _get_ollama_params},
    LLMServerType.XINFERENCE.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
    LLMServerType.LLAMACPP.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
    LLMServerType.VLLM.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},

    # 官方API服务
    LLMServerType.OPENAI.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
    LLMServerType.AZURE_OPENAI.value: {"client": AzureOpenAIEmbeddings, "params_handler": _get_azure_openai_params},
    LLMServerType.QWEN.value: {"client": DashScopeEmbeddings, "params_handler": _get_qwen_params},
    LLMServerType.QIAN_FAN.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
    LLMServerType.MINIMAX.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
    LLMServerType.ZHIPU.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
    LLMServerType.TENCENT.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
    LLMServerType.VOLCENGINE.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
    LLMServerType.SILICON.value: {"client": OpenAIEmbeddings, "params_handler": _get_openai_params},
}


class BishengEmbedding(BishengBase, Embeddings):
    """ Use the embedding model that has been launched in model management """

    model: str = Field(default='', description='后端服务保存的model名称')
    embedding_ctx_length: int = Field(default=8192, description='embedding模型上下文长度')
    max_retries: int = Field(default=6, description='embedding模型调用失败重试次数')
    request_timeout: int = Field(default=200, description='embedding模型调用超时时间')
    model_kwargs: dict = Field(default={}, description='embedding模型调用参数')

    embeddings: Optional[Embeddings] = Field(default=None)

    @classmethod
    async def get_bisheng_embedding(cls, **kwargs) -> Self:
        return await cls.get_class_instance(**kwargs)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model_id = kwargs.get('model_id')
        if not self.model_id:
            raise Exception('没有找到embedding模型配置')
        if "model_info" in kwargs and "server_info" in kwargs:
            self._init_client(model_info=kwargs.pop('model_info'), server_info=kwargs.pop('server_info'), **kwargs)
        else:
            model_info, server_info = self.get_model_server_info_sync(self.model_id)
            self._init_client(model_info=model_info, server_info=server_info, **kwargs)

    def _init_client(self, model_info, server_info, **kwargs):
        ignore_online = kwargs.get('ignore_online', False)
        if not model_info:
            raise Exception('embedding模型配置已被删除，请重新配置模型')
        if not server_info:
            raise Exception('服务提供方配置已被删除，请重新配置embedding模型')
        if model_info.model_type != LLMModelType.EMBEDDING.value:
            raise Exception(f'只支持Embedding类型的模型，不支持{model_info.model_type}类型的模型')
        if not ignore_online and not model_info.online:
            raise Exception(f'{server_info.name}下的{model_info.model_name}模型已下线，请联系管理员上线对应的模型')
        logger.debug(
            f'init_bisheng_embedding: server_id: {server_info.id}, model_id: {model_info.id}')
        self.model_info: LLMModel = model_info
        self.server_info: LLMServer = server_info
        self.model = model_info.model_name

        class_object = self._get_embedding_class(server_info.type)
        params = self._get_embedding_params(server_info, **kwargs)
        try:
            self.embeddings = class_object(**params)
        except Exception as e:
            logger.exception('init_bisheng_embedding error')
            raise Exception(f'初始化bisheng embedding组件失败，请检查配置或联系管理员。错误信息：{e}')

    @staticmethod
    def _get_embedding_class(server_type: str) -> type[Embeddings]:
        node_type = _node_type.get(server_type)
        if not node_type:
            raise Exception(f'{server_type}类型的服务提供方暂不支持embedding')
        class_object = node_type.get('client')
        return class_object

    def _get_default_params(self, server_config: dict, model_config: dict, **kwargs) -> dict:
        params = {
            "model": self.model_info.model_name,
        }
        return params

    def _get_embedding_params(self, server_info: LLMServer, **kwargs) -> dict:
        server_config = self.get_server_info_config()
        model_config = self.get_model_info_config()
        default_params = self._get_default_params(server_config, model_config, **kwargs)

        params_handler = _node_type[server_info.type]['params_handler']
        params = params_handler(default_params, server_config, model_config)
        return params

    @wrapper_bisheng_model_limit_check
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """embedding"""
        ret = self.embeddings.embed_documents(texts)
        # 盘单向量是否归一化了
        if ret:
            vector = ret[0]
            if np.linalg.norm(vector) != 1:
                ret = [(np.array(doc) / np.linalg.norm(doc)).tolist() for doc in ret]
        return ret

    @wrapper_bisheng_model_limit_check
    def embed_query(self, text: str) -> List[float]:
        """embedding"""
        ret = self.embeddings.embed_query(text)
        if np.linalg.norm(ret) != 1:
            ret = (np.array(ret) / np.linalg.norm(ret)).tolist()
        return ret
