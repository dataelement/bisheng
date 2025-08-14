# 重试装饰器 异步
import asyncio
import time
from logging import getLogger

logger = getLogger(__name__)


def retry_async(num_retries=3, delay=0.5, return_exceptions=False):
    def wrapper(func):
        async def wrapped(*args, **kwargs):
            for i in range(num_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.info(
                        f"Retrying {func.__name__} in {delay} seconds... Attempt {i + 1} of {num_retries}... error: {e}")
                    if i == num_retries - 1:
                        if return_exceptions:
                            # 返回异常的参数 将e.args拆分成元组
                            return e.args if len(e.args) > 1 else e.args[0]
                        logger.error(f"Failed to execute {func.__name__} after {num_retries} retries")
                        raise e
                    await asyncio.sleep(delay)
            return None

        return wrapped

    return wrapper


# 重试装饰器
def retry_sync(num_retries=3, delay=0.5, return_exceptions=False):
    def wrapper(func):
        def wrapped(*args, **kwargs):
            for i in range(num_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.info(
                        f"Retrying {func.__name__} in {delay} seconds... Attempt {i + 1} of {num_retries}... error: {e}")
                    if i == num_retries - 1:
                        if return_exceptions:
                            # 返回异常的参数 将e.args拆分成元组
                            return e.args if len(e.args) > 1 else e.args[0]
                        logger.error(f"Failed to execute {func.__name__} after {num_retries} retries")
                        raise e
                    time.sleep(delay)
            return None

        return wrapped

    return wrapper
