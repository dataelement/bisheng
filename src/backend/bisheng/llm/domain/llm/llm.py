import json
from typing import List, Optional, Any, Sequence, Union, Dict, Type, Callable, Iterator, AsyncIterator

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage, BaseMessageChunk
from langchain_core.outputs import ChatResult, ChatGenerationChunk
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from loguru import logger
from pydantic import Field
from typing_extensions import Self

from bisheng.common.errcode.server import NoLlmModelConfigError, LlmModelConfigDeletedError, LlmProviderDeletedError, \
    LlmModelTypeError, LlmModelOfflineError, InitLlmError
from bisheng.core.ai import CustomChatOllamaWithReasoning, ChatOpenAI, ChatOpenAICompatible, \
    AzureChatOpenAI, ChatTongyi, ChatZhipuAI, MiniMaxChat, ChatAnthropic, ChatDeepSeek, \
    MoonshotChat
from bisheng.llm.domain.const import LLMModelType, LLMServerType
from bisheng.llm.domain.models import LLMServer, LLMModel
from .base import BishengBase
from ..utils import wrapper_bisheng_model_limit_check, wrapper_bisheng_model_limit_check_async, \
    wrapper_bisheng_model_generator, wrapper_bisheng_model_generator_async


def _get_user_kwargs(model_config: dict) -> dict:
    user_kwargs = model_config.get('user_kwargs', {})
    if isinstance(user_kwargs, str) and user_kwargs:
        return json.loads(user_kwargs)
    return user_kwargs if user_kwargs else {}


# Attention needs to be paid to the priority of the initialization parameters. Instantiation Incoming Highest -> The following configurations of the front-end interface -> Advanced parameters of the front-end interface have the lowest priority
def _get_ollama_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['base_url'] = server_config.get('base_url', '').rstrip('/')
    # some bugs
    params['extract_reasoning'] = False
    params['stream'] = params.pop('streaming', True)
    if params.get('max_tokens'):
        params['num_ctx'] = params.pop('max_tokens', None)

    # User advanced custom configuration
    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_xinference_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params = _get_openai_params(params, server_config, model_config)
    if not params.get('api_key', None):
        params['api_key'] = 'Empty'

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_openai_params(params: dict, server_config: dict, model_config: dict) -> dict:
    if server_config:
        params.update({
            'api_key': server_config.get('openai_api_key') or server_config.get('api_key') or "empty",
            'base_url': server_config.get('openai_api_base') or server_config.get('base_url'),
        })
        params['base_url'] = params['base_url'].rstrip('/')
    if server_config.get('openai_proxy'):
        params['openai_proxy'] = server_config.get('openai_proxy')
    params['stream_usage'] = True

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_azure_openai_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params.update({
        'azure_endpoint': server_config.get('azure_endpoint').rstrip('/'),
        'openai_api_key': server_config.get('openai_api_key'),
        'openai_api_version': server_config.get('openai_api_version'),
        'azure_deployment': params.pop('model'),
        'stream_usage': True,
    })

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_qwen_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['dashscope_api_key'] = server_config.get('openai_api_key', '')
    params['model_kwargs'] = {
        'enable_search': model_config.get('enable_web_search', False),
    }
    if params.get("streaming"):
        params['model_kwargs']['incremental_output'] = True

    if params.get('temperature'):
        params['model_kwargs']['temperature'] = params.pop('temperature')

    if params.get('max_tokens'):
        params['model_kwargs']['max_tokens'] = params.pop('max_tokens')

    user_kwargs = _get_user_kwargs(model_config)
    if user_model_kwargs := user_kwargs.get('model_kwargs'):
        user_model_kwargs.update(params['model_kwargs'])
        params['model_kwargs'] = user_model_kwargs
        user_kwargs.pop('model_kwargs', None)
    user_kwargs.update(params)

    return user_kwargs


def _get_minimax_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['minimax_api_key'] = server_config.get('openai_api_key')
    params['base_url'] = server_config.get('openai_api_base').rstrip('/')
    if 'max_tokens' not in params:
        params['max_tokens'] = 2048
    if '/chat/completions' not in params['base_url']:
        params['base_url'] = f"{params['base_url']}/chat/completions"

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_anthropic_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params.update(server_config)

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return user_kwargs


def _get_zhipu_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['zhipuai_api_key'] = server_config.get('openai_api_key')
    params['zhipuai_api_base'] = server_config.get('openai_api_base').rstrip('/')
    if 'chat/completions' not in params['zhipuai_api_base']:
        params['zhipuai_api_base'] = f"{params['zhipuai_api_base'].rstrip('/')}/chat/completions"

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return params


def _get_spark_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params.update({
        'api_key': f'{server_config.get("api_key")}:{server_config.get("api_secret")}',
        'base_url': server_config.get('openai_api_base').rstrip('/'),
    })

    user_kwargs = _get_user_kwargs(model_config)
    user_kwargs.update(params)
    return params


_llm_node_type: Dict = {
    # Open source inference framework
    LLMServerType.OLLAMA.value: {'client': CustomChatOllamaWithReasoning, 'params_handler': _get_ollama_params},
    LLMServerType.XINFERENCE.value: {'client': ChatOpenAI, 'params_handler': _get_xinference_params},
    LLMServerType.LLAMACPP.value: {'client': ChatOpenAI, 'params_handler': _get_openai_params},
    LLMServerType.VLLM.value: {'client': ChatOpenAICompatible, 'params_handler': _get_openai_params},

    # OfficalapiSERVICES
    LLMServerType.OPENAI.value: {'client': ChatOpenAICompatible, 'params_handler': _get_openai_params},
    LLMServerType.AZURE_OPENAI.value: {'client': AzureChatOpenAI, 'params_handler': _get_azure_openai_params},
    LLMServerType.QWEN.value: {'client': ChatTongyi, 'params_handler': _get_qwen_params},
    LLMServerType.QIAN_FAN.value: {'client': ChatOpenAICompatible, 'params_handler': _get_openai_params},
    LLMServerType.ZHIPU.value: {'client': ChatZhipuAI, 'params_handler': _get_zhipu_params},
    LLMServerType.MINIMAX.value: {'client': MiniMaxChat, 'params_handler': _get_minimax_params},
    LLMServerType.ANTHROPIC.value: {'client': ChatAnthropic, 'params_handler': _get_anthropic_params},
    LLMServerType.DEEPSEEK.value: {'client': ChatDeepSeek, 'params_handler': _get_openai_params},
    LLMServerType.SPARK.value: {'client': ChatOpenAICompatible, 'params_handler': _get_spark_params},
    LLMServerType.TENCENT.value: {'client': ChatOpenAICompatible, 'params_handler': _get_openai_params},
    LLMServerType.MOONSHOT.value: {'client': MoonshotChat, 'params_handler': _get_openai_params},
    LLMServerType.VOLCENGINE.value: {'client': ChatOpenAICompatible, 'params_handler': _get_openai_params},
    LLMServerType.SILICON.value: {'client': ChatOpenAICompatible, 'params_handler': _get_openai_params},
    LLMServerType.MIND_IE.value: {'client': ChatOpenAICompatible, 'params_handler': _get_openai_params},
}


class BishengLLM(BishengBase, BaseChatModel):
    """
     Use the llm model that has been launched in model management
    """

    streaming: Optional[bool] = Field(default=None, description="Whether to use streaming output", alias="stream")
    temperature: Optional[float] = Field(default=None, description="Model Generated Temperature")

    llm: Optional[BaseChatModel] = Field(default=None)

    @classmethod
    async def get_bisheng_llm(cls, **kwargs) -> Self:
        return await cls.get_class_instance(**kwargs)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model_id = kwargs.get('model_id')
        if not self.model_id:
            raise NoLlmModelConfigError()

        if "model_info" in kwargs and "server_info" in kwargs:
            # Description is fromclass methodInitialized No need to query the database again
            self._init_client(model_info=kwargs.pop("model_info"), server_info=kwargs.pop("server_info"), **kwargs)
        else:
            model_info, server_info = self.get_model_server_info_sync(self.model_id)
            self._init_client(model_info, server_info, **kwargs)

    def _init_client(self, model_info: LLMModel, server_info: LLMServer, **kwargs):
        ignore_online = kwargs.get('ignore_online', False)
        self.temperature = kwargs.get('temperature', None)
        self.streaming = kwargs.get('streaming', None)

        if not model_info:
            raise LlmModelConfigDeletedError()
        if not server_info:
            raise LlmProviderDeletedError()
        if model_info.model_type != LLMModelType.LLM.value:
            raise LlmModelTypeError(model_type=model_info.model_type)
        if not ignore_online and not model_info.online:
            raise LlmModelOfflineError(server_name=server_info.name, model_name=model_info.model_name)

        logger.debug(f'init_bisheng_llm: server_id: {server_info.id}, model_id: {model_info.id}')
        self.model_info = model_info
        self.model_name = model_info.model_name
        self.server_info = server_info

        class_object = self._get_llm_class(server_info.type)
        params = self._get_llm_params(server_info, model_info)
        try:
            self.llm = class_object(**params)
        except Exception as e:
            logger.exception('init bisheng llm error')
            raise InitLlmError(exception=e)

    @staticmethod
    def _get_llm_class(server_type: str) -> type[BaseChatModel]:
        if server_type not in _llm_node_type:
            raise Exception(f'not support llm type: {server_type}')
        class_type = _llm_node_type[server_type]['client']
        return class_type

    def _get_llm_params(self, server_info: LLMServer, model_info: LLMModel) -> dict:
        server_config = self.get_server_info_config()
        model_config = self.get_model_info_config()
        default_params = self._get_default_params(server_config, model_config)

        params_handler = _llm_node_type[server_info.type]['params_handler']
        params = params_handler(default_params, server_config, model_config)
        return params

    def _get_default_params(self, server_config: dict, model_config: dict) -> dict:
        # Highest priority parameters because they are passed in when the object is instantiated
        default_params: Dict[str, Any] = {
            'model': self.model_info.model_name,
        }

        # The highest priority is passed in the instantiation, followed by the advanced configuration. Otherwise defaults totrue
        if self.streaming is not None:
            default_params['streaming'] = self.streaming
        else:
            user_kwargs = _get_user_kwargs(model_config)
            if user_kwargs.get('streaming', None) is None:
                default_params['streaming'] = True
            else:
                default_params['streaming'] = user_kwargs.get('streaming', None)

        if self.temperature is not None:
            default_params['temperature'] = self.temperature
        if model_config.get('max_tokens'):
            default_params['max_tokens'] = model_config.get('max_tokens')
        return default_params

    @property
    def _llm_type(self):
        return self.llm._llm_type

    def parse_kwargs(self, messages: List[BaseMessage], kwargs: Dict[str, Any]) -> (List[BaseMessage], Dict[str, Any]):
        if self.server_info.type == LLMServerType.MINIMAX.value:
            if self.get_model_info_config().get('enable_web_search'):
                if 'tools' not in kwargs:
                    kwargs.update({
                        'tools': [{'type': 'web_search'}],
                    })
                else:
                    tool_exists = False
                    for tool in kwargs['tools']:
                        if tool.get('type') == 'web_search':
                            tool_exists = True
                            break
                    if not tool_exists:
                        kwargs['tools'].append({
                            'type': 'web_search',
                        })
        elif self.server_info.type == LLMServerType.MOONSHOT.value:
            if self.get_model_info_config().get('enable_web_search'):
                if 'tools' not in kwargs:
                    kwargs.update({
                        'tools': [{
                            "type": "builtin_function",
                            "function": {
                                "name": "$web_search",
                            },
                        }],
                    })
                else:
                    tool_exists = False
                    for tool in kwargs['tools']:
                        if tool.get('type') == 'builtin_function':
                            tool_exists = True
                            break
                    if not tool_exists:
                        kwargs['tools'].append({
                            "type": "builtin_function",
                            "function": {
                                "name": "$web_search",
                            },
                        })
        elif self.server_info.type == LLMServerType.QWEN.value:
            # ChatTongYi The input parameters for multimodality are special and need to be converted to support
            user_message = messages[-1]
            if isinstance(user_message, HumanMessage):
                if isinstance(user_message.content, list):
                    for one in user_message.content:
                        if one.get('type') == 'image' and one.get('data'):
                            one['type'] = 'image'
                            one['image'] = f"data:{one.get('mime_type')};{one.get('source_type')},{one.get('data')}"
                        elif one.get('type') == 'image_url' and one.get('image_url'):
                            one['type'] = 'image'
                            one['image'] = one.pop('image_url', {}).get('url')
        return messages, kwargs

    @wrapper_bisheng_model_limit_check
    def _generate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            stream: Optional[bool] = None,
            **kwargs: Any,
    ) -> ChatResult:
        messages, kwargs = self.parse_kwargs(messages, kwargs)
        if self.server_info.type == LLMServerType.MOONSHOT.value:
            ret = self.moonshot_generate(messages, stop, run_manager, **kwargs)
        else:
            ret = self.llm._generate(messages, stop, run_manager, **kwargs)
            if self.server_info.type == LLMServerType.QWEN.value:
                ret.generations[0].message = self.convert_qwen_result(ret.generations[0].message)
        return ret

    def moonshot_generate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> ChatResult:
        result = None
        finish_reason = None
        while finish_reason is None or finish_reason == 'tool_calls':
            result = self.llm._generate(messages, stop, run_manager, **kwargs)
            result_message = result.generations[0].message
            finish_reason = result.generations[0].generation_info.get('finish_reason')
            for tool_call in result_message.tool_calls:
                tool_call_name = tool_call['name']
                if tool_call_name == "$web_search":
                    messages.append(result_message)
                    messages.append(ToolMessage(
                        tool_call_id=tool_call['id'],
                        name=tool_call_name,
                        content=json.dumps(tool_call['args'], ensure_ascii=False),
                    ))
                else:
                    break
        return result

    @wrapper_bisheng_model_limit_check_async
    async def _agenerate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            stream: Optional[bool] = None,
            **kwargs: Any,
    ) -> ChatResult:
        messages, kwargs = self.parse_kwargs(messages, kwargs)
        if self.server_info.type == LLMServerType.MOONSHOT.value:
            ret = await self.moonshot_agenerate(messages, stop, run_manager, **kwargs)
        else:
            ret = await self.llm._agenerate(messages, stop, run_manager, **kwargs)
            if self.server_info.type == LLMServerType.QWEN.value:
                ret.generations[0].message = self.convert_qwen_result(ret.generations[0].message)
        return ret

    async def moonshot_agenerate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> ChatResult:
        result = None
        finish_reason = None
        while finish_reason is None or finish_reason == 'tool_calls':
            result = await self.llm._agenerate(messages, stop, run_manager, **kwargs)
            result_message = result.generations[0].message
            finish_reason = result.generations[0].generation_info.get('finish_reason')
            for tool_call in result_message.tool_calls:
                tool_call_name = tool_call['name']
                if tool_call_name == "$web_search":
                    messages.append(result_message)
                    messages.append(ToolMessage(
                        tool_call_id=tool_call['id'],
                        name=tool_call_name,
                        content=json.dumps(tool_call['args'], ensure_ascii=False),
                    ))
                else:
                    break
        return result

    def bind_tools(
            self,
            tools: Sequence[Union[Dict[str, Any], Type, Callable, BaseTool]],
            **kwargs: Any,
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        formatted_tools = [convert_to_openai_tool(tool) for tool in tools]
        return super().bind(tools=formatted_tools, **kwargs)

    def convert_qwen_result(self, message: BaseMessageChunk | BaseMessage) -> BaseMessageChunk | BaseMessage:
        # ChatTongYi model vl model message.content is list
        if isinstance(message.content, list):
            message.content = ''.join([one.get('text', '') for one in message.content])
        return message

    @wrapper_bisheng_model_generator
    def _stream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[CallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for one in self.llm._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
            if self.server_info.type == LLMServerType.QWEN.value:
                one.message = self.convert_qwen_result(one.message)
            yield one

    @wrapper_bisheng_model_generator_async
    async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        async for one in self.llm._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            if self.server_info.type == LLMServerType.QWEN.value:
                one.message = self.convert_qwen_result(one.message)
            yield one
