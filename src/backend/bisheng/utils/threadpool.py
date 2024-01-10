import asyncio
import concurrent.futures
import threading
import time
from typing import Dict, List, Tuple

from loguru import logger


class ThreadPoolManager:

    def __init__(self, max_workers, thread_name_prefix='pool'):
        self.thread_group = thread_name_prefix
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=thread_name_prefix)
        # 设计每个同步线程配备一个协程
        self.event_loops = {}
        self.future_dict: Dict[str, List[concurrent.futures.Future]] = {}
        self.async_task: Dict[str, List[asyncio.Task]] = {}
        self.lock = threading.Lock()

    def submit(self, key: str, fn, *args, **kwargs):
        with self.lock:
            if key not in self.future_dict:
                self.future_dict[key] = []
            if key not in self.async_task:
                self.async_task[key] = []
            if asyncio.coroutines.iscoroutinefunction(fn):
                future = self.executor.submit(self.run_in_event_loop, fn, *args, **kwargs)
                self.async_task[key].append(future)
            else:
                future = self.executor.submit(self.context_wrapper, fn, *args, **kwargs)
                self.future_dict[key].append(future)
            return future

    def context_wrapper(self, func, *args, **kwargs):
        trace_id = kwargs.pop('trace_id', '2')
        start_wait = time.time()
        with logger.contextualize(trace_id=trace_id):
            result = func(*args, **kwargs)
            end_wait = time.time()  # Time when the task actually started
            logger.info(
                f'Task_waited={end_wait - start_wait:.2f} seconds and executed={time.time() - end_wait:.2f} seconds',
            )
            return result

    def run_in_event_loop(self, coro, *args, **kwargs):
        try:
            loop = asyncio.get_event_loop()
            logger.info('event loop {}', loop)
        except Exception:
            loop = asyncio.new_event_loop()
            logger.info('Creating new event loop {}', loop)
        asyncio.set_event_loop(loop)
        if loop not in self.event_loops:
            logger.info('create_new_thread_event')
            thread_event = threading.Thread(target=self.start_loop, args=(loop, ))
            thread_event.start()
        trace_id = kwargs.pop('trace_id', '2')
        start_wait = time.time()
        with logger.contextualize(trace_id=trace_id):
            future = asyncio.run_coroutine_threadsafe(coro(*args, **kwargs), loop)
            # result = loop.run_until_complete(coro(*args, **kwargs))
            end_wait = time.time()
            logger.info(f'async_task_waited={end_wait - start_wait:.2f} seconds', )
            return future

    def start_loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    async def as_completed(self) -> List[Tuple[str, concurrent.futures.Future]]:
        with self.lock:
            completed_futures = []
            for k, lf in list(self.future_dict.items()):
                for f in lf:
                    if f.done():
                        completed_futures.append((k, f))
                        self.future_dict[k].remove(f)
                if len(lf) == 0:
                    self.future_dict.pop(k)

            for k, lf in list(self.async_task.items()):
                for f in lf:
                    if f.done():
                        # 获取task
                        task = f.result()
                        if task.done():
                            completed_futures.append((k, task))
                            self.async_task[k].remove(f)
                if len(lf) == 0:
                    self.async_task.pop(k)

            return completed_futures

    # async def async_done_callback(self, future):
    #     self.async_task_result.append(future)


# 创建一个线程池管理器
thread_pool = ThreadPoolManager(5)
