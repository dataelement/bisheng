from typing import List, Optional

from loguru import logger
from pydantic import Field

from bisheng.database.models.llm_server import LLMServerType, LLMDao, LLMModelType, LLMServer, LLMModel
from bisheng.interface.importing import import_by_type
from langchain.embeddings.base import Embeddings


class OpenAIProxyEmbedding(Embeddings):

    def __init__(self) -> None:
        super().__init__()
        from bisheng.api.services.llm import LLMService

        knowledge_llm = LLMService.get_knowledge_llm()
        self.embeddings = BishengEmbeddings(model_id=knowledge_llm.embedding_model_id)

    @classmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed search docs."""
        if not texts:
            return []

        return self.embeddings.embed_documents(texts)

    @classmethod
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


class BishengEmbeddings(Embeddings):
    """依赖bisheng后端服务的embedding组件     根据model的类型不同 调用不同的embedding组件"""

    model_id: int = Field(description="后端服务保存的model唯一ID")

    embeddings: Optional[Embeddings] = Field(default=None)
    llm_node_type = {
        # 开源推理框架
        LLMServerType.OLLAMA: 'OllamaEmbeddings',
        LLMServerType.XINFERENCE: 'XinferenceEmbeddings',
        LLMServerType.LLAMACPP: 'LlamaCppEmbeddings',
        LLMServerType.VLLM: '',

        LLMServerType.OPENAI: 'OpenAIEmbeddings',
        LLMServerType.AZURE_OPENAI: 'AzureOpenAIEmbeddings',
        LLMServerType.QWEN: 'DashScopeEmbeddings',
        LLMServerType.QIAN_FAN: 'QianfanEmbeddingsEndpoint',
        LLMServerType.MINIMAX: 'MiniMaxEmbeddings',
        LLMServerType.CHAT_GLM: '',
    }

    def __init__(self, **kwargs):
        from bisheng.interface.initialize.loading import instantiate_embedding

        super().__init__(**kwargs)
        self.model_id = kwargs.get('model_id')
        if not self.model_id:
            raise Exception('没有找到模型配置')
        model_info = LLMDao.get_model_by_id(self.model_id)
        if not model_info:
            raise Exception('模型配置已被删除，请重新配置模型')
        server_info = LLMDao.get_server_by_id(model_info.server_id)
        if not server_info:
            raise Exception('服务提供方配置已被删除，请重新配置模型')
        if model_info.model_type != LLMModelType.EMBEDDING:
            raise Exception(f'只支持Embedding类型的模型，不支持{model_info.model_type.value}类型的模型')
        if not model_info.online:
            raise Exception(f'{server_info.name}下的{model_info.model_name}模型已下线，请联系管理员上线对应的模型')
        logger.debug(f'init_bisheng_embedding: server_info: {server_info}, model_info: {model_info}')

        class_object = self._get_embedding_class(server_info.type)
        params = self._get_embedding_params(server_info, model_info)
        try:
            self.embeddings = instantiate_embedding(class_object, params)
        except Exception as e:
            logger.exception('init bisheng embedding error')
            raise Exception(f'初始化bisheng embedding组件失败，请检查配置或联系管理员。错误信息：{e}')

    def _get_embedding_class(self, server_type: LLMServerType) -> Embeddings:
        node_type = self.llm_node_type.get(server_type)
        if not node_type:
            raise Exception(f'没有找到对应的embedding组件{server_type}')
        class_object = import_by_type(_type='embeddings', name=node_type)
        return class_object

    def _get_embedding_params(self, server_info: LLMServer, model_info: LLMModel) -> dict:
        params = {}
        if server_info.config:
            params.update(server_info.config)
        if model_info.config:
            params.update(model_info.config)
        params.update({
            'model_name': model_info.model_name,
        })
        if server_info.type == LLMServerType.QWEN:
            params = {
                "dashscope_api_key": params.get('openai_api_key'),
                "model": params.get('model_name'),
            }
        return params

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """embedding"""
        try:
            ret = self.embeddings.embed_documents(texts)
            self._update_model_status(0)
            return ret
        except Exception as e:
            self._update_model_status(1, str(e))
            logger.exception('embedding error')
            raise Exception(f'embedding组件异常，请检查配置或联系管理员。错误信息：{e}')

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
}
