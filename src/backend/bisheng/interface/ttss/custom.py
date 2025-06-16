import io
import json
import time
from typing import List, Optional, Any, Sequence, Union, Dict, Type, Callable
from bisheng.api.utils import md5_hash, tts_text_md5_hash, format_text_for_tts
from bisheng.api.services.tts_cache import TTSCacheService
from bisheng.cache.utils import save_uploaded_file
from bisheng.database.models.llm_server import LLMDao, LLMModelType, LLMServerType, LLMModel, LLMServer
from bisheng.interface.importing import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm
from bisheng.interface.ttss.models.qwen_tts import QwenTTS
from bisheng.interface.utils import wrapper_bisheng_model_limit_check, wrapper_bisheng_model_limit_check_async
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseLanguageModel, BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import Field


class BishengTTS:
    model_id: int = Field(description="后端服务保存的model唯一ID")
    model_name: Optional[str] = Field(default='', description="后端服务保存的model名称")

    tts_node_type = {
        LLMServerType.QWEN.value: QwenTTS,
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
            raise Exception('tts模型配置已被删除，请重新配置模型')
        self.model_name = model_info.model_name
        server_info = LLMDao.get_server_by_id(model_info.server_id)
        if not server_info:
            raise Exception('服务提供方配置已被删除，请重新配置tts模型')
        if model_info.model_type != LLMModelType.TTS.value:
            raise Exception(f'只支持{LLMModelType.TTS.value}类型的模型，不支持{model_info.model_type}类型的模型')
        if not ignore_online and not model_info.online:
            raise Exception(f'{server_info.name}下的{model_info.model_name}模型已下线，请联系管理员上线对应的模型')
        logger.debug(f'init_bisheng_tts: server_id: {server_info.id}, model_id: {model_info.id}')
        self.model_info = model_info
        self.server_info = server_info

        class_object = self._get_tts_class(server_info.type)
        params = self._get_tts_params(server_info, model_info)
        try:
            self.tts = class_object(**params)
            logger.debug(f'init_bisheng_tts: {self.tts.__dir__()}')
        except Exception as e:
            logger.exception('init bisheng tts error')
            raise Exception(f'初始化tts失败，请检查配置或联系管理员。错误信息：{e}')

    def synthesize(self,text):
        try:
            text = format_text_for_tts(text)
            audio = self.tts.synthesize(text)
            self._update_model_status(0)
            return audio
        except Exception as e:
            self._update_model_status(1, str(e))
            raise e

    def synthesize_and_save(self, text, out_file=None):
        try:
            text = format_text_for_tts(text)
            audio = self.tts.synthesize(text)
            # 将音频保存至本地
            if out_file:
                with open(out_file, 'wb') as f:
                    f.write(audio)
            self._update_model_status(0)
            return audio
        except Exception as e:
            self._update_model_status(1, str(e))
            raise e

    def synthesize_and_upload(self, text,cache=True):
        try:
            text = format_text_for_tts(text)
            text_md5 = md5_hash(text)
            if cache:
                tts_cache = TTSCacheService.get_cache(md5=text_md5,model_id=self.model_id,after_time=self.model_info.update_time)
                if tts_cache:
                    return tts_cache.voice_url
            audio = self.tts.synthesize(text)
            file_name = f"{time.time()}.mp3"
            url = save_uploaded_file(io.BytesIO(audio), 'bisheng', file_name)
            if cache:
                TTSCacheService.create_cache(text=text, md5=text_md5, model_id=self.model_id,voice_url=url)
            self._update_model_status(0)
            return url
        except Exception as e:
            self._update_model_status(1, str(e))
            raise e


    def _get_tts_class(self, server_type: str) -> BaseLanguageModel:
        node_type = self.tts_node_type[server_type]
        return node_type

    def _get_tts_params(self, server_info: LLMServer, model_info: LLMModel):
        params = {}
        if server_info.config:
            params.update(server_info.config)
        if server_info.type == LLMServerType.QWEN.value:
            params["api_key"] = params.pop("openai_api_key")
            params["voice"] = model_info.config.get("voice")
            params["model"] = model_info.model_name
        return params

    def _update_model_status(self, status: int, remark: str = ''):
        """更新模型状态"""
        # todo 接入到异步任务模块
        LLMDao.update_model_status(self.model_id, status, remark)

CUSTOM_TTS = {
    'BishengTTS': BishengTTS,
}