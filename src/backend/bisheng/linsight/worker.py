import argparse
import asyncio
import logging

from multiprocessing import Process, Manager, set_start_method
from multiprocessing.managers import ValueProxy
from typing import Optional, Union

from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.logger import set_logger_config
from bisheng.linsight.task_exec import LinsightWorkflowTask
from bisheng.common.services.config_service import settings

logger = logging.getLogger(__name__)


# LinsightQueue queue
class LinsightQueue(object):
    def __init__(self, name, namespace, redis):
        self.__db: RedisClient = redis
        self.key = '%s:%s' % (namespace, name)

    async def qsize(self):
        return await self.__db.allen(self.key)  # Back to queuelistNumber of inner elements

    async def put(self, data, timeout=None):
        await self.__db.arpush(self.key, data, expiration=timeout)  # Add a new element to the far right of the queue

    async def get_wait(self, timeout=None):
        # Returns the first element of the queue, if empty, wait until an element is queued (the timeout threshold istimeout, if isNonehas been waiting)
        item = await self.__db.ablpop(self.key, timeout=timeout)
        return item

    async def get_nowait(self):
        # Returns the first element of the queue directly, if the queue is emptyNone
        item = await self.__db.alpop(self.key)
        return item

    # Get the position of a task's data in the queue
    async def index(self, data):
        """
        Get the position of a task's data in the queue
        :param data: Task Data
        :return: the position of the task data in the queue,-1Indicates not in queue
        """
        items = await self.__db.alrange(self.key)
        try:
            index = items.index(data)
            return index + 1  # Return index from1Getting Started
        except ValueError:
            return 0

    # Delete a task data
    async def remove(self, data):
        """
        Delete a task data
        :param data: Task Data
        :return: None
        """
        await self.__db.alrem(self.key, data)  # Remove the specified data from the queue


class ScheduleCenterProcess(Process):
    def __init__(self, max_concurrency: ValueProxy = None):
        """
        Dispatch Center process responsible for moving from Redis Get tasks in queue and execute
        :param max_concurrency:
        """
        super().__init__()
        self.daemon = True
        self.queue: Optional[LinsightQueue] = None
        # Semaphores
        self.semaphore: Optional[asyncio.Semaphore] = None
        self.max_concurrency: Optional[Union[int, ValueProxy]] = max_concurrency

    def handle_task_result(self, task: asyncio.Task):
        try:
            result = task.result()  # If there is an exception, it will be thrown here
        except Exception as e:
            logger.error(f"Task failed with exception: {e}")
        finally:
            # Release semaphore
            if self.semaphore:
                logger.info("Releasing semaphore after task completion.")
                self.semaphore.release()

    async def async_run(self):
        """
        Asynchronous operation method, monitoring Redis Queue and execute tasks
        :return:
        """
        logger.info("ScheduleCenterProcess started...")
        while True:
            await self.semaphore.acquire()  # Acquire semaphore, limit concurrency
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

                task.add_done_callback(self.handle_task_result)  # Add Callback Processing Task Result

            except Exception as e:
                logger.error(f"Error in ScheduleCenterProcess: {e}")
                if self.semaphore:
                    if self.semaphore._value < self.max_concurrency:
                        logger.info("Releasing semaphore due to error.")
                        self.semaphore.release()
                continue

    def run(self):
        """
        Run Process
        :return:
        """

        set_logger_config(settings.logger_conf)

        if self.max_concurrency is not None:
            self.max_concurrency = self.max_concurrency.value  # Dapatkan ValueProxy Actual value
        else:
            self.max_concurrency = 32
            logger.warning("No max_concurrency provided, using default value of 32.")

        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        logger.info(f"Semaphore initialized with max concurrency: {self.semaphore._value}")

        redis_client = get_redis_client_sync()
        self.queue = LinsightQueue('queue', namespace="linsight", redis=redis_client)
        for _ in range(10000):
            try:
                asyncio.run(self.async_run())
            except Exception as e:
                logger.error(f"Error in ScheduleCenterProcess run method: {e}")


def start_schedule_center_process(worker_num: int = 4, max_concurrency: ValueProxy = None):
    """
    Start the dispatch center process
    :param max_concurrency:
    :param worker_num: Number of worker processes started
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

    set_start_method("spawn", force=True)  # make sure that people are using the spawn Method Starts a New Process

    parser = argparse.ArgumentParser()
    parser.add_argument('--worker_num', type=int, default=4, help='Number of processes, defaults to4')
    # Maximum number of concurrency for a single process
    parser.add_argument('--max_concurrency', type=int, default=32, help='Maximum number of concurrency for a single process, defaults to32')

    args = parser.parse_args()

    max_concurrency = Manager().Value('i', args.max_concurrency)

    # Check for incomplete tasks and terminate
    from bisheng.linsight.utils import check_and_terminate_incomplete_tasks

    asyncio.run(check_and_terminate_incomplete_tasks())

    try:
        processes = start_schedule_center_process(worker_num=args.worker_num,
                                                  max_concurrency=max_concurrency)
        if processes:
            for p in processes:
                p.join()  # Wait for all processes to end
    except KeyboardInterrupt:
        logger.info("ScheduleCenterProcess interrupted by user.")
        logger.info("Stopping ScheduleCenterProcess workers...")
