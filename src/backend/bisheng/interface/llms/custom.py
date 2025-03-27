import json
from typing import List, Optional, Any, Sequence, Union, Dict, Type, Callable

from bisheng.database.models.llm_server import LLMDao, LLMModelType, LLMServerType, LLMModel, LLMServer
from bisheng.interface.importing import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm
from bisheng.interface.utils import wrapper_bisheng_model_limit_check, wrapper_bisheng_model_limit_check_async
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseLanguageModel, BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import Field


class BishengLLM(BaseChatModel):
    """
     Use the llm model that has been launched in model management
    """

    model_id: int = Field(description="后端服务保存的model唯一ID")
    model_name: Optional[str] = Field(default='', description="后端服务保存的model名称")
    streaming: bool = Field(default=True, description="是否使用流式输出", alias="stream")
    temperature: float = Field(default=0.3, description="模型生成的温度")
    top_p: float = Field(default=1, description="模型生成的top_p")
    cache: bool = Field(default=True, description="是否使用缓存")

    llm: Optional[BaseChatModel] = Field(default=None)
    llm_node_type = {
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
        LLMServerType.VOLCENGINE.value: 'ChatHunyuanOpenai'
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

        class_object = self._get_llm_class(server_info.type)
        params = self._get_llm_params(server_info, model_info)
        try:
            self.llm = instantiate_llm(self.llm_node_type.get(server_info.type), class_object, params)
            logger.debug(f'init_bisheng_llm: {self.llm.__dir__()}')
        except Exception as e:
            logger.exception('init bisheng llm error')
            raise Exception(f'初始化llm失败，请检查配置或联系管理员。错误信息：{e}')

    def _get_llm_class(self, server_type: str) -> BaseLanguageModel:
        node_type = self.llm_node_type[server_type]
        class_object = import_by_type(_type='llms', name=node_type)
        logger.debug(f'get_llm_class: {class_object}')
        return class_object

    def _get_llm_params(self, server_info: LLMServer, model_info: LLMModel) -> dict:
        params = {}
        if server_info.config:
            params.update(server_info.config)
        enable_web_search = False
        if model_info.config:
            enable_web_search = model_info.config.get('enable_web_search', False)
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
            params['model_kwargs'] = {'enable_search': enable_web_search}
            if params.get('max_tokens'):
                params['model_kwargs']['max_tokens'] = params.pop('max_tokens')
        elif server_info.type == LLMServerType.TENCENT.value:
            params['extra_body'] = {'enable_enhancement': enable_web_search}
        return params

    @property
    def _llm_type(self):
        return self.llm._llm_type

    def get_model_info_config(self):
        if self.model_info.config:
            return self.model_info.config
        return {}

    def parse_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
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
        return kwargs

    @wrapper_bisheng_model_limit_check
    def _generate(
            self,
            messages: List[BaseMessage],
            stop: Optional[List[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: Any,
    ) -> ChatResult:
        try:
            kwargs = self.parse_kwargs(kwargs)
            if self.server_info.type == LLMServerType.MOONSHOT.value:
                ret = self.moonshot_generate(messages, stop, run_manager, **kwargs)
            else:
                ret = self.llm._generate(messages, stop, run_manager, **kwargs)
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
            kwargs = self.parse_kwargs(kwargs)
            if self.server_info.type == LLMServerType.MOONSHOT.value:
                ret = await self.moonshot_agenerate(messages, stop, run_manager, **kwargs)
            else:
                ret = await self.llm._agenerate(messages, stop, run_manager, **kwargs)
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
        # todo 接入到异步任务模块
        LLMDao.update_model_status(self.model_id, status, remark)

    def bind_tools(
            self,
            tools: Sequence[Union[Dict[str, Any], Type, Callable, BaseTool]],
            **kwargs: Any,
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        return self.llm.bind_tools(tools, **kwargs)
