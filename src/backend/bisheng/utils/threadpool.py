import asyncio
import concurrent.futures
import threading
from typing import List

from loguru import logger


class ThreadPoolManager:

    def __init__(self, max_workers):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.futures: List[concurrent.futures.Future] = []
        self.lock = threading.Lock()

    def submit(self, fn, *args, **kwargs):
        with self.lock:
            if asyncio.coroutines.iscoroutinefunction(fn):
                future = self.executor.submit(self.run_in_event_loop, fn, *args, **kwargs)
            else:
                future = self.executor.submit(fn, *args, **kwargs)

            self.futures.append(future)
            return future

    def run_in_event_loop(self, coro, *args, **kwargs):
        try:
            loop = asyncio.get_event_loop()
        except Exception:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro(*args, **kwargs))

    def as_completed(self) -> List[concurrent.futures.Future]:
        with self.lock:
            completed_futures = [f for f in self.futures if f.done()]
            for f in completed_futures:
                self.futures.remove(f)
            if self.futures:
                logger.info(f'thread_pool pool_size={len(self.futures)}')
            return completed_futures


# 创建一个线程池管理器
thread_pool = ThreadPoolManager(5)
