import argparse
import asyncio
import logging

from multiprocessing import Process
from typing import Optional

from bisheng.cache.redis import RedisClient, redis_client
from bisheng.linsight.task_exec import LinsightWorkflowTask
from bisheng.settings import settings
from bisheng.utils.logger import configure

logger = logging.getLogger(__name__)


# Redis 队列
class RedisQueue(object):
    def __init__(self, name, namespace, redis):
        self.__db: RedisClient = redis
        self.key = '%s:%s' % (namespace, name)

    async def qsize(self):
        return await self.__db.allen(self.key)  # 返回队列里面list内元素的数量

    async def put(self, data, timeout=None):
        await self.__db.arpush(self.key, data)  # 添加新元素到队列最右方
        if isinstance(timeout, int):
            await self.__db.aexpire_key(self.key, timeout)

    async def get_wait(self, timeout=None):
        # 返回队列第一个元素，如果为空则等待至有元素被加入队列（超时时间阈值为timeout，如果为None则一直等待）
        item = await self.__db.ablpop(self.key, timeout=timeout)
        return item

    async def get_nowait(self):
        # 直接返回队列第一个元素，如果队列为空返回的是None
        item = await self.__db.alpop(self.key)
        return item


class ScheduleCenterProcess(Process):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.queue: Optional[RedisQueue] = None
        # 信号量
        self.semaphore: Optional[asyncio.Semaphore] = None

    @staticmethod
    def handle_task_result(task: asyncio.Task):
        try:
            result = task.result()  # 如果有异常，这里会抛出
        except Exception as e:
            logger.error(f"Task failed with exception: {e}")

    async def async_run(self):
        """
        异步运行方法，监听 Redis 队列并执行任务
        :return:
        """
        logger.info("ScheduleCenterProcess started...")
        while True:
            try:
                session_version_id = await self.queue.get_wait()
                if session_version_id is None:
                    continue
                await self.semaphore.acquire()  # 获取信号量，限制并发数
                exec_task = LinsightWorkflowTask(semaphore=self.semaphore)

                logger.info(f"Processing session_version_id: {session_version_id}")

                task = asyncio.create_task(
                    exec_task.async_run(session_version_id)
                )

                task.add_done_callback(self.handle_task_result)  # 添加回调处理任务结果

            except Exception as e:
                logger.error(f"Error in ScheduleCenterProcess: {e}")
                continue

    def run(self):
        """
        运行进程
        :return:
        """

        self.queue = RedisQueue('queue', namespace="linsight", redis=redis_client)
        for _ in range(10000):
            self.semaphore = asyncio.Semaphore(settings.linsight_conf.max_concurrency)
            try:
                asyncio.run(self.async_run())
            except Exception as e:
                logger.error(f"Error in ScheduleCenterProcess run method: {e}")


def start_schedule_center_process(worker_num: int = 4) -> Optional[list[ScheduleCenterProcess]]:
    """
    启动调度中心进程
    :param worker_num: 启动的工作进程数量
    :return:
    """
    logger.info(f"Starting {worker_num} ScheduleCenterProcess workers...")
    if worker_num <= 0:
        logger.error("worker_num must be greater than 0")
        return
    processes = []
    for _ in range(worker_num):
        process = ScheduleCenterProcess()
        process.start()
        logger.info(f"Started ScheduleCenterProcess with PID: {process.pid}")
        processes.append(process)

    logger.info(f"Started {len(processes)} ScheduleCenterProcess workers successfully.")
    return processes


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('--worker_num', type=int, default=4, help='进程数量，默认为4')

    args = parser.parse_args()

    configure(settings.logger_conf)

    try:
        processes = start_schedule_center_process(worker_num=args.worker_num)
        if processes:
            for p in processes:
                p.join()  # 等待所有进程结束
    except KeyboardInterrupt:
        logger.info("ScheduleCenterProcess interrupted by user.")
        logger.info("Stopping ScheduleCenterProcess workers...")
