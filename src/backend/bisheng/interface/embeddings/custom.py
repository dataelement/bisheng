from typing import List, Optional

from bisheng.database.models.llm_server import (LLMDao, LLMModel, LLMModelType, LLMServer,
                                                LLMServerType)
from bisheng.interface.importing import import_by_type
from bisheng.interface.utils import wrapper_bisheng_model_limit_check
from langchain.embeddings.base import Embeddings
from langchain_core.pydantic_v1 import BaseModel
from loguru import logger
from pydantic import Field


class OpenAIProxyEmbedding(Embeddings):
    embeddings: Optional[Embeddings] = Field(default=None)

    def __init__(self) -> None:
        super().__init__()
        from bisheng.api.services.llm import LLMService

        knowledge_llm = LLMService.get_knowledge_llm()
        self.embeddings = BishengEmbedding(model_id=knowledge_llm.embedding_model_id)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed search docs."""
        if not texts:
            return []

        return self.embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""

        return self.embeddings.embed_query(text)


class FakeEmbedding(Embeddings):
    """为了保证milvus等，在模型下线还能继续用"""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """embedding"""
        return []

    def embed_query(self, text: str) -> List[float]:
        """embedding"""
        return []


class BishengEmbedding(BaseModel, Embeddings):
    """ Use the embedding model that has been launched in model management """

    model_id: int = Field(default=0, description='后端服务保存的model唯一ID')
    model: str = Field(default='', description='后端服务保存的model名称')
    embedding_ctx_length: int = Field(default=8192, description='embedding模型上下文长度')
    max_retries: int = Field(default=6, description='embedding模型调用失败重试次数')
    request_timeout: int = Field(default=200, description='embedding模型调用超时时间')
    model_kwargs: dict = Field(default={}, description='embedding模型调用参数')

    embeddings: Optional[Embeddings] = Field(default=None)
    llm_node_type = {
        # 开源推理框架
        LLMServerType.OLLAMA.value: 'OllamaEmbeddings',
        LLMServerType.XINFERENCE.value: 'OpenAIEmbeddings',
        LLMServerType.LLAMACPP.value: 'OpenAIEmbeddings',
        LLMServerType.VLLM.value: 'OpenAIEmbeddings',
        LLMServerType.BISHENG_RT.value: 'HostEmbeddings',

        # 官方API服务
        LLMServerType.OPENAI.value: 'OpenAIEmbeddings',
        LLMServerType.AZURE_OPENAI.value: 'AzureOpenAIEmbeddings',
        LLMServerType.QWEN.value: 'DashScopeEmbeddings',
        LLMServerType.QIAN_FAN.value: 'QianfanEmbeddingsEndpoint',
        LLMServerType.MINIMAX.value: 'OpenAIEmbeddings',
        LLMServerType.ZHIPU.value: 'OpenAIEmbeddings',
    }

    # bisheng强相关的业务参数
    model_info: Optional[LLMModel] = Field(default=None)
    server_info: Optional[LLMServer] = Field(default=None)

    class Config:
        """Configuration for this pydantic object."""
        allow_population_by_field_name = True
        arbitrary_types_allowed = True

    def __init__(self, **kwargs):
        from bisheng.interface.initialize.loading import instantiate_embedding
        super().__init__()
        self.model_id = kwargs.get('model_id')
        # 是否忽略模型是否上线的检查
        ignore_online = kwargs.get('ignore_online', False)

        if not self.model_id:
            raise Exception('没有找到embedding模型配置')
        model_info = LLMDao.get_model_by_id(self.model_id)
        if not model_info:
            raise Exception('embedding模型配置已被删除，请重新配置模型')
        server_info = LLMDao.get_server_by_id(model_info.server_id)
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
        params = self._get_embedding_params(server_info, model_info)
        try:
            if server_info.type == LLMServerType.OLLAMA.value:
                params['query_instruction'] = 'passage: '
            self.embeddings = instantiate_embedding(class_object, params)
        except Exception as e:
            logger.exception('init_bisheng_embedding error')
            raise Exception(f'初始化bisheng embedding组件失败，请检查配置或联系管理员。错误信息：{e}')

    def _get_embedding_class(self, server_type: str) -> Embeddings:
        node_type = self.llm_node_type.get(server_type)
        if not node_type:
            raise Exception(f'{server_type}类型的服务提供方暂不支持embedding')
        class_object = import_by_type(_type='embeddings', name=node_type)
        return class_object

    def _get_embedding_params(self, server_info: LLMServer, model_info: LLMModel) -> dict:
        params = {}
        if server_info.config:
            params.update(server_info.config)
        if model_info.config:
            params.update(model_info.config)
        params.update({
            'model': model_info.model_name,
        })
        if server_info.type == LLMServerType.QWEN.value:
            params = {
                'dashscope_api_key': params.get('openai_api_key'),
                'model': params.get('model'),
            }
        elif server_info.type == LLMServerType.QIAN_FAN.value:
            params = {
                'qianfan_ak': params.get('wenxin_api_key'),
                'qianfan_sk': params.get('wenxin_secret_key'),
                'model': params.get('model'),
            }
        elif server_info.type in [
                LLMServerType.XINFERENCE.value, LLMServerType.LLAMACPP.value,
                LLMServerType.VLLM.value
        ]:
            params['openai_api_key'] = params.pop('openai_api_key', None) or 'EMPTY'
        return params

    @wrapper_bisheng_model_limit_check
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """embedding"""
        try:
            if self.server_info.limit_flag:
                pass
            ret = self.embeddings.embed_documents(texts)
            self._update_model_status(0)
            return ret
        except Exception as e:
            self._update_model_status(1, str(e))
            logger.exception('embedding error')
            raise Exception(f'embedding error: {e}')

    @wrapper_bisheng_model_limit_check
    def embed_query(self, text: str) -> List[float]:
        """embedding"""
        try:
            ret = self.embeddings.embed_query(text)
            self._update_model_status(0)
            return ret
        except Exception as e:
            self._update_model_status(1, str(e))
            logger.exception('embedding error')
            raise Exception(f'embedding组件异常，请检查配置或联系管理员。错误信息：{e}')

    def _update_model_status(self, status: int, remark: str = ''):
        """更新模型状态"""
        LLMDao.update_model_status(self.model_id, status, remark)


CUSTOM_EMBEDDING = {
    'OpenAIProxyEmbedding': OpenAIProxyEmbedding,
    'BishengEmbedding': BishengEmbedding,
}
