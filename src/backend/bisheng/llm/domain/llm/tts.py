import httpx
from pydantic import Field
from typing_extensions import Self

from bisheng.common.errcode.server import NoTtsModelConfigError, TtsModelConfigDeletedError, \
    TtsModelTypeError, TtsProviderDeletedError, TtsModelOfflineError
from bisheng.core.ai import BaseTTSClient, OpenAITTSClient, \
    AliyunTTSClient, AzureOpenAITTSClient
from bisheng.llm.const import LLMModelType, LLMServerType
from bisheng.llm.domain.models import LLMServer, LLMModel
from .base import BishengBase
from ..utils import wrapper_bisheng_model_limit_check_async


async def _get_openai_params(params: dict, server_info: LLMServer, model_info: LLMModel) -> dict:
    new_params = {
        "api_key": params.get("openai_api_key"),
        "model": model_info.model_name,
        "base_url": params.get("openai_base_url"),
    }
    if params.get("openai_api_base"):
        new_params["base_url"] = params["openai_api_base"]
    if params.get("voice"):
        new_params["voice"] = params["voice"]
    if params.get("openai_proxy"):
        new_params["http_client"] = httpx.AsyncClient(proxy=params["openai_proxy"])
    return new_params


async def _get_azure_openai_params(params: dict, server_info: LLMServer, model_info: LLMModel) -> dict:
    new_params = {
        "api_key": params.get("openai_api_key"),
        "api_version": params.get("openai_api_version"),
        "azure_endpoint": params.get("azure_endpoint"),
        "model": model_info.model_name,
    }
    if params.get("voice"):
        new_params["voice"] = params["voice"]
    return new_params


async def _get_qwen_params(params: dict, server_info: LLMServer, model_info: LLMModel) -> dict:
    new_params = {
        "api_key": params.get("openai_api_key") or params.get("api_key"),
        "model": model_info.model_name,
    }
    if params.get("voice"):
        new_params["voice"] = params["voice"]
    return new_params


_tts_client_type = {
    LLMServerType.OPENAI.value: {
        "client": OpenAITTSClient,
        "params_handler": _get_openai_params
    },
    LLMServerType.AZURE_OPENAI.value: {
        "client": AzureOpenAITTSClient,
        "params_handler": _get_azure_openai_params
    },
    LLMServerType.QWEN.value: {
        "client": AliyunTTSClient,
        "params_handler": _get_qwen_params
    }
}


class BishengTTS(BishengBase):
    tts: BaseTTSClient = Field(..., description="tts实例")

    @classmethod
    async def get_bisheng_tts(cls, **kwargs) -> Self:
        model_id = kwargs.get('model_id')
        if not model_id:
            raise NoTtsModelConfigError()
        model_info, server_info = await cls.get_model_server_info(model_id)
        # ignore_online参数用于跳过模型在线状态检查
        ignore_online = kwargs.get('ignore_online', False)

        if not model_info:
            raise TtsModelConfigDeletedError()
        if model_info.model_type != LLMModelType.TTS.value:
            raise TtsModelTypeError(model_type=model_info.model_type)
        if not server_info:
            raise TtsProviderDeletedError()
        if not ignore_online and not model_info.online:
            raise TtsModelOfflineError(server_name=server_info.name, model_name=model_info.model_name)

        # 初始化tts客户端
        tts_client = await cls.init_tts_client(model_info=model_info, server_info=server_info)

        return cls(model_id=model_id, tts=tts_client, model_info=model_info, server_info=server_info)

    @classmethod
    async def init_tts_client(cls, model_info: LLMModel, server_info: LLMServer) -> BaseTTSClient:
        params = {}
        if server_info.config:
            if server_info.config:
                params.update(server_info.config)
            if model_info.config:
                params.update(model_info.config)
        if server_info.type not in _tts_client_type:
            raise Exception(f'Tts模型不支持{server_info.type}类型的服务提供方')
        params_handler = _tts_client_type[server_info.type]['params_handler']
        new_params = await params_handler(params, server_info, model_info)
        client = _tts_client_type[server_info.type]['client'](**new_params)
        return client

    @wrapper_bisheng_model_limit_check_async
    async def ainvoke(self, text: str, **kwargs) -> bytes:
        return await self.tts.synthesize(text, **kwargs)
