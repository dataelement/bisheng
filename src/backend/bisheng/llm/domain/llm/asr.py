from typing import BinaryIO, Self, Union

import httpx
from pydantic import Field

from bisheng.common.errcode.server import (
    AsrModelConfigDeletedError,
    AsrModelOfflineError,
    AsrModelTypeError,
    AsrProviderDeletedError,
    NoAsrModelConfigError,
)
from bisheng.core.ai import AliyunASRClient, AzureOpenAIASRClient, BaseASRClient, OpenAIASRClient
from bisheng.core.ai.asr.realtime import RealtimeASRClient, realtime_protocol
from bisheng.core.ai.asr.speech_cloud import BaiduRealtimeASRClient, TencentRealtimeASRClient
from bisheng.core.ai.asr.volcengine import VolcengineRealtimeASRClient
from bisheng.llm.domain.const import LLMModelType, LLMServerType
from bisheng.llm.domain.models import LLMModel, LLMServer

from ..utils import usable_proxy_url, wrapper_bisheng_model_limit_check_async
from .base import BishengBase


async def _get_openai_params(params: dict, server_info: LLMServer, model_info: LLMModel) -> dict:
    new_params = {
        "api_key": params.get("openai_api_key"),
        "model": model_info.model_name,
    }
    if params.get("openai_api_base"):
        new_params["base_url"] = params["openai_api_base"]
    proxy = usable_proxy_url(params.get("openai_proxy"))
    if proxy:
        new_params["http_client"] = httpx.AsyncClient(proxy=proxy)
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
    LLMServerType.OPENAI.value: {"client": OpenAIASRClient, "params_handler": _get_openai_params},
    LLMServerType.AZURE_OPENAI.value: {"client": AzureOpenAIASRClient, "params_handler": _get_azure_openai_params},
    LLMServerType.QWEN.value: {"client": AliyunASRClient, "params_handler": _get_qwen_params},
}


_streaming_client_type = {
    "volcengine": VolcengineRealtimeASRClient,
    "qianfan": BaiduRealtimeASRClient,
    "tencent": TencentRealtimeASRClient,
}


def is_asr_provider_supported(server_type: str) -> bool:
    return server_type in _asr_client_type or server_type in _streaming_client_type


class BishengASR(BishengBase):
    asr: BaseASRClient = Field(..., description="asrInstances")

    @classmethod
    async def get_bisheng_asr(cls, **kwargs) -> Self:
        model_id = kwargs.pop("model_id", 0)
        if not model_id:
            raise NoAsrModelConfigError()
        model_info, server_info = await cls.get_model_server_info(model_id)
        # ignore_onlineParameters are used to skip model presence checks
        ignore_online = kwargs.pop("ignore_online", False)

        if not model_info:
            raise AsrModelConfigDeletedError()
        if not LLMModelType.is_speech(model_info.model_type):
            raise AsrModelTypeError(model_type=model_info.model_type)
        if not server_info:
            raise AsrProviderDeletedError()
        if not ignore_online and not model_info.online:
            raise AsrModelOfflineError(server_name=server_info.name, model_name=model_info.model_name)

        # InisialisasiasrClient
        asr_client = await cls.init_asr_client(model_info=model_info, server_info=server_info)

        return cls(model_id=model_id, asr=asr_client, model_info=model_info, server_info=server_info, **kwargs)

    @classmethod
    async def init_asr_client(cls, model_info: LLMModel, server_info: LLMServer) -> BaseASRClient:
        if model_info.model_type == LLMModelType.ASR_RT.value:
            return cls._realtime_client(model_info, server_info)
        if model_info.model_type == LLMModelType.ASR.value:
            return await cls._file_client(model_info, server_info)
        raise AsrModelTypeError(model_type=model_info.model_type)

    @classmethod
    def _merged_asr_params(cls, model_info: LLMModel, server_info: LLMServer) -> dict:
        params = {}
        if server_info.config:
            params.update(server_info.config)
        if model_info.config:
            params.update(model_info.config)
        return params

    @classmethod
    def _realtime_client(cls, model_info: LLMModel, server_info: LLMServer) -> BaseASRClient:
        model_name = str(model_info.model_name or "").strip()
        if not model_name:
            raise ValueError("ASR model name is required")
        params = cls._merged_asr_params(model_info, server_info)
        client_cls = _streaming_client_type.get(server_info.type)
        if client_cls:
            return client_cls(model=model_name, config=params)
        if server_info.type == LLMServerType.QWEN.value:
            if not realtime_protocol(server_info.type, model_name):
                raise ValueError("This realtime ASR model has no registered protocol adapter")
            return RealtimeASRClient(
                api_key=params.get("openai_api_key") or params.get("api_key"),
                model=model_name,
                base_url=params.get("openai_api_base", ""),
            )
        raise ValueError(f"This provider has no realtime ASR client: {server_info.type}")

    @classmethod
    async def _file_client(cls, model_info: LLMModel, server_info: LLMServer) -> BaseASRClient:
        if server_info.type in _streaming_client_type or server_info.type not in _asr_client_type:
            raise ValueError(f"This provider has no file ASR client: {server_info.type}")
        params = cls._merged_asr_params(model_info, server_info)
        params_handler = _asr_client_type[server_info.type]["params_handler"]
        new_params = await params_handler(params, server_info, model_info)
        return _asr_client_type[server_info.type]["client"](**new_params)

    @wrapper_bisheng_model_limit_check_async
    async def ainvoke(self, audio: Union[str, bytes, BinaryIO], **kwargs) -> str:
        return await self.asr.transcribe(audio=audio, **kwargs)

    @wrapper_bisheng_model_limit_check_async
    async def astream(self, audio, on_ready, on_event):
        if not isinstance(self.asr, RealtimeASRClient):
            raise ValueError("The configured ASR model supports file recognition")
        await self.asr.stream(audio, on_ready, on_event)
