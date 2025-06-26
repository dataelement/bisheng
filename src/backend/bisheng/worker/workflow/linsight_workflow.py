import logging
from asyncio import Queue
from typing import Optional, List

from celery import Task

from bisheng.utils import util
from bisheng.worker import bisheng_celery
from bisheng.worker.main import loop

logger = logging.getLogger(__name__)


# 任务执行器
class TaskExecutor(object):
    """
    任务执行器，用于执行具体的任务逻辑
    """

    def __init__(self, task):
        """
        初始化任务执行器
        :param task: 任务实例
        """
        self.task = task
        # TODO: 任务执行器需要的参数待定
        pass

    async def execute(self, *args, **kwargs):
        """
        执行任务逻辑
        """
        try:
            # TODO: 在这里添加具体的任务执行逻辑
            pass
        except Exception as e:
            logger.error(f"Error executing task {self.task.name}: {str(e)}")
            raise e


# 任务Manager器
class TaskManager(object):
    """
    任务管理器，用于管理和执行任务
    """

    def __init__(self, queue: Queue, tasks: List):
        """
        初始化任务管理器
        :param queue: 可选的任务队列
        """
        self._queue = queue
        self._tasks = tasks
        # TODO: 任务Manager需要需要的参数待定
        pass

    async def run_task(self, *args, **kwargs):
        """
        运行任务
        """
        for task in self._tasks:
            # Todo: 按顺序调用一级任务
            # Todo: 如果有子任务，则用 asyncio.gather 并发执行子任务
            pass


class LinsightWorkflowTask(Task):
    name = "linsight_workflow_task"

    def __init__(self):
        super().__init__()
        self._queue: Optional[Queue] = None

    def before_start(self, task_id, args, kwargs):
        """
        任务开始前执行的初始化逻辑
        """

        # 创建通信队列
        self._queue = Queue()

        # TODO: 可以在这里添加其他初始化逻辑，比如加载配置、连接数据库等

    @staticmethod
    def delay(*args, **kwargs):
        """使用 Celery 异步加入任务队列"""
        return bisheng_celery.send_task(LinsightWorkflowTask.name, args=args, kwargs=kwargs)

    async def async_run(self, *args, **kwargs):
        """
        异步任务执行逻辑
        """
        try:
            # TODO: 在这里添加具体的任务执行逻辑
            pass
        except Exception as e:
            logger.error(f"Error in LinsightWorkflowTask: {str(e)}")
            raise e

    def run(self, *args, **kwargs):
        """同步 Celery 任务执行入口"""
        util.run_async(self.async_run(*args, **kwargs), loop=loop)


# 注册任务
bisheng_celery.register_task(LinsightWorkflowTask())
