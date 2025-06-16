import json
from typing import List, Optional, Any, Sequence, Union, Dict, Type, Callable, Iterator, AsyncIterator, ClassVar

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage, BaseMessageChunk
from langchain_core.outputs import ChatResult, ChatGenerationChunk
from typing import List, Optional, Any, Sequence, Union, Dict, Type, Callable

from bisheng.database.models.llm_server import LLMDao, LLMModelType, LLMServerType, LLMModel, LLMServer
from bisheng.interface.importing import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm
from bisheng.interface.utils import wrapper_bisheng_model_limit_check, wrapper_bisheng_model_limit_check_async, \
    wrapper_bisheng_model_generator, wrapper_bisheng_model_generator_async

from bisheng.interface.utils import wrapper_bisheng_model_limit_check, wrapper_bisheng_model_limit_check_async
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseLanguageModel, BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import Field


def _get_ollama_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['base_url'] = server_config.get('base_url', '')
    # some bugs
    params['extract_reasoning'] = False
    params['stream'] = params.pop('streaming', True)
    if params.get('max_tokens'):
        params['num_ctx'] = params.pop('max_tokens', None)
    return params


def _get_xinference_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params = _get_openai_params(params, server_config, model_config)
    if not params.get('api_key', None):
        params['api_key'] = 'Empty'
    return params


def _get_bisheng_rt_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params.update(server_config)
    return params


def _get_openai_params(params: dict, server_config: dict, model_config: dict) -> dict:
    if server_config:
        params.update({
            'api_key': server_config.get('openai_api_key') or server_config.get('api_key'),
            'base_url': server_config.get('openai_api_base') or server_config.get('base_url'),
        })
    if server_config.get('openai_proxy'):
        params['openai_proxy'] = server_config.get('openai_proxy')
    return params


def _get_azure_openai_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params.update({
        'azure_endpoint': server_config.get('azure_endpoint'),
        'openai_api_key': server_config.get('openai_api_key'),
        'openai_api_version': server_config.get('openai_api_version'),
        'azure_deployment': params.pop('model'),
    })
    return params


def _get_qwen_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['dashscope_api_key'] = server_config.get('openai_api_key', '')
    enable_web_search = model_config.get('enable_web_search', False)
    params['model_kwargs'] = {
        'enable_search': enable_web_search,
        'search_options': {
            'forced_search': enable_web_search
        },
        'temperature': params.pop('temperature', 0.3)
    }

    if params.get('max_tokens'):
        params['model_kwargs']['max_tokens'] = params.get('max_tokens')
    return params


def _get_qianfan_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['qianfan_ak'] = server_config.get('wenxin_api_key')
    params['qianfan_sk'] = server_config.get('wenxin_secret_key')
    if params.get('max_tokens'):
        params['model_kwargs'] = {"max_output_tokens": params.pop('max_tokens')}
    return params


def _get_minimax_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['minimax_api_key'] = server_config.get('openai_api_key')
    params['base_url'] = server_config.get('openai_api_base')
    if 'max_tokens' not in params:
        params['max_tokens'] = 2048
    if '/chat/completions' not in params['base_url']:
        params['base_url'] = f"{params['base_url']}/chat/completions"
    return params


def _get_anthropic_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params.update(server_config)
    return params


def _get_zhipu_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params['zhipuai_api_key'] = server_config.get('openai_api_key')
    params['zhipuai_api_base'] = server_config.get('openai_api_base')
    if 'chat/completions' not in params['zhipuai_api_base']:
        params['zhipuai_api_base'] = f"{params['zhipuai_api_base'].rstrip('/')}/chat/completions"
    return params


def _get_spark_params(params: dict, server_config: dict, model_config: dict) -> dict:
    params.update({
        'api_key': f'{server_config.get("api_key")}:{server_config.get("api_secret")}',
        'base_url': server_config.get('openai_api_base'),
    })
    return params


_llm_node_type: Dict = {
    # 开源推理框架
    LLMServerType.OLLAMA.value: {'client': 'ChatOllama', 'params_handler': _get_ollama_params},
    LLMServerType.XINFERENCE.value: {'client': 'ChatOpenAI', 'params_handler': _get_xinference_params},
    LLMServerType.LLAMACPP.value: {'client': 'ChatOpenAI', 'params_handler': _get_openai_params},
    # 此组件是加载本地的模型文件，待确认是否有api服务提供
    LLMServerType.VLLM.value: {'client': 'ChatOpenAI', 'params_handler': _get_openai_params},
    LLMServerType.BISHENG_RT.value: {'client': 'HostChatGLM', 'params_handler': _get_bisheng_rt_params},

    # 官方api服务
    LLMServerType.OPENAI.value: {'client': 'ChatOpenAI', 'params_handler': _get_openai_params},
    LLMServerType.AZURE_OPENAI.value: {'client': 'AzureChatOpenAI', 'params_handler': _get_azure_openai_params},
    LLMServerType.QWEN.value: {'client': 'ChatTongyi', 'params_handler': _get_qwen_params},
    LLMServerType.QIAN_FAN.value: {'client': 'QianfanChatEndpoint', 'params_handler': _get_qianfan_params},
    LLMServerType.ZHIPU.value: {'client': 'ChatZhipuAI', 'params_handler': _get_zhipu_params},
    LLMServerType.MINIMAX.value: {'client': 'MiniMaxChat', 'params_handler': _get_minimax_params},
    LLMServerType.ANTHROPIC.value: {'client': 'ChatAnthropic', 'params_handler': _get_anthropic_params},
    LLMServerType.DEEPSEEK.value: {'client': 'ChatDeepSeek', 'params_handler': _get_openai_params},
    LLMServerType.SPARK.value: {'client': 'ChatSparkOpenAI', 'params_handler': _get_spark_params},
    LLMServerType.TENCENT.value: {'client': 'ChatSparkOpenAI', 'params_handler': _get_openai_params},
    LLMServerType.MOONSHOT.value: {'client': 'MoonshotChat', 'params_handler': _get_openai_params},
    LLMServerType.VOLCENGINE.value: {'client': 'ChatSparkOpenAI', 'params_handler': _get_openai_params},
    LLMServerType.SILICON.value: {'client': 'ChatSparkOpenAI', 'params_handler': _get_openai_params},
}


class BishengLLM(BaseChatModel):
    """
     Use the llm model that has been launched in model management
    """

    model_id: int = Field(description="后端服务保存的model唯一ID")
    model_name: Optional[str] = Field(default='', description="后端服务保存的model名称")
    streaming: bool = Field(default=True, description="是否使用流式输出", alias="stream")
    enable_web_search: bool = Field(default=False, description="开启联网搜索")
    temperature: float = Field(default=0.3, description="模型生成的温度")
    top_p: float = Field(default=1, description="模型生成的top_p")
    cache: bool = Field(default=False, description="是否使用缓存")

    llm: Optional[BaseChatModel] = Field(default=None)
    # DONE merge_check 1.2.0中已删除
    llm_node_type: ClassVar[Dict[str, str]] = {
        # 开源推理框架
        LLMServerType.OLLAMA.value: 'ChatOllama',
        LLMServerType.XINFERENCE.value: 'ChatOpenAI',
        LLMServerType.LLAMACPP.value: 'ChatOpenAI',  # 此组件是加载本地的模型文件，待确认是否有api服务提供
        LLMServerType.VLLM.value: 'ChatOpenAI',
        LLMServerType.BISHENG_RT.value: "HostChatGLM",

        # 官方api服务
        LLMServerType.OPENAI.value: 'ChatOpenAI',
        LLMServerType.AZURE_OPENAI.value: 'AzureChatOpenAI',
        LLMServerType.QWEN.value: 'ChatTongyi',
        LLMServerType.QIAN_FAN.value: 'QianfanChatEndpoint',
        LLMServerType.ZHIPU.value: 'ChatOpenAI',
        LLMServerType.MINIMAX.value: 'ChatOpenAI',
        LLMServerType.ANTHROPIC.value: 'ChatAnthropic',
        LLMServerType.DEEPSEEK.value: 'ChatOpenAI',
        LLMServerType.SPARK.value: 'ChatOpenAI',
        LLMServerType.TENCENT.value: 'ChatHunyuanOpenai',
        LLMServerType.MOONSHOT.value: 'ChatOpenAI',
        LLMServerType.VOLCENGINE.value: 'ChatHunyuanOpenai',
        LLMServerType.SILICON.value: 'ChatOpenAI'
    }

    # bisheng强相关的业务参数
    model_info: Optional[LLMModel] = Field(default=None)
    server_info: Optional[LLMServer] = Field(default=None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model_id = kwargs.get('model_id')
        self.model_name = kwargs.get('model_name')
        self.streaming = kwargs.get('streaming', True)
        self.temperature = kwargs.get('temperature', 0.3)
        self.top_p = kwargs.get('top_p', 1)
        self.cache = kwargs.get('cache', True)
        self.enable_web_search = kwargs.get('enable_web_search', False)

        # 是否忽略模型是否上线的检查
        ignore_online = kwargs.get('ignore_online', False)

        if not self.model_id:
            raise Exception('没有找到llm模型配置')
        model_info = LLMDao.get_model_by_id(self.model_id)
        if not model_info:
            raise Exception('llm模型配置已被删除，请重新配置模型')
        self.model_name = model_info.model_name
        server_info = LLMDao.get_server_by_id(model_info.server_id)
        if not server_info:
            raise Exception('服务提供方配置已被删除，请重新配置llm模型')
        if model_info.model_type != LLMModelType.LLM.value:
            raise Exception(f'只支持LLM类型的模型，不支持{model_info.model_type}类型的模型')
        if not ignore_online and not model_info.online:
            raise Exception(f'{server_info.name}下的{model_info.model_name}模型已下线，请联系管理员上线对应的模型')
        logger.debug(f'init_bisheng_llm: server_id: {server_info.id}, model_id: {model_info.id}')
        self.model_info = model_info
        self.server_info = server_info

        class_object, class_name = self._get_llm_class(server_info.type)
        params = self._get_llm_params(server_info, model_info)
        class_name2 = self.llm_node_type.get(server_info.type)
        try:
            # TODO merge_check 2
            # 1.2.0
            self.llm = instantiate_llm(class_name, class_object, params)
            # 0527
            # self.llm = instantiate_llm(class_name2, class_object, params)
            logger.debug(f'init_bisheng_llm: server_info.type:{server_info.type} class_object:{class_object} class_name:{class_name} class_name2:{class_name2} params:{params} dir:{self.llm.__dir__()}')
        except Exception as e:
            logger.exception('init bisheng llm error')
            raise Exception(f'初始化llm失败，请检查配置或联系管理员。错误信息：{e}')

    def _get_llm_class(self, server_type: str) -> (BaseLanguageModel, str):
        if server_type not in _llm_node_type:
            raise Exception(f'not support llm type: {server_type}')
        node_type = _llm_node_type[server_type]['client']
        class_object = import_by_type(_type='llms', name=node_type)
        logger.debug(f'get_llm_class: {class_object}')
        return class_object, node_type

    def _get_llm_params(self, server_info: LLMServer, model_info: LLMModel) -> dict:
        server_config = self.get_server_info_config()
        model_config = self.get_model_info_config()
        default_params = self._get_default_params(server_config, model_config)

        params_handler = _llm_node_type[server_info.type]['params_handler']

        model_config['enable_web_search'] = self.get_enable_web_search()
        if server_info.type == LLMServerType.TENCENT.value:
            default_params['extra_body'] = {'enable_enhancement': self.get_enable_web_search()}

        params = params_handler(default_params, server_config, model_config)

        return params

        params = {}
        if server_info.config:
            params.update(server_info.config)
        enable_web_search = self.get_enable_web_search()
        if model_info.config:
            # enable_web_search = model_info.config.get('enable_web_search', False)
            if model_info.config.get('max_tokens'):
                params['max_tokens'] = model_info.config.get('max_tokens')

        params.update({
            'model_name': model_info.model_name,
            'streaming': self.streaming,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'cache': self.cache
        })
        if server_info.type == LLMServerType.OLLAMA.value:
            params['model'] = params.pop('model_name')
            if params.get('max_tokens'):
                params['num_ctx'] = params.pop('max_tokens')
        elif server_info.type == LLMServerType.AZURE_OPENAI.value:
            params['azure_deployment'] = params.pop('model_name')
        elif server_info.type == LLMServerType.QIAN_FAN.value:
            params['model'] = params.pop('model_name')
            params['qianfan_ak'] = params.pop('wenxin_api_key')
            params['qianfan_sk'] = params.pop('wenxin_secret_key')
            if params.get('max_tokens'):
                params['model_kwargs'] = {"max_output_tokens": params.pop('max_tokens')}
        elif server_info.type == LLMServerType.SPARK.value:
            params['openai_api_key'] = f'{params.pop("api_key")}:{params.pop("api_secret")}'
        elif server_info.type in [LLMServerType.XINFERENCE.value, LLMServerType.LLAMACPP.value,
                                  LLMServerType.VLLM.value]:
            params['openai_api_key'] = params.pop('openai_api_key', None) or "EMPTY"
        elif server_info.type == LLMServerType.QWEN.value:
            params['dashscope_api_key'] = params.pop('openai_api_key')
            params.pop('openai_api_base', None)
            params['model_kwargs'] = {
                'enable_search': enable_web_search,
                'search_options': {
                    'forced_search': enable_web_search
                }
            }
            if params.get('max_tokens'):
                params['model_kwargs']['max_tokens'] = params.pop('max_tokens')
        elif server_info.type == LLMServerType.TENCENT.value:
            params['extra_body'] = {'enable_enhancement': enable_web_search}
        elif server_info.type == LLMServerType.MINIMAX.value:
            params['api_key'] = params.pop('openai_api_key', None)
            params.pop('openai_api_base', None)
        return params

    def _get_default_params(self, server_config: dict, model_config: dict) -> dict:
        default_params = {
            'model': self.model_info.model_name,
            'streaming': self.streaming,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'cache': self.cache
        }
        if model_config.get('max_tokens'):
            default_params['max_tokens'] = model_config.get('max_tokens')

        return default_params

    @property
    def _llm_type(self):
        return self.llm._llm_type

    def get_server_info_config(self):
        if self.server_info.config:
            return self.server_info.config
        return {}

    def get_model_info_config(self):
        if self.model_info.config:
            return self.model_info.config
        return {}

    def get_enable_web_search(self):
        # self.get_model_info_config().get('enable_web_search')
        return self.enable_web_search

    def parse_kwargs(self, messages: List[BaseMessage], kwargs: Dict[str, Any]) -> (List[BaseMessage], Dict[str, Any]):
        if self.server_info.type == LLMServerType.MINIMAX.value:
            if self.get_enable_web_search():
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
            if self.get_enable_web_search():
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
            # ChatTongYi 对多模态的入参比较特殊，需要转换以支持
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
            **kwargs: Any,
    ) -> ChatResult:
        try:
            messages, kwargs = self.parse_kwargs(messages, kwargs)
            if self.server_info.type == LLMServerType.MOONSHOT.value:
                ret = self.moonshot_generate(messages, stop, run_manager, **kwargs)
            else:
                ret = self.llm._generate(messages, stop, run_manager, **kwargs)
                if self.server_info.type == LLMServerType.QWEN.value:
                    ret.generations[0].message = self.convert_qwen_result(ret.generations[0].message)
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1, str(e))
            raise e
        return ret

    def moonshot_generate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> ChatResult:
        try:
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
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1, str(e))
            raise e
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
        try:
            messages, kwargs = self.parse_kwargs(messages, kwargs)
            if self.server_info.type == LLMServerType.MOONSHOT.value:
                ret = await self.moonshot_agenerate(messages, stop, run_manager, **kwargs)
            else:
                ret = await self.llm._agenerate(messages, stop, run_manager, **kwargs)
                if self.server_info.type == LLMServerType.QWEN.value:
                    ret.generations[0].message = self.convert_qwen_result(ret.generations[0].message)
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1, str(e))
            # 记录失败状态
            raise e
        return ret

    async def moonshot_agenerate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> ChatResult:
        try:
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
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1, str(e))
            raise e
        return result

    def _update_model_status(self, status: int, remark: str = ''):
        """更新模型状态"""
        # todo 接入到异步任务模块 累计5分钟更新一次
        if self.model_info.status != status:
            self.model_info.status = status
            LLMDao.update_model_status(self.model_id, status, remark)

    def bind_tools(
            self,
            tools: Sequence[Union[Dict[str, Any], Type, Callable, BaseTool]],
            **kwargs: Any,
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        return self.llm.bind_tools(tools, **kwargs)

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
        try:
            for one in self.llm._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
                if self.server_info.type == LLMServerType.QWEN.value:
                    one.message = self.convert_qwen_result(one.message)
                yield one
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1, str(e))
            raise e

    @wrapper_bisheng_model_generator_async
    async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        try:
            async for one in self.llm._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                if self.server_info.type == LLMServerType.QWEN.value:
                    one.message = self.convert_qwen_result(one.message)
                yield one
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1, str(e))
            raise e
