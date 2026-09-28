"""异步流程发布同步消息时使用的线程边界。"""

import asyncio
from collections.abc import Callable
from typing import Any


async def run_sync_dispatch(publish: Callable[..., Any], *args, **kwargs) -> Any:
    """等待发布结果并透传异常；取消时不会声称 Broker 已停止发布。"""
    return await asyncio.to_thread(publish, *args, **kwargs)
