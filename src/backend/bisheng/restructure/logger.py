# log工具
from functools import wraps
from uuid import uuid4

from bisheng.utils.logger import logger


def log_trace(func):
    """添加trace_id用于log追踪"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        trace_id = uuid4().hex
        with logger.contextualize(trace_id=trace_id):
            return await func(*args, **kwargs)

    return wrapper
