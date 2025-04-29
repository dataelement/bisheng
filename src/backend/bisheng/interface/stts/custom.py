import json
from typing import List, Optional, Any, Sequence, Union, Dict, Type, Callable

from bisheng.database.models.llm_server import LLMDao, LLMModelType, LLMServerType, LLMModel, LLMServer
from bisheng.interface.importing import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm
from bisheng.interface.stts.models.qwen_stt import QwenSTT
from bisheng.interface.utils import wrapper_bisheng_model_limit_check, wrapper_bisheng_model_limit_check_async
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseLanguageModel, BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import Field


class BishengSTT:
    """
         Use the llm model that has been launched in model management
        """

    model_id: int = Field(description="后端服务保存的model唯一ID")
    model_name: Optional[str] = Field(default='', description="后端服务保存的model名称")

    stt_node_type = {
        LLMServerType.QWEN.value: QwenSTT,
    }

    def __init__(self, **kwargs):
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
            raise Exception('stt模型配置已被删除，请重新配置模型')
        self.model_name = model_info.model_name
        server_info = LLMDao.get_server_by_id(model_info.server_id)
        if not server_info:
            raise Exception('服务提供方配置已被删除，请重新配置stt模型')
        if model_info.model_type != LLMModelType.STT.value:
            raise Exception(f'只支持LLM类型的模型，不支持{model_info.model_type}类型的模型')
        if not ignore_online and not model_info.online:
            raise Exception(f'{server_info.name}下的{model_info.model_name}模型已下线，请联系管理员上线对应的模型')
        logger.debug(f'init_bisheng_stt: server_id: {server_info.id}, model_id: {model_info.id}')
        self.model_info = model_info
        self.server_info = server_info

        class_object = self._get_stt_class(server_info.type)
        params = self._get_stt_params(server_info, model_info)
        try:
            self.stt = class_object(**params)
            logger.debug(f'init_bisheng_stt: {self.stt.__dir__()}')
        except Exception as e:
            logger.exception('init bisheng llm error')
            raise Exception(f'初始化llm失败，请检查配置或联系管理员。错误信息：{e}')

    def _get_stt_class(self, server_type: str) -> BaseLanguageModel:
        node_type = self.stt_node_type[server_type]
        return node_type

    def _get_stt_params(self, server_info: LLMServer, model_info: LLMModel):
        params = {}
        if server_info.config:
            params.update(server_info.config)
        if server_info.type == LLMServerType.QWEN.value:
            params["api_key"] = params.pop("openai_api_key")
            params["model"] = model_info.model_name
        return params

    def transcribe(self,file_url):
        try:
            ret = self.stt.transcribe(file_url)
            self._update_model_status(0)
        except Exception as e:
            self._update_model_status(1,str(e))
            raise e
        return ret

    def _update_model_status(self, status: int, remark: str = ''):
        """更新模型状态"""
        # todo 接入到异步任务模块
        LLMDao.update_model_status(self.model_id, status, remark)
