import argparse
import asyncio
import logging
import socket
import uuid

from multiprocessing import Process, Manager, set_start_method
from multiprocessing.managers import ValueProxy
from typing import Optional, Union

from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.logger import set_logger_config
from bisheng.common.services.config_service import settings
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

logger = logging.getLogger(__name__)


class NodeManager:
    _instance = None

    def __init__(self, redis_client, node_id):
        # generate unique node ID
        self.node_id = node_id
        self.redis = redis_client
        self.heartbeat_key = f"linsight:node:heartbeat:{self.node_id}"
        # Heartbeat interval (seconds)
        self.interval = 5
        # Redis key expiration time (seconds)
        self.ttl = 15

    @classmethod
    def get_instance(cls, node_id):
        if not cls._instance:
            redis_client = get_redis_client_sync()
            cls._instance = cls(redis_client, node_id)
        return cls._instance

    async def start_heartbeat(self):
        """Start the heartbeat task to indicate node liveness"""
        logger.info(f"Starting heartbeat for node: {self.node_id}")
        while True:
            try:
                # set heartbeat key with expiration
                await self.redis.aset(self.heartbeat_key, "1", expiration=self.ttl)
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
            await asyncio.sleep(self.interval)

    async def register_task_ownership(self, session_version_id):
        """Register task ownership to this node"""
        key = f"linsight:task:owner:{session_version_id}"
        # Set the node ID as the owner of the task with a TTL
        await self.redis.aset(key, self.node_id, expiration=86400)  # 1 day expiration

    async def release_task_ownership(self, session_version_id):
        """Release task ownership"""
        key = f"linsight:task:owner:{session_version_id}"
        await self.redis.delete(key)

    async def is_node_alive(self, target_node_id):
        """Check if a target node is alive based on its heartbeat"""
        if not target_node_id:
            return False
        key = f"linsight:node:heartbeat:{target_node_id}"
        exists = await self.redis.exists(key)
        return exists > 0


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
        :return: Position in queue, starting from 1; if not found, return 0
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
        Delete a task data from the queue
        :param data: Task Data
        :return:
        """
        await self.__db.alrem(self.key, data)  # Remove the specified data from the queue


class ScheduleCenterProcess(Process):
    def __init__(self, max_concurrency: ValueProxy = None, node_id: ValueProxy = None):
        """
        Dispatch Center Process
        :param max_concurrency: Maximum number of concurrent tasks allowed per process
        """
        super().__init__()
        self.daemon = True
        self.queue: Optional[LinsightQueue] = None
        # Semaphores
        self.semaphore: Optional[asyncio.Semaphore] = None
        self.node_manager: Optional[NodeManager] = None
        self.max_concurrency: Optional[Union[int, ValueProxy]] = max_concurrency
        self.node_id: Optional[ValueProxy] = node_id

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
        Asynchronous Run Method for Process
        :return:
        """
        logger.info("ScheduleCenterProcess started...")

        # node manager heartbeat
        node_manager = self.node_manager or NodeManager.get_instance(self.node_id.value)

        while True:
            await self.semaphore.acquire()  # Acquire semaphore, limit concurrency
            try:
                session_version_id = await self.queue.get_wait()
                if session_version_id is None:
                    logger.info("No session_version_id found in queue, waiting...")
                    self.semaphore.release()
                    continue

                # Register task ownership
                await node_manager.register_task_ownership(session_version_id)

                exec_task = LinsightWorkflowTask()
                logger.info(f"Processing session_version_id: {session_version_id} on node {node_manager.node_id}")

                task = asyncio.create_task(
                    exec_task.async_run(session_version_id)
                )
                task.add_done_callback(self.handle_task_result)  # Add callback to handle task completion

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

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 启动心跳
        self.node_manager = NodeManager.get_instance(self.node_id.value)
        loop.create_task(self.node_manager.start_heartbeat())

        # 启动主逻辑
        for _ in range(10000):  # 你的原始逻辑
            try:
                loop.run_until_complete(self.async_run())
            except Exception as e:
                logger.error(f"Unhandled exception in main loop: {e}")
        loop.close()


def start_schedule_center_process(worker_num: int = 4, max_concurrency: ValueProxy = None, node_id: ValueProxy = None):
    """

    Start Schedule Center Process Workers
    :param worker_num: Number of worker processes to start
    :param max_concurrency: Maximum number of concurrent tasks allowed per process
    :return:

    Args:
        node_id:
    """
    logger.info(f"Starting {worker_num} ScheduleCenterProcess workers...")
    if worker_num <= 0:
        logger.error("worker_num must be greater than 0")
        return
    processes = []
    for _ in range(worker_num):
        process = ScheduleCenterProcess(max_concurrency, node_id)
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
    parser.add_argument('--max_concurrency', type=int, default=32,
                        help='Maximum number of concurrency for a single process, defaults to32')

    args = parser.parse_args()

    process_manager = Manager()

    node_id = process_manager.Value('s', f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")

    max_concurrency = process_manager.Value('i', args.max_concurrency)

    # Check for incomplete tasks and terminate
    from bisheng.linsight.domain.utils import check_and_terminate_incomplete_tasks

    asyncio.run(check_and_terminate_incomplete_tasks(node_id.value))

    try:
        processes = start_schedule_center_process(worker_num=args.worker_num,
                                                  max_concurrency=max_concurrency,
                                                  node_id=node_id)
        if processes:
            for p in processes:
                p.join()  # Wait for all processes to end
    except KeyboardInterrupt:
        logger.info("ScheduleCenterProcess interrupted by user.")
        logger.info("Stopping ScheduleCenterProcess workers...")
