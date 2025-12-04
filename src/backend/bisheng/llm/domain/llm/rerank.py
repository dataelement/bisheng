from typing import Dict, Optional, Sequence

import dashscope
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from loguru import logger
from pydantic import Field
from typing_extensions import Self

from bisheng.core.ai import XinferenceRerank, CommonRerank, DashScopeRerank
from bisheng.llm.domain.const import LLMServerType, LLMModelType
from .llm import BishengBase
from ..utils import wrapper_bisheng_model_limit_check, wrapper_bisheng_model_limit_check_async


def _get_xinference_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['base_url'] = server_config.get('openai_api_base') or server_config.get('base_url')
    params['api_key'] = server_config.get('openai_api_key') or server_config.get('api_key') or 'empty'
    params['model_uid'] = params.pop('model', '')
    return params


def _get_common_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['base_url'] = server_config.get('openai_api_base') or server_config.get('base_url')
    params['api_key'] = server_config.get('openai_api_key') or server_config.get('api_key') or 'empty'
    params['rerank_endpoint'] = '/rerank'
    return params


def _get_qwen_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['dashscope_api_key'] = server_config.get('openai_api_key', '')
    params['top_n'] = None  # return all documents
    params["client"] = dashscope.TextReRank
    return params


_node_type: Dict = {
    # 开源推理框架
    LLMServerType.XINFERENCE.value: {'client': XinferenceRerank, 'params_handler': _get_xinference_params},
    LLMServerType.LLAMACPP.value: {'client': CommonRerank, 'params_handler': _get_common_params},
    LLMServerType.VLLM.value: {'client': CommonRerank, 'params_handler': _get_common_params},

    # 官方api服务
    LLMServerType.QWEN.value: {'client': DashScopeRerank, 'params_handler': _get_qwen_params},
    LLMServerType.QIAN_FAN.value: {'client': CommonRerank, 'params_handler': _get_common_params},
    LLMServerType.SILICON.value: {'client': CommonRerank, 'params_handler': _get_common_params},
}


class BishengRerank(BishengBase, BaseDocumentCompressor):
    """Rerank LLM wrapper class"""
    rerank: Optional[BaseDocumentCompressor] = Field(None, description="Rerank client instance")

    @classmethod
    async def get_bisheng_rerank(cls, **kwargs) -> Self:
        return await cls.get_class_instance(**kwargs)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model_id = kwargs.get('model_id')
        if not self.model_id:
            raise Exception('没有找到rerank模型配置')
        if "model_info" in kwargs and "server_info" in kwargs:
            self._init_client(model_info=kwargs.pop('model_info'), server_info=kwargs.pop('server_info'), **kwargs)
        else:
            model_info, server_info = self.get_model_server_info_sync(self.model_id)
            self._init_client(model_info=model_info, server_info=server_info, **kwargs)

    def _init_client(self, model_info, server_info, **kwargs):
        ignore_online = kwargs.get('ignore_online', False)
        if not model_info:
            raise Exception('rerank模型配置已被删除，请重新配置模型')
        if not server_info:
            raise Exception('服务提供方配置已被删除，请重新配置rerank模型')
        if model_info.model_type != LLMModelType.RERANK.value:
            raise Exception(f'只支持Rerank类型的模型，不支持{model_info.model_type}类型的模型')
        if not ignore_online and not model_info.online:
            raise Exception(f'{server_info.name}下的{model_info.model_name}模型已下线，请联系管理员上线对应的模型')
        logger.debug(f'init_bisheng_rerank: server_id: {server_info.id}, model_id: {model_info.id}')

        node_conf = _node_type.get(server_info.type)
        if not node_conf:
            raise Exception(f'不支持rerank的服务提供方：{server_info.type}')
        self.model_info = model_info
        self.model_name = model_info.model_name
        self.server_info = server_info

        params_handler = node_conf['params_handler']
        client_class = node_conf['client']
        params = {
            "model": self.model_name,
        }
        params = params_handler(params, self.get_server_info_config(), self.get_model_info_config())
        try:
            self.rerank = client_class(**params)
        except Exception as e:
            logger.exception('init_bisheng_rerank error')
            raise Exception(f'init bisheng rerank error，error msg：{e}')

    @wrapper_bisheng_model_limit_check
    def compress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        return self.rerank.compress_documents(documents, query, callbacks=callbacks)

    @wrapper_bisheng_model_limit_check_async
    async def acompress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        return await self.rerank.acompress_documents(documents, query, callbacks=callbacks)
