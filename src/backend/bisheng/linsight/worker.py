import argparse
import asyncio
import logging

from multiprocessing import Process, Manager, set_start_method
from multiprocessing.managers import ValueProxy
from typing import Optional, Union
from bisheng.cache.redis import RedisClient, redis_client
from bisheng.linsight.task_exec import LinsightWorkflowTask
from bisheng.settings import settings
from bisheng.utils.logger import configure

logger = logging.getLogger(__name__)


# LinsightQueue 队列
class LinsightQueue(object):
    def __init__(self, name, namespace, redis):
        self.__db: RedisClient = redis
        self.key = '%s:%s' % (namespace, name)

    async def qsize(self):
        return await self.__db.allen(self.key)  # 返回队列里面list内元素的数量

    async def put(self, data, timeout=None):
        await self.__db.arpush(self.key, data, expiration=timeout)  # 添加新元素到队列最右方

    async def get_wait(self, timeout=None):
        # 返回队列第一个元素，如果为空则等待至有元素被加入队列（超时时间阈值为timeout，如果为None则一直等待）
        item = await self.__db.ablpop(self.key, timeout=timeout)
        return item

    async def get_nowait(self):
        # 直接返回队列第一个元素，如果队列为空返回的是None
        item = await self.__db.alpop(self.key)
        return item

    # 获取某个任务数据在队列中的位置
    async def index(self, data):
        """
        获取某个任务数据在队列中的位置
        :param data: 任务数据
        :return: 任务数据在队列中的位置，-1表示不在队列中
        """
        items = await self.__db.alrange(self.key)
        try:
            index = items.index(data)
            return index + 1  # 返回索引从1开始
        except ValueError:
            return 0

    # 删除某个任务数据
    async def remove(self, data):
        """
        删除某个任务数据
        :param data: 任务数据
        :return: None
        """
        await self.__db.alrem(self.key, data)  # 从队列中删除指定数据


class ScheduleCenterProcess(Process):
    def __init__(self, max_concurrency: ValueProxy = None):
        """
        调度中心进程，负责从 Redis 队列中获取任务并执行
        :param max_concurrency:
        """
        super().__init__()
        self.daemon = True
        self.queue: Optional[LinsightQueue] = None
        # 信号量
        self.semaphore: Optional[asyncio.Semaphore] = None
        self.max_concurrency: Optional[Union[int, ValueProxy]] = max_concurrency

    def handle_task_result(self, task: asyncio.Task):
        try:
            result = task.result()  # 如果有异常，这里会抛出
        except Exception as e:
            logger.error(f"Task failed with exception: {e}")
        finally:
            # 释放信号量
            if self.semaphore:
                logger.info("Releasing semaphore after task completion.")
                self.semaphore.release()

    async def async_run(self):
        """
        异步运行方法，监听 Redis 队列并执行任务
        :return:
        """
        logger.info("ScheduleCenterProcess started...")
        while True:
            await self.semaphore.acquire()  # 获取信号量，限制并发数
            try:
                session_version_id = await self.queue.get_wait()
                if session_version_id is None:
                    logger.info("No session_version_id found in queue, waiting...")
                    self.semaphore.release()
                    continue
                exec_task = LinsightWorkflowTask()

                logger.info(f"Processing session_version_id: {session_version_id}")

                task = asyncio.create_task(
                    exec_task.async_run(session_version_id)
                )

                task.add_done_callback(self.handle_task_result)  # 添加回调处理任务结果

            except Exception as e:
                logger.error(f"Error in ScheduleCenterProcess: {e}")
                if self.semaphore:
                    if self.semaphore._value < self.max_concurrency:
                        logger.info("Releasing semaphore due to error.")
                        self.semaphore.release()
                continue

    def run(self):
        """
        运行进程
        :return:
        """

        configure(settings.logger_conf)

        if self.max_concurrency is not None:
            self.max_concurrency = self.max_concurrency.value  # 获取 ValueProxy 的实际值
        else:
            self.max_concurrency = 32
            logger.warning("No max_concurrency provided, using default value of 32.")

        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        logger.info(f"Semaphore initialized with max concurrency: {self.semaphore._value}")

        self.queue = LinsightQueue('queue', namespace="linsight", redis=redis_client)
        for _ in range(10000):
            try:
                asyncio.run(self.async_run())
            except Exception as e:
                logger.error(f"Error in ScheduleCenterProcess run method: {e}")


def start_schedule_center_process(worker_num: int = 4, max_concurrency: ValueProxy = None):
    """
    启动调度中心进程
    :param max_concurrency:
    :param worker_num: 启动的工作进程数量
    :return:
    """
    logger.info(f"Starting {worker_num} ScheduleCenterProcess workers...")
    if worker_num <= 0:
        logger.error("worker_num must be greater than 0")
        return
    processes = []
    for _ in range(worker_num):
        process = ScheduleCenterProcess(max_concurrency)
        process.start()
        logger.info(f"Started ScheduleCenterProcess with PID: {process.pid}")
        processes.append(process)

    logger.info(f"Started {len(processes)} ScheduleCenterProcess workers successfully.")
    return processes


if __name__ == '__main__':

    set_start_method("spawn", force=True)  # 确保使用 spawn 方法启动新进程

    parser = argparse.ArgumentParser()
    parser.add_argument('--worker_num', type=int, default=4, help='进程数量，默认为4')
    # 单个进程的最大并发数
    parser.add_argument('--max_concurrency', type=int, default=32, help='单个进程的最大并发数，默认为32')

    args = parser.parse_args()

    max_concurrency = Manager().Value('i', args.max_concurrency)

    # 检查是否有未完成的任务并终止
    from bisheng.linsight.utils import check_and_terminate_incomplete_tasks

    asyncio.run(check_and_terminate_incomplete_tasks())

    try:
        processes = start_schedule_center_process(worker_num=args.worker_num,
                                                  max_concurrency=max_concurrency)
        if processes:
            for p in processes:
                p.join()  # 等待所有进程结束
    except KeyboardInterrupt:
        logger.info("ScheduleCenterProcess interrupted by user.")
        logger.info("Stopping ScheduleCenterProcess workers...")
