from typing import List, Optional, Any, Dict

from loguru import logger
from pydantic import Field, root_validator
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from langchain_core.language_models import LLM, BaseLanguageModel

from bisheng.database.models.llm_server import LLMDao, LLMModelType, LLMServerType, LLMModel, LLMServer
from bisheng.interface.importing import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm


class BishengChatLLM(LLM):
    """
     依赖bisheng后端服务的llm组件
     根据model的类型不同 调用不同的llm
    """

    model_name: str = Field(description="后端服务保存的model名称")
    model_id: int = Field(description="后端服务保存的model唯一ID")
    streaming: bool = Field(default=True, description="是否使用流式输出", alias="stream")
    temperature: float = Field(default=0, description="模型生成的温度")
    top_p: float = Field(default=0, description="模型生成的top_p")
    cache: bool = Field(default=True, description="是否使用缓存")

    _llm: Optional[LLM] = Field(default=None, exclude=True)
    _llm_node_type = {
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

    @root_validator()
    def validate_llm(cls, values: Dict) -> Dict:
        model_id = values.get('model_id')
        if not model_id:
            raise Exception('没有找到模型配置')
        model_info = LLMDao.get_model_by_id(model_id)
        if not model_info:
            raise Exception('模型配置已被删除，请重新配置模型')
        server_info = LLMDao.get_server_by_id(model_info.server_id)
        if not server_info:
            raise Exception('服务提供方配置已被删除，请重新配置模型')
        if model_info.model_type != LLMModelType.LLM:
            raise Exception(f'只支持LLM类型的模型，不支持{model_info.model_type.value}类型的模型')

        class_object = cls._get_llm_class(server_info.type)
        params = cls._get_llm_params(server_info, model_info)
        try:
            values['llm'] = instantiate_llm(cls._llm_node_type.get(server_info.type), class_object, params)
        except Exception as e:
            logger.exception('init bisheng llm error')
            raise Exception(f'初始化llm组件失败，请检查配置或联系管理员。错误信息：{e}')
        return values

    @classmethod
    def _get_llm_class(cls, server_type: LLMServerType) -> BaseLanguageModel:
        node_type = cls._llm_node_type.get(server_type)
        class_object = import_by_type(_type='llms', name=node_type)
        return class_object

    @classmethod
    def _get_llm_params(cls, server_info: LLMServer, model_info: LLMModel) -> dict:
        params = {}
        if server_info.config:
            params.update(server_info.config)
        if model_info.config:
            params.update(model_info.config)

        params.update({
            'model_name': model_info.model_name,
            'stream': cls.stream,
            'temperature': cls.temperature,
            'top_p': cls.top_p,
            'cache': cls.cache
        })
        return params

    @property
    def _llm_type(self):
        return self._llm._llm_type

    def _call(
            self,
            prompt: str,
            stop: Optional[List[str]] = None,
            run_manager: Optional[CallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> str:
        try:
            ret = self._llm._call(prompt, stop, run_manager, **kwargs)
        except Exception as e:
            # 记录失败状态
            raise e
        return ret

    async def _acall(
            self,
            prompt: str,
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> str:
        try:
            ret = await self._llm._acall(prompt, stop, run_manager, **kwargs)
        except Exception as e:
            # 记录失败状态
            raise e
        return ret
