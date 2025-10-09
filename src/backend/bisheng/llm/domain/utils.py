import functools
from datetime import datetime

from bisheng.cache.redis import redis_client
from bisheng.database.models.llm_server import LLMModelStatus


async def bisheng_model_limit_check(self: 'BishengBase'):
    now = datetime.now().strftime("%Y-%m-%d")
    if self.server_info.limit_flag:
        # 开启了调用次数检查
        cache_key = f"model_limit:{now}:{self.server_info.id}"
        use_num = await redis_client.aincr(cache_key)
        if use_num > self.server_info.limit:
            raise Exception(f'{self.server_info.name}/{self.model_info.model_name} 额度已用完')


def wrapper_bisheng_model_limit_check_async(func):
    """
    调用次数检查的装饰器
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        self = args[0]
        await bisheng_model_limit_check(self)
        status = LLMModelStatus.NORMAL.value
        remark = ""
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            status = LLMModelStatus.ERROR.value
            remark = str(e)
            raise e
        finally:
            await args[0].update_model_status(status, remark)

    return wrapper
