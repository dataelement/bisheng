import asyncio
import concurrent.futures
import threading
import time
from typing import Dict, List, Set, Tuple

from loguru import logger

from bisheng.utils.async_thread import AsyncTaskRunner


class ThreadPoolManager:

    def __init__(self, max_workers, thread_name_prefix='pool'):
        self.thread_group = thread_name_prefix
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=thread_name_prefix)
        self.async_executor = AsyncTaskRunner()
        # 设计每个同步线程配备一个协程
        self.future_dict: Dict[str, List[concurrent.futures.Future]] = {}
        self.async_task: Dict[str, List[concurrent.futures.Future]] = {}
        self.lock = threading.Lock()

    def submit(self, key: str, fn, *args, **kwargs):
        with self.lock:
            if key not in self.future_dict:
                self.future_dict[key] = []
            if key not in self.async_task:
                self.async_task[key] = []
            if asyncio.coroutines.iscoroutinefunction(fn):
                future = asyncio.create_task(self.acontext_wrapper(fn, *args, **kwargs))
                # future = self.async_executor.submit(self.acontext_wrapper(fn, *args, **kwargs))
                self.async_task[key].append(future)
            else:
                future = self.executor.submit(self.context_wrapper, fn, *args, **kwargs)
                self.future_dict[key].append(future)
            return future

    async def acontext_wrapper(self, func, *args, **kwargs):
        trace_id = kwargs.pop('trace_id', '2')
        start_wait = time.time()
        with logger.contextualize(trace_id=trace_id):
            result = await func(*args, **kwargs)
            end_wait = time.time()  # Time when the task actually started
            logger.info(
                f'aTask_waited={end_wait - start_wait:.2f} seconds and {func.__name__} executed={time.time() - end_wait:.2f} seconds',
            )
            return result

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

    async def as_completed(self,
                           key_list: Set[str]) -> List[Tuple[str, concurrent.futures.Future]]:
        with self.lock:
            completed_futures = []
            for k, lf in list(self.future_dict.items()):
                for f in lf:
                    if f.done():
                        if k in key_list:
                            completed_futures.append((k, f))
                            self.future_dict[k].remove(f)
                if len(lf) == 0:
                    self.future_dict.pop(k)

            pending_count = 0
            for k, lf in list(self.async_task.items()):
                for f in lf:
                    if f.done():
                        # 获取task
                        if k in key_list:
                            completed_futures.append((k, f))
                            self.async_task[k].remove(f)
                    else:
                        pending_count += 1
                if len(lf) == 0:
                    self.async_task.pop(k)
            if pending_count > 0:
                logger.info('async_wait_count={}', pending_count)
            return completed_futures

    # async def async_done_callback(self, future):
    #     self.async_task_result.append(future)

    def cancel_task(self, key_list: List[str]):
        res = [False] * len(key_list)
        with self.lock:
            for index, key in enumerate(key_list):
                if self.async_task.get(key):
                    for task in self.async_task.get(key):
                        cancel_res = task.cancel()
                        logger.info('clean_pending_task key={} task={} res={}', key, task,
                                    cancel_res)
                        res[index] = cancel_res
                if self.future_dict.get(key):
                    for task in self.future_dict.get(key):
                        res.append(task.cancel())
            return res

    def tear_down(self):
        key_list = list(self.async_task.keys())
        self.cancel_task(key_list)
        self.executor.shutdown(cancel_futures=True)
        self.async_executor.shutdown()


# 创建一个线程池管理器
thread_pool = ThreadPoolManager(5)

if __name__ == '__main__':
    def wait_(name: str):
        logger.info('{} enter wait {}', threading.current_thread(), name)
        time.sleep(10)
        logger.info('{} done {}', threading.current_thread(), name)


    async def await_(name: str = 1):
        logger.info('{} enter wait {}', threading.current_thread(), name)
        await asyncio.sleep(10)
        logger.info('{} done {}', threading.current_thread(), name)


    thread_pool.submit('ABB', wait_, 'NO.1')
    thread_pool.submit('AAA', await_)
    # time.sleep(3)
    # thread_pool.submit("AA", wait_, "~~~~~~~~~~~~")
    # thread_pool.submit("AA", await_, "NO.3")
    # time.sleep(2)
    # thread_pool.tear_down(["AAA"])
