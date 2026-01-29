import functools
import time
from datetime import datetime
from typing import Any, Dict, Optional, Union
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import ChatResult, GenerationChunk, ChatGenerationChunk
from loguru import logger

from bisheng.common.constants.enums.telemetry import StatusEnum, BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.event_data_schema import ModelInvokeEventData
from bisheng.common.services import telemetry_service
from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync
from bisheng.core.logger import trace_id_var
from bisheng.llm.domain.const import LLMModelStatus


async def bisheng_model_limit_check(self: 'BishengBase'):
    now = datetime.now().strftime("%Y-%m-%d")
    if self.server_info.limit_flag:
        # Number of calls checked
        cache_key = f"model_limit:{now}:{self.server_info.id}"
        redis_client = await get_redis_client()
        use_num = await redis_client.aincr(cache_key)
        if use_num > self.server_info.limit:
            raise Exception(f'{self.server_info.name}/{self.model_info.model_name} Quota used up')


def sync_bisheng_model_limit_check(self: 'BishengBase'):
    now = datetime.now().strftime("%Y-%m-%d")
    if self.server_info.limit_flag:
        # Number of calls checked
        cache_key = f"model_limit:{now}:{self.server_info.id}"
        use_num = get_redis_client_sync().incr(cache_key)
        if use_num > self.server_info.limit:
            raise Exception(f'{self.server_info.name}/{self.model_info.model_name} Quota used up')


def get_token_from_usage(token_usage: Dict[str, Any]) -> tuple[int, int, int, int]:
    """
    FROMtoken_usageGet in DictionarytokenUsage
    """
    input_token = token_usage.get('input_tokens', 0) or token_usage.get('prompt_tokens', 0)
    output_token = token_usage.get('output_tokens', 0) or token_usage.get('completion_tokens', 0)
    cache_token = token_usage.get('cached_token', 0) or token_usage.get("prompt_tokens_details", {}).get(
        'cached_tokens', 0) or token_usage.get('input_tokens_details', {}).get('cache_read', 0)
    total_token = token_usage.get('total_tokens', 0)
    return input_token, output_token, cache_token, total_token


def parse_token_usage(result: Any) -> tuple[int, int, int, int]:
    """
    analyzingtokenUsage
    """
    input_token, output_token, cache_token, total_token = 0, 0, 0, 0
    if isinstance(result, ChatResult):
        for generation in result.generations:
            token_usage = generation.generation_info.get('token_usage', {}) or generation.message.response_metadata.get(
                'token_usage', {}) or generation.message.usage_metadata
            tmp1, tmp2, tmp3, tmp4 = get_token_from_usage(token_usage)
            input_token += tmp1
            output_token += tmp2
            cache_token += tmp3
            total_token += tmp4
    elif isinstance(result, ChatGenerationChunk):
        token_usage = result.message.response_metadata.get('token_usage', {}) or result.generation_info.get(
            'token_usage', {}) or result.message.usage_metadata
        input_token, output_token, cache_token, total_token = get_token_from_usage(token_usage)
    else:
        logger.warning(f'unknown result type: {type(result)}')
    return input_token, output_token, cache_token, total_token


class TelemetryCallback(BaseCallbackHandler):
    """
    Telemetry Slider Callbacks
    """

    def __init__(self, start_time: float):
        self.start_time = start_time
        self.first_token_time: Optional[int] = 0

    def on_llm_new_token(
            self,
            token: str,
            *,
            chunk: Optional[Union[GenerationChunk, ChatGenerationChunk]] = None,
            run_id: UUID,
            parent_run_id: Optional[UUID] = None,
            **kwargs: Any,
    ) -> Any:
        if not self.first_token_time:
            self.first_token_time = int((time.time() - self.start_time) * 1000)


def upload_telemetry_log(self: 'BishengBase', start_time: float, end_time: float, first_token_cost_time: int,
                         status: StatusEnum, is_stream: bool = False, result: Any = None):
    """
    Upload Buried Point Log
    """
    try:
        logger.debug("start upload model invoke telemetry log")
        input_token, output_token, cache_token, total_token = 0, 0, 0, 0
        if self.model_info.model_type in ['llm']:
            try:
                input_token, output_token, cache_token, total_token = parse_token_usage(result)
            except Exception as e:
                logger.warning(f"parse token usage failed: {e}")

        telemetry_service.log_event_sync(user_id=self.user_id, event_type=BaseTelemetryTypeEnum.MODEL_INVOKE,
                                         trace_id=trace_id_var.get(),
                                         event_data=ModelInvokeEventData(
                                             model_id=self.model_id,
                                             model_name=self.model_name,
                                             model_type=self.model_info.model_type,
                                             model_server_id=self.server_info.id,
                                             model_server_name=self.server_info.name,

                                             app_id=self.app_id,
                                             app_name=self.app_name,
                                             app_type=self.app_type,

                                             start_time=int(start_time),
                                             end_time=int(end_time),
                                             first_token_cost_time=first_token_cost_time,

                                             status=status,
                                             is_stream=is_stream,
                                             input_token=input_token,
                                             output_token=output_token,
                                             cache_token=cache_token,
                                             total_token=total_token,
                                         ))

        logger.debug("end upload model invoke telemetry log")
    except Exception as e:
        logger.exception(f"upload telemetry log failed")


def wrapper_bisheng_model_limit_check(func):
    """
    Number of calls to check the decorator
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        self = args[0]
        sync_bisheng_model_limit_check(self)
        status = LLMModelStatus.NORMAL.value
        remark = ""
        start_time = time.time()
        result = None
        telemetry_status = StatusEnum.SUCCESS
        telemetry_callback = None
        try:
            if self.model_info.model_type == 'llm':
                telemetry_callback = TelemetryCallback(start_time=start_time)
                if kwargs.get('run_manager') is not None:
                    kwargs['run_manager'].handlers.append(telemetry_callback)
            result = func(*args, **kwargs)

            return result
        except Exception as e:
            status = LLMModelStatus.ERROR.value
            remark = str(e)
            telemetry_status = StatusEnum.FAILED
            raise e
        finally:
            end_time = time.time()
            # Avoid blocking the main thread by uploading logs asynchronously using the thread pool
            first_token_cost_time = telemetry_callback.first_token_time if telemetry_callback else 0
            upload_telemetry_log(self, start_time, end_time, first_token_cost_time, telemetry_status, result=result)
            self.sync_update_model_status(status, remark)

    return wrapper


def wrapper_bisheng_model_limit_check_async(func):
    """
    Number of calls to check the decorator
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        self = args[0]
        await bisheng_model_limit_check(self)
        status = LLMModelStatus.NORMAL.value
        remark = ""
        start_time = time.time()
        telemetry_status = StatusEnum.SUCCESS
        result = None
        telemetry_callback = None
        try:
            if self.model_info.model_type == 'llm':
                telemetry_callback = TelemetryCallback(start_time=start_time)
                if kwargs.get('run_manager') is not None:
                    kwargs['run_manager'].handlers.append(telemetry_callback)
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            status = LLMModelStatus.ERROR.value
            remark = str(e)
            telemetry_status = StatusEnum.FAILED
            raise e
        finally:
            end_time = time.time()
            first_token_cost_time = telemetry_callback.first_token_time if telemetry_callback else 0
            upload_telemetry_log(self, start_time, end_time, first_token_cost_time, telemetry_status, result=result)
            await args[0].update_model_status(status, remark)

    return wrapper


def wrapper_bisheng_model_generator(func):
    """
    Number of calls to check the decorator  Decorative Synchronization Builder Functions
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        self = args[0]
        sync_bisheng_model_limit_check(self)

        status = LLMModelStatus.NORMAL.value
        remark = ""
        start_time = time.time()
        first_token_cost_time = 0
        telemetry_status = StatusEnum.SUCCESS
        item = None
        try:
            for item in func(*args, **kwargs):
                yield item
                if first_token_cost_time == 0:
                    first_token_cost_time = int((time.time() - start_time) * 1000)
        except Exception as e:
            status = LLMModelStatus.ERROR.value
            remark = str(e)
            telemetry_status = StatusEnum.FAILED
            raise e
        finally:
            end_time = time.time()
            upload_telemetry_log(self, start_time, end_time, first_token_cost_time, telemetry_status, True, result=item)
            self.sync_update_model_status(status, remark)

    return wrapper


def wrapper_bisheng_model_generator_async(func):
    """
    Number of calls to check the decorator  Decorative Asynchronous Builder Functions
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        self = args[0]
        await bisheng_model_limit_check(self)
        status = LLMModelStatus.NORMAL.value
        remark = ""
        start_time = time.time()
        first_token_cost_time = 0
        telemetry_status = StatusEnum.SUCCESS
        item = None
        try:
            async for item in func(*args, **kwargs):
                yield item
                if first_token_cost_time == 0:
                    first_token_cost_time = int((time.time() - start_time) * 1000)
        except Exception as e:
            status = LLMModelStatus.ERROR.value
            remark = str(e)
            telemetry_status = StatusEnum.FAILED
            raise e
        finally:
            end_time = time.time()
            upload_telemetry_log(self, start_time, end_time, first_token_cost_time, telemetry_status, True, result=item)
            await self.update_model_status(status, remark)

    return wrapper
