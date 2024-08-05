import uuid
from typing import List, Optional, Any, Dict, Union

from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult, ChatResult
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import Field, root_validator
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun, Callbacks
from langchain_core.language_models import LLM, BaseLanguageModel, LanguageModelInput, BaseChatModel

from bisheng.database.models.llm_server import LLMDao, LLMModelType, LLMServerType, LLMModel, LLMServer
from bisheng.interface.importing import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm


class BishengLLM(BaseChatModel):
    """
     依赖bisheng后端服务的llm组件
     根据model的类型不同 调用不同的llm
    """

    model_name: str = Field(default='', description="后端服务保存的model名称")
    model_id: int = Field(description="后端服务保存的model唯一ID")
    streaming: bool = Field(default=True, description="是否使用流式输出", alias="stream")
    temperature: float = Field(default=0.3, description="模型生成的温度")
    top_p: float = Field(default=1, description="模型生成的top_p")
    cache: bool = Field(default=True, description="是否使用缓存")

    llm: Optional[BaseChatModel] = Field(default=None)
    llm_node_type = {
        LLMServerType.OPENAI: 'ChatOpenAI',
        LLMServerType.AZURE_OPENAI: 'AzureChatOpenAI',
        LLMServerType.OLLAMA: 'CohereChatOpenAI',
        LLMServerType.XINFERENCE: 'XInferenceChatOpenAI',
        LLMServerType.LLAMACPP: 'ChatOpenAI',
        LLMServerType.VLLM: 'VLLMChatOpenAI',
        LLMServerType.QWEN: 'ChatQWen',
        LLMServerType.QIAN_FAN: 'ChatQianFan',
        LLMServerType.CHAT_GLM: 'ChatGLM',
        LLMServerType.MINIMAX: 'ChatMinimaxAI',
        LLMServerType.ANTHROPIC: 'ChatAnthropic',
        LLMServerType.DEEPSEEK: 'ChatDeepSeek',
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model_id = kwargs.get('model_id')
        self.model_name = kwargs.get('model_name')
        self.cache = kwargs.get('cache')
        self.streaming = kwargs.get('streaming')
        self.temperature = kwargs.get('temperature')
        self.top_p = kwargs.get('top_p')

        if not self.model_id:
            raise Exception('没有找到模型配置')
        model_info = LLMDao.get_model_by_id(self.model_id)
        if not model_info:
            raise Exception('模型配置已被删除，请重新配置模型')
        server_info = LLMDao.get_server_by_id(model_info.server_id)
        if not server_info:
            raise Exception('服务提供方配置已被删除，请重新配置模型')
        if model_info.model_type != LLMModelType.LLM:
            raise Exception(f'只支持LLM类型的模型，不支持{model_info.model_type.value}类型的模型')
        if not model_info.online:
            raise Exception(f'{server_info.name}下的{model_info.model_name}模型已下线，请联系管理员上线对应的模型')
        logger.debug(f'init_bisheng_llm: server_info: {server_info}, model_info: {model_info}')

        class_object = self._get_llm_class(server_info.type)
        params = self._get_llm_params(server_info, model_info)
        try:
            self.llm = instantiate_llm(self.llm_node_type.get(server_info.type), class_object, params)
        except Exception as e:
            logger.exception('init bisheng llm error')
            raise Exception(f'初始化llm组件失败，请检查配置或联系管理员。错误信息：{e}')

    def _get_llm_class(self, server_type: LLMServerType) -> BaseLanguageModel:
        node_type = self.llm_node_type.get(server_type)
        class_object = import_by_type(_type='llms', name=node_type)
        return class_object

    def _get_llm_params(self, server_info: LLMServer, model_info: LLMModel) -> dict:
        params = {}
        if server_info.config:
            params.update(server_info.config)
        if model_info.config:
            params.update(model_info.config)

        params.update({
            'model_name': model_info.model_name,
            'stream': self.stream,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'cache': self.cache
        })
        return params

    @property
    def _llm_type(self):
        return self.llm._llm_type

    def _generate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            stream: Optional[bool] = None,
            **kwargs: Any,
    ) -> ChatResult:
        try:
            ret = self.llm._generate(messages, stop, run_manager, **kwargs)
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1)
            raise e
        return ret

    async def _agenerate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            stream: Optional[bool] = None,
            **kwargs: Any,
    ) -> ChatResult:
        try:
            ret = await self.llm._agenerate(messages, stop, run_manager, **kwargs)
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1)
            # 记录失败状态
            raise e
        return ret

    def _update_model_status(self, status: int):
        """更新模型状态"""
        # todo 接入到异步任务模块
        LLMDao.update_model_status(self.model_id, status)
