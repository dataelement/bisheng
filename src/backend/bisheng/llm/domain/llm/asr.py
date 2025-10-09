from typing import Union, BinaryIO

import httpx
from pydantic import Field
from typing_extensions import Self

from bisheng.api.errcode.server import NoAsrModelConfigError, AsrModelConfigDeletedError, AsrModelTypeError, \
    AsrProviderDeletedError, \
    AsrModelOfflineError
from bisheng.core.ai import BaseASRClient, OpenAIASRClient, AliyunASRClient, AzureOpenAIASRClient
from bisheng.database.models.llm_server import LLMModel, LLMServer, LLMDao, LLMModelType, LLMServerType
from .base import BishengBase
from ..utils import wrapper_bisheng_model_limit_check_async


async def _get_openai_params(params: dict, server_info: LLMServer, model_info: LLMModel) -> dict:
    new_params = {
        "api_key": params.get("openai_api_key"),
        "model": model_info.model_name,
    }
    if params.get("openai_api_base"):
        new_params["base_url"] = params["openai_api_base"]
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
    return new_params


async def _get_qwen_params(params: dict, server_info: LLMServer, model_info: LLMModel) -> dict:
    new_params = {
        "api_key": params.get("openai_api_key") or params.get("api_key"),
        "model": model_info.model_name,
    }
    return new_params


_asr_client_type = {
    LLMServerType.OPENAI.value: {
        "client": OpenAIASRClient,
        "params_handler": _get_openai_params
    },
    LLMServerType.AZURE_OPENAI.value: {
        "client": AzureOpenAIASRClient,
        "params_handler": _get_azure_openai_params
    },
    LLMServerType.QWEN.value: {
        "client": AliyunASRClient,
        "params_handler": _get_qwen_params
    }
}


class BishengASR(BishengBase):
    asr: BaseASRClient = Field(..., description="asr实例")

    @classmethod
    async def get_bisheng_asr(cls, **kwargs) -> Self:
        model_id = kwargs.get('model_id')
        if not model_id:
            raise NoAsrModelConfigError()
        # ignore_online参数用于跳过模型在线状态检查
        ignore_online = kwargs.get('ignore_online', False)

        model_info = await LLMDao.aget_model_by_id(model_id=model_id)
        if not model_info:
            raise AsrModelConfigDeletedError()
        if model_info.model_type != LLMModelType.ASR.value:
            raise AsrModelTypeError(model_type=model_info.model_type)
        server_info = await LLMDao.aget_server_by_id(server_id=model_info.server_id)
        if not server_info:
            raise AsrProviderDeletedError()
        if not ignore_online and not model_info.online:
            raise AsrModelOfflineError(server_name=server_info.name, model_name=model_info.model_name)

        # 初始化asr客户端
        asr_client = await cls.init_asr_client(model_info=model_info, server_info=server_info)

        return cls(model_id=model_id, asr=asr_client, model_info=model_info, server_info=server_info)

    @classmethod
    async def init_asr_client(cls, model_info: LLMModel, server_info: LLMServer) -> BaseASRClient:
        params = {}
        if server_info.config:
            if server_info.config:
                params.update(server_info.config)
            if model_info.config:
                params.update(model_info.config)
        if server_info.type not in _asr_client_type:
            raise Exception(f'asr模型不支持{server_info.type}类型的服务提供方')
        params_handler = _asr_client_type[server_info.type]['params_handler']
        new_params = await params_handler(params, server_info, model_info)
        client = _asr_client_type[server_info.type]['client'](**new_params)
        return client

    @wrapper_bisheng_model_limit_check_async
    async def ainvoke(self, audio: Union[str, bytes, BinaryIO], **kwargs) -> str:
        return await self.asr.transcribe(audio=audio, **kwargs)
